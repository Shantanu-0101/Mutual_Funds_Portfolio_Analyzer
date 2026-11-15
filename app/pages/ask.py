"""Ask page (FR-6.1): one question through one chunking method or the pandas baseline."""

from __future__ import annotations

import streamlit as st

import common as c
from src.app_data import BASELINE, METHOD_NAMES

c.require_data()

st.title("Ask")
st.caption("Ask a question about the ABSL monthly portfolio disclosures. The answer comes only from the "
           "retrieved chunks (or, for the baseline, from pandas code run on the full table).")

month, picked = c.filters("ask")
method = st.sidebar.selectbox("Chunking method", METHOD_NAMES, format_func=c.method_label, key="ask_method")
st.sidebar.caption(c.blurb(method))
st.sidebar.caption(f"Top-k: {c.settings().retrieval.top_k} chunks (from `config.yaml`).")
c.llm_caption()


@st.cache_data(show_spinner=False)
def example_questions() -> list[str]:
    from src.eval.questions import load_questions

    try:
        return [q.text for q in load_questions(eval_months=c.settings().data.eval_months)]
    except Exception:
        return []


examples = example_questions()
if examples:
    pick = st.selectbox("Start from an evaluation question (optional)", ["", *examples], key="ask_example",
                        format_func=lambda q: q or "Type your own below")
    if pick and st.session_state.get("ask_last_example") != pick:
        st.session_state["ask_question"] = pick
        st.session_state["ask_last_example"] = pick

with st.form("ask_form", border=False):
    question = st.text_area("Question", key="ask_question", height=90,
                            placeholder="e.g. What % of AUM does Aditya Birla Sun Life Flexi Cap Fund hold in "
                                        "ICICI Bank Ltd.?")
    go = st.form_submit_button("Ask", type="primary")

if go:
    if not question.strip():
        st.warning("Type a question first.")
        st.stop()
    with st.spinner(f"Asking {c.method_label(method)}…"):
        st.session_state["ask_result"] = (question.strip(), method, month, tuple(picked),
                                          c.ask(method, question.strip(), month, picked))

saved = st.session_state.get("ask_result")
if not saved:
    st.stop()

q, m, mo, schemes, v = saved
if (m, mo, schemes) != (method, month, tuple(picked)) or q != question.strip():
    st.caption("Showing the last answer; the question or the sidebar has changed since. Press **Ask** to "
               "run it again.")

st.subheader(c.method_label(m))
note = c.baseline_note(mo, list(schemes)) if m == BASELINE else None
if note:
    st.caption(note)
c.answer_body(v)
c.usage_metrics(v)
c.cited_rows(v)
c.retrieved_chunks(v)
c.raw_reply(v)
