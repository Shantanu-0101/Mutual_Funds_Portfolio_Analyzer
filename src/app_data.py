"""Plain functions behind the Streamlit app (Phase 6). No Streamlit import here, so all of it is tested.

The pages stay thin: they call ``src.rag.pipeline`` / ``src.baseline.pipeline`` for answers and the
functions below to turn results into tables.

- ``AnswerView``: one shape for a RAG or a baseline answer (status, text, value, tokens, latency).
- ``rows_table``: cited / context row keys → the holdings rows themselves, for display.
- ``indexed_months`` / ``scheme_options``: what the sidebar can offer (only what is indexed; FR-6.4).
- ``*_frame``: the Results page tables, as numbers (the same definitions as ``results/summary.md``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.baseline.pipeline import BaselineResult
from src.chunking import REGISTRY
from src.chunking.base import RowKey
from src.eval.excel_report import _gold, _given
from src.eval.recommend import Recommendation
from src.eval.report import _methods, _types, accuracy_table
from src.eval.runner import BASELINE
from src.rag.pipeline import RagResult

CHUNKER_NAMES: tuple[str, ...] = tuple(REGISTRY)
METHOD_NAMES: tuple[str, ...] = (*CHUNKER_NAMES, BASELINE)

# One line per method, shown next to its name in the app.
METHOD_BLURB = {
    "fixed_size": "fixed token windows over the sheet text, with overlap",
    "row_wise": "one chunk per holding row, with its labels",
    "header_window": "blocks of rows, each repeating the table header",
    "scheme_level": "the whole scheme as one chunk (truncated if too long)",
    "section_aware": "one chunk per section (equity, debt, ...), split if too long",
    "hierarchical": "search single rows, then show the LLM their whole section",
    BASELINE: "no chunking: the LLM writes pandas code that runs on the full table",
}

HOLDING_COLUMNS = {"scheme_code": "Scheme code", "scheme": "Scheme", "section": "Section",
                   "instrument": "Instrument", "isin": "ISIN", "industry_or_rating": "Industry / rating",
                   "quantity": "Quantity", "market_value_lakhs": "Value (Rs lakh)", "pct_nav": "% to AUM",
                   "source_sheet": "Sheet", "source_row": "Excel row"}
KEY_COLUMNS = ["source_file", "source_sheet", "source_row"]


# --------------------------------------------------------------------------- answers

@dataclass
class AnswerView:
    """What the Ask and Compare pages show for one method, whatever pipeline produced it."""
    method: str
    status: str
    text: str                              # the answer sentence, or why there is none
    value: float | None = None
    unit: str | None = None
    items: list[str] = field(default_factory=list)
    insufficient: bool = False
    error: str | None = None
    cited_rows: list[RowKey] = field(default_factory=list)
    context_rows: list[RowKey] = field(default_factory=list)
    n_chunks: int | None = None            # None for the baseline (no retrieval)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    retrieval_ms: float | None = None
    generation_ms: float = 0.0
    execution_ms: float | None = None      # baseline only: running the generated code
    cached: bool = False
    provider: str | None = None
    model: str | None = None
    fallback_reason: str | None = None
    code: str | None = None                # baseline only
    raw_text: str | None = None
    retrieved: list = field(default_factory=list)   # RAG only: the Retrieved chunks shown to the LLM

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def total_ms(self) -> float:
        return (self.retrieval_ms or 0.0) + self.generation_ms + (self.execution_ms or 0.0)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def short(self) -> str:
        """The answer in a few words, for the Compare summary table."""
        if not self.ok:
            return f"({self.status})"
        if self.insufficient:
            return "says the data does not answer this"
        if self.value is not None:
            return f"{format_value(self.value)} {self.unit or ''}".strip()
        if self.items:
            more = f" (+{len(self.items) - 3} more)" if len(self.items) > 3 else ""
            return "; ".join(self.items[:3]) + more
        return self.text


STATUS_TEXT = {
    "format_error": "The model replied, but not in the agreed JSON format (counted as wrong; not repaired).",
    "context_overflow": "The prompt was too large for the model (on the Groq free tier this is usual for "
                        "scheme_level and hierarchical, whose prompts are near or above 8,000 tokens).",
    "rate_limited": "The provider's rate limit did not clear after retrying. Wait a minute and ask again.",
    "provider_unavailable": "The provider refused the key, has no credit, or is down.",
    "llm_error": "The provider returned an error.",
    "blocked": "The generated pandas code was refused by the safety check.",
    "syntax_error": "The generated pandas code does not parse.",
    "runtime_error": "The generated pandas code raised an error.",
    "no_result": "The generated code ran but did not set `result`.",
    "timeout": "The generated code ran too long and was stopped.",
    "sandbox_error": "The sandbox process failed (not the model's fault).",
}


def format_value(v: float) -> str:
    return f"{v:,.4f}".rstrip("0").rstrip(".") if isinstance(v, float) else f"{v:,}"


def view_of(result: RagResult | BaselineResult, method: str | None = None) -> AnswerView:
    """Turn a pipeline result into an ``AnswerView``."""
    is_rag = isinstance(result, RagResult)
    a = result.answer or {}
    text = a.get("answer") or STATUS_TEXT.get(result.status, result.status)
    common = dict(status=result.status, text=text, value=a.get("value"), unit=a.get("unit"),
                  items=[str(x) for x in a.get("items") or []], insufficient=bool(a.get("insufficient_context")),
                  error=result.error, cited_rows=list(result.cited_rows), prompt_tokens=result.prompt_tokens or 0,
                  completion_tokens=result.completion_tokens or 0, generation_ms=result.generation_ms or 0.0,
                  cached=result.cached, provider=result.provider, model=result.model,
                  fallback_reason=result.fallback_reason, raw_text=result.raw_text)
    if is_rag:
        return AnswerView(method=method or result.chunker, context_rows=list(result.context_rows),
                          n_chunks=len(result.retrieval.chunks), retrieval_ms=result.retrieval_ms,
                          retrieved=list(result.retrieval.chunks), **common)
    return AnswerView(method=method or BASELINE, execution_ms=result.execution_ms, code=result.code, **common)


def compare_frame(views: list[AnswerView]) -> pd.DataFrame:
    """One row per method for the Compare page's summary table."""
    return pd.DataFrame([{"Method": v.method, "Status": v.status, "Answer": v.short,
                          "Cited rows": len(v.cited_rows),
                          "Chunks": float("nan") if v.n_chunks is None else v.n_chunks,
                          "Prompt tokens": v.prompt_tokens, "Completion tokens": v.completion_tokens,
                          "Total ms": round(v.total_ms), "Cached": v.cached} for v in views])


