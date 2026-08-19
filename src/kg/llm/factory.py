"""Construct the configured LLM client.

Providers are presets, not classes: each fills in the ``base_url`` / default
model / auth expectation that the user's env didn't. Everything ends up in the
same :class:`~kg.llm.openai_compatible.OpenAICompatibleLLMClient`.
"""

from __future__ import annotations

from kg.config.models import LLMSettings
from kg.llm.base import LLMClient, LLMError
from kg.llm.openai_compatible import OpenAICompatibleLLMClient

# Defaults applied only where the user's config left the field empty.
# base_url is matched loosely (in) so custom gateways on the same host work.
_PROVIDER_PRESETS: dict[str, dict[str, str | bool]] = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "qwen/qwen3-30b-a3b-instruct",
        "needs_key": True,
    },
    "vllm": {
        "base_url": "http://localhost:8000/v1",
        "model": "kg-extractor",
        "needs_key": False,
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "needs_key": True,
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "needs_key": True,
    },
    "fireworks": {
        "base_url": "https://api.fireworks.ai/inference/v1",
        "model": "accounts/fireworks/models/llama-v3p3-70b-instruct",
        "needs_key": True,
    },
    "litellm": {
        "base_url": "http://localhost:4000/v1",
        "model": "gpt-4o-mini",
        "needs_key": False,
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "llama3.1",
        "needs_key": False,
    },
}


def apply_provider_defaults(settings: LLMSettings) -> LLMSettings:
    """Fill empty base_url/model fields from the provider preset, then validate.

    Constructing raw ``LLMSettings`` with empty fields is allowed (tests, partial
    config); this is where completeness is enforced, with provider-appropriate
    defaults filled in first.
    """
    preset = _PROVIDER_PRESETS.get(settings.provider)
    if preset is None:
        raise LLMError(
            f"unknown LLM_PROVIDER {settings.provider!r}. "
            f"Known: {', '.join(sorted(_PROVIDER_PRESETS))} (or set LLM_BASE_URL explicitly)."
        )

    updates: dict[str, str] = {}
    if not settings.base_url:
        updates["base_url"] = str(preset["base_url"])
    if not settings.model:
        updates["model"] = str(preset["model"])
    if updates:
        settings = settings.model_copy(update=updates)

    if preset["needs_key"] and not settings.api_key:
        raise LLMError(
            f"provider {settings.provider!r} needs LLM_API_KEY (env, Vault, or K8s secret)."
        )
    return settings


def build_llm_client(settings: LLMSettings) -> LLMClient:
    """Validate against the preset, then hand back the shared client."""
    return OpenAICompatibleLLMClient(apply_provider_defaults(settings))
