"""One interface to the LLM, whichever provider runs it (tasks 3.1–3.3, spec §5, §9.1).

Why a wrapper: the RAG pipeline (Phase 3), the pandas baseline (Phase 4) and the
evaluation (Phase 5) must all call the model the same way: same model,
temperature 0, same retry rules, same token accounting. They also must be able
to run without the network (``mock``) and without paying twice for the same
prompt (the disk cache).

    llm = LLM.from_settings(get_settings())
    result = llm.generate([{"role": "system", "content": ...}, {"role": "user", "content": ...}])

Providers (chosen by ``LLM_PROVIDER`` / ``llm.provider``):

- ``groq``: model from ``llm.models.groq``. JSON mode on; for gpt-oss models,
  ``reasoning_effort`` from config and the hidden reasoning is not returned.
- ``gemini``: model from ``llm.models.gemini``. Written to the same interface
  but **not yet run against the live API** (no key on this laptop yet).
- ``mock``: no network; returns a fixed JSON answer, or whatever a test's
  ``responder`` returns. Used by every unit test.

Errors are sorted into what the evaluation needs to record (D9):

- ``ContextOverflow``: the provider refused the request as too large (context
  window, or a single request above the tokens-per-minute limit, which Groq
  answers with HTTP 413). Not retried: the same request would fail again.
- ``RateLimited``: still limited after ``llm.retries`` retries, or the
  provider asks us to wait longer than ``MAX_WAIT_S`` (a daily limit).
- 429s with a short ``retry-after``, 5xx errors, timeouts and dropped
  connections are retried with backoff.
- Groq's ``json_validate_failed`` (JSON mode, model wrote invalid JSON) is not
  an exception: the model's text is returned with ``finish_reason`` set to it,
  so the caller records a format failure instead of the text being repaired.

Cache (§9.1): responses are stored as JSON under ``<paths.cache>/llm/``, keyed by
a hash of provider, model, every generation setting and the full messages.
``fresh=True`` skips reading the cache (still writes), for the final recorded
run. Errors are never cached.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable, Protocol

from src.config import Settings

Message = dict[str, str]  # {"role": "system" | "user" | "assistant", "content": "..."}

MAX_WAIT_S = 90.0          # a longer retry-after means a daily limit: give up instead of sleeping
JSON_INVALID = "json_validate_failed"

DEFAULT_MOCK_ANSWER = json.dumps({
    "answer": "Mock answer.", "value": None, "unit": None, "items": [], "sources": [],
    "insufficient_context": True,
})


class LLMError(RuntimeError):
    """The model could not produce an answer."""

    kind = "llm_error"


class ContextOverflow(LLMError):
    """The provider rejected the request as too large (recorded as "context overflow", D9)."""

    kind = "context_overflow"


class RateLimited(LLMError):
    """Rate limit not cleared after retrying, or the wait would be too long (daily limit)."""

    kind = "rate_limited"


class _Retry(Exception):
    """Internal: a transient failure; retry after ``wait_s`` (None = use backoff)."""

    def __init__(self, message: str, wait_s: float | None = None):
        super().__init__(message)
        self.wait_s = wait_s


@dataclass(frozen=True)
class LLMResult:
    text: str
    prompt_tokens: int
    completion_tokens: int     # includes hidden reasoning tokens where the provider counts them
    latency_ms: float          # of the original call, also when served from cache
    provider: str
    model: str
    reasoning_tokens: int | None = None
    finish_reason: str | None = None
    cached: bool = False


@dataclass(frozen=True)
class Completion:
    """What a provider returns for one call."""

    text: str
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int | None = None
    finish_reason: str | None = None


class Provider(Protocol):
    name: str
    model: str

    def complete(self, messages: list[Message], json_mode: bool) -> Completion: ...


# --------------------------------------------------------------------------- error sorting

_OVERFLOW_HINTS = ("request too large", "context_length_exceeded", "context length", "reduce the length",
                   "maximum context", "too many tokens", "exceeds the maximum")


def scrub(message: str) -> str:
    """Remove account identifiers (Groq organization ids) from provider error text before it is stored."""
    return re.sub(r"\borg_[A-Za-z0-9]+", "org_<redacted>", message)



def classify_http_error(status: int | None, message: str, retry_after: float | None = None) -> Exception:
    """Turn a provider's HTTP error into ContextOverflow / _Retry / RateLimited / LLMError."""
    message = scrub(message)
    text = message.lower()
    if status == 413 or any(h in text for h in _OVERFLOW_HINTS):
        return ContextOverflow(message)
    if status == 429:
        if retry_after is not None and retry_after > MAX_WAIT_S:
            return RateLimited(f"{message} (retry after {retry_after:.0f} s)")
        return _Retry(message, retry_after)
    if status is None or status >= 500 or status == 408:
        return _Retry(message)
    return LLMError(message)


