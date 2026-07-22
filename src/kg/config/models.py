"""Pydantic models for configuration: the ontology and the app settings.

The ontology is the single biggest lever on extraction quality — constraining
the LLM to a fixed, closed set of labels is what prevents messy, inconsistent
graphs. We validate it hard here so a bad ontology fails loudly at startup.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class NodeType(BaseModel):
    """A node label declared in the ontology (e.g. Article, Institution)."""

    label: str
    description: str | None = None
    properties: list[str] = Field(default_factory=list)


class RelationshipType(BaseModel):
    """An edge label with allowed source/target node labels."""

    label: str
    description: str | None = None
    source: str
    target: str
    properties: list[str] = Field(default_factory=list)


class Ontology(BaseModel):
    """The full ontology: node types + relationship types.

    A relationship is only valid if its source and target reference declared
    node labels. Duplicate labels are rejected. This is enforced here, not at
    extraction time, so misconfigurations surface immediately.
    """

    name: str
    description: str | None = None
    node_types: list[NodeType]
    relationship_types: list[RelationshipType] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_consistency(self) -> Ontology:
        if not self.node_types:
            raise ValueError("ontology must define at least one node_type")

        node_labels = [nt.label for nt in self.node_types]
        dup_nodes = {label for label in node_labels if node_labels.count(label) > 1}
        if dup_nodes:
            raise ValueError(f"duplicate node_type labels: {sorted(dup_nodes)}")

        node_label_set = set(node_labels)
        for rt in self.relationship_types:
            if rt.source not in node_label_set:
                raise ValueError(
                    f"relationship_type '{rt.label}' references unknown source "
                    f"node '{rt.source}'. Allowed: {sorted(node_label_set)}"
                )
            if rt.target not in node_label_set:
                raise ValueError(
                    f"relationship_type '{rt.label}' references unknown target "
                    f"node '{rt.target}'. Allowed: {sorted(node_label_set)}"
                )

        rel_labels = [rt.label for rt in self.relationship_types]
        dup_rels = {label for label in rel_labels if rel_labels.count(label) > 1}
        if dup_rels:
            raise ValueError(f"duplicate relationship_type labels: {sorted(dup_rels)}")

        return self

    # -- convenience lookups used by the extractor and store --
    def node_labels(self) -> set[str]:
        return {nt.label for nt in self.node_types}

    def relationship_labels(self) -> set[str]:
        return {rt.label for rt in self.relationship_types}

    def allowed_rel_pairs(self) -> set[tuple[str, str, str]]:
        """Set of (rel_label, source_label, target_label) triples the LLM may emit."""
        return {(rt.label, rt.source, rt.target) for rt in self.relationship_types}

    def node_properties(self, label: str) -> list[str]:
        for nt in self.node_types:
            if nt.label == label:
                return nt.properties
        return []

    def relationship_properties(self, label: str) -> list[str]:
        for rt in self.relationship_types:
            if rt.label == label:
                return rt.properties
        return []


class DatabaseSettings(BaseModel):
    """PostgreSQL + AGE connection settings (from .env)."""

    user: str
    password: str
    dbname: str
    host: str = "localhost"
    port: int = 5432
    graph_name: str = "kg_graph"

    @property
    def dsn(self) -> str:
        """A libpq-style connection string for psycopg."""
        return (
            f"host={self.host} port={self.port} dbname={self.dbname} "
            f"user={self.user} password={self.password}"
        )


class OllamaSettings(BaseModel):
    """Ollama HTTP API settings (from .env)."""

    host: str = "http://localhost:11434"
    model: str = "llama3.1"
    timeout: float = 120.0


class Settings(BaseModel):
    """Top-level settings: connection config + tuning knobs.

    Populated by the loader from .env (secrets/hosts) merged with the settings
    YAML (tuning). Env values win where they overlap.
    """

    db: DatabaseSettings
    ollama: OllamaSettings
    ontology_path: Path
    chunker: str = "structural"
    log_level: str = "INFO"

    # tuning
    temperature: float = 0.0
    json_mode: bool = True
    chunk_size: int = 1200
    chunk_overlap: int = 200
    extract_batch_size: int = 8
    max_retries: int = 1
    use_embeddings_fusion: bool = False
