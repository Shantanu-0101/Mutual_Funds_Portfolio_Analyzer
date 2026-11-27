"""Phase R5: the Stage B verdict rule (§6.5), summary.md and retrieval_report.xlsx.

Synthetic Stage B rows only: no LLM, no index, no Grok. The rule is what the spec fixed before the paid
run, so these tests check the tie-breaks in order, the per-type best, the bootstrap note (RD8) and the
provisional cases (pending rows, a shortlisted method with no rows).
"""

from __future__ import annotations

import json
import math

import pandas as pd
import pytest
from openpyxl import load_workbook

from src.retrieval.excel_report import write_excel
from src.retrieval.report import stage_b_summary_md
from src.retrieval.verdict import verdict, verdict_line

QS = [("Q1", "lookup", "number"), ("Q2", "lookup", "number"), ("Q3", "aggregation", "number"),
      ("Q4", "cross_scheme", "choice"), ("Q5", "unanswerable", "not_in_data")]
SETTINGS = {"dense": {}, "scheme_filter": {"fuzzy_threshold": 0.85}, "best_combo": {"ranker": "mmr"}}


def row(method, qid, qtype, kind, correct, *, recall=1.0, tokens=1000, ms=10, pending=0, status="ok",
        filter_miss=None):
    answerable = kind != "not_in_data"
    failure = "" if correct else ("retrieval miss" if answerable and recall < 1 else "generation error")
    has_filter = method != "dense"
    return {"method": method, "retrieval_method": method,
            "method_id": {"dense": "M1", "scheme_filter": "M6", "best_combo": "M8"}[method],
            "method_settings": json.dumps(SETTINGS[method]), "qid": qid, "type": qtype,
            "answer_kind": kind, "unit": "pct" if answerable else "", "question": f"question {qid}",
            "gold_value": "5.0" if answerable else "null", "status": status, "error": "",
            "pending": pending, "failure": "" if pending else failure, "correct": correct, "refused": 0,
            "false_refusal": 0 if answerable else math.nan,
            "unanswerable_correct": math.nan if answerable else correct,
            "retrieval_hit": (1 if recall > 0 else 0) if answerable else math.nan,
            "gold_row_recall": recall if answerable else math.nan, "value": "5.0", "answer_unit": "pct",
            "items": "[]", "answer": "5%", "prompt_tokens": tokens, "completion_tokens": 100,
            "n_chunks": 2, "n_context_rows": 40, "context_tokens": tokens - 300, "retrieval_ms": ms,
            "generation_ms": 900, "execution_ms": math.nan, "total_ms": 900 + ms, "model": "m",
            "cached": 0, "filter_match": "exact" if has_filter else "",
            "schemes_found": "ABC" if has_filter else "",
            "filter_miss": (filter_miss if filter_miss is not None else 0) if has_filter and answerable
            else math.nan,
            "filter_wrong": 0 if has_filter and answerable else math.nan,
            "padded": 0, "retrieval_debug": "{}"}


def method_rows(method, right: set[str], **kw):
    return [row(method, q, t, k, int(q in right), **kw) for q, t, k in QS]


def frame(*parts) -> pd.DataFrame:
    return pd.DataFrame([r for p in parts for r in p])


ALL = {q for q, _, _ in QS}
MANIFEST = {"llm": {"provider": "velona", "model": "x-ai/grok-4.20"},
            "embedding_model": "BAAI/bge-small-en-v1.5", "candidate_k": 20, "top_k": 5,
            "reranker": {"model": "BAAI/bge-reranker-base", "revision": "abc123"},
            "question_set": "test", "setup": {"questions_sha256": "f" * 64}, "stage": "B",
            "phase": "full", "retrieval_methods": ["best_combo", "scheme_filter", "dense"],
            "method_settings": SETTINGS, "rows": 15, "expected_rows": 15, "complete": True,
            "config": {"llm": {"temperature": 0}, "data": {"eval_months": ["2026-09-30"]}}}


