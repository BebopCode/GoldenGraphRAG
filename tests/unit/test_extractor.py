"""Extractor unit tests with a mocked LLM (no Ollama required)."""

from __future__ import annotations

import json

from kg.config.models import Ontology
from kg.extract.llm_extractor import LLMExtractor
from kg.extract.schemas import Entity, Relationship
from kg.ingest.chunkers.base import Chunk
from kg.llm.base import LLMClient

ONTOLOGY = Ontology.model_validate(
    {
        "name": "test",
        "node_types": [{"label": "Person"}, {"label": "Place"}],
        "relationship_types": [
            {"label": "BORN_IN", "source": "Person", "target": "Place"},
            {"label": "KNOWS", "source": "Person", "target": "Person"},
        ],
    }
)

CHUNK = Chunk(id="c1", text="some text", document_id="d", source="d.md")


class MockLLM(LLMClient):
    """Returns scripted responses in order (supports retry sequences)."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def complete(self, prompt: str, *, system=None, temperature=0.0, format=None) -> str:
        self.calls += 1
        if not self.responses:
            return ""
        return self.responses.pop(0)


def _ext(client: LLMClient) -> LLMExtractor:
    return LLMExtractor(client, ONTOLOGY, temperature=0.0, max_retries=1, json_mode=False)


def test_valid_extraction_keeps_entities_and_rels() -> None:
    client = MockLLM(
        [
            json.dumps(
                {
                    "entities": [
                        {"name": "Ada", "label": "Person"},
                        {"name": "London", "label": "Place"},
                    ],
                    "relationships": [
                        {"source_name": "Ada", "target_name": "London", "label": "BORN_IN"}
                    ],
                }
            )
        ]
    )
    result = _ext(client).extract(CHUNK)
    assert {e.name for e in result.entities} == {"Ada", "London"}
    assert len(result.relationships) == 1
    assert result.relationships[0].label == "BORN_IN"


def test_off_ontology_entity_label_dropped() -> None:
    client = MockLLM(
        [
            json.dumps(
                {
                    "entities": [
                        {"name": "Ada", "label": "Person"},
                        {"name": "Widget", "label": "Gadget"},  # not in ontology
                    ],
                    "relationships": [],
                }
            )
        ]
    )
    result = _ext(client).extract(CHUNK)
    assert {e.name for e in result.entities} == {"Ada"}


def test_off_ontology_relationship_label_dropped() -> None:
    client = MockLLM(
        [
            json.dumps(
                {
                    "entities": [
                        {"name": "Ada", "label": "Person"},
                        {"name": "Boo", "label": "Person"},
                    ],
                    "relationships": [
                        {
                            "source_name": "Ada",
                            "target_name": "Boo",
                            "label": "MARRIED_TO",
                        },  # not allowed
                    ],
                }
            )
        ]
    )
    result = _ext(client).extract(CHUNK)
    assert result.relationships == []


def test_relationship_wrong_endpoint_types_dropped() -> None:
    # BORN_IN requires Person->Place; Place->Person is invalid.
    client = MockLLM(
        [
            json.dumps(
                {
                    "entities": [
                        {"name": "Ada", "label": "Person"},
                        {"name": "London", "label": "Place"},
                    ],
                    "relationships": [
                        {"source_name": "London", "target_name": "Ada", "label": "BORN_IN"}
                    ],
                }
            )
        ]
    )
    result = _ext(client).extract(CHUNK)
    assert result.relationships == []


def test_json_in_code_fence_parses() -> None:
    payload = json.dumps({"entities": [{"name": "Ada", "label": "Person"}], "relationships": []})
    client = MockLLM([f"```json\n{payload}\n```"])
    result = _ext(client).extract(CHUNK)
    assert {e.name for e in result.entities} == {"Ada"}


def test_malformed_then_valid_on_retry() -> None:
    client = MockLLM(["this is not json", json.dumps({"entities": [], "relationships": []})])
    result = _ext(client).extract(CHUNK)
    assert client.calls == 2  # retried once
    assert result.entities == [] and result.relationships == []


def test_persistently_malformed_skips_chunk() -> None:
    client = MockLLM(["nope", "still nope"])
    result = _ext(client).extract(CHUNK)
    assert result.entities == [] and result.relationships == []
    assert result.chunk_id == "c1"


def test_schemas_round_trip() -> None:
    e = Entity(name="X", label="Person", properties={"a": "1"})
    r = Relationship(source_name="X", target_name="Y", label="KNOWS")
    assert e.model_dump()["label"] == "Person"
    assert r.source_name == "X"
