# CLI Reference

Everything runs through the `kg` command (installed by `uv sync`; run it bare after
`source .venv/bin/activate`, or as `uv run kg`). Every
command accepts `--env <file>` to use a different `.env` profile; see
[Multiple configurations](configuration.md#multiple-configurations).

## `kg init`

```bash
kg init
```

Create the AGE graph if it doesn't exist (idempotent, safe on every run) and confirm
connectivity. Run this once after `docker compose up -d`.

## `kg delete`

```bash
kg delete [--yes | -y]
```

Delete the AGE graph and everything in it: every node and edge. **Irreversible.**
Asks for confirmation first; pass `--yes` to skip the prompt (scripts, CI). Deleting
a graph that doesn't exist is a no-op, not an error.

| Flag | Description |
|---|---|
| `--yes`, `-y` | Delete without asking |

```bash
kg delete                  # asks "Permanently delete graph 'kg_graph'? ..."
kg delete --yes            # no prompt
```

## `kg ingest`

```bash
kg ingest <path> [--limit N | -n N]
```

Run the full pipeline (load → chunk → extract → fuse → store) over a file or
directory. Supported formats: `.txt`, `.md`, `.json`, `.csv`; directories are walked
recursively.

| Flag | Description |
|---|---|
| `--limit N`, `-n N` | Stop after the first N chunks (cheap partial run) |

```bash
kg ingest data/samples/example.txt        # one file
kg ingest data/samples/ --limit 5         # a directory, first 5 chunks only
```

## `kg query`

```bash
kg query "<openCypher>"
```

Run an openCypher query against the graph and print rows as JSON. Results are
deserialized from AGE's `agtype` to plain Python values; multi-column `RETURN`
clauses are supported.

## `kg info`

```bash
kg info [--check-llm]
```

Show the effective config and ontology; no database or LLM needed.

| Flag | Description |
|---|---|
| `--check-llm` | Ping the LLM endpoint with a tiny request; wrong URL, dead key, or bad model slug surface in seconds |

## Example queries

```bash
# What entities exist, and their type?
kg query "MATCH (n) RETURN n.name AS name, n.type AS type"

# Who is related to whom?
kg query "MATCH (a)-[r]->(b) RETURN a.name AS src, type(r) AS rel, b.name AS tgt"

# Count nodes by label
kg query "MATCH (n) RETURN labels(n) AS label, count(n) AS n"
```

!!! tip
    Queries are hand-written openCypher; there's no text-to-Cypher layer (yet).
    The [openCypher spec](https://opencypher.org/) covers everything AGE supports.
