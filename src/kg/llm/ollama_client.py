"""Ollama implementation of :class:`~kg.llm.base.LLMClient`.

Talks to a local Ollama server over HTTP (``/api/chat``). ``format='json'`` is
passed straight through so Ollama constrains the output to valid JSON — the
single biggest help for reliable extraction parsing.
"""

from __future__ import annotations

import logging

import httpx

from kg.config.models import Settings
from kg.llm.base import LLMClient

logger = logging.getLogger(__name__)


class OllamaLLMClient(LLMClient):
    def __init__(self, host: str, model: str, timeout: float = 120.0) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._http = httpx.Client(timeout=timeout)

    @classmethod
    def from_settings(cls, settings: Settings) -> OllamaLLMClient:
        o = settings.ollama
        return cls(host=o.host, model=o.model, timeout=o.timeout)

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        format: str | None = None,
    ) -> str:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if format:
            payload["format"] = format

        url = f"{self.host}/api/chat"
        logger.debug("Ollama request -> %s (model=%s, %d chars)", url, self.model, len(prompt))
        try:
            resp = self._http.post(url, json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Ollama call to {url} failed: {exc}") from exc

        data = resp.json()
        if data.get("error"):
            raise RuntimeError(f"Ollama returned an error: {data['error']}")
        content = data.get("message", {}).get("content", "")
        logger.debug("Ollama response <- %d chars", len(content))
        return content

    def close(self) -> None:
        self._http.close()
