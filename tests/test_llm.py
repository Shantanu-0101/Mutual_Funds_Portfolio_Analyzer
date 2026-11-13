"""LLM wrapper tests (spec §10): provider choice, cache, retries, error sorting. No network."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import groq
import httpx
import pytest

from src.config import load_settings
from src.llm import (
    JSON_INVALID, LLM, ContextOverflow, GeminiProvider, GroqProvider, LLMError, MockProvider, RateLimited, _Retry,
    classify_http_error, make_provider,
)

NO_ENV = Path("does-not-exist.env")
MSGS = [{"role": "system", "content": "rules"}, {"role": "user", "content": "question?"}]


def settings_for(tmp_path, provider="mock", **env):
    s = load_settings(env_file=NO_ENV, environ={"LLM_PROVIDER": provider, **env})
    return replace(s, paths=replace(s.paths, cache=tmp_path / "cache"))


def test_provider_from_env(tmp_path):
    assert isinstance(make_provider(settings_for(tmp_path, "mock")), MockProvider)
    with pytest.raises(LLMError, match="GROQ_API_KEY"):
        make_provider(settings_for(tmp_path, "groq"))
    with pytest.raises(LLMError, match="llm.models.gemini"):
        make_provider(settings_for(tmp_path, "gemini", GEMINI_API_KEY="x"))


def test_cache_hit_miss_and_fresh(tmp_path):
    s = settings_for(tmp_path)
    p = MockProvider(s)
    first = LLM(s, p).generate(MSGS)
    second = LLM(s, p).generate(MSGS)
    assert p.calls == 1 and not first.cached and second.cached
    assert second.text == first.text and second.prompt_tokens == first.prompt_tokens
    assert second.latency_ms == first.latency_ms          # original latency is kept
    LLM(s, p, fresh=True).generate(MSGS)
    assert p.calls == 2
    LLM(s, p).generate(MSGS + [{"role": "user", "content": "more"}])
    assert p.calls == 3
    LLM(s, p, cache=False).generate(MSGS)
    assert p.calls == 4
    assert len(list((tmp_path / "cache" / "llm").rglob("*.json"))) == 2


def test_cache_key_covers_settings(tmp_path):
    s = settings_for(tmp_path)
    key = LLM(s, MockProvider(s)).cache_key(MSGS, True)
    hot = replace(s, llm=replace(s.llm, temperature=0.7))
    assert LLM(hot, MockProvider(hot)).cache_key(MSGS, True) != key
    assert LLM(s, MockProvider(s)).cache_key(MSGS, False) != key


class Flaky:
    """Raises the given errors in turn, then answers."""
    name, model = "flaky", "m"

    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = 0

    def complete(self, messages, json_mode):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return MockProvider().complete(messages, json_mode)


def test_retries_with_backoff_and_retry_after(tmp_path):
    waits = []
    p = Flaky([_Retry("500"), _Retry("429", wait_s=7.0)])
    res = LLM(settings_for(tmp_path), p, cache=False, sleep=waits.append).generate(MSGS)
    assert p.calls == 3 and waits == [2.0, 7.0] and res.text


def test_gives_up_after_retries(tmp_path):
    s = settings_for(tmp_path)
    p = Flaky([_Retry("429 rate limit")] * 10)
    with pytest.raises(RateLimited):
        LLM(s, p, sleep=lambda _: None).generate(MSGS)
    assert p.calls == s.llm.retries + 1
    assert not (tmp_path / "cache" / "llm").exists()       # errors are never cached


def test_overflow_not_retried(tmp_path):
    p = Flaky([ContextOverflow("413 request too large")])
    with pytest.raises(ContextOverflow):
        LLM(settings_for(tmp_path), p, sleep=lambda _: pytest.fail("no retry")).generate(MSGS)
    assert p.calls == 1


@pytest.mark.parametrize("status, msg, retry_after, kind", [
    (413, "Request too large for model on tokens per minute (TPM): Limit 8000", None, ContextOverflow),
    (400, "context_length_exceeded", None, ContextOverflow),
    (429, "rate limit", 5.0, _Retry),
    (429, "rate limit tokens per day", 3600.0, RateLimited),
    (503, "unavailable", None, _Retry),
    (None, "connection reset", None, _Retry),
    (401, "invalid api key", None, LLMError),
])
def test_classify_http_error(status, msg, retry_after, kind):
    err = classify_http_error(status, msg, retry_after)
    assert type(err) is kind
    if kind is _Retry and retry_after:
        assert err.wait_s == retry_after


# --------------------------------------------------------------------------- groq provider with a fake client

def _status_error(status, body, headers=None):
    resp = httpx.Response(status, headers=headers or {}, request=httpx.Request("POST", "https://example.invalid"))
    return groq.APIStatusError("err", response=resp, body=body)


class FakeGroq:
    def __init__(self, result=None, error=None):
        self.kwargs = None
        self.result, self.error = result, error
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.result


def _groq_reply(text="{}"):
    usage = SimpleNamespace(prompt_tokens=120, completion_tokens=40,
                            completion_tokens_details=SimpleNamespace(reasoning_tokens=25))
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")],
                           usage=usage)


def test_groq_request_and_usage(tmp_path):
    s = settings_for(tmp_path, "groq")
    client = FakeGroq(_groq_reply('{"a": 1}'))
    c = GroqProvider(s, client=client).complete(MSGS, json_mode=True)
    assert client.kwargs["model"] == "openai/gpt-oss-120b"
    assert client.kwargs["temperature"] == 0 and client.kwargs["response_format"] == {"type": "json_object"}
    assert client.kwargs["reasoning_effort"] == "low" and client.kwargs["include_reasoning"] is False
    assert (c.text, c.prompt_tokens, c.completion_tokens, c.reasoning_tokens) == ('{"a": 1}', 120, 40, 25)


def test_groq_errors(tmp_path):
    s = settings_for(tmp_path, "groq")
    bad_json = _status_error(400, {"error": {"code": JSON_INVALID, "failed_generation": "{oops"}})
    c = GroqProvider(s, client=FakeGroq(error=bad_json)).complete(MSGS, True)
    assert c.finish_reason == JSON_INVALID and c.text == "{oops"
    with pytest.raises(ContextOverflow):
        GroqProvider(s, client=FakeGroq(error=_status_error(413, {"error": {"message": "too large"}}))).complete(MSGS, True)
    with pytest.raises(_Retry) as e:
        GroqProvider(s, client=FakeGroq(error=_status_error(429, {}, {"retry-after": "3"}))).complete(MSGS, True)
    assert e.value.wait_s == 3.0
    with pytest.raises(RateLimited):
        GroqProvider(s, client=FakeGroq(error=_status_error(429, {}, {"retry-after": "4000"}))).complete(MSGS, True)


def test_gemini_needs_model_and_key(tmp_path):
    s = settings_for(tmp_path, "gemini")
    s = replace(s, llm=replace(s.llm, models={**s.llm.models, "gemini": "some-model"}))
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        GeminiProvider(s)


def test_error_text_scrubbed():
    err = classify_http_error(413, "Request too large in organization `org_01kr10abcXYZ` on TPM")
    assert "org_01kr" not in str(err) and "org_<redacted>" in str(err)