def test_most_correct_wins_and_the_reasons_use_the_numbers():
    df = frame(method_rows("best_combo", ALL - {"Q3"}), method_rows("scheme_filter", {"Q1", "Q5"}),
               method_rows("dense", {"Q1"}))
    v = verdict(df)
    assert v.best == ["best_combo"] and v.final and v.ranking[0].rank == 1
    assert verdict_line(v) == "Best retrieval method for this data: M8 best_combo (final for this run)."
    assert v.reasons[0].startswith("Most correct answers: 80% (4/5), 2 more than the runner-up "
                                   "M6 scheme_filter")
    assert any("Against the reference M1 dense" in r for r in v.reasons)
    assert [s.method for s in v.ranking] == ["best_combo", "scheme_filter", "dense"]


def test_tie_breaks_in_spec_order():
    """Accuracy → context gold-row recall → prompt tokens → retrieval latency (§6.5)."""
    df = frame(method_rows("best_combo", {"Q1"}, recall=0.5), method_rows("dense", {"Q1"}, recall=0.9))
    v = verdict(df)
    assert v.best == ["dense"] and "context gold-row recall 90% vs 50%" in v.reasons[0]

    df = frame(method_rows("best_combo", {"Q1"}, tokens=2000), method_rows("dense", {"Q1"}, tokens=900))
    v = verdict(df)
    assert v.best == ["dense"] and "prompt tokens per question (900 vs 2,000)" in v.reasons[0]

    df = frame(method_rows("best_combo", {"Q1"}, ms=50), method_rows("dense", {"Q1"}, ms=5))
    v = verdict(df)
    assert v.best == ["dense"] and "retrieval latency (5 ms vs 50 ms median)" in v.reasons[0]

    df = frame(method_rows("best_combo", {"Q1"}), method_rows("dense", {"Q1"}))
    v = verdict(df)
    assert sorted(v.best) == ["best_combo", "dense"] and v.reasons[0].startswith("Full tie")
    assert all(s.note == "joint best" for s in v.ranking)


def test_best_method_per_question_type():
    df = frame(method_rows("best_combo", {"Q1", "Q2"}), method_rows("dense", {"Q3", "Q4", "Q5"}))
    v = verdict(df)
    by_type = {b.type: b for b in v.by_type}
    assert by_type["lookup"].best == ["M8 best_combo"] and by_type["lookup"].accuracy == 1.0
    assert by_type["aggregation"].best == ["M1 dense"]
    assert by_type["cross_scheme"].decided_by == "accuracy"


def test_a_type_nobody_answers_names_no_best():
    df = frame(method_rows("best_combo", {"Q1"}), method_rows("dense", {"Q1"}))
    v = verdict(df)
    agg = next(b for b in v.by_type if b.type == "aggregation")
    assert agg.best == [] and agg.decided_by == "no method answered any correctly"


def test_pending_rows_are_left_out_for_every_method_and_make_it_provisional():
    good = method_rows("best_combo", ALL)
    half = method_rows("dense", {"Q1", "Q2", "Q3", "Q4"})
    half[4] = row("dense", "Q5", "unanswerable", "not_in_data", 0, pending=1, status="not_asked")
    v = verdict(frame(good, half))
    assert v.qids == ["Q1", "Q2", "Q3", "Q4"] and not v.final
    assert list(v.left_out) == ["Q5"] and all(s.n == 4 for s in v.ranking)
    assert any("1 question(s) left out" in c for c in v.caveats)


def test_a_shortlisted_method_with_no_rows_is_not_run_not_ranked():
    df = frame(method_rows("best_combo", ALL), method_rows("dense", {"Q1"}))
    v = verdict(df, methods=["best_combo", "dense", "scheme_filter"])
    assert v.not_run == ["scheme_filter"] and not v.final
    assert [s.method for s in v.ranking] == ["dense", "best_combo"][::-1]
    assert any("scheme_filter" in c for c in v.caveats)


