"""Phase 6: the app's helpers (src/app_data.py) and a smoke run of the Results page.

The helpers use the small synthetic index from test_rag.py and a mock LLM; no network, no real index.
The Results page runs on the committed ``results/`` folder (skipped if it is not there).
"""

import json
import math
import sys
from pathlib import Path

import pandas as pd
import pytest

from src.app_data import (
    METHOD_NAMES, AnswerView, accuracy_frame, compare_frame, cost_frame, holdings_by_key, indexed_months,
    per_question_frame, ranking_frame, refusal_frame, retrieval_frame, rows_table, scheme_options, status_frame,
    view_of,
)
from src.baseline.pipeline import BaselineResult
from src.eval.recommend import recommend
from src.eval.runner import BASELINE
from tests.test_chunkers import CODE, DATE
from tests.test_rag import GOOD, _pipe, env  # noqa: F401  (env is a fixture)
from tests.test_recommend import ALL, all_chunkers, frame, method_rows

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- answers

def test_view_of_rag_answer(env):
    r = _pipe(env, lambda m: json.dumps(GOOD)).answer("Stock A Ltd. % to AUM", "row_wise")
    v = view_of(r)
    assert v.ok and v.method == "row_wise" and v.value == 5.6 and v.short.startswith("5.6")
    assert v.cited_rows == [("synthetic.xls", "SYNEQ", 8)]
    assert v.n_chunks == len(v.retrieved) == env.s.retrieval.top_k and v.context_rows
    assert v.retrieval_ms > 0 and v.execution_ms is None and v.code is None
    assert v.total_ms == pytest.approx(v.retrieval_ms + v.generation_ms)


def test_view_of_failed_rag_answer_explains_status(env):
    v = view_of(_pipe(env, lambda m: "not json").answer("Stock A", "row_wise"))
    assert not v.ok and v.status == "format_error" and "JSON format" in v.text
    assert v.short == "(format_error)" and v.raw_text == "not json"


def test_view_of_baseline_answer():
    res = BaselineResult(question="q", status="ok", code="result = 3", unit="count", execution_ms=12.0,
                         answer={"answer": "Result: 3 (count)", "value": 3, "unit": "count", "items": [],
                                 "sources": [], "insufficient_context": False},
                         error=None, prompt_tokens=50, completion_tokens=10, generation_ms=100.0)
    v = view_of(res)
    assert v.method == BASELINE and v.code == "result = 3" and v.n_chunks is None and v.retrieved == []
    assert v.total_ms == 112.0 and v.total_tokens == 60 and v.short == "3 count"


def test_short_answer_forms():
    base = dict(method="m", status="ok", text="t")
    assert AnswerView(**base, insufficient=True).short == "says the data does not answer this"
    assert AnswerView(**base, items=list("abcde")).short == "a; b; c (+2 more)"
    assert AnswerView(**base, value=1234.5, unit="pct").short == "1,234.5 pct"
    assert AnswerView(**base).short == "t"


def test_compare_frame_one_row_per_method():
    views = [AnswerView(method="row_wise", status="ok", text="x", value=2.0, n_chunks=5, prompt_tokens=10),
             AnswerView(method=BASELINE, status="timeout", text="y")]
    f = compare_frame(views)
    assert list(f["Method"]) == ["row_wise", BASELINE] and list(f["Answer"]) == ["2", "(timeout)"]
    assert math.isnan(f.loc[1, "Chunks"])


# --------------------------------------------------------------------------- rows and filters

def test_rows_table_keeps_order_and_skips_unknown(env):
    by_key = holdings_by_key(env.sheet)
    keys = [("synthetic.xls", "SYNEQ", 9), ("nope.xls", "X", 1), ("synthetic.xls", "SYNEQ", 8)]
    t = rows_table(by_key, keys)
    assert list(t["Excel row"]) == [9, 8] and list(t["Instrument"]) == ["Stock B Ltd.", "Stock A Ltd."]
    assert "% to AUM" in t.columns
    assert rows_table(by_key, []).empty


