"""Abstract graph store. AGE, Neo4j, etc. all implement this."""

from __future__ import annotations

from abc import ABC, abstractmethod


class GraphStore(ABC):
    """The graph-persistence contract.

    ``key`` identifies a node uniquely within a label (for MERGE idempotency).
    ``props`` are the remaining properties. Edges match their endpoints by key.
    """

    @abstractmethod
    def init_graph(self, name: str) -> None:
        """Create the named graph if it does not exist (idempotent)."""
        raise NotImplementedError

    def drop_graph(self, name: str) -> bool:
        """Delete the named graph and everything in it. Returns whether it existed.

        Irreversible. Concrete stores implement this; the default raises so a
        partial implementation fails loudly instead of silently keeping data.
        """
        raise NotImplementedError

    @abstractmethod
    def upsert_node(self, label: str, key: dict, props: dict) -> None:
        """Insert or update a node, matched on ``key`` (e.g. {"name": ...})."""
        raise NotImplementedError

    @abstractmethod
    def upsert_edge(self, label: str, src: dict, tgt: dict, props: dict) -> None:
        """Insert or update an edge between two nodes matched by their keys."""
        raise NotImplementedError

    @abstractmethod
    def query(self, cypher: str, params: dict | None = None) -> list[dict]:
        """Run an openCypher query and return rows as Python dicts."""
        raise NotImplementedError
