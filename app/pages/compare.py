"""Compare page (FR-6.2): the same question through every chunking method and the baseline, side by side."""

from __future__ import annotations

import streamlit as st

import common as c
from src.app_data import BASELINE, METHOD_NAMES, compare_frame, rows_table

c.require_data()

st.title("Compare")
st.caption("One question through each method, one after another, with the same LLM and settings. Replies are "
           "cached, so asking the same question again costs nothing.")

month, picked = c.filters("cmp")
methods = st.sidebar.multiselect("Methods", METHOD_NAMES, default=list(METHOD_NAMES), key="cmp_methods",
                                 format_func=c.method_label)
c.llm_caption()
if c.settings().llm.provider == "groq":
    st.sidebar.caption("On the Groq free tier (8,000 tokens/minute) `scheme_level` and `hierarchical` usually "
                       "fail with *context_overflow*, and asking all methods at once can wait on the rate "
                       "limit for up to a minute or two.")

with st.form("cmp_form", border=False):
    question = st.text_area("Question", key="cmp_question", height=90,
                            placeholder="e.g. Which scheme holds more of HDFC Bank Ltd.: Flexi Cap or Large Cap?")
    go = st.form_submit_button("Compare", type="primary")

if go:
    if not question.strip():
        st.warning("Type a question first.")
        st.stop()
    if not methods:
        st.warning("Pick at least one method in the sidebar.")
        st.stop()
    views = []
    bar = st.progress(0.0)
    for i, m in enumerate(methods):
        bar.progress(i / len(methods), text=f"Asking {c.method_label(m)} ({i + 1} of {len(methods)})…")
        views.append(c.ask(m, question.strip(), month, picked))
    bar.empty()
    st.session_state["cmp_result"] = (question.strip(), month, tuple(picked), views)

saved = st.session_state.get("cmp_result")
if not saved:
    st.stop()

q, mo, schemes, views = saved
st.markdown(f"**Question:** {q}")
if (mo, schemes) != (month, tuple(picked)) or q != question.strip():
    st.caption("Showing the last comparison; the question or the sidebar has changed since.")
note = c.baseline_note(mo, list(schemes)) if any(v.method == BASELINE for v in views) else None
if note:
    st.caption(note)

st.dataframe(compare_frame(views), hide_index=True, placeholder="–",
             column_config={"Prompt tokens": st.column_config.NumberColumn(format="localized"),
                            "Completion tokens": st.column_config.NumberColumn(format="localized"),
                            "Total ms": st.column_config.NumberColumn(format="localized")})

PER_ROW = 3
for start in range(0, len(views), PER_ROW):
    cols = st.columns(PER_ROW)
    for col, v in zip(cols, views[start:start + PER_ROW]):
        with col, st.container(border=True):
            st.markdown(f"#### {c.method_label(v.method)}")
            st.caption(c.blurb(v.method))
            c.answer_body(v)
            st.caption(c.usage_line(v))
            label = "result rows" if v.method == BASELINE else "cited rows"
            with st.expander(f"{len(v.cited_rows)} {label}"
                             + (f" · {len(v.retrieved)} chunks" if v.method != BASELINE else " · code")):
                if v.cited_rows:
                    st.dataframe(rows_table(c.holdings(), v.cited_rows), hide_index=True,
                                 column_config=c.ROW_CONFIG)
                if v.code:
                    st.code(v.code, language="python")
                for r in v.retrieved:
                    st.caption(f"#{r.rank} · score {r.score:.3f} · {r.chunk.scheme_code} · {r.chunk.section} · "
                               f"{r.chunk.n_tokens:,} tokens")
                    st.text(r.chunk.text[:3000] + ("…" if len(r.chunk.text) > 3000 else ""))
                if v.raw_text and not v.ok:
                    st.caption("Raw model reply")
                    st.text(v.raw_text[:2000])