def test_small_lead_is_called_out():
    df = frame(method_rows("best_combo", {"Q1", "Q2", "Q3"}), method_rows("dense", {"Q1", "Q2"}))
    v = verdict(df)
    assert any("lead over M1 dense is small (1 correct answer(s) out of 5)" in c for c in v.caveats)


def _offline(section_recall: dict[str, float]) -> pd.DataFrame:
    """A minimal Stage A frame: one answerable row per (method, question)."""
    rows = []
    for method, value in section_recall.items():
        for qid, qtype, kind in QS:
            if kind == "not_in_data":
                continue
            rows.append({"set": "test", "method": method, "variant": method, "qid": qid, "type": qtype,
                         "answerable": 1, "section_recall@5": value, "hit@5": 1.0, "mrr@10": 1.0,
                         "retrieval_ms": 10.0})
    return pd.DataFrame(rows)


def test_bootstrap_covers_correct_and_section_recall_and_flags_a_tie():
    """RD8: the interval is reported for both metrics; one including 0 becomes a caveat."""
    df = frame(method_rows("best_combo", ALL), method_rows("dense", {"Q1"}))
    v = verdict(df, _offline({"best_combo": 0.9, "dense": 0.4}))
    assert [n.metric for n in v.noise] == ["correct", "section_recall@5"]
    assert all(n.distinguishable for n in v.noise)
    assert all("not distinguishable" not in c for c in v.caveats)

    # Same section_recall@5 on every question: a zero difference, so the interval includes 0.
    v = verdict(df, _offline({"best_combo": 0.7, "dense": 0.7}))
    recall_note = next(n for n in v.noise if n.metric == "section_recall@5")
    assert not recall_note.distinguishable
    assert any("not distinguishable from M1 dense on this question set" in c for c in v.caveats)


def test_no_bootstrap_when_dense_itself_wins():
    df = frame(method_rows("dense", ALL), method_rows("best_combo", {"Q1"}))
    v = verdict(df, _offline({"best_combo": 0.4, "dense": 0.9}))
    assert v.best == ["dense"] and v.noise == []


def test_verdict_needs_rows():
    with pytest.raises(ValueError):
        verdict(pd.DataFrame({"retrieval_method": [], "qid": [], "pending": []}))
    only_pending = method_rows("dense", set(), pending=1)
    with pytest.raises(ValueError):
        verdict(frame(only_pending))


def test_summary_md_has_every_section_and_the_verdict():
    df = frame(method_rows("best_combo", ALL - {"Q3"}), method_rows("scheme_filter", {"Q1", "Q5"}),
               method_rows("dense", {"Q1"}))
    v = verdict(df, _offline({"best_combo": 0.9, "scheme_filter": 0.8, "dense": 0.4}))
    spend = [{"at_ist": "2026-11-24T10:25:50+05:30", "phase": "full", "questions": "5", "calls": "15",
              "cached": "2", "paid_calls": "13", "prompt_tokens": "1000", "completion_tokens": "100",
              "total_tokens": "1100", "est_total_tokens": "2000", "max_tokens": "5000", "stopped": ""}]
    md = stage_b_summary_md(df, MANIFEST, v, None, spend)
    for head in ("## 1. Verdict", "## 2. Accuracy", "## 3. Retrieval", "## 4. Tokens and latency",
                 "## 5. Refusals", "## 6. Failure examples", "## 7. What the run cost"):
        assert head in md
    assert "M8 best_combo (final for this run)" in md
    assert "Paired bootstrap, 10,000 resamples, seed 42" in md
    assert "### M1 dense" in md and "### M8 best_combo" in md
    assert "filter_miss" in md                       # R4.4 labels are explained
    assert "1,100" in md and "2,000" in md           # spend row, tokens only (RD11)
    assert "$" not in md                             # no prices in the repo (RD11)


