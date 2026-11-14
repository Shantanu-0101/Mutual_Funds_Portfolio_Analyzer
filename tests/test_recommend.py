"""Phase 5c: best-chunker ranking (R2–R5) and the Excel report. Synthetic results only; no LLM, no index."""

import math

import pandas as pd
import pytest
from openpyxl import load_workbook

from src.eval.excel_report import write_excel
from src.eval.recommend import CHUNKERS, recommend

QS = [("Q1", "lookup", "number"), ("Q2", "lookup", "number"), ("Q3", "aggregation", "number"),
      ("Q4", "aggregation", "number"), ("Q5", "unanswerable", "not_in_data")]


def row(method, qid, qtype, kind, correct, *, recall=1.0, tokens=1000, pending=0, status="ok"):
    answerable = kind != "not_in_data"
    failure = "" if correct else ("retrieval miss" if answerable and recall < 1 else "generation error")
    return {"method": method, "qid": qid, "type": qtype, "answer_kind": kind, "unit": "pct" if answerable else "",
            "question": f"question {qid}", "gold_value": "5.0" if answerable else "null", "status": status,
            "error": "", "pending": pending, "failure": "" if pending else failure, "correct": correct,
            "refused": 0, "false_refusal": 0 if answerable else math.nan,
            "unanswerable_correct": math.nan if answerable else correct,
            "retrieval_hit": (1 if recall > 0 else 0) if answerable else math.nan,
            "gold_row_recall": recall if answerable else math.nan, "value": "5.0", "answer_unit": "pct",
            "items": "[]", "answer": "5%", "prompt_tokens": tokens, "completion_tokens": 100, "n_chunks": 5,
            "n_context_rows": 10, "context_tokens": tokens - 300, "retrieval_ms": 10, "generation_ms": 900,
            "execution_ms": math.nan, "total_ms": 910, "model": "m"}


def method_rows(method, right: set[str], **kw):
    return [row(method, q, t, k, int(q in right), **kw) for q, t, k in QS]


def frame(*parts) -> pd.DataFrame:
    return pd.DataFrame([r for p in parts for r in p])


ALL = {q for q, _, _ in QS}


def all_chunkers(right_by_method: dict[str, set[str]], **kw) -> pd.DataFrame:
    return frame(*(method_rows(m, right_by_method.get(m, set()), **kw) for m in CHUNKERS))


def test_most_correct_wins_and_reasons_use_the_numbers():
    df = all_chunkers({"row_wise": ALL - {"Q3"}, "fixed_size": {"Q5"}})
    rec = recommend(df)
    assert rec.best == ["row_wise"] and rec.final and rec.caveats == []
    assert rec.reasons[0].startswith("Most correct answers: 80% (4/5), 3 more than the runner-up fixed_size")
    assert any(r.startswith("Weakest on aggregation: 50% (1/2)") for r in rec.reasons)
    assert [s.rank for s in rec.ranking][:2] == [1, 2]


def test_tie_on_accuracy_broken_by_recall_then_tokens():
    df = frame(method_rows("row_wise", {"Q1"}, recall=0.5), method_rows("fixed_size", {"Q1"}, recall=0.9))
    rec = recommend(df)
    assert rec.best == ["fixed_size"] and "gold-row recall 90% vs 50%" in rec.reasons[0]

    df = frame(method_rows("row_wise", {"Q1"}, tokens=900), method_rows("fixed_size", {"Q1"}, tokens=2000))
    rec = recommend(df)
    assert rec.best == ["row_wise"] and "fewer tokens" in rec.reasons[0]


def test_full_tie_names_joint_best():
    rec = recommend(frame(method_rows("row_wise", {"Q1"}), method_rows("fixed_size", {"Q1"})))
    assert rec.best == ["fixed_size", "row_wise"] and rec.reasons[0].startswith("Full tie")
    assert {s.rank for s in rec.ranking} == {1}


