"""Fixed-size chunker: character windows with overlap.

The fallback for unstructured text where no natural structure exists. Splits on
word boundaries so entities aren't cut mid-token.
"""

from __future__ import annotations

from kg.ingest.chunkers.base import Chunk, Chunker
from kg.ingest.loaders import Document


class FixedChunker(Chunker):
    def __init__(self, chunk_size: int = 1200, overlap: int = 200) -> None:
        """Configure the window size; ``overlap`` must stay below ``chunk_size``
        or the sliding window would never advance."""
        if overlap >= chunk_size:
            raise ValueError(f"overlap ({overlap}) must be < chunk_size ({chunk_size})")
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, document: Document) -> list[Chunk]:
        """Slide character windows over the text, breaking on word boundaries.

        Windows are trimmed back to the last whitespace so an entity is never
        cut mid-token, and consecutive windows share ``overlap`` characters of
        context so statements straddling a boundary still extract once.
        """
        text = document.text
        if not text.strip():
            return []
        chunks: list[Chunk] = []
        start = 0
        idx = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            # nudge `end` back to the last whitespace so we don't split a word
            if end < len(text):
                boundary = text.rfind(" ", start, end)
                if boundary > start:
                    end = boundary
            piece = text[start:end].strip()
            if piece:
                chunks.append(
                    Chunk(
                        id=f"{document.id}#{idx}",
                        text=piece,
                        document_id=document.id,
                        source=document.source,
                        metadata={"strategy": "fixed", "index": idx, **document.metadata},
                    )
                )
                idx += 1
            if end >= len(text):
                break
            start = end - self.overlap if end - self.overlap > start else end
            # avoid infinite loop on tiny windows
            if start <= end - self.chunk_size:
                start = end
        return chunks
