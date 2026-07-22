"""Core data contracts shared across the extraction / fusion / store layers.

These are the glue between modules. Defined first, depended on everywhere.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Entity(BaseModel):
    """A node extracted from text. `label` must be one of the ontology's node types."""

    name: str
    label: str
    properties: dict[str, str] = Field(default_factory=dict)


class Relationship(BaseModel):
    """An edge extracted from text. `label` must be one of the ontology's relationship types."""

    source_name: str
    target_name: str
    label: str
    properties: dict[str, str] = Field(default_factory=dict)


class ExtractionResult(BaseModel):
    """Everything extracted from a single chunk."""

    entities: list[Entity] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    chunk_id: str
