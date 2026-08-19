"""Abstract LLM client + the error contract every implementation raises.

Every provider (OpenRouter, vLLM, OpenAI, Ollama, ...) goes through
:class:`LLMClient`. Because they all speak the OpenAI Chat Completions API,
one concrete implementation covers all of them — providers are config values.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMError(RuntimeError):
    """Base class for client-side LLM failures (bad config, dead endpoint)."""


class LLMCallError(LLMError):
    """A completion attempt failed permanently (network, auth, malformed).

    Raised only after retries are exhausted, so callers can treat it as
    "this chunk is poisoned, skip it" rather than "the run is dead".
    """


class LLMClient(ABC):
    """Minimal text-completion interface used by the extractor.

    Keeping this tiny is the point: a new provider is just this one method.
    """

    @abstractmethod
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
        """Return the model's completion as a string.

        Args:
            prompt: The user prompt text.
            system: Optional system message steering the model.
            temperature: Sampling temperature (0 = deterministic).
            format: Pass ``"json"`` to request structured/JSON output where the
                provider supports it (legacy knob, superseded by ``json_schema``).
            json_schema: Optional JSON Schema the response must conform to.
                Providers with structured outputs (OpenAI, vLLM, some OpenRouter
                endpoints) enforce this at decode time; others ignore it and the
                prompt remains the floor.
            schema_name: Name for the schema when the API requires one.
        """
        raise NotImplementedError

    def health_check(self) -> dict[str, Any]:
        """Cheap liveness/auth probe. Subclasses override; default is unknown."""
        return {"ok": False, "error": "health_check not implemented"}

    def close(self) -> None:  # noqa: B027 - intentional optional no-op
        """Release connections. No-op by default."""