# --------------------------------------------------------------------------- rows and filters

def holdings_by_key(holdings: pd.DataFrame) -> pd.DataFrame:
    """Holdings indexed by (source_file, source_sheet, source_row), the RowKey."""
    return holdings.set_index(KEY_COLUMNS, drop=False).sort_index()


def rows_table(by_key: pd.DataFrame, keys: list[RowKey]) -> pd.DataFrame:
    """The holdings rows behind ``keys``, in the given order, with readable column names.
    Keys not in the table are skipped (they cannot happen with matching data and index)."""
    wanted = [tuple(k) for k in keys]
    present = [k for k in wanted if k in by_key.index]
    if not present:
        return pd.DataFrame(columns=list(HOLDING_COLUMNS.values()))
    rows = by_key.loc[present, list(HOLDING_COLUMNS)].reset_index(drop=True)
    return rows.rename(columns=HOLDING_COLUMNS)


def indexed_months(client) -> list[str]:
    """Months present in every chunker collection that exists (read from Chroma metadata)."""
    months: set[str] | None = None
    for col in client.list_collections():
        n = col.count()
        found = {m.get("as_of_date") for m in col.get(limit=n, include=["metadatas"])["metadatas"]}
        months = found if months is None else months & found
    return sorted(m for m in (months or set()) if m)


def scheme_options(schemes: pd.DataFrame, month: str) -> dict[str, str]:
    """scheme code → label for one month, sorted by name."""
    s = schemes[schemes["as_of_date"].astype(str) == month].sort_values("scheme")
    return {r.scheme_code: f"{r.scheme} ({r.scheme_code})" for r in s.itertuples(index=False)}


# --------------------------------------------------------------------------- results page tables

def _pct_mean(s: pd.Series) -> float:
    s = s.dropna()
    return float(s.mean()) if len(s) else float("nan")


def accuracy_frame(df: pd.DataFrame) -> pd.DataFrame:
    """method × question type (and overall) → share correct, on every row of results.csv (as summary.md)."""
    counts = df.groupby("type")["qid"].nunique()
    t = accuracy_table(df)
    t.columns = [f"{c} ({counts[c]})" if c in counts else f"overall ({df['qid'].nunique()})" for c in t.columns]
    t.index.name = "Method"
    return t.reset_index()