def test_baseline_is_compared_but_never_ranked():
    df = frame(method_rows("row_wise", {"Q1"}), method_rows("baseline", ALL))
    rec = recommend(df)
    assert rec.best == ["row_wise"] and "baseline" not in [s.method for s in rec.ranking]
    assert rec.baseline is not None and rec.baseline.correct == 5
    assert "compared, not ranked" in rec.baseline_note and "On aggregation: baseline 2/2, row_wise 0/2" in rec.baseline_note


def test_baseline_with_no_answers_says_so():
    df = frame(method_rows("row_wise", {"Q1"}), method_rows("baseline", set(), pending=1, status="rate_limited"))
    rec = recommend(df)
    assert rec.baseline is None and "has no answers yet: 5 of 5 rows are pending" in rec.baseline_note


def test_not_run_chunkers_make_the_verdict_provisional():
    rec = recommend(frame(method_rows("row_wise", ALL)))
    assert not rec.final and rec.not_run == [m for m in CHUNKERS if m != "row_wise"]
    assert rec.caveats[0].startswith("Not run, so not ranked: fixed_size")


def test_pending_question_is_left_out_for_every_chunker():
    rows = method_rows("row_wise", ALL)
    pend = method_rows("fixed_size", {"Q1", "Q2", "Q3", "Q4"})
    pend[4].update(pending=1, status="rate_limited", correct=0, failure="")
    df = pd.DataFrame(rows + pend)
    rec = recommend(df)
    assert rec.qids == ["Q1", "Q2", "Q3", "Q4"] and rec.left_out == {"Q5": ["fixed_size"]}
    assert not rec.final and any("left out (Q5)" in c and "fixed_size" in c for c in rec.caveats)
    # with Q5 left out, the two chunkers are level on correct answers and recall and tokens
    assert rec.best == ["fixed_size", "row_wise"]


def test_small_lead_is_called_out():
    rec = recommend(all_chunkers({"row_wise": {"Q1", "Q2"}, "fixed_size": {"Q1"}}))
    assert any("lead is small (1 correct answer(s) out of 5)" in c for c in rec.caveats)


def test_best_per_type_and_no_best_when_nobody_is_right():
    df = frame(method_rows("row_wise", {"Q1", "Q2"}), method_rows("fixed_size", {"Q3"}))
    by = {b.type: b for b in recommend(df).by_type}
    assert by["lookup"].best == ["row_wise"] and by["lookup"].decided_by == "accuracy"
    assert by["aggregation"].best == ["fixed_size"] and by["aggregation"].accuracy == 0.5
    assert by["unanswerable"].best == [] and by["unanswerable"].decided_by == "no chunker answered any correctly"


def test_nothing_to_rank_raises():
    with pytest.raises(ValueError):
        recommend(frame(method_rows("baseline", ALL)))


def test_excel_has_every_sheet_and_the_verdict(tmp_path):
    df = pd.concat([all_chunkers({"row_wise": ALL - {"Q3"}, "fixed_size": {"Q1"}}),
                    frame(method_rows("baseline", ALL))])
    rec = recommend(df)
    path = write_excel(df, {"llm": {"provider": "mock", "model": "m"}}, rec, tmp_path / "r.xlsx")
    wb = load_workbook(path)
    assert wb.sheetnames == ["Recommendation", "Ranking", "Accuracy by type", "Retrieval & cost", "Per question",
                             "Run info"]
    rec_ws = wb["Recommendation"]
    cells = {c.value for r in rec_ws.iter_rows() for c in r if c.value is not None}
    assert "row_wise" in cells and "Final for this run" in cells
    rank = wb["Ranking"]
    assert rank["B2"].value == "row_wise" and rank["E2"].value == pytest.approx(0.8) and rank["E2"].number_format == "0%"
    assert any(r[1].value == "baseline" and r[0].value == "not ranked" for r in rank.iter_rows(min_row=2))
    assert wb["Per question"].max_row == len(df) + 1
