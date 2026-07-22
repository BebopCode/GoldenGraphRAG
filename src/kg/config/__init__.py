"""Configuration: ontology + app settings, loaded and validated at startup."""

from kg.config.models import (
    DatabaseSettings,
    NodeType,
    OllamaSettings,
    Ontology,
    RelationshipType,
    Settings,
)

__all__ = [
    "DatabaseSettings",
    "NodeType",
    "Ontology",
    "OllamaSettings",
    "RelationshipType",
    "Settings",
]