def retrieval_frame(df: pd.DataFrame) -> pd.DataFrame:
    ans = df[df["answer_kind"] != "not_in_data"]
    rows = []
    for m in _methods(df):
        sub, sub_all = ans[ans["method"] == m], df[df["method"] == m]
        rows.append({"Method": m, "Hit": _pct_mean(sub["retrieval_hit"]),
                     "Gold-row recall": _pct_mean(sub["gold_row_recall"]),
                     "Chunks": sub_all["n_chunks"].mean(), "Holding rows": sub_all["n_context_rows"].mean(),
                     "Context tokens": sub_all["context_tokens"].mean(),
                     "Prompt tokens": sub_all["prompt_tokens"].mean(),
                     "Accuracy (answerable)": _pct_mean(sub["correct"])})
    return pd.DataFrame(rows)


def cost_frame(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for m in _methods(df):
        sub = df[df["method"] == m]
        rows.append({"Method": m, "Prompt tokens": sub["prompt_tokens"].mean(),
                     "Completion tokens": sub["completion_tokens"].mean(),
                     "Total tokens (all questions)": sub["prompt_tokens"].sum() + sub["completion_tokens"].sum(),
                     "Retrieval ms": sub["retrieval_ms"].mean(), "Generation ms": sub["generation_ms"].mean(),
                     "Code run ms": sub["execution_ms"].mean(), "Total ms": sub["total_ms"].mean()})
    return pd.DataFrame(rows)


def refusal_frame(df: pd.DataFrame) -> pd.DataFrame:
    una = df[df["answer_kind"] == "not_in_data"]
    ans = df[df["answer_kind"] != "not_in_data"]
    return pd.DataFrame([{"Method": m,
                          "Unanswerable: correctly refused": _pct_mean(una[una["method"] == m]["unanswerable_correct"]),
                          "Answerable: refused anyway": _pct_mean(ans[ans["method"] == m]["false_refusal"])}
                         for m in _methods(df)])


def status_frame(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for m in _methods(df):
        sub = df[df["method"] == m]
        st = sub[sub["status"] != "ok"]["status"].value_counts()
        fl = sub[sub["failure"] != ""]["failure"].value_counts()
        rows.append({"Method": m, "Non-ok status": ", ".join(f"{k} {v}" for k, v in st.items()) or "all ok",
                     "Wrong answers by kind": ", ".join(f"{k} {v}" for k, v in fl.items()) or "none",
                     "Pending": int(sub["pending"].fillna(0).sum())})
    return pd.DataFrame(rows)


def ranking_frame(rec: Recommendation) -> pd.DataFrame:
    rows = [{"Rank": str(s.rank), "Method": s.method, "Correct": f"{s.correct}/{s.n}", "Accuracy": s.accuracy,
             "Gold-row recall": s.recall, "Tokens / question": s.tokens,
             "Main failure": s.main_failure or "none", "Note": s.note} for s in rec.ranking]
    rows += [{"Rank": "–", "Method": m, "Correct": "", "Accuracy": None, "Gold-row recall": None,
              "Tokens / question": None, "Main failure": "", "Note": "not run, so not ranked"} for m in rec.not_run]
    b = rec.baseline
    if b is not None:
        rows.append({"Rank": "not ranked", "Method": BASELINE, "Correct": f"{b.correct}/{b.n}",
                     "Accuracy": b.accuracy, "Gold-row recall": None, "Tokens / question": b.tokens,
                     "Main failure": b.main_failure or "none", "Note": "no chunking; compared only"})
    return pd.DataFrame(rows)


def by_type_frame(rec: Recommendation) -> pd.DataFrame:
    return pd.DataFrame([{"Question type": b.type, "Questions": b.n, "Best method": ", ".join(b.best) or "none",
                          "Accuracy": b.accuracy if b.best else None, "Runner-up": b.runner_up or "–",
                          "Decided by": b.decided_by} for b in rec.by_type])


def per_question_frame(df: pd.DataFrame) -> pd.DataFrame:
    order = {m: i for i, m in enumerate(METHOD_NAMES)}
    rows = df.assign(_o=df["method"].map(order).fillna(99)).sort_values(["_o", "qid"])
    return pd.DataFrame([{"Method": r["method"], "Question": r["qid"], "Type": r["type"],
                          "Question text": r["question"], "Gold answer": _gold(r["gold_value"], r["unit"]),
                          "Answer given": _given(r), "Correct": r["correct"] == 1,
                          "Wrong because": "pending" if r["pending"] == 1 else r["failure"],
                          "Status": r["status"]} for _, r in rows.iterrows()])


def types_in(df: pd.DataFrame) -> list[str]:
    return _types(df)