def test_summary_md_warns_when_the_run_is_not_complete():
    half = method_rows("dense", {"Q1"})
    half[4] = row("dense", "Q5", "unanswerable", "not_in_data", 0, pending=1, status="not_asked")
    df = frame(method_rows("best_combo", ALL), half)
    md = stage_b_summary_md(df, {**MANIFEST, "complete": False}, verdict(df))
    assert "Not a complete run" in md


def test_excel_has_the_sheets_and_no_bootstrap_note(tmp_path):
    """RD8: the 'not distinguishable' sentence stays out of the Excel."""
    df = frame(method_rows("best_combo", ALL), method_rows("dense", {"Q1"}))
    v = verdict(df, _offline({"best_combo": 0.7, "dense": 0.7}))
    assert any("not distinguishable" in c for c in v.caveats)       # it is in summary.md
    path = write_excel(df, MANIFEST, v, None, tmp_path / "retrieval_report.xlsx")
    wb = load_workbook(path)
    assert wb.sheetnames == ["Verdict", "Ranking", "Accuracy by type", "Retrieval & cost",
                             "Offline (Stage A)", "Per question", "Run info"]
    text = " ".join(str(c.value) for ws in wb for r in ws.iter_rows() for c in r if c.value is not None)
    assert "not distinguishable" not in text
    assert "M8 best_combo" in text and "Best retrieval method for this data" in text
    assert wb["Per question"].max_row == len(df) + 1
    assert wb["Ranking"].cell(row=2, column=1).value == 1


def test_excel_carries_no_run_level_call_or_token_totals(tmp_path, monkeypatch):
    """27 Nov 2026: the workbook must not hold a whole run's calls or tokens (the spend table).

    Per-question token means stay (the verdict's third tie-break); what goes is anything a reader could
    multiply by a provider's rate to price the run. The spend log itself stays in summary.md and
    spend_log.csv.
    """
    import csv

    df = frame(method_rows("best_combo", ALL, tokens=1000), method_rows("dense", {"Q1"}, tokens=4000))
    spend = {"at_ist": "2026-11-24T10:25:50+05:30", "phase": "full", "set": "test", "questions": "5",
             "calls": "15", "cached": "2", "paid_calls": "13", "prompt_tokens": "123456",
             "completion_tokens": "7890", "total_tokens": "131346", "est_total_tokens": "200000",
             "max_tokens": "900000", "stopped": ""}
    with (tmp_path / "spend_log.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(spend))
        w.writeheader()
        w.writerow(spend)

    manifest = {**MANIFEST, "max_tokens": 900000}
    path = write_excel(df, manifest, verdict(df), None, tmp_path / "retrieval_report.xlsx")
    wb = load_workbook(path)
    cells = [str(c.value) for ws in wb for r in ws.iter_rows() for c in r if c.value is not None]
    text = " ".join(cells)
    for forbidden in ("123456", "7890", "131346", "200000", "900000", "Paid calls", "Total tokens",
                      "Estimated total", "Token cap"):
        assert forbidden not in text, f"{forbidden!r} is back in the Excel"
    run = wb["Run info"]
    assert "not in this workbook" in " ".join(str(c.value) for r in run.iter_rows() for c in r
                                              if c.value is not None)
    # The per-question means are still there, on the sheets that rank the methods.
    assert any(c.value == "Prompt tokens / question" for r in wb["Ranking"].iter_rows() for c in r)
    assert 1000 in [c.value for r in wb["Ranking"].iter_rows() for c in r]


def test_excel_offline_sheet_says_so_when_stage_a_is_missing(tmp_path):
    df = frame(method_rows("best_combo", ALL), method_rows("dense", {"Q1"}))
    wb = load_workbook(write_excel(df, MANIFEST, verdict(df), pd.DataFrame(), tmp_path / "r.xlsx"))
    assert "No Stage A rows" in str(wb["Offline (Stage A)"].cell(row=1, column=1).value)
