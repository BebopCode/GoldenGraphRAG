"""Chunker implementations: structural (preferred) and fixed-size (fallback)."""

from kg.ingest.chunkers.base import Chunk, Chunker
from kg.ingest.chunkers.fixed import FixedChunker
from kg.ingest.chunkers.structural import StructuralChunker

__all__ = ["Chunk", "Chunker", "FixedChunker", "StructuralChunker", "get_chunker"]


def get_chunker(kind: str, **kwargs: object) -> Chunker:
    """Construct the configured chunker. New chunker = new branch here."""
    kind = kind.lower()
    if kind == "structural":
        return StructuralChunker(max_chars=kwargs.get("max_chars"))
    if kind == "fixed":
        return FixedChunker(
            chunk_size=int(kwargs.get("chunk_size", 1200)),
            overlap=int(kwargs.get("chunk_overlap", 200)),
        )
    raise ValueError(f"Unknown chunker '{kind}'. Supported: structural, fixed")
