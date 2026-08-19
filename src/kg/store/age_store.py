"""Apache AGE implementation of :class:`~kg.store.base.GraphStore`.

AGE runs openCypher *inside* PostgreSQL. Three things make it different from a
native graph DB, and all three are handled here:

  1. Every session must ``LOAD 'age'`` and set ``search_path`` to include
     ``ag_catalog``. Done once per connection.
  2. Cypher is executed wrapped in SQL via ``cypher('graph', $$ ... $$, params)``
     and *requires* a column-definition list ``AS (c0 agtype, ...)`` whose arity
     matches the RETURN clause.
  3. Results come back as ``agtype`` text (JSON-ish with a ``::vertex`` /
     ``::edge`` / ``::path`` suffix), which we deserialize to Python.

Writes use ``MERGE`` for idempotency so re-running ingestion doesn't duplicate.
The connection is in ``autocommit`` mode because AGE's DDL/cypher manage their
own transaction state.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import psycopg

from kg.config.models import Settings
from kg.store.base import GraphStore

logger = logging.getLogger(__name__)

_IDENT_SAFE = re.compile(r"[^A-Za-z0-9_]")


def _sanitize_ident(name: str) -> str:
    """Make a label/property name safe for backtick-quoting in Cypher."""
    cleaned = _IDENT_SAFE.sub("_", str(name)).strip("_")
    return cleaned or "prop"


def _split_top_level_commas(s: str) -> list[str]:
    """Split on commas that are not inside (), [], {} or a quoted string."""
    parts: list[str] = []
    cur: list[str] = []
    depth = 0
    quote: str | None = None
    for ch in s:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch in "([{":
            depth += 1
            cur.append(ch)
        elif ch in ")]}":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return parts


_RETURN_RE = re.compile(r"\bRETURN\b", re.IGNORECASE)
_TRAILING_RE = re.compile(r"\b(LIMIT|SKIP|ORDER\s+BY|UNION\s+ALL|UNION)\b", re.IGNORECASE)


def _normalize_query(cypher: str) -> tuple[str, int]:
    """Normalize a user Cypher query so it returns exactly ONE column.

    AGE needs a fixed column-definition list matching RETURN arity. We can't know
    that arity for arbitrary queries, so multi-column returns are wrapped into a
    single map: ``RETURN a, b`` -> ``RETURN {col0: (a), col1: (b)}``. Single-column
    returns pass through. Output is therefore always a list of values or dicts.
    """
    m = _RETURN_RE.search(cypher)
    if not m:
        return cypher, 1  # no RETURN -> caller deals with AGE's response
    proj_start = m.end()
    tm = _TRAILING_RE.search(cypher[proj_start:])
    if tm:
        proj_end = proj_start + tm.start()
        trailing = cypher[proj_end:]
    else:
        proj_end = len(cypher)
        trailing = ""
    proj = cypher[proj_start:proj_end].strip()
    items = [i for i in _split_top_level_commas(proj) if i.strip()]
    if len(items) <= 1:
        return cypher, 1
    pairs: list[str] = []
    for i, item in enumerate(items):
        expr, key = _split_proj_alias(item.strip(), i)
        pairs.append(f"`{_sanitize_ident(key)}`: ({expr})")
    map_literal = "{" + ", ".join(pairs) + "}"
    prefix = cypher[: m.start()]
    return f"{prefix}RETURN {map_literal} {trailing}".strip(), 1


def _split_proj_alias(item: str, idx: int) -> tuple[str, str]:
    """Split ``expr AS alias`` into (expr, alias); alias defaults to col<idx>."""
    m = re.search(r"\bAS\b\s+(\w+)", item, re.IGNORECASE)
    if m:
        return item[: m.start()].strip(), m.group(1)
    return item, f"col{idx}"


def _loads_agtype_obj(s: str) -> Any:
    """Parse the JSON-ish body of an agtype vertex/edge/path/map."""
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # AGE sometimes emits single-quoted strings; best-effort conversion.
        try:
            return json.loads(s.replace("'", '"'))
        except json.JSONDecodeError:
            return s  # give back the raw text rather than crashing


def _parse_agtype(val: Any) -> Any:
    """Deserialize a single agtype cell to a Python value."""
    if val is None or not isinstance(val, str):
        return val
    s = val.strip()
    for suffix in ("::vertex", "::edge", "::path"):
        if s.endswith(suffix):
            return _loads_agtype_obj(s[: -len(suffix)].strip())
    # Scalar: quoted string, number, bool, null, or a bare map/list.
    if s in ("NULL", "null"):
        return None
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        return s[1:-1]
    parsed = _loads_agtype_obj(s)
    return parsed


class AgeGraphStore(GraphStore):
    def __init__(self, dsn: str, graph_name: str) -> None:
        """Store the connection info; the connection itself is opened lazily.

        AGE requires the graph name as a literal inside cypher() — it cannot be
        a bind parameter — so we inline it. Validate it hard to stay injection-safe.
        """
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", graph_name):
            raise ValueError(
                f"Invalid graph name {graph_name!r}: must match [A-Za-z_][A-Za-z0-9_]*"
            )
        self._dsn = dsn
        self._graph = graph_name
        self._conn: psycopg.Connection | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> AgeGraphStore:
        """Build a store from the db block of validated :class:`Settings`."""
        return cls(settings.db.dsn, settings.db.graph_name)

    # -- connection -------------------------------------------------------
    def _connect(self) -> psycopg.Connection:
        """Open (or reuse) the session, with the AGE setup every session needs:
        autocommit, ``LOAD 'age'``, and ``search_path`` including ``ag_catalog``."""
        if self._conn is None or self._conn.closed:
            conn = psycopg.connect(self._dsn)
            conn.autocommit = True  # AGE manages its own tx state
            with conn.cursor() as cur:
                cur.execute("LOAD 'age';")
                cur.execute('SET search_path = ag_catalog, "$user", public;')
            self._conn = conn
        return self._conn

    def close(self) -> None:
        """Close the connection if open; safe to call repeatedly."""
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._conn = None

    # -- low-level cypher execution --------------------------------------
    def _exec_cypher(
        self, cypher_text: str, params: dict | None = None, n_cols: int = 1
    ) -> list[tuple]:
        """Run cypher wrapped in ``SELECT * FROM cypher(...)`` and fetch raw rows.

        ``n_cols`` must match the RETURN arity (AGE demands a column-definition
        list of exactly that size). Values come back as agtype text — parse
        them with :func:`_parse_agtype` before use. Params are bound (as a JSON
        blob); only the pre-validated graph name is ever inlined.
        """
        conn = self._connect()
        coldefs = ", ".join(f"c{i} agtype" for i in range(n_cols))
        # Graph name is a validated identifier, inlined as a literal (see __init__).
        # The params map IS safe to bind, so it stays parameterized.
        sql = f"SELECT * FROM cypher('{self._graph}', $$\n{cypher_text}\n$$, %s) AS ({coldefs})"
        params_json = json.dumps(params or {})
        with conn.cursor() as cur:
            cur.execute(sql, (params_json,))
            return cur.fetchall()

    # -- GraphStore API ---------------------------------------------------
    def init_graph(self, name: str) -> None:
        """Create the AGE graph if absent (idempotent — safe on every run)."""
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM ag_catalog.ag_graph WHERE name = %s;", (name,))
            if cur.fetchone()[0] == 0:
                cur.execute("SELECT create_graph(%s);", (name,))
                logger.info("Created graph '%s'", name)
            else:
                logger.info("Graph '%s' already exists", name)

    def upsert_node(self, label: str, key: dict, props: dict) -> None:
        """MERGE a node on ``key`` (e.g. ``{"name": ...}``) and SET the props.

        Idempotent: re-ingesting the same entity updates it in place instead of
        duplicating. Labels and property names are sanitized to identifiers.
        """
        if not key:
            raise ValueError("upsert_node requires a non-empty key dict")
        label = _sanitize_ident(label)
        params: dict[str, Any] = {}
        key_terms: list[str] = []
        for i, (k, v) in enumerate(key.items()):
            key_terms.append(f"`{_sanitize_ident(k)}`: $k{i}")
            params[f"k{i}"] = v
        set_clauses = []
        for i, (k, v) in enumerate(props.items()):
            set_clauses.append(f"n.`{_sanitize_ident(k)}` = $p{i}")
            params[f"p{i}"] = v
        merge = f"MERGE (n:`{label}` {{{', '.join(key_terms)}}})"
        set_clause = ("SET " + ", ".join(set_clauses)) if set_clauses else ""
        cypher = f"{merge} {set_clause} RETURN n".strip()
        self._exec_cypher(cypher, params)

    def upsert_edge(self, label: str, src: dict, tgt: dict, props: dict) -> bool:
        """MERGE an edge between nodes matched by their keys; True if both endpoints
        existed. A missing endpoint means the edge silently references nothing —
        the caller logs and moves on rather than failing the ingest."""
        if not src or not tgt:
            raise ValueError("upsert_edge requires non-empty src and tgt key dicts")
        label = _sanitize_ident(label)
        params: dict[str, Any] = {}
        src_terms = self._key_terms(src, "s", params)
        tgt_terms = self._key_terms(tgt, "t", params)
        set_parts = []
        for i, (k, v) in enumerate(props.items()):
            set_parts.append(f"r.`{_sanitize_ident(k)}` = $e{i}")
            params[f"e{i}"] = v
        set_clause = ("SET " + ", ".join(set_parts)) if set_parts else ""
        cypher = (
            f"MATCH (a {{{', '.join(src_terms)}}}), (b {{{', '.join(tgt_terms)}}}) "
            f"MERGE (a)-[r:`{label}`]->(b) {set_clause} "
            "RETURN count(r) AS c"
        ).strip()
        rows = self._exec_cypher(cypher, params)
        created = bool(rows and _parse_agtype(rows[0][0]))
        if not created:
            logger.warning("Edge :%s %s -> %s matched no endpoints; skipped.", label, src, tgt)
        return created

    def query(self, cypher: str, params: dict | None = None) -> list[dict]:
        """Run an arbitrary user query and return agtype-parsed rows.

        Multi-column RETURN clauses are rewritten into a single map
        (see :func:`_normalize_query`) because AGE's column-definition list
        must match the RETURN arity, which we can't know up front.
        """
        norm, n_cols = _normalize_query(cypher)
        rows = self._exec_cypher(norm, params, n_cols=n_cols)
        out: list[Any] = []
        for row in rows:
            parsed = [_parse_agtype(v) for v in row]
            out.append(parsed[0] if n_cols == 1 else dict(enumerate(parsed)))
        return out

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _key_terms(key: dict, prefix: str, params: dict[str, Any]) -> list[str]:
        """Build ``{`prop`: $pfxN}` match terms, adding bindings to ``params``."""
        terms: list[str] = []
        for i, (k, v) in enumerate(key.items()):
            terms.append(f"`{_sanitize_ident(k)}`: ${prefix}{i}")
            params[f"{prefix}{i}"] = v
        return terms
