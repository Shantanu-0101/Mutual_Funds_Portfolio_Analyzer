"""Question → retrieved chunks → LLM → checked answer (task 3.9, FR-3.6, FR-3.7).

``RagPipeline.answer(question, chunker)`` returns a ``RagResult`` that has
everything the evaluation needs: the parsed answer (or why there is none), the
retrieved chunks with scores, the context rows, the rows the answer cites,
prompt / completion tokens, and retrieval and generation latency.

``status`` is one of:

- ``ok``               valid JSON answer in the agreed format
- ``format_error``     the model replied, but not in the format (counts as wrong; not repaired)
- ``context_overflow`` the provider refused the request as too large (D9)
- ``rate_limited``     limits not cleared after retrying (the run can be resumed later)
- ``provider_unavailable`` bad key, no credit, or the provider stayed down (and no fallback helped)
- ``llm_error``        any other provider failure
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.chunking.base import RowKey, _clean, row_key
from src.llm import JSON_INVALID, LLM, LLMError, LLMResult
from src.parsing.pipeline import HOLDINGS_FILE
from src.rag.prompt import AnswerFormatError, build_messages, norm_name, parse_answer
from src.rag.retrieve import Retrieval, Retriever

STATUSES = ("ok", "format_error", "context_overflow", "rate_limited", "provider_unavailable", "llm_error")


@dataclass
class RagResult:
    question: str
    chunker: str
    status: str
    answer: dict | None
    error: str | None
    raw_text: str | None
    retrieval: Retrieval
    cited_rows: list[RowKey] = field(default_factory=list)
    unmatched_sources: list[dict] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int | None = None
    generation_ms: float = 0.0
    cached: bool = False
    model: str | None = None              # the model that answered (the fallback's, if it was used)
    provider: str | None = None
    fallback_reason: str | None = None    # set when the fallback provider answered

    @property
    def retrieval_ms(self) -> float:
        return self.retrieval.latency_ms

    @property
    def context_rows(self) -> list[RowKey]:
        return self.retrieval.context_rows


def load_row_names(processed_dir) -> dict[RowKey, tuple[str, str]]:
    """row key → (normalised scheme, normalised instrument), to resolve cited sources to rows."""
    h = pd.read_parquet(processed_dir / HOLDINGS_FILE, columns=["scheme", "instrument", "source_file",
                                                                "source_sheet", "source_row"])
    return {row_key(r): (norm_name(_clean(r.scheme)), norm_name(_clean(r.instrument)))
            for r in h.itertuples(index=False)}


def resolve_sources(sources: list[dict], context_rows: list[RowKey],
                    names: dict[RowKey, tuple[str, str]]) -> tuple[list[RowKey], list[dict]]:
    """Match each cited (scheme, instrument) to context rows. Returns (rows, sources that matched nothing)."""
    rows: dict[RowKey, None] = {}
    unmatched = []
    for src in sources:
        scheme, inst = norm_name(src.get("scheme", "")), norm_name(src.get("instrument", ""))
        hits = [k for k in context_rows if k in names and names[k][1] == inst
                and (not scheme or scheme in names[k][0] or names[k][0] in scheme)]
        if hits:
            for k in hits:
                rows.setdefault(k, None)
        else:
            unmatched.append(src)
    return list(rows), unmatched


class RagPipeline:
    def __init__(self, settings, retriever: Retriever | None = None, llm: LLM | None = None,
                 row_names: dict[RowKey, tuple[str, str]] | None = None):
        self.settings = settings
        self.retriever = retriever or Retriever(settings)
        self.llm = llm or LLM.from_settings(settings)
        self._row_names = row_names

    @property
    def row_names(self) -> dict[RowKey, tuple[str, str]]:
        if self._row_names is None:
            self._row_names = load_row_names(self.settings.paths.processed)
        return self._row_names

    def answer(self, question: str, chunker: str, top_k: int | None = None,
               scheme_code: str | None = None, as_of_date: str | None = None) -> RagResult:
        retrieval = self.retriever.retrieve(question, chunker, top_k, scheme_code, as_of_date)
        messages = build_messages(question, [r.chunk for r in retrieval.chunks])
        base = dict(question=question, chunker=chunker, retrieval=retrieval, model=self.llm.model,
                    provider=self.llm.provider.name)
        try:
            res: LLMResult = self.llm.generate(messages, json=True)
        except LLMError as e:
            return RagResult(status=e.kind, answer=None, error=str(e), raw_text=None, **base)
        base.update(model=res.model, provider=res.provider, fallback_reason=res.fallback_reason)
        usage = dict(prompt_tokens=res.prompt_tokens, completion_tokens=res.completion_tokens,
                     reasoning_tokens=res.reasoning_tokens, generation_ms=res.latency_ms, cached=res.cached)
        try:
            if res.finish_reason == JSON_INVALID:
                raise AnswerFormatError("provider rejected the reply as invalid JSON")
            answer = parse_answer(res.text)
        except AnswerFormatError as e:
            note = " (reply cut at max_output_tokens)" if res.finish_reason == "length" else ""
            return RagResult(status="format_error", answer=None, error=f"{e}{note}", raw_text=res.text,
                             **base, **usage)
        cited, unmatched = resolve_sources(answer["sources"], retrieval.context_rows, self.row_names)
        return RagResult(status="ok", answer=answer, error=None, raw_text=res.text, cited_rows=cited,
                         unmatched_sources=unmatched, **base, **usage)
