"""Abstract extractor."""

from __future__ import annotations

from abc import ABC, abstractmethod

from kg.config.models import Ontology
from kg.extract.schemas import ExtractionResult
from kg.ingest.chunkers.base import Chunk
from kg.llm.base import LLMClient


class Extractor(ABC):
    """Turns a chunk into an ontology-constrained :class:`ExtractionResult`."""

    @abstractmethod
    def extract(self, chunk: Chunk) -> ExtractionResult:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def from_settings(client: LLMClient, ontology: Ontology, **kwargs: object) -> Extractor:
        """Factory so the pipeline can construct the configured extractor."""
        raise NotImplementedError
