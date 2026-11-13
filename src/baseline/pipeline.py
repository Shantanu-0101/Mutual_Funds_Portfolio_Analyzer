"""Question → LLM writes pandas code → checked → run in the sandbox → answer (task 4.5, FR-4.3, FR-4.4).

``BaselinePipeline.answer(question)`` returns a ``BaselineResult`` with the
code, the raw result, any error, tokens and both latencies, and an ``answer``
in the same shape as the RAG answer (``src.rag.prompt``), so the Phase 5
metrics treat both methods identically.

``status`` is one of:

- ``ok``               the code ran and set ``result``
- ``format_error``     the reply was not the agreed JSON object
- ``blocked``          the static check refused the code (``guard.py``)
- ``syntax_error``     the code does not parse
- ``runtime_error``    the code raised an exception
- ``no_result``        the code ran but never set ``result``
- ``timeout``          killed after ``baseline.timeout_s``
- ``sandbox_error``    the sandbox process itself failed (not the model's fault; worth a re-run)
- ``context_overflow`` / ``rate_limited`` / ``provider_unavailable`` / ``llm_error``: as in RAG

Failures are reported, never retried with hints (FR-4.3).

Result → answer (``to_answer``):

- a number → ``value``; a string → one item; a bool → the answer text only;
- a list / set → ``items`` (a single number in a list becomes ``value``);
- a Series or DataFrame with one cell → ``value``;
- other Series / DataFrames: rows of ``df`` (index found in ``df``) become
  ``items`` = their instrument names and are cited as sources; otherwise the
  index labels (Series) or the first text column (DataFrame) become ``items``;
- ``None``, NaN or an empty result → ``insufficient_context`` = true
  (the prompt tells the model to set ``result = None`` when df cannot answer).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from src.baseline.guard import BlockedCode, check_code
from src.baseline.sandbox import load_frame, run_in_sandbox
from src.baseline.schema import describe_frame
from src.baseline.text_to_pandas import ReplyFormatError, build_messages, parse_reply
from src.chunking.base import RowKey, row_key
from src.llm import JSON_INVALID, LLM, LLMError, LLMResult
from src.parsing.pipeline import HOLDINGS_FILE

STATUSES = ("ok", "format_error", "blocked", "syntax_error", "runtime_error", "no_result", "timeout",
            "sandbox_error", "context_overflow", "rate_limited", "provider_unavailable", "llm_error")

Runner = Callable[[str], dict]


@dataclass
class BaselineResult:
    question: str
    status: str
    answer: dict | None
    error: str | None
    code: str | None = None
    unit: str | None = None
    raw_text: str | None = None
    result: dict | None = None            # the sandbox's plain-JSON form of `result`
    cited_rows: list[RowKey] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int | None = None
    generation_ms: float = 0.0
    execution_ms: float = 0.0             # sandbox wall time after the data was loaded
    cached: bool = False
    model: str | None = None
    provider: str | None = None
    fallback_reason: str | None = None


# --------------------------------------------------------------------------- result → answer object

def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _fmt(x: Any) -> str:
    return f"{x:,.4f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


def to_answer(res: dict, unit: str | None, frame_index: pd.Index | None = None,
              instruments: pd.Series | None = None) -> tuple[dict, list[int]]:
    """(answer object, index labels of df rows the result is made of)."""
    kind = res["kind"]
    value: float | int | None = None
    items: list[str] = []
    rows: list[int] = []
    text: str | None = None

    def as_rows(index: list[Any]) -> list[int]:
        if frame_index is None or not index or not all(isinstance(i, int) and not isinstance(i, bool)
                                                       for i in index):
            return []
        return index if frame_index.isin(index).sum() == len(set(index)) else []

    if kind == "scalar":
        v = res["value"]
        if _is_number(v):
            value = v
        elif isinstance(v, bool):
            text = "Yes" if v else "No"
        elif isinstance(v, str) and v.strip():
            items = [v]
    elif kind in ("list", "dict"):
        vals = [v for v in res["values"] if v is not None]
        if kind == "list" and len(vals) == 1 and _is_number(vals[0]):
            value = vals[0]
        elif kind == "dict":
            items = [f"{k}: {_fmt(v)}" for k, v in zip(res["keys"], res["values"])]
        else:
            items = [str(v) for v in vals]
    elif kind == "series":
        vals = res["values"]
        if res["n"] == 1 and vals and _is_number(vals[0]):
            value = vals[0]
        else:
            rows = as_rows(res["index"])
            if rows and instruments is not None:
                items = [str(instruments.loc[i]) for i in rows]
            elif rows:
                items = [str(v) for v in vals if v is not None]
            else:
                items = [str(i) for i in res["index"] if i is not None]
    elif kind == "dataframe":
        cols, data = res["columns"], res["rows"]
        if res["n"] == 1 and len(cols) == 1 and data and _is_number(data[0][0]):
            value = data[0][0]
        else:
            rows = as_rows(res["index"])
            if "instrument" in cols:
                j = cols.index("instrument")
                items = [str(r[j]) for r in data if r[j] is not None]
            elif rows and instruments is not None:
                items = [str(instruments.loc[i]) for i in rows]
            else:
                j = next((n for n, c in enumerate(cols) if data and isinstance(data[0][n], str)), 0)
                items = [str(r[j]) for r in data if cols and r[j] is not None]

    insufficient = value is None and not items and text is None
    if insufficient:
        summary = "The data does not answer this (the code returned an empty result)."
    elif value is not None:
        summary = f"Result: {_fmt(value)}" + (f" ({unit})" if unit else "")
    elif text is not None:
        summary = f"Result: {text}"
    else:
        more = res.get("n", len(items)) - len(items)
        summary = f"Result: {len(items) + max(more, 0)} item(s): " + "; ".join(items[:10]) \
                  + (" ..." if len(items) > 10 else "")
    answer = {"answer": summary, "value": value, "unit": unit if value is not None else None, "items": items,
              "sources": [], "insufficient_context": insufficient}
    return answer, rows


# --------------------------------------------------------------------------- pipeline

class BaselinePipeline:
    def __init__(self, settings, llm: LLM | None = None, runner: Runner | None = None,
                 frame: pd.DataFrame | None = None):
        self.settings = settings
        self.llm = llm or LLM.from_settings(settings)
        self.parquet = settings.paths.processed / HOLDINGS_FILE
        self.months = list(settings.data.eval_months)
        self.runner: Runner = runner or (lambda code: run_in_sandbox(code, self.parquet, self.months,
                                                                     settings.baseline.timeout_s))
        self._frame = frame
        self._schema: str | None = None
        self._keys: pd.DataFrame | None = None

    @property
    def frame(self) -> pd.DataFrame:
        """The same df the sandbox builds; used for the schema text and to resolve cited rows."""
        if self._frame is None:
            self._frame = load_frame(self.parquet, self.months)
        return self._frame

    @property
    def schema(self) -> str:
        if self._schema is None:
            self._schema = describe_frame(self.frame)
        return self._schema

    def _row_keys(self, labels: list[int]) -> list[RowKey]:
        if not labels:
            return []
        if self._keys is None:
            self._keys = pd.read_parquet(self.parquet, columns=["source_file", "source_sheet", "source_row"])
        return [row_key(r) for r in self._keys.loc[labels].itertuples(index=False)]

    def answer(self, question: str) -> BaselineResult:
        messages = build_messages(question, self.schema)
        base: dict[str, Any] = dict(question=question, model=self.llm.model, provider=self.llm.provider.name)
        try:
            res: LLMResult = self.llm.generate(messages, json=True)
        except LLMError as e:
            return BaselineResult(status=e.kind, answer=None, error=str(e), **base)
        base.update(raw_text=res.text, prompt_tokens=res.prompt_tokens, completion_tokens=res.completion_tokens,
                    reasoning_tokens=res.reasoning_tokens, generation_ms=res.latency_ms, cached=res.cached,
                    model=res.model, provider=res.provider, fallback_reason=res.fallback_reason)
        try:
            if res.finish_reason == JSON_INVALID:
                raise ReplyFormatError("provider rejected the reply as invalid JSON")
            code, unit = parse_reply(res.text)
        except ReplyFormatError as e:
            note = " (reply cut at max_output_tokens)" if res.finish_reason == "length" else ""
            return BaselineResult(status="format_error", answer=None, error=f"{e}{note}", **base)
        base.update(code=code, unit=unit)
        try:
            check_code(code)
        except SyntaxError as e:
            return BaselineResult(status="syntax_error", answer=None, error=f"line {e.lineno}: {e.msg}", **base)
        except BlockedCode as e:
            return BaselineResult(status="blocked", answer=None, error=str(e), **base)

        t0 = time.perf_counter()
        run = self.runner(code)
        execution_ms = run.get("wall_ms", (time.perf_counter() - t0) * 1000)
        if not run.get("ok"):
            return BaselineResult(status=run.get("error_type", "sandbox_error"), answer=None,
                                  error=run.get("error"), execution_ms=execution_ms, **base)
        frame = self.frame
        answer, labels = to_answer(run["result"], unit, frame.index, frame["instrument"])
        cited = self._row_keys(labels)
        if labels:
            answer["sources"] = [{"scheme": str(frame.at[i, "scheme"]), "instrument": str(frame.at[i, "instrument"])}
                                 for i in labels]
        return BaselineResult(status="ok", answer=answer, error=None, result=run["result"], cited_rows=cited,
                              execution_ms=execution_ms, **base)
