"""Pipeline orchestration: load -> chunk -> extract -> fuse -> store.

This is the seam that composes every module behind the interfaces. Swapping the
LLM, the chunker, or the store only changes which concrete class is constructed
here — the flow stays the same.

Extraction fans out across threads (network latency dominates once the model is
remote, and vLLM's continuous batching makes 32 concurrent requests nearly free
compared to 4). Fusion and the AGE upserts stay single-threaded by design: the
MERGE-based writes are not safe to interleave, so extractions are collected
first, then fused, then written.
"""

from __future__ import annotations

import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from kg.config.loader import get_settings, load_ontology
from kg.config.models import Settings
from kg.extract.llm_extractor import LLMExtractor
from kg.extract.schemas import ExtractionResult
from kg.fusion.resolver import EntityResolver
from kg.ingest.chunkers import get_chunker
from kg.ingest.loaders import load_dataset
from kg.llm.base import LLMCallError
from kg.llm.factory import build_llm_client
from kg.store.age_store import AgeGraphStore

logger = logging.getLogger(__name__)

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = None  # type: ignore[assignment]


def _progress(iterable, desc: str):
    """Wrap ``iterable`` in a tqdm bar — but only on an interactive stderr.

    Piped/CI runs (``kg ingest > log``) get the plain iterable so logs stay clean.
    """
    if tqdm is None or not sys.stderr.isatty():
        return iterable
    return tqdm(iterable, desc=desc)


def _extract_all(extractor: LLMExtractor, chunks: list, workers: int) -> list[ExtractionResult]:
    """Extract concurrently, preserving chunk order, isolating per-chunk failures.

    One poisoned chunk must not kill a 6-hour ingest: permanent LLM failures are
    logged and that chunk yields an empty result instead.
    """
    results: list[ExtractionResult | None] = [None] * len(chunks)
    bar = _progress(chunks, "extract")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(extractor.extract, chunk): i for i, chunk in enumerate(bar)}
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except LLMCallError as exc:
                logger.error("chunk %s failed permanently: %s", chunks[i].id, exc)
                results[i] = ExtractionResult(entities=[], relationships=[], chunk_id=chunks[i].id)
            except Exception as exc:  # extraction must never abort the whole run
                logger.exception("Extraction failed for chunk %s: %s", chunks[i].id, exc)
                results[i] = ExtractionResult(entities=[], relationships=[], chunk_id=chunks[i].id)

    return [r for r in results if r is not None]  # order preserved


def run_pipeline(
    dataset: str | Path,
    *,
    settings: Settings | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Run the full pipeline end-to-end: load -> chunk -> extract -> fuse -> store.

    Args:
        dataset: File or directory to ingest (see :func:`load_dataset`).
        settings: Validated settings; loaded from .env/config when omitted.
        limit: Keep only the first N chunks — useful for a cheap partial run.

    Returns:
        Stats dict with ``documents``, ``chunks``, ``nodes`` and ``edges``
        (nodes/edges are post-fusion counts of what was written).
    """
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

    # 3. extract (concurrent; one shared, thread-safe client)
    client = build_llm_client(settings.llm)
    logger.info(
        "LLM: provider=%s model=%s base_url=%s concurrency=%d",
        settings.llm.provider,
        settings.llm.model,
        settings.llm.base_url,
        settings.llm.concurrency,
    )
    extractor = LLMExtractor.from_settings(
        client,
        ontology,
        temperature=settings.temperature,
        max_retries=settings.max_retries,
        json_mode=settings.json_mode,
    )
    results = _extract_all(extractor, chunks, settings.llm.concurrency)

    total_entities = sum(len(r.entities) for r in results)
    total_rels = sum(len(r.relationships) for r in results)
    logger.info(
        "Extracted %d entities / %d relationships (pre-fusion).", total_entities, total_rels
    )
    usage = getattr(client, "usage_summary", None)
    if callable(usage):
        logger.info("LLM usage: %s", usage())

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