def test_indexed_months_and_multi_scheme_filter(env):
    assert indexed_months(env.client) == [DATE]
    both = env.retriever.retrieve("Stock C", "row_wise", top_k=3, scheme_code=["NOPE", CODE], as_of_date=DATE)
    assert len(both.chunks) == 3 and {r.chunk.scheme_code for r in both.chunks} == {CODE}
    assert env.retriever.retrieve("Stock C", "row_wise", scheme_code=["NOPE", "NOPE2"]).chunks == []


def test_scheme_options_for_one_month():
    s = pd.DataFrame({"scheme_code": ["B", "A", "A"], "scheme": ["BETA FUND", "ALPHA FUND", "ALPHA FUND"],
                      "as_of_date": ["2026-09-30", "2026-09-30", "2026-08-31"]})
    assert scheme_options(s, "2026-09-30") == {"A": "ALPHA FUND (A)", "B": "BETA FUND (B)"}


# --------------------------------------------------------------------------- results tables

def _results() -> pd.DataFrame:
    df = all_chunkers({"row_wise": ALL - {"Q3"}, "fixed_size": {"Q5"}})
    base = pd.DataFrame(method_rows(BASELINE, {"Q1", "Q3"}))
    return pd.concat([df, base], ignore_index=True)


def test_results_frames_match_summary_definitions():
    df = _results()
    acc = accuracy_frame(df).set_index("Method")
    assert acc.loc["row_wise", "overall (5)"] == pytest.approx(0.8)
    assert acc.loc["row_wise", "aggregation (2)"] == pytest.approx(0.5)
    ret = retrieval_frame(df).set_index("Method")
    assert ret.loc["row_wise", "Accuracy (answerable)"] == pytest.approx(0.75)
    assert ret.loc["row_wise", "Hit"] == 1.0
    cost = cost_frame(df).set_index("Method")
    assert cost.loc["row_wise", "Total tokens (all questions)"] == 5 * 1100
    ref = refusal_frame(df).set_index("Method")
    assert ref.loc["row_wise", "Unanswerable: correctly refused"] == 1.0
    st = status_frame(df).set_index("Method")
    assert st.loc["fixed_size", "Wrong answers by kind"] == "generation error 4"
    assert list(accuracy_frame(df)["Method"])[-1] == BASELINE


def test_ranking_frame_lists_not_run_and_baseline_unranked():
    df = pd.concat([frame(method_rows("row_wise", {"Q1"}), method_rows("fixed_size", ALL)),
                    pd.DataFrame(method_rows(BASELINE, {"Q1"}))], ignore_index=True)
    r = ranking_frame(recommend(df))
    assert list(r["Method"][:2]) == ["fixed_size", "row_wise"] and list(r["Rank"][:2]) == ["1", "2"]
    assert set(r[r["Rank"] == "–"]["Method"]) == set(METHOD_NAMES) - {"row_wise", "fixed_size", BASELINE}
    assert r.iloc[-1]["Method"] == BASELINE and r.iloc[-1]["Rank"] == "not ranked"


def test_per_question_frame_orders_methods():
    pq = per_question_frame(_results())
    assert pq["Method"].iloc[0] == METHOD_NAMES[0] and pq["Method"].iloc[-1] == BASELINE
    assert pq["Correct"].dtype == bool and len(pq) == len(_results())


# --------------------------------------------------------------------------- the Results page itself

@pytest.mark.skipif(not (ROOT / "results" / "results.csv").is_file(), reason="no committed results")
def test_results_page_renders_recommendation_and_download():
    from streamlit.testing.v1 import AppTest

    sys.path.insert(0, str(ROOT / "app"))
    try:
        at = AppTest.from_file(str(ROOT / "app" / "pages" / "results.py"), default_timeout=60).run()
    finally:
        sys.path.remove(str(ROOT / "app"))
    assert not at.exception, at.exception
    text = " ".join(m.value for m in [*at.success, *at.warning])
    assert "Best chunking method for this data" in text
    assert [h.value for h in at.markdown if h.value.startswith("###")][0] == "### Recommended chunking method"
    assert len(at.dataframe) >= 7
