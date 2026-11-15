"""Shared pieces of the Streamlit pages: cached resources, the sidebar, and how one answer is drawn.

Everything heavy (settings, the embedding model, Chroma, the parsed tables, both pipelines) is built
once per server with ``st.cache_resource`` and only *read*: the app never parses or indexes (FR-6.4).
If the index or the parsed data is missing, the page says which command to run and stops.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src.app_data import (  # noqa: E402
    BASELINE, METHOD_BLURB, STATUS_TEXT, AnswerView, format_value, holdings_by_key, indexed_months,
    rows_table, scheme_options, view_of,
)
from src.config import get_settings  # noqa: E402
from src.parsing.pipeline import HOLDINGS_FILE  # noqa: E402

SCHEMES_FILE = "schemes.parquet"
SETUP_HINT = ("Build the data first, from the project folder:\n\n"
              "```\npython -m src.parsing\npython -m src.index --month 2026-09-30 --chunkers all\n```")


# --------------------------------------------------------------------------- cached resources

@st.cache_resource(show_spinner=False)
def settings():
    return get_settings()


@st.cache_resource(show_spinner="Loading the embedding model and the index…")
def retriever():
    from src.rag.retrieve import Retriever

    r = Retriever(settings())
    r.embedder.load()
    return r


@st.cache_resource(show_spinner=False)
def rag_pipeline():
    from src.rag.pipeline import RagPipeline

    return RagPipeline(settings(), retriever=retriever())


@st.cache_resource(show_spinner=False)
def baseline_pipeline():
    from src.baseline.pipeline import BaselinePipeline

    return BaselinePipeline(settings())


@st.cache_resource(show_spinner=False)
def holdings() -> pd.DataFrame:
    return holdings_by_key(pd.read_parquet(settings().paths.processed / HOLDINGS_FILE))


@st.cache_resource(show_spinner=False)
def schemes() -> pd.DataFrame:
    return pd.read_parquet(settings().paths.processed / SCHEMES_FILE)


@st.cache_resource(show_spinner=False)
def months() -> list[str]:
    return indexed_months(retriever().client)


def require_data() -> None:
    """Stop the page with a clear message if the parsed data or the index is not there."""
    s = settings()
    missing = [f for f in (HOLDINGS_FILE, SCHEMES_FILE) if not (s.paths.processed / f).is_file()]
    if missing:
        st.error(f"Parsed data not found in `{s.paths.processed}` ({', '.join(missing)}).\n\n" + SETUP_HINT)
        st.stop()
    try:
        found = months()
    except Exception as e:                     # Chroma missing or built with another model
        st.error(f"The index could not be opened: {e}\n\n" + SETUP_HINT)
        st.stop()
    if not found:
        st.error("The index is empty.\n\n" + SETUP_HINT)
        st.stop()


# --------------------------------------------------------------------------- sidebar

def llm_caption() -> None:
    llm = settings().llm
    fb = llm.fallback if llm.fallback not in (None, "none") else "none"
    st.sidebar.caption(f"LLM: **{llm.provider}** / `{llm.models.get(llm.provider)}` · fallback {fb} · "
                       f"temperature {llm.temperature}. Change `llm.provider` in `config.yaml` to switch.")


def filters(key: str) -> tuple[str, list[str]]:
    """Month and scheme(s) pickers in the sidebar. Only indexed months are offered."""
    ms = months()
    month = st.sidebar.selectbox("Month", ms, index=len(ms) - 1, key=f"{key}_month",
                                 format_func=lambda m: pd.Timestamp(m).strftime("%B %Y"))
    opts = scheme_options(schemes(), month)
    picked = st.sidebar.multiselect("Scheme(s)", list(opts), format_func=opts.get, key=f"{key}_schemes",
                                    placeholder="All schemes",
                                    help="Search only these schemes' chunks. Leave empty to search all of them "
                                         "(the evaluation runs without this filter).")
    return month, picked


def method_label(m: str) -> str:
    return "pandas baseline (no chunking)" if m == BASELINE else m


# --------------------------------------------------------------------------- asking

def ask(method: str, question: str, month: str, scheme_codes: list[str]) -> AnswerView:
    """One question through one method. The baseline reads the whole evaluated month (no filters)."""
    if method == BASELINE:
        return view_of(baseline_pipeline().answer(question))
    res = rag_pipeline().answer(question, method, scheme_code=scheme_codes or None, as_of_date=month)
    return view_of(res)


def baseline_note(month: str, scheme_codes: list[str]) -> str | None:
    s = settings()
    notes = []
    if scheme_codes:
        notes.append("the scheme filter does not apply (its code reads the whole table)")
    if month not in s.data.eval_months:
        notes.append(f"it reads the evaluated month(s) {', '.join(s.data.eval_months)}, not {month}")
    return ("Baseline: " + "; ".join(notes) + ".") if notes else None


# --------------------------------------------------------------------------- drawing one answer

ROW_CONFIG = {
    "Quantity": st.column_config.NumberColumn(format="localized"),
    "Value (Rs lakh)": st.column_config.NumberColumn(format="localized"),
    "% to AUM": st.column_config.NumberColumn(format="%.2f"),
    "Excel row": st.column_config.NumberColumn(format="plain"),
}


def answer_body(v: AnswerView) -> None:
    """The answer itself: sentence, value or items, or why there is none."""
    if not v.ok:
        st.warning(f"**{v.status}**: {STATUS_TEXT.get(v.status, '')}")
        if v.error:
            st.caption(v.error)
        return
    if v.insufficient:
        st.info(v.text)
    else:
        st.markdown(v.text)
    if v.value is not None:
        st.markdown(f"**Value:** {format_value(v.value)} {v.unit or ''}")
    if v.items:
        shown = v.items[:25]
        st.markdown("\n".join(f"- {x}" for x in shown)
                    + (f"\n- … {len(v.items) - 25} more" if len(v.items) > 25 else ""))
    if v.fallback_reason:
        st.caption(f"Answered by the fallback {v.provider} / {v.model} because {v.fallback_reason}.")


def usage_line(v: AnswerView) -> str:
    parts = [f"{v.prompt_tokens:,} prompt + {v.completion_tokens:,} completion tokens"]
    if v.retrieval_ms is not None:
        parts.append(f"retrieval {v.retrieval_ms:,.0f} ms")
    parts.append(f"generation {v.generation_ms:,.0f} ms")
    if v.execution_ms is not None:
        parts.append(f"code run {v.execution_ms:,.0f} ms")
    if v.cached:
        parts.append("cached reply (latency is the original call's)")
    return " · ".join(parts)


def duration(ms: float) -> str:
    """Short enough for a metric tile: '850 ms', '1.2 s'."""
    return f"{ms:,.0f} ms" if ms < 1000 else f"{ms / 1000:,.1f} s"


def usage_metrics(v: AnswerView) -> None:
    cols = st.columns(4)
    cols[0].metric("Prompt tokens", f"{v.prompt_tokens:,}")
    cols[1].metric("Completion tokens", f"{v.completion_tokens:,}")
    if v.retrieval_ms is not None:
        cols[2].metric("Retrieval", duration(v.retrieval_ms))
    else:
        cols[2].metric("Code run", duration(v.execution_ms or 0))
    cols[3].metric("Generation", duration(v.generation_ms))
    if v.cached:
        st.caption("Cached reply: the same prompt was asked before, so no new LLM call was made; "
                   "latency shown is that of the original call.")


def cited_rows(v: AnswerView) -> None:
    if v.method == BASELINE:
        label = "Rows the result is made of"
    else:
        label = "Rows the answer cites"
    st.markdown(f"**{label}** ({len(v.cited_rows)})")
    if v.cited_rows:
        st.dataframe(rows_table(holdings(), v.cited_rows), hide_index=True, column_config=ROW_CONFIG)
    else:
        st.caption("None." if v.ok else "No answer, so no rows.")


def retrieved_chunks(v: AnswerView, expanded_first: bool = False) -> None:
    if v.method == BASELINE:
        if v.code:
            with st.expander("Generated pandas code", expanded=expanded_first):
                st.code(v.code, language="python")
        return
    st.markdown(f"**Retrieved chunks** ({len(v.retrieved)}; {len(v.context_rows)} holding rows shown to the LLM)")
    for r in v.retrieved:
        c = r.chunk
        via = f" · via {len(r.children)} child row(s)" if r.children else ""
        with st.expander(f"#{r.rank} · score {r.score:.3f} · {c.scheme_code} · {c.section} · "
                         f"{c.n_tokens:,} tokens{via}", expanded=expanded_first and r.rank == 1):
            st.caption(f"`{c.id}`" + (" · truncated to the embedding limit" if c.truncated else ""))
            st.text(c.text)


def raw_reply(v: AnswerView) -> None:
    if v.raw_text and not v.ok:
        with st.expander("Raw model reply"):
            st.text(v.raw_text[:4000])


def blurb(method: str) -> str:
    return METHOD_BLURB.get(method, "")
