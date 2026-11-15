"""Results page (FR-6.3, Phase 5c): the recorded evaluation, read from ``results/results.csv``.

Nothing is re-asked here. The page opens with the recommendation (``src.eval.recommend``, the same verdict
as ``chunking_report.xlsx``) and a download of that Excel file, then the tables of ``summary.md`` as
numbers, the chart, and every answer.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import common as c
from src.app_data import (
    accuracy_frame, by_type_frame, cost_frame, per_question_frame, ranking_frame, refusal_frame,
    retrieval_frame, status_frame, types_in,
)
from src.eval.excel_report import EXCEL_FILE
from src.eval.recommend import recommend, verdict_line
from src.eval.report import CHART_FILE, load
from src.eval.runner import RESULTS_FILE



def table(df: pd.DataFrame, pct=(), bar=(), ints=(), dec1=(), **kw) -> None:
    """Show a frame of numbers the way summary.md writes them: whole percents, whole tokens / ms.
    ``pct`` / ``bar`` columns hold shares (0–1); ``bar`` also draws a bar."""
    df = df.copy()
    cfg = {}
    for col in [*pct, *bar]:
        df[col] = pd.to_numeric(df[col], errors="coerce") * 100
        cfg[col] = (st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100) if col in bar
                    else st.column_config.NumberColumn(format="%.0f%%"))
    for col in ints:
        df[col] = pd.to_numeric(df[col], errors="coerce").round(0)
        cfg[col] = st.column_config.NumberColumn(format="localized")
    for col in dec1:
        cfg[col] = st.column_config.NumberColumn(format="%.1f")
    st.dataframe(df, hide_index=True, placeholder="–", column_config={**cfg, **kw.pop("column_config", {})},
                 **kw)


st.title("Results")
c.llm_caption()

results_dir = c.settings().paths.results
csv = results_dir / RESULTS_FILE
if not csv.is_file():
    st.info(f"No evaluation results yet (`{csv}` not found). Run `python -m src.eval run`, then "
            "`python -m src.eval report`.")
    st.stop()


@st.cache_data(show_spinner=False)
def _load(path: str, mtime: float):        # mtime in the key: a new run is picked up without a restart
    return load(results_dir)


df, manifest = _load(str(csv), csv.stat().st_mtime)
llm = manifest.get("llm", {})
st.caption(f"From `results/{RESULTS_FILE}`: {len(df)} rows, {df['method'].nunique()} methods × "
           f"{df['qid'].nunique()} questions. Answered by {llm.get('provider')} / `{llm.get('model')}`; run "
           f"started {manifest.get('created_at', '–')}, {'complete' if manifest.get('complete') else 'not complete'}.")

# ---------------------------------------------------------------- recommendation (Phase 5c)
try:
    rec = recommend(df)
except ValueError as e:
    rec = None
    st.info(f"No recommendation yet: {e}.")

if rec is not None:
    with st.container(border=True):
        st.markdown("### Recommended chunking method")
        if rec.final:
            st.success(verdict_line(rec))
        else:
            st.warning(verdict_line(rec) + " See the caveats below.")
        st.caption("Rule: most correct answers; a tie goes to higher gold-row recall, then to fewer tokens per "
                   "question. The pandas baseline is compared but not ranked. Every sentence below is built "
                   "from the measured numbers, not written by the LLM.")
        st.markdown("\n".join(f"- {r}" for r in rec.reasons))
        for cav in rec.caveats:
            st.caption(f":material/warning: {cav}")
        st.markdown("**Best method per question type**")
        table(by_type_frame(rec), pct=["Accuracy"])
        if rec.baseline_note:
            st.caption(rec.baseline_note)
        xlsx = results_dir / EXCEL_FILE
        if xlsx.is_file():
            st.download_button("Download the Excel report", xlsx.read_bytes(), file_name=EXCEL_FILE,
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               icon=":material/download:", type="primary")
            st.caption(f"`results/{EXCEL_FILE}`: recommendation, ranking, accuracy by type, retrieval and cost, "
                       "every answer, run info.")
        else:
            st.caption(f"`results/{EXCEL_FILE}` not found: run `python -m src.eval report` to write it.")

    st.markdown("#### Ranking")
    st.caption(f"Every chunker on the same {len(rec.qids)} questions (questions still pending for any chunker "
               "are left out for all).")
    table(ranking_frame(rec), pct=["Accuracy", "Gold-row recall"], ints=["Tokens / question"])

# ---------------------------------------------------------------- the summary.md tables
st.markdown("#### Accuracy by method and question type")
st.caption("Correct answers / questions, on every row of results.csv (as in `summary.md`). Unanswerable "
           "questions count as correct when the method says the data does not contain the answer.")
acc = accuracy_frame(df)
table(acc, bar=[col for col in acc.columns if col != "Method"])

chart = results_dir / CHART_FILE
if chart.is_file():
    left, _ = st.columns([3, 2])
    left.image(str(chart), caption="Overall accuracy by method (results/accuracy_by_method.png)")

st.markdown("#### Retrieval and context size")
st.caption("Answerable questions only. *Hit*: at least one gold row was in the context. *Gold-row recall*: "
           "share of the gold rows in the context. Context tokens use the embedding tokenizer; prompt tokens "
           "are the LLM's count of the whole prompt. The baseline has no retrieval.")
table(retrieval_frame(df), pct=["Hit", "Gold-row recall", "Accuracy (answerable)"], dec1=["Chunks"],
      ints=["Holding rows", "Context tokens", "Prompt tokens"])

st.markdown("#### Tokens and latency")
st.caption("Means per question. Latency of a cached answer is that of its original call.")
cost = cost_frame(df)
table(cost, ints=[k for k in cost.columns if k != "Method"])

st.markdown("#### Refusals")
table(refusal_frame(df), pct=["Unanswerable: correctly refused", "Answerable: refused anyway"])

st.markdown("#### Status and failure kinds")
st.caption("*retrieval miss*: not every gold row reached the LLM; *generation error*: the rows were there and "
           "the answer is still wrong; *format error*: the reply broke the JSON format; *context overflow*: the "
           "prompt was too large. *Pending* rows have no real answer yet (rate limit, provider down).")
st.dataframe(status_frame(df), hide_index=True)

# ---------------------------------------------------------------- every answer
st.markdown("#### Every answer")
f1, f2, f3 = st.columns(3)
pick_m = f1.multiselect("Method", list(dict.fromkeys(df["method"])), placeholder="All methods")
pick_t = f2.multiselect("Question type", types_in(df), placeholder="All types")
only_wrong = f3.toggle("Only wrong answers")
pq = per_question_frame(df)
if pick_m:
    pq = pq[pq["Method"].isin(pick_m)]
if pick_t:
    pq = pq[pq["Type"].isin(pick_t)]
if only_wrong:
    pq = pq[~pq["Correct"]]
st.dataframe(pq, hide_index=True, height=420,
             column_config={"Question text": st.column_config.TextColumn(width="large"),
                            "Answer given": st.column_config.TextColumn(width="large")})
st.caption(f"{len(pq)} of {len(df)} rows.")
