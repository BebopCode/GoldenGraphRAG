"""Configuration: ontology + app settings, loaded and validated at startup."""

from kg.config.models import (
    DatabaseSettings,
    LLMSettings,
    NodeType,
    Ontology,
    RelationshipType,
    Settings,
)

__all__ = [
    "DatabaseSettings",
    "LLMSettings",
    "NodeType",
    "Ontology",
    "RelationshipType",
    "Settings",
]
