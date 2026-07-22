"""Integration tests for AgeGraphStore. Requires the AGE container running.

Skipped automatically if the database isn't reachable, so `pytest` still works
without Docker. Run with the container up:
    docker compose up -d && pytest tests/integration
"""

from __future__ import annotations

import uuid

import pytest

from kg.store.age_store import AgeGraphStore

pytestmark = pytest.mark.integration


@pytest.fixture
def store(age_store):
    return age_store


def test_init_graph_idempotent(store: AgeGraphStore) -> None:
    # Should not raise whether or not the graph already exists.
    store.init_graph("kg_graph")
    store.init_graph("kg_graph")


def test_upsert_and_query_round_trip(store: AgeGraphStore) -> None:
    suffix = uuid.uuid4().hex[:8]
    a, b = f"NodeA_{suffix}", f"NodeB_{suffix}"
    store.upsert_node("TestThing", {"name": a}, {"kind": "alpha"})
    store.upsert_node("TestThing", {"name": b}, {"kind": "beta"})
    ok = store.upsert_edge("RELATED_TO", {"name": a}, {"name": b}, {"why": "test"})
    assert ok

    rows = store.query(f"MATCH (n:TestThing) WHERE n.name = '{a}' RETURN n")
    assert len(rows) == 1
    node = rows[0]
    assert node["label"] == "TestThing"
    assert node["properties"]["name"] == a
    assert node["properties"]["kind"] == "alpha"


def test_upsert_node_is_idempotent(store: AgeGraphStore) -> None:
    name = f"Idem_{uuid.uuid4().hex[:8]}"
    store.upsert_node("TestThing", {"name": name}, {"kind": "x"})
    store.upsert_node("TestThing", {"name": name}, {"kind": "y"})  # update
    rows = store.query(f"MATCH (n:TestThing) WHERE n.name = '{name}' RETURN n")
    assert len(rows) == 1, "MERGE must not duplicate on re-upsert"
    assert rows[0]["properties"]["kind"] == "y", "props should be updated"


def test_multi_column_query(store: AgeGraphStore) -> None:
    suffix = uuid.uuid4().hex[:8]
    a, b = f"Multi_{suffix}", f"MultiB_{suffix}"
    store.upsert_node("TestThing", {"name": a}, {})
    store.upsert_node("TestThing", {"name": b}, {})
    store.upsert_edge("RELATED_TO", {"name": a}, {"name": b}, {})

    rows = store.query(
        f"MATCH (x:TestThing)-[r:RELATED_TO]->(y:TestThing) "
        f"WHERE x.name = '{a}' RETURN x.name, y.name"
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["col0"] == a
    assert row["col1"] == b


def test_edge_to_missing_endpoint_is_skipped(store: AgeGraphStore, caplog) -> None:
    # No node named this exists; edge should be skipped, not error.
    created = store.upsert_edge(
        "RELATED_TO", {"name": f"Ghost_{uuid.uuid4().hex[:8]}"}, {"name": "AlsoGhost"}, {}
    )
    assert created is False
