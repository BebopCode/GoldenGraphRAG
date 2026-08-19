"""One LLM client for every OpenAI-compatible endpoint.

OpenRouter, vLLM, OpenAI, Together, Fireworks, LiteLLM and Ollama all speak the
OpenAI Chat Completions API, so the provider is a ``base_url`` + ``api_key``
pair, not a code path. What *does* vary is structured-output support, so this
client negotiates it:

  * ``json_schema``  — standard ``response_format`` (OpenAI, vLLM, and the
    OpenRouter endpoints that advertise ``structured_outputs``).
  * vLLM legacy      — ``extra_body={"structured_outputs": {"json": schema}}``
    (``guided_json`` was removed in vLLM 0.12.0); tried when a 400 suggests the
    server rejected ``response_format``.
  * ``json_object``  — valid JSON, schema left to the prompt. The floor.

In ``auto`` mode it starts strict and degrades on rejection, remembering the
mode that worked so the probe costs one request per process, not per chunk.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from openai.types.chat import ChatCompletionMessageParam

from kg.config.models import LLMSettings
from kg.llm.base import LLMCallError, LLMClient

logger = logging.getLogger(__name__)

# Seconds to sleep before retry N (index 0 = first retry). Bounded so a dead
# endpoint still fails fast enough for `kg info --check-llm`.
_BACKOFF_SCHEDULE = (1.0, 2.0, 4.0, 8.0)


class OpenAICompatibleLLMClient(LLMClient):
    """Chat Completions client shared across providers.

    One instance is safe to use from many threads (the underlying SDK client
    is thread-safe), which is what makes concurrent chunk extraction cheap.
    """

    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings
        self._client = OpenAI(
            api_key=settings.api_key or "none",
            base_url=settings.base_url,
            timeout=settings.timeout,
            max_retries=0,  # we own retry policy (backoff + structured-mode fallback)
            default_headers=settings.extra_headers or None,
        )
        # Auto-detected structured-output mode; guarded because complete() runs
        # in worker threads.
        self._mode_lock = threading.Lock()
        self._mode: str | None = (
            None if settings.structured_mode == "auto" else settings.structured_mode
        )
        self._usage_lock = threading.Lock()
        self._usage: dict[str, Any] = {
            "requests": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    # -- completion --------------------------------------------------------
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        format: str | None = None,
        json_schema: dict[str, Any] | None = None,
        schema_name: str = "extraction",
    ) -> str:
        messages: list[ChatCompletionMessageParam] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        mode = self._effective_mode(json_schema, format)
        last_exc: Exception | None = None
        attempts = 1 + max(0, self.settings.max_retries)

        while True:
            kwargs = self._request_kwargs(mode, json_schema, schema_name, temperature)
            try:
                resp = self._client.chat.completions.create(
                    model=self.settings.model,
                    messages=messages,
                    temperature=temperature,
                    **kwargs,
                )
            except APITimeoutError as exc:
                last_exc = exc
                attempts -= 1
                logger.warning("LLM call timed out (%d retries left)", attempts)
            except APIConnectionError as exc:
                last_exc = exc
                attempts -= 1
                logger.warning("LLM endpoint unreachable (%d retries left)", attempts)
            except APIStatusError as exc:
                status = exc.status_code
                new_mode = self._downgrade_mode(mode, json_schema, exc)
                if new_mode:
                    mode = new_mode
                    continue  # retry immediately with a weaker structured mode
                last_exc = exc
                if status == 400:
                    # A 400 that isn't a response_format rejection will not heal
                    # with retries — fail now with the server's message.
                    raise LLMCallError(f"LLM rejected the request (400): {exc}") from exc
                if status not in (408, 409, 425, 429) and status < 500:
                    raise LLMCallError(f"LLM call failed (HTTP {status}): {exc}") from exc
                attempts -= 1
                logger.warning("LLM call failed (HTTP %d, %d retries left)", status, attempts)
            else:
                self._record_usage(resp)
                self._warn_if_truncated(resp)
                content = resp.choices[0].message.content or ""
                logger.debug(
                    "LLM response <- %d chars (model=%s, mode=%s)",
                    len(content),
                    self.settings.model,
                    mode,
                )
                return content

            if attempts <= 0:
                break
            time.sleep(_BACKOFF_SCHEDULE[min(attempts, len(_BACKOFF_SCHEDULE) - 1)])

        raise LLMCallError(f"LLM call failed after retries: {last_exc}")

    # -- structured-output negotiation ------------------------------------
    def _effective_mode(self, json_schema: dict[str, Any] | None, format: str | None) -> str:
        """Pick the structured-output mode for this call."""
        configured = self.settings.structured_mode
        if configured == "none":
            return "none"
        if json_schema is None:
            # No schema to enforce; legacy json_mode still asks for valid JSON.
            return "json_object" if (format == "json" and configured != "none") else "none"
        if configured == "auto":
            with self._mode_lock:
                return self._mode or "json_schema"
        return configured

    def _request_kwargs(
        self,
        mode: str,
        json_schema: dict[str, Any] | None,
        schema_name: str,
        temperature: float,
    ) -> dict[str, Any]:
        """Translate the mode into chat.completions.create() kwargs."""
        if mode == "json_schema" and json_schema is not None:
            kwargs: dict[str, Any] = {
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "schema": json_schema,
                        "strict": False,
                    },
                }
            }
            if self.settings.provider == "openrouter":
                # Without this, OpenRouter may route to an endpoint that ignores
                # the schema and silently degrade to plain JSON.
                routing: dict[str, Any] = {"require_parameters": True}
                if self.settings.allowed_providers:
                    routing["order"] = list(self.settings.allowed_providers)
                    routing["allow_fallbacks"] = False
                kwargs["extra_body"] = {"provider": routing}
            return kwargs
        if mode == "json_object":
            return {"response_format": {"type": "json_object"}}
        if mode == "vllm_structured_outputs" and json_schema is not None:
            # vLLM >= 0.12.0 spelling (guided_json was removed)
            return {"extra_body": {"structured_outputs": {"json": json_schema}}}
        if mode == "vllm_guided_json" and json_schema is not None:
            # vLLM < 0.12.0 spelling
            return {"extra_body": {"guided_json": json_schema}}
        # mode == "none": the prompt carries the schema; no response_format.
        return {}

    def _downgrade_mode(
        self, mode: str, json_schema: dict[str, Any] | None, exc: APIStatusError
    ) -> str | None:
        """On a 400 that smells like response_format rejection, weaken the mode.

        Returns the next mode to try (remembered for the process), or None if
        this error isn't about structured output.
        """
        if exc.status_code != 400 or json_schema is None:
            return None
        body = str(exc).lower()
        if not any(
            token in body
            for token in ("response_format", "json_schema", "structured", "guided", "schema")
        ):
            return None

        downgrade = {
            "json_schema": "vllm_structured_outputs",
            "vllm_structured_outputs": "vllm_guided_json",
            "vllm_guided_json": "json_object",
        }
        nxt = downgrade.get(mode)
        if nxt is None:
            return None
        with self._mode_lock:
            self._mode = nxt
        logger.warning(
            "Endpoint rejected structured mode %r; downgrading to %r (remembered).",
            mode,
            nxt,
        )
        return nxt

    # -- observability -----------------------------------------------------
    def _record_usage(self, resp: Any) -> None:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return
        with self._usage_lock:
            self._usage["requests"] += 1
            self._usage["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
            self._usage["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0
            self._usage["total_tokens"] += getattr(usage, "total_tokens", 0) or 0
            # OpenRouter returns real dollars here; other providers omit it.
            cost = getattr(usage, "cost", None)
            if cost is not None:
                self._usage["cost"] = self._usage.get("cost", 0.0) + float(cost)

    def usage_summary(self) -> dict[str, Any]:
        with self._usage_lock:
            return dict(self._usage)

    @staticmethod
    def _warn_if_truncated(resp: Any) -> None:
        try:
            finish = resp.choices[0].finish_reason
        except (AttributeError, IndexError):
            return
        if finish == "length":
            logger.warning(
                "LLM response truncated (finish_reason=length): raise LLM_MAX_TOKENS / "
                "--max-model-len, or shrink CHUNK_SIZE — extractions will be lossy."
            )

    def health_check(self) -> dict[str, Any]:
        """One tiny request: wrong base URL / dead key surfaces here, not mid-run."""
        out: dict[str, Any] = {
            "provider": self.settings.provider,
            "base_url": self.settings.base_url,
            "model": self.settings.model,
        }
        try:
            resp = self._client.chat.completions.create(
                model=self.settings.model,
                messages=[{"role": "user", "content": "say ok"}],
                max_tokens=5,
                timeout=15.0,
            )
            out["ok"] = True
            out["reply"] = (resp.choices[0].message.content or "")[:40]
        except Exception as exc:  # noqa: BLE001 - report, don't raise
            out["ok"] = False
            out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    def close(self) -> None:
        self._client.close()


def _json_dumps_for_log(schema: dict[str, Any]) -> str:
    return json.dumps(schema)[:200]
