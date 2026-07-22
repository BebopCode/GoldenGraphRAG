"""Fusion / entity-resolution tests."""

from __future__ import annotations

from kg.extract.schemas import Entity, ExtractionResult, Relationship
from kg.fusion.resolver import EntityResolver, normalize_name


def test_normalize_handles_abbreviations_and_case() -> None:
    assert normalize_name("Article 21") == normalize_name("Art. 21")
    assert normalize_name("Article 21") == normalize_name("ARTICLE 21")
    assert normalize_name("The Supreme Court") == normalize_name("supreme court")


def test_resolve_merges_duplicate_entities() -> None:
    r1 = ExtractionResult(
        chunk_id="a",
        entities=[Entity(name="Ada Lovelace", label="Person")],
        relationships=[],
    )
    r2 = ExtractionResult(
        chunk_id="b",
        entities=[Entity(name="ada lovelace", label="Person")],
        relationships=[],
    )
    entities, rels = EntityResolver().resolve([r1, r2])
    assert len(entities) == 1
    assert rels == []


def test_resolve_rewires_relationships_to_canonical() -> None:
    r1 = ExtractionResult(
        chunk_id="a",
        entities=[Entity(name="Article 21", label="Article")],
        relationships=[],
    )
    r2 = ExtractionResult(
        chunk_id="b",
        entities=[
            Entity(name="Art. 21", label="Article"),
            Entity(name="Article 14", label="Article"),
        ],
        relationships=[
            Relationship(source_name="Art. 21", target_name="Article 14", label="REFERENCES")
        ],
    )
    entities, rels = EntityResolver().resolve([r1, r2])
    names = {e.name for e in entities}
    assert names == {"Article 21", "Article 14"}  # "Art. 21" merged into "Article 21"
    assert len(rels) == 1
    assert rels[0].source_name == "Article 21"
    assert rels[0].target_name == "Article 14"


def test_resolve_drops_self_loops() -> None:
    r = ExtractionResult(
        chunk_id="a",
        entities=[Entity(name="X", label="Thing"), Entity(name="x", label="Thing")],
        relationships=[Relationship(source_name="X", target_name="x", label="RELATED_TO")],
    )
    entities, rels = EntityResolver().resolve([r])
    assert len(entities) == 1
    assert rels == []  # X->x became a self-loop after merge


def test_resolve_dedupes_identical_edges_and_merges_props() -> None:
    r1 = ExtractionResult(
        chunk_id="a",
        entities=[Entity(name="A", label="Thing"), Entity(name="B", label="Thing")],
        relationships=[
            Relationship(
                source_name="A", target_name="B", label="RELATED_TO", properties={"w": "1"}
            )
        ],
    )
    r2 = ExtractionResult(
        chunk_id="b",
        entities=[],
        relationships=[
            Relationship(
                source_name="A", target_name="B", label="RELATED_TO", properties={"note": "x"}
            )
        ],
    )
    _, rels = EntityResolver().resolve([r1, r2])
    assert len(rels) == 1
    assert rels[0].properties == {"w": "1", "note": "x"}
