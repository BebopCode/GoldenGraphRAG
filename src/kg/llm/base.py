"""Abstract LLM client. Every concrete client (Ollama, OpenAI, ...) implements this."""

from __future__ import annotations

from abc import ABC, abstractmethod


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
    ) -> str:
        """Return the model's completion as a string.

        Args:
            prompt: The user prompt text.
            system: Optional system message steering the model.
            temperature: Sampling temperature (0 = deterministic).
            format: Pass ``"json"`` to request structured/JSON output where the
                provider supports it (Ollama does).
        """
        raise NotImplementedError