def _retry_after(headers: Any) -> float | None:
    try:
        value = headers.get("retry-after") if headers is not None else None
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- providers

class GroqProvider:
    name = "groq"

    def __init__(self, settings: Settings, client: Any = None):
        llm = settings.llm
        if not llm.models.get("groq"):
            raise LLMError("llm.models.groq is not set in config.yaml")
        if client is None:
            if not settings.secrets.groq_api_key:
                raise LLMError("GROQ_API_KEY is not set (put it in .env)")
            from groq import Groq

            # max_retries=0: retries are ours, so every wait is visible and counted
            client = Groq(api_key=settings.secrets.groq_api_key, timeout=llm.timeout_s, max_retries=0)
        self.client = client
        self.model = llm.models["groq"]
        self.temperature = llm.temperature
        self.max_tokens = llm.max_output_tokens
        self.reasoning_effort = llm.reasoning_effort

    def complete(self, messages: list[Message], json_mode: bool) -> Completion:
        import groq

        kwargs: dict[str, Any] = dict(model=self.model, messages=messages, temperature=self.temperature,
                                      max_completion_tokens=self.max_tokens)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self.model.startswith("openai/gpt-oss"):
            kwargs["include_reasoning"] = False
            if self.reasoning_effort:
                kwargs["reasoning_effort"] = self.reasoning_effort
        try:
            r = self.client.chat.completions.create(**kwargs)
        except groq.APIStatusError as e:
            body = e.body if isinstance(e.body, dict) else {}
            err = body.get("error", body) if isinstance(body, dict) else {}
            if isinstance(err, dict) and err.get("code") == JSON_INVALID:
                return Completion(text=str(err.get("failed_generation") or ""), prompt_tokens=0,
                                  completion_tokens=0, finish_reason=JSON_INVALID)
            raise classify_http_error(e.status_code, str(e), _retry_after(e.response.headers)) from e
        except (groq.APITimeoutError, groq.APIConnectionError) as e:
            raise _Retry(scrub(str(e))) from e
        choice = r.choices[0]
        usage = r.usage
        details = getattr(usage, "completion_tokens_details", None)
        return Completion(text=choice.message.content or "", prompt_tokens=usage.prompt_tokens,
                          completion_tokens=usage.completion_tokens,
                          reasoning_tokens=getattr(details, "reasoning_tokens", None),
                          finish_reason=choice.finish_reason)


class GeminiProvider:
    """Same interface on Google's Gemini API. Not yet run against the live API."""

    name = "gemini"

    def __init__(self, settings: Settings, client: Any = None):
        llm = settings.llm
        if not llm.models.get("gemini"):
            raise LLMError("llm.models.gemini is not set in config.yaml (pick one from the live model list)")
        if client is None:
            if not settings.secrets.gemini_api_key:
                raise LLMError("GEMINI_API_KEY is not set (put it in .env)")
            from google import genai

            client = genai.Client(api_key=settings.secrets.gemini_api_key)
        self.client = client
        self.model = llm.models["gemini"]
        self.temperature = llm.temperature
        self.max_tokens = llm.max_output_tokens

    def complete(self, messages: list[Message], json_mode: bool) -> Completion:
        from google.genai import errors, types

        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system") or None
        contents = [types.Content(role="model" if m["role"] == "assistant" else "user",
                                  parts=[types.Part(text=m["content"])])
                    for m in messages if m["role"] != "system"]
        config = types.GenerateContentConfig(
            system_instruction=system, temperature=self.temperature, max_output_tokens=self.max_tokens,
            response_mime_type="application/json" if json_mode else None)
        try:
            r = self.client.models.generate_content(model=self.model, contents=contents, config=config)
        except errors.APIError as e:
            raise classify_http_error(getattr(e, "code", None), str(e)) from e
        usage = r.usage_metadata
        finish = r.candidates[0].finish_reason if r.candidates else None
        return Completion(text=r.text or "", prompt_tokens=getattr(usage, "prompt_token_count", 0) or 0,
                          completion_tokens=(getattr(usage, "candidates_token_count", 0) or 0)
                          + (getattr(usage, "thoughts_token_count", 0) or 0),
                          reasoning_tokens=getattr(usage, "thoughts_token_count", None),
                          finish_reason=getattr(finish, "name", None))


