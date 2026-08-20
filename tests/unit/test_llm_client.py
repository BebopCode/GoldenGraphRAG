"""OpenAI-compatible client + factory tests (fully mocked — no network)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from openai import APIConnectionError, APIStatusError

from kg.config.models import LLMSettings
from kg.llm.base import LLMCallError, LLMError
from kg.llm.factory import apply_provider_defaults, build_llm_client
from kg.llm.openai_compatible import OpenAICompatibleLLMClient

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"entities": {"type": "array"}},
    "required": ["entities"],
}


def _settings(**kw: Any) -> LLMSettings:
    base: dict[str, Any] = {
        "provider": "vllm",
        "model": "kg-extractor",
        "base_url": "http://localhost:8000/v1",
        "api_key": "test",
        "max_retries": 0,
    }
    base.update(kw)
    return LLMSettings(**base)


def _client(**kw: Any) -> OpenAICompatibleLLMClient:
    return OpenAICompatibleLLMClient(_settings(**kw))


def _status_error(status: int, message: str) -> APIStatusError:
    """A real APIStatusError (status_code is derived from the httpx response)."""
    request = httpx.Request("POST", "http://localhost:8000/v1/chat/completions")
    response = httpx.Response(status, request=request, json={"error": {"message": message}})
    return APIStatusError(message, response=response, body=None)


def _conn_error() -> APIConnectionError:
    request = httpx.Request("POST", "http://localhost:8000/v1/chat/completions")
    return APIConnectionError(request=request)


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content
        self.refusal = None


class _FakeChoice:
    def __init__(self, content: str, finish_reason: str = "stop") -> None:
        self.message = _FakeMessage(content)
        self.finish_reason = finish_reason


class _FakeUsage:
    prompt_tokens = 10
    completion_tokens = 5
    total_tokens = 15


class _FakeResponse:
    def __init__(self, content: str = '{"entities": []}', finish_reason: str = "stop") -> None:
        self.choices = [_FakeChoice(content, finish_reason)]
        self.usage = _FakeUsage()


class _FakeCompletions:
    """Records create() kwargs; returns scripted outcomes (response or exception)."""

    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _wire(client: OpenAICompatibleLLMClient, outcomes: list[Any]) -> _FakeCompletions:
    fake = _FakeCompletions(outcomes)
    client._client.chat.completions = fake  # type: ignore[assignment]
    return fake


def test_json_schema_mode_sends_response_format() -> None:
    c = _client(structured_mode="json_schema")
    fake = _wire(c, [_FakeResponse()])
    c.complete("p", json_schema=SCHEMA, schema_name="kg_extraction")
    rf = fake.calls[0]["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "kg_extraction"
    assert rf["json_schema"]["schema"] == SCHEMA


def test_openrouter_adds_require_parameters() -> None:
    c = _client(provider="openrouter", base_url="https://openrouter.ai/api/v1")
    fake = _wire(c, [_FakeResponse()])
    c.complete("p", json_schema=SCHEMA)
    assert fake.calls[0]["extra_body"]["provider"]["require_parameters"] is True


def test_openrouter_allowlist_restricts_routing() -> None:
    c = _client(
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        allowed_providers=["Groq", "DeepInfra"],
    )
    fake = _wire(c, [_FakeResponse()])
    c.complete("p", json_schema=SCHEMA)
    provider = fake.calls[0]["extra_body"]["provider"]
    assert provider["order"] == ["Groq", "DeepInfra"]
    assert provider["allow_fallbacks"] is False


def test_non_openrouter_gets_no_routing_hints() -> None:
    c = _client()
    fake = _wire(c, [_FakeResponse()])
    c.complete("p", json_schema=SCHEMA)
    assert "extra_body" not in fake.calls[0]


def test_none_mode_sends_no_response_format() -> None:
    c = _client(structured_mode="none")
    fake = _wire(c, [_FakeResponse()])
    c.complete("p", json_schema=SCHEMA)
    assert "response_format" not in fake.calls[0]


def test_auto_mode_degrades_on_schema_rejection(monkeypatch) -> None:
    monkeypatch.setattr("kg.llm.openai_compatible.time.sleep", lambda s: None)
    c = _client()  # auto
    err1 = _status_error(400, "response_format json_schema not supported")
    err2 = _status_error(400, "structured_outputs param not recognized")
    err3 = _status_error(400, "guided_json is not a valid field")
    fake = _wire(c, [err1, err2, err3, _FakeResponse()])

    out = c.complete("p", json_schema=SCHEMA)

    assert out == '{"entities": []}'
    assert fake.calls[1]["extra_body"] == {"structured_outputs": {"json": SCHEMA}}
    assert fake.calls[2]["extra_body"] == {"guided_json": SCHEMA}
    # everything rejected -> plain json_object (schema stays prompt-side)
    assert fake.calls[3]["response_format"] == {"type": "json_object"}


def test_remembered_mode_is_reused(monkeypatch) -> None:
    monkeypatch.setattr("kg.llm.openai_compatible.time.sleep", lambda s: None)
    c = _client()
    err = _status_error(400, "response_format not supported")
    fake = _wire(c, [err, _FakeResponse()])
    c.complete("p", json_schema=SCHEMA)

    # The downgrade is remembered: the next call starts at the fallback shape,
    # not json_schema, so it succeeds without another 400.
    fake.outcomes.append(_FakeResponse())
    c.complete("p", json_schema=SCHEMA)
    assert fake.calls[2].get("response_format", {}).get("type") != "json_schema"


def test_non_schema_400_raises_immediately() -> None:
    err = _status_error(400, "invalid model id")
    c = _client(max_retries=3)
    fake = _wire(c, [err])
    with pytest.raises(LLMCallError):
        c.complete("p", json_schema=SCHEMA)
    assert len(fake.calls) == 1  # no retries on a hard 400


def test_openrouter_404_routing_refusal_downgrades() -> None:
    # `:free` endpoints without structured-output support answer
    # require_parameters with this 404 — the free tier's only dialect.
    c = _client(provider="openrouter", base_url="https://openrouter.ai/api/v1")
    err = _status_error(404, "No endpoints found that can handle the requested parameters")
    fake = _wire(c, [err, _FakeResponse()])

    out = c.complete("p", json_schema=SCHEMA)

    assert out == '{"entities": []}'
    # OpenRouter skips the vLLM spellings and lands directly on json_object.
    assert fake.calls[1]["response_format"] == {"type": "json_object"}
    assert "extra_body" not in fake.calls[1]


def test_generic_404_still_raises_immediately() -> None:
    err = _status_error(404, "Not Found")
    c = _client(max_retries=3)
    fake = _wire(c, [err])
    with pytest.raises(LLMCallError):
        c.complete("p", json_schema=SCHEMA)
    assert len(fake.calls) == 1  # a wrong base URL is not a downgrade signal


def test_connection_errors_retry_then_raise(monkeypatch) -> None:
    monkeypatch.setattr("kg.llm.openai_compatible.time.sleep", lambda s: None)
    c = _client(max_retries=1)
    _wire(c, [_conn_error(), _conn_error()])
    with pytest.raises(LLMCallError):
        c.complete("p")


def test_usage_summary_accumulates() -> None:
    c = _client()
    _wire(c, [_FakeResponse(), _FakeResponse()])
    c.complete("p")
    c.complete("p")
    usage = c.usage_summary()
    assert usage["requests"] == 2
    assert usage["total_tokens"] == 30


def test_truncation_is_only_logged() -> None:
    c = _client()
    _wire(c, [_FakeResponse(finish_reason="length")])
    assert c.complete("p") == '{"entities": []}'


def test_health_check_reports_failure() -> None:
    c = _client()
    _wire(c, [RuntimeError("boom")])
    out = c.health_check()
    assert out["ok"] is False and "boom" in out["error"]


# -- factory --------------------------------------------------------------


def test_factory_fills_preset_defaults() -> None:
    s = apply_provider_defaults(LLMSettings(provider="vllm", api_key="k"))
    assert s.base_url == "http://localhost:8000/v1"
    assert s.model == "kg-extractor"


def test_factory_explicit_base_url_wins() -> None:
    s = apply_provider_defaults(
        LLMSettings(provider="vllm", base_url="http://gpu-box:9000/v1", api_key="k")
    )
    assert s.base_url == "http://gpu-box:9000/v1"


def test_factory_rejects_unknown_provider() -> None:
    with pytest.raises(LLMError):
        apply_provider_defaults(LLMSettings(provider="nope", base_url="http://x/v1"))


def test_factory_requires_key_for_hosted_providers() -> None:
    s = LLMSettings(provider="openrouter")  # no api_key
    with pytest.raises(LLMError):
        apply_provider_defaults(s)


def test_build_llm_client_returns_shared_client() -> None:
    client = build_llm_client(_settings())
    assert isinstance(client, OpenAICompatibleLLMClient)
    client.close()
