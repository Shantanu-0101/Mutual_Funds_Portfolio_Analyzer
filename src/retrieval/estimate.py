"""What a Stage B run would cost in tokens, without making one call (FR-R9.1, RD11).

For a planned run (methods × questions) it builds the **real** prompt each question would send — the
method's top-5 children, the parent swap, ``build_messages`` — and then:

- asks the LLM wrapper for that prompt's **cache key** and looks for the file: a prompt already in the
  cache is free (FR-R3.3), and this is the same key ``LLM.generate`` would use, so the count is exact;
- counts prompt tokens as the retrieved parents' own tokens (the embedding tokenizer, as
  ``results.csv``'s ``context_tokens``) plus ``PROMPT_OVERHEAD`` (≈680, measured from the recorded
  ``hierarchical`` run: mean prompt 7,119 − mean context 6,435, Velona's extra included);
- counts ``COMPLETION_TOKENS`` (460) per call that is not cached (recorded mean 457).

Tokens only: prices are not kept in this repo (RD11), so nothing here prints or stores money.
No provider is contacted; a missing API key does not stop an estimate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from src.eval.questions import Question
from src.llm import LLM
from src.rag.prompt import build_messages
from src.rag.retrieve import swap_for_parents
from src.retrieval.base import build_method

PROMPT_OVERHEAD = 680            # fixed part of the prompt, measured from the recorded run (FR-R9.1)
COMPLETION_TOKENS = 460          # recorded hierarchical mean 457


@dataclass
class MethodEstimate:
    method: str
    calls: int = 0               # questions asked
    cached: int = 0              # already in the LLM cache: free
    prompt_tokens: int = 0       # of the calls that are not cached
    completion_tokens: int = 0
    context_tokens: int = 0      # the retrieved parents only, all questions
    qids: list[str] = field(default_factory=list)

    @property
    def to_pay(self) -> int:
        return self.calls - self.cached

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class Estimate:
    set_name: str
    by_method: list[MethodEstimate]
    overhead: int = PROMPT_OVERHEAD
    completion: int = COMPLETION_TOKENS

    @property
    def calls(self) -> int:
        return sum(m.calls for m in self.by_method)

    @property
    def cached(self) -> int:
        return sum(m.cached for m in self.by_method)

    @property
    def to_pay(self) -> int:
        return sum(m.to_pay for m in self.by_method)

    @property
    def prompt_tokens(self) -> int:
        return sum(m.prompt_tokens for m in self.by_method)

    @property
    def completion_tokens(self) -> int:
        return sum(m.completion_tokens for m in self.by_method)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def table(self) -> str:
        """The printed table the rule asks for before any paid run (§9.2)."""
        head = f"{'method':<16}{'calls':>7}{'cached':>8}{'to pay':>8}{'prompt':>12}{'completion':>12}{'total':>12}"
        lines = [head, "-" * len(head)]
        for m in self.by_method:
            lines.append(f"{m.method:<16}{m.calls:>7}{m.cached:>8}{m.to_pay:>8}{m.prompt_tokens:>12,}"
                         f"{m.completion_tokens:>12,}{m.total_tokens:>12,}")
        lines.append("-" * len(head))
        lines.append(f"{'all':<16}{self.calls:>7}{self.cached:>8}{self.to_pay:>8}{self.prompt_tokens:>12,}"
                     f"{self.completion_tokens:>12,}{self.total_tokens:>12,}")
        return "\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        return {"set": self.set_name, "prompt_overhead": self.overhead, "completion_per_call": self.completion,
                "calls": self.calls, "cached": self.cached, "to_pay": self.to_pay,
                "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
                "methods": [{"method": m.method, "calls": m.calls, "cached": m.cached,
                             "prompt_tokens": m.prompt_tokens, "completion_tokens": m.completion_tokens}
                            for m in self.by_method]}


class CacheProbe:
    """Is this prompt already answered? Uses the wrapper's own key and cache layout, makes no call."""

    def __init__(self, llm: LLM, json_mode: bool = True):
        self.llm = llm
        self.json_mode = json_mode

    def key(self, messages: list[dict]) -> str:
        return self.llm.cache_key(messages, self.json_mode)

    def hit(self, messages: list[dict]) -> bool:
        path = self.llm._cache_path(self.key(messages))     # the very path generate() would read
        return bool(path and path.is_file())


def quiet_llm(settings) -> LLM:
    """An ``LLM`` for cache keys only: no HTTP client is built, so no API key is needed."""
    return LLM(settings, provider=_KeyOnlyProvider(settings), fallback=None)


class _KeyOnlyProvider:
    """Stands in for the real provider in the cache key: same name and model, and it cannot be called."""

    def __init__(self, settings):
        name = settings.llm.provider
        model = settings.llm.models.get(name)
        if not model:
            raise ValueError(f"llm.models.{name} is not set in config.yaml: no model to estimate for")
        self.name, self.model = name, model

    def complete(self, messages, json_mode):      # pragma: no cover - an estimate never calls a provider
        raise RuntimeError("the estimator never calls the provider")


def estimate(settings, shared, parents: dict, questions: Sequence[Question], methods: Sequence[str],
             set_name: str, top_k: int | None = None, llm: LLM | None = None) -> Estimate:
    """Tokens for ``methods`` × ``questions``, with the cache hits counted as free."""
    top_k = top_k or settings.retrieval.top_k
    probe = CacheProbe(llm or quiet_llm(settings))
    out: list[MethodEstimate] = []
    for name in methods:
        method = build_method(name, shared)
        est = MethodEstimate(method=name)
        for q in questions:
            res = method.retrieve(q.text, top_k)
            sections = swap_for_parents(res.children, parents)
            context = sum(s.chunk.n_tokens for s in sections)
            messages = build_messages(q.text, [s.chunk for s in sections])
            est.calls += 1
            est.context_tokens += context
            est.qids.append(q.id)
            if probe.hit(messages):
                est.cached += 1
                continue
            est.prompt_tokens += context + PROMPT_OVERHEAD
            est.completion_tokens += COMPLETION_TOKENS
        out.append(est)
    return Estimate(set_name=set_name, by_method=out)


SMOKE_TYPES = ("lookup", "aggregation", "cross_scheme")


def smoke_questions(questions: Sequence[Question], types: Sequence[str] = SMOKE_TYPES) -> list[Question]:
    """The smoke run's 3 questions (FR-R3.2): the first answerable question of each type, in order."""
    out = []
    for t in types:
        q = next((q for q in questions if q.type == t and q.answerable), None)
        if q is not None:
            out.append(q)
    return out
