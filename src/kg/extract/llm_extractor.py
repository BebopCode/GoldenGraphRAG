"""Ontology-constrained LLM extractor.

Flow per chunk:
  1. Build the prompt (ontology injected) and call the LLM, sending the JSON
     Schema alongside it so endpoints with structured outputs can constrain
     decoding. The prompt keeps its own copy of the schema: some endpoints
     ignore ``response_format``, and the prompt is the floor.
  2. Parse the JSON the model returns.
  3. Validate against the ontology: drop entities/relationships whose labels
     aren't allowed (or whose endpoints break the declared source/target rules),
     and log everything that's dropped so extraction stays observable.
  4. On malformed JSON, retry once with a stricter reminder; if it still fails,
     skip the chunk and log it (extraction is probabilistic — never crash).
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache

from kg.config.models import Ontology
from kg.extract.base import Extractor
from kg.extract.prompts import SYSTEM_PROMPT, build_extraction_prompt, build_retry_prompt
from kg.extract.schemas import Entity, ExtractionResult, Relationship
from kg.ingest.chunkers.base import Chunk
from kg.llm.base import LLMCallError, LLMClient

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.DOTALL)


@lru_cache(maxsize=1)
def _extraction_schema() -> dict:
    """The Pydantic schema for ExtractionResult, computed once per process.

    lru_cache also gives every thread the same dict object, which keeps the
    schema thread-safe to pass around during concurrent extraction.
    """
    return ExtractionResult.model_json_schema()


class LLMExtractor(Extractor):
    def __init__(
        self,
        client: LLMClient,
        ontology: Ontology,
        *,
        temperature: float = 0.0,
        max_retries: int = 1,
        json_mode: bool = True,
    ) -> None:
        """Bind the client, ontology, and extraction knobs (see the class docstring)."""
        self.client = client
        self.ontology = ontology
        self.temperature = temperature
        self.max_retries = max_retries
        self.json_mode = json_mode

    @staticmethod
    def from_settings(  # type: ignore[override]
        client: LLMClient, ontology: Ontology, **kwargs: object
    ) -> LLMExtractor:
        """Factory used by the pipeline: build an extractor from loose settings kwargs."""
        return LLMExtractor(
            client,
            ontology,
            temperature=float(kwargs.get("temperature", 0.0)),
            max_retries=int(kwargs.get("max_retries", 1)),
            json_mode=bool(kwargs.get("json_mode", True)),
        )

    # -- main entry -------------------------------------------------------
    def extract(self, chunk: Chunk) -> ExtractionResult:
        """Extract entities/relationships from one chunk, constrained to the ontology.

        Never raises for bad model output: unparseable JSON (after the retry)
        yields an empty result with a warning, so one bad chunk doesn't abort
        the run. Off-ontology output is dropped inside ``_validate``.
        """
        prompt = build_extraction_prompt(chunk.text, self.ontology)
        data = self._call_and_parse(prompt)

        if data is None:
            logger.warning("Chunk %s yielded no parseable JSON; skipped.", chunk.id)
            return ExtractionResult(entities=[], relationships=[], chunk_id=chunk.id)

        return self._validate(data, chunk.id)

    # -- LLM call + JSON parsing with one retry ---------------------------
    def _call_and_parse(self, prompt: str) -> dict | None:
        """Call the LLM and parse its output to a dict.

        Retries up to ``max_retries`` times, re-sending the prompt with a
        stricter reminder after unparseable output. Returns None only when
        every attempt failed (the caller then skips the chunk).
        """
        fmt = "json" if self.json_mode else None
        attempts = 1 + max(0, self.max_retries)
        last_raw = ""
        for attempt in range(attempts):
            current = prompt if attempt == 0 else build_retry_prompt(prompt)
            try:
                raw = self.client.complete(
                    current,
                    system=SYSTEM_PROMPT,
                    temperature=self.temperature,
                    format=fmt,
                    json_schema=_extraction_schema(),
                    schema_name="kg_extraction",
                )
            except LLMCallError as exc:
                logger.error("LLM call failed permanently (attempt %d): %s", attempt + 1, exc)
                continue
            last_raw = raw
            data = _safe_json(raw)
            if data is not None:
                return data
            logger.warning("Attempt %d: could not parse JSON from LLM output.", attempt + 1)
        logger.debug("Unparseable LLM output was: %s", last_raw[:300])
        return None

    # -- ontology validation ---------------------------------------------
    def _validate(self, data: dict, chunk_id: str) -> ExtractionResult:
        """Filter raw model output against the ontology, logging every drop.

        Drops entities/relationships with missing fields or unknown labels,
        and relationships whose (label, src_label, tgt_label) triple isn't
        declared. Endpoints that name no extracted entity are kept — fusion
        may still resolve them against other chunks.
        """
        node_labels = self.ontology.node_labels()
        rel_labels = self.ontology.relationship_labels()
        allowed_pairs = self.ontology.allowed_rel_pairs()

        # label lookup: entity name -> label (first seen wins; fusion dedups later)
        name_to_label: dict[str, str] = {}

        entities: list[Entity] = []
        for raw in data.get("entities", []) or []:
            name = str(raw.get("name", "")).strip()
            label = str(raw.get("label", "")).strip()
            if not name or not label:
                logger.info("[%s] dropping entity missing name/label: %r", chunk_id, raw)
                continue
            if label not in node_labels:
                logger.info(
                    "[%s] dropping off-ontology entity %r (label %r)", chunk_id, name, label
                )
                continue
            props = {str(k): str(v) for k, v in (raw.get("properties") or {}).items()}
            entities.append(Entity(name=name, label=label, properties=props))
            name_to_label.setdefault(name, label)

        relationships: list[Relationship] = []
        for raw in data.get("relationships", []) or []:
            src = str(raw.get("source_name", "")).strip()
            tgt = str(raw.get("target_name", "")).strip()
            label = str(raw.get("label", "")).strip()
            if not src or not tgt or not label:
                logger.info("[%s] dropping relationship missing fields: %r", chunk_id, raw)
                continue
            if label not in rel_labels:
                logger.info(
                    "[%s] dropping off-ontology relationship %r (label %r)", chunk_id, src, label
                )
                continue
            # endpoints must reference extracted entities (forward ref is allowed but warned)
            src_label = name_to_label.get(src)
            tgt_label = name_to_label.get(tgt)
            if src_label is None or tgt_label is None:
                logger.info(
                    "[%s] rel %r -[%r]-> %r unknown endpoint; kept (fusion may resolve).",
                    chunk_id,
                    src,
                    label,
                    tgt,
                )
            elif allowed_pairs and (label, src_label, tgt_label) not in allowed_pairs:
                logger.info(
                    "[%s] dropping relationship %r -[%r]-> %r: %s->%s not allowed by ontology.",
                    chunk_id,
                    src,
                    label,
                    tgt,
                    src_label,
                    tgt_label,
                )
                continue
            props = {str(k): str(v) for k, v in (raw.get("properties") or {}).items()}
            relationships.append(
                Relationship(source_name=src, target_name=tgt, label=label, properties=props)
            )

        return ExtractionResult(entities=entities, relationships=relationships, chunk_id=chunk_id)


def _safe_json(raw: str) -> dict | None:
    """Extract and parse a JSON object from raw LLM output (tolerates fences/prose)."""
    if not raw or not raw.strip():
        return None
    s = _FENCE_RE.sub("", raw.strip())
    # If there's stray prose around the JSON, narrow to the outermost braces.
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end > start:
        s = s[start : end + 1]
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed
