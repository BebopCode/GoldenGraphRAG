"""LLM client abstraction. One OpenAI-compatible client covers every provider."""

from kg.llm.base import LLMCallError, LLMClient, LLMError

__all__ = ["LLMCallError", "LLMClient", "LLMError"]
