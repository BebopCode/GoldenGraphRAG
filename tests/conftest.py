"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def pytest_configure(config) -> None:
    config.addinivalue_line("markers", "integration: needs the AGE container running")


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def generic_ontology_path() -> Path:
    return PROJECT_ROOT / "config" / "ontologies" / "generic.yaml"


@pytest.fixture
def constitution_ontology_path() -> Path:
    return PROJECT_ROOT / "config" / "ontologies" / "constitution.yaml"


@pytest.fixture
def age_store():
    """A live AgeGraphStore. Tests skip (not fail) if the DB is unreachable."""
    from kg.config.loader import load_settings
    from kg.store.age_store import AgeGraphStore

    settings = load_settings()
    store = AgeGraphStore.from_settings(settings)
    try:
        store.init_graph(settings.db.graph_name)
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"AGE container not reachable: {exc}")
    yield store
    store.close()
