"""Pipeline orchestration: load -> chunk -> extract -> fuse -> store.

This is the seam that composes every module behind the interfaces. Swapping the
LLM, the chunker, or the store only changes which concrete class is constructed
here — the flow stays the same.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from kg.config.loader import get_settings, load_ontology
from kg.config.models import Settings
from kg.extract.llm_extractor import LLMExtractor
from kg.extract.schemas import ExtractionResult
from kg.fusion.resolver import EntityResolver
from kg.ingest.chunkers import get_chunker
from kg.ingest.loaders import load_dataset
from kg.llm.ollama_client import OllamaLLMClient
from kg.store.age_store import AgeGraphStore

logger = logging.getLogger(__name__)

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = None  # type: ignore[assignment]


def _progress(iterable, desc: str):
    if tqdm is None or not sys.stderr.isatty():
        return iterable
    return tqdm(iterable, desc=desc)


def run_pipeline(
    dataset: str | Path,
    *,
    settings: Settings | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Run the full pipeline end-to-end. Returns a small stats dict."""
    settings = settings or get_settings()
    ontology = load_ontology(settings=settings)

    # 1. load
    documents = load_dataset(dataset)
    logger.info("Loaded %d document(s) from %s", len(documents), dataset)

    # 2. chunk
    chunker = get_chunker(
        settings.chunker,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    chunks: list = []
    for doc in documents:
        chunks.extend(chunker.chunk(doc))
    if limit:
        chunks = chunks[:limit]
        logger.info("Limiting to first %d chunk(s).", len(chunks))
    logger.info("Produced %d chunk(s) (chunker=%s).", len(chunks), settings.chunker)
    if not chunks:
        return {"documents": len(documents), "chunks": 0, "nodes": 0, "edges": 0}

    # 3. extract
    client = OllamaLLMClient.from_settings(settings)
    extractor = LLMExtractor.from_settings(
        client,
        ontology,
        temperature=settings.temperature,
        max_retries=settings.max_retries,
        json_mode=settings.json_mode,
    )
    results: list[ExtractionResult] = []
    for chunk in _progress(chunks, "extract"):
        try:
            results.append(extractor.extract(chunk))
        except Exception as exc:  # extraction must never abort the whole run
            logger.exception("Extraction failed for chunk %s: %s", chunk.id, exc)
            results.append(ExtractionResult(entities=[], relationships=[], chunk_id=chunk.id))

    total_entities = sum(len(r.entities) for r in results)
    total_rels = sum(len(r.relationships) for r in results)
    logger.info(
        "Extracted %d entities / %d relationships (pre-fusion).", total_entities, total_rels
    )

    # 4. fuse
    entities, relationships = EntityResolver(use_embeddings=settings.use_embeddings_fusion).resolve(
        results
    )

    # 5. store — nodes first (edges MATCH them by name)
    store = AgeGraphStore.from_settings(settings)
    store.init_graph(settings.db.graph_name)
    for e in entities:
        store.upsert_node(e.label, {"name": e.name}, dict(e.properties))
    for r in relationships:
        store.upsert_edge(
            r.label, {"name": r.source_name}, {"name": r.target_name}, dict(r.properties)
        )

    client.close()
    store.close()

    stats = {
        "documents": len(documents),
        "chunks": len(chunks),
        "nodes": len(entities),
        "edges": len(relationships),
    }
    logger.info("Pipeline complete: %s", stats)
    return stats
