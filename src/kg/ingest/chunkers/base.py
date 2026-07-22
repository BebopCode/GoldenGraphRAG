"""Chunker ABC and the shared ``Chunk`` model."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    """A slice of a document fed to the extractor.

    ``metadata`` carries structural context (e.g. the active section heading,
    parent part) so the extractor still knows *where* a chunk came from after
    the document has been split up.
    """

    id: str
    text: str
    document_id: str
    source: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Chunker(ABC):
    """Splits a :class:`~kg.ingest.loaders.Document` into :class:`Chunk` objects."""

    @abstractmethod
    def chunk(self, document: Document) -> list[Chunk]:
        raise NotImplementedError


# Avoid a hard import cycle: Document is defined in loaders.py, which does not
# import this module. Import lazily under TYPE_CHECKING for type hints.
from typing import TYPE_CHECKING  # noqa: E402

if TYPE_CHECKING:  # pragma: no cover
    from kg.ingest.loaders import Document  # noqa: F401