class MockProvider:
    """No network. ``responder(messages) -> text``; default: a fixed 'insufficient context' JSON answer."""

    name = "mock"

    def __init__(self, settings: Settings | None = None, responder: Callable[[list[Message]], str] | None = None):
        self.model = (settings.llm.models.get("mock") if settings else None) or "mock"
        self.responder = responder or (lambda messages: DEFAULT_MOCK_ANSWER)
        self.calls = 0

    def complete(self, messages: list[Message], json_mode: bool) -> Completion:
        self.calls += 1
        text = self.responder(messages)
        return Completion(text=text, prompt_tokens=sum(len(m["content"].split()) for m in messages),
                          completion_tokens=len(text.split()), finish_reason="stop")


PROVIDERS = {"groq": GroqProvider, "gemini": GeminiProvider, "mock": MockProvider}


def make_provider(settings: Settings) -> Provider:
    return PROVIDERS[settings.llm.provider](settings)


# --------------------------------------------------------------------------- the wrapper

class LLM:
    def __init__(self, settings: Settings, provider: Provider | None = None, *, cache: bool = True,
                 fresh: bool = False, sleep: Callable[[float], None] = time.sleep):
        self.settings = settings
        self.provider = provider or make_provider(settings)
        self.cache_dir: Path | None = settings.paths.cache / "llm" if cache else None
        self.fresh = fresh
        self.sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings, **kwargs: Any) -> "LLM":
        return cls(settings, **kwargs)

    @property
    def model(self) -> str:
        return self.provider.model

    def cache_key(self, messages: list[Message], json_mode: bool) -> str:
        llm = self.settings.llm
        payload = {"provider": self.provider.name, "model": self.provider.model, "temperature": llm.temperature,
                   "max_output_tokens": llm.max_output_tokens, "reasoning_effort": llm.reasoning_effort,
                   "json": json_mode, "messages": messages}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Path | None:
        return self.cache_dir / key[:2] / f"{key}.json" if self.cache_dir else None

    def generate(self, messages: list[Message], json: bool = True) -> LLMResult:  # noqa: A002 (spec name)
        key = self.cache_key(messages, json)
        path = self._cache_path(key)
        if path and not self.fresh and path.is_file():
            data = _json_load(path)
            return replace(LLMResult(**data["result"]), cached=True)

        result = self._call_with_retries(messages, json)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(_json_dump({"key": key, "messages": messages, "json": json,
                                       "result": asdict(result)}), encoding="utf-8")
            tmp.replace(path)
        return result

    def _call_with_retries(self, messages: list[Message], json_mode: bool) -> LLMResult:
        retries = self.settings.llm.retries
        for attempt in range(retries + 1):
            t0 = time.perf_counter()
            try:
                c = self.provider.complete(messages, json_mode)
            except _Retry as e:
                if attempt == retries:
                    raise (RateLimited if "429" in str(e) or "rate" in str(e).lower() else LLMError)(
                        f"gave up after {retries} retries: {e}") from e
                self.sleep(e.wait_s if e.wait_s is not None else min(2.0 * 2 ** attempt, 60.0))
                continue
            return LLMResult(text=c.text, prompt_tokens=c.prompt_tokens, completion_tokens=c.completion_tokens,
                             latency_ms=(time.perf_counter() - t0) * 1000, provider=self.provider.name,
                             model=self.provider.model, reasoning_tokens=c.reasoning_tokens,
                             finish_reason=c.finish_reason)
        raise AssertionError("unreachable")


def _json_dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)


def _json_load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
