"""Entity resolution / dedup / canonicalization (stage 3 of extraction).

Across chunks the same real-world entity shows up under different surface forms
("Article 21", "Art. 21", "ARTICLE 21"). Without fusion the graph fills with
duplicate nodes. The resolver normalizes names, groups by the normalized key,
picks a canonical representative per group, and rewires every relationship to
the canonical node name.

The matching is normalized string equality (exact + a light abbreviation
normalizer). Embedding-based fuzzy matching is left as a hook
(``use_embeddings``) for a later phase — it's deliberately not wired here.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from typing import TYPE_CHECKING

from kg.extract.schemas import Entity, Relationship

if TYPE_CHECKING:
    from kg.extract.schemas import ExtractionResult

logger = logging.getLogger(__name__)

# Common abbreviations expanded so "Art. 21" and "Article 21" share a key.
_ABBREVIATIONS = {
    "art": "article",
    "sec": "section",
    "ch": "chapter",
    "no": "number",
    "vol": "volume",
    "fig": "figure",
}
_WHITESPACE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Normalize an entity name for matching. Lowercased, de-abbreviated, trimmed."""
    s = name.lower().strip()
    s = s.replace("&", "and")
    # expand "art." / "art " tokens; strip the periods that often follow abbreviations
    s = re.sub(r"\.", " ", s)
    tokens = [_ABBREVIATIONS.get(t, t) for t in s.split()]
    s = " ".join(tokens)
    # drop leading articles and surrounding punctuation
    s = re.sub(r"^(the|a|an)\s+", "", s)
    s = re.sub(r"^[^a-z0-9]+|[^a-z0-9]+$", "", s)
    return _WHITESPACE.sub(" ", s).strip()


class EntityResolver:
    def __init__(self, use_embeddings: bool = False) -> None:
        """``use_embeddings`` is accepted for config compatibility but not yet
        implemented — matching stays normalized-string-equality (warns if set)."""
        if use_embeddings:
            logger.warning(
                "use_embeddings=True requested but not implemented; using string matching."
            )
        self.use_embeddings = use_embeddings

    def resolve(self, results: list[ExtractionResult]) -> tuple[list[Entity], list[Relationship]]:
        """Return (canonical entities, rewired relationships) from per-chunk results."""
        # 1. group entities by normalized key
        groups: dict[str, list[Entity]] = defaultdict(list)
        for r in results:
            for e in r.entities:
                groups[normalize_name(e.name)].append(e)

        # 2. pick a canonical representative per group
        canonical: list[Entity] = []
        original_to_canonical: dict[str, str] = {}
        norm_to_canonical: dict[str, str] = {}
        for norm, group in groups.items():
            rep_name = self._pick_representative_name(group)
            rep_entity = self._merge_group(group, rep_name)
            canonical.append(rep_entity)
            norm_to_canonical[norm] = rep_name
            for e in group:
                original_to_canonical[e.name] = rep_name

        logger.info(
            "Fusion: %d raw entities -> %d canonical (%d duplicates merged).",
            sum(len(g) for g in groups.values()),
            len(canonical),
            sum(len(g) for g in groups.values()) - len(canonical),
        )

        # 3. rewire relationships to canonical names, dedupe identical edges
        relationships = self._rewire(results, original_to_canonical, norm_to_canonical)
        logger.info("Fusion: %d canonical relationships.", len(relationships))
        return canonical, relationships

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _pick_representative_name(group: list[Entity]) -> str:
        """Choose the canonical surface form: most frequent, ties to the longest."""
        counts = Counter(e.name for e in group)
        return max(group, key=lambda e: (counts[e.name], len(e.name))).name

    @staticmethod
    def _merge_group(group: list[Entity], rep_name: str) -> Entity:
        """Collapse duplicate entities into one: union of properties, first label.

        Conflicting labels within a group are logged (and the first wins) —
        they usually mean two genuinely different things normalized to the
        same key, which is worth a human's glance.
        """
        labels = {e.label for e in group}
        if len(labels) > 1:
            logger.info(
                "Entity %r has conflicting labels %s; keeping first.", rep_name, sorted(labels)
            )
        merged_props: dict[str, str] = {}
        for e in group:
            merged_props.update(e.properties)
        return Entity(name=rep_name, label=group[0].label, properties=merged_props)

    @staticmethod
    def _rewire(
        results: list[ExtractionResult],
        original_to_canonical: dict[str, str],
        norm_to_canonical: dict[str, str],
    ) -> list[Relationship]:
        """Point every relationship at canonical names, then dedupe identical edges.

        Edges that become self-loops after canonicalization are dropped (they
        only ever linked a duplicate to itself). Duplicate (src, tgt, label)
        edges are merged, later properties overwriting earlier ones.
        """

        def resolve_name(name: str) -> str:
            if name in original_to_canonical:
                return original_to_canonical[name]
            norm = normalize_name(name)
            return norm_to_canonical.get(norm, name)

        seen: dict[tuple[str, str, str], Relationship] = {}
        for r in results:
            for rel in r.relationships:
                src = resolve_name(rel.source_name)
                tgt = resolve_name(rel.target_name)
                if src == tgt:
                    continue  # drop self-loops created by fusion
                key = (src, tgt, rel.label)
                if key in seen:
                    seen[key].properties.update(rel.properties)  # merge duplicate edge props
                    continue
                seen[key] = Relationship(
                    source_name=src,
                    target_name=tgt,
                    label=rel.label,
                    properties=dict(rel.properties),
                )
        return list(seen.values())
