"""Runner and report (tasks 5.5, 5.6): scoring rows, resume rules, manifest, summary. No network, no index."""

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from src.baseline.pipeline import BaselineResult
from src.chunking.base import Chunk
from src.config import load_settings
from src.eval import report, runner
from src.eval.gold import GoldAnswer
from src.eval.questions import Question
from src.rag.pipeline import RagResult
from src.rag.retrieve import Retrieval, Retrieved

NO_ENV = Path("does-not-exist.env")
F = "30092026_TEST.xls"
EQ = "Equity & Equity Related"


def hrow(code, n, inst, isin, pct):
    return dict(scheme_code=code, as_of_date="2026-09-30", section=EQ, subsection="a) Listed", instrument=inst,
                isin=isin, industry_or_rating="Banks", market_value_lakhs=pct * 100, pct_nav=pct, pct_nav_flag=None,
                source_file=F, source_sheet=code, source_row=n)


HOLDINGS = pd.DataFrame([hrow("A", 8, "ICICI Bank Ltd.", "INE090A01021", 5.0),
                         hrow("A", 9, "HDFC Bank Ltd.", "INE040A01034", 4.0),
                         hrow("B", 8, "ICICI Bank Ltd.", "INE090A01021", 3.0)])

QUESTIONS = [
    Question("Q01", "lookup", "What % does A hold in ICICI Bank?", "number", "holding_pct",
             {"scheme_code": "A", "as_of_date": "2026-09-30", "instrument": "ICICI Bank Ltd."}, unit="pct"),
    Question("Q02", "cross_scheme", "Which holds more ICICI Bank: A or B?", "choice", "which_holds_more",
             {"schemes": ["A", "B"], "as_of_date": "2026-09-30", "instrument": "ICICI Bank Ltd."},
             options={"A": ["Fund A"], "B": ["Fund B"]}),
    Question("Q03", "unanswerable", "What is the expense ratio of A?", "not_in_data", "not_in_data"),
]


def ans(text="", value=None, items=(), insufficient=False):
    return {"answer": text, "value": value, "unit": None, "items": list(items), "sources": [],
            "insufficient_context": insufficient}


def chunk(code, *rows):
    return Chunk(id=f"row_wise:{code}:{rows[0]}", text="t", chunker="row_wise", amc="ABSL", scheme_code=code,
                 scheme=code, as_of_date="2026-09-30", section=EQ, source_rows=tuple((F, code, r) for r in rows),
                 n_tokens=100, truncated=False)


def rag(status="ok", answer=None, rows=(("A", 8),), fallback=None, chunker="row_wise"):
    chunks = [Retrieved(chunk(c, r), 0.9, i + 1) for i, (c, r) in enumerate(rows)]
    return RagResult(question="q", chunker=chunker, status=status, answer=answer, error=None if status == "ok"
                     else "boom", raw_text="{}", retrieval=Retrieval(chunker, chunks, 12.0), prompt_tokens=500,
                     completion_tokens=20, generation_ms=800.0, model="mock", provider="mock",
                     fallback_reason=fallback)


def base(status="ok", answer=None):
    return BaselineResult(question="q", status=status, answer=answer, error=None, code="result = 1",
                          prompt_tokens=300, completion_tokens=30, generation_ms=600.0, execution_ms=200.0,
                          model="mock", provider="mock")


@pytest.fixture
def settings(tmp_path):
    s = load_settings(env_file=NO_ENV, environ={"LLM_PROVIDER": "mock", "LLM_FALLBACK": "none"})
    (tmp_path / "raw").mkdir()
    return replace(s, paths=replace(s.paths, raw=tmp_path / "raw", processed=tmp_path / "processed",
                                    results=tmp_path / "results"))


@pytest.fixture
def qfile(tmp_path):
    p = tmp_path / "questions.yaml"
    p.write_text("- placeholder\n", encoding="utf-8")
    return p


def run(settings, qfile, answerers, **kw):
    return runner.run_eval(settings, QUESTIONS, HOLDINGS, answerers, out_dir=settings.paths.results,
                           questions_file=qfile, progress=lambda _: None, **kw)


# --------------------------------------------------------------------------- one row

def test_make_row_correct_number_and_retrieval():
    gold = GoldAnswer(5.0, [(F, "A", 8)])
    row = runner.make_row("row_wise", QUESTIONS[0], gold, rag(answer=ans("5.0%", 5.0), rows=[("A", 8), ("B", 8)]),
                          0.01, 0.01)
    assert row["correct"] == 1 and row["failure"] == "" and row["pending"] == 0
    assert row["retrieval_hit"] == 1 and row["gold_row_recall"] == 1.0
    assert row["n_chunks"] == 2 and row["context_tokens"] == 200 and row["n_context_rows"] == 2
    assert row["total_ms"] == 812.0 and json.loads(row["gold_value"]) == 5.0


def test_failure_labels():
    gold = GoldAnswer(5.0, [(F, "A", 8)])
    q = QUESTIONS[0]
    miss = runner.make_row("row_wise", q, gold, rag(answer=ans("3%", 3.0), rows=[("B", 8)]), 0.01, 0.01)
    assert (miss["correct"], miss["retrieval_hit"], miss["failure"]) == (0, 0, "retrieval miss")
    gen = runner.make_row("row_wise", q, gold, rag(answer=ans("3%", 3.0)), 0.01, 0.01)
    assert gen["failure"] == "generation error"
    fmt = runner.make_row("row_wise", q, gold, rag(status="format_error"), 0.01, 0.01)
    assert (fmt["failure"], fmt["answer"]) == ("format error", None)
    over = runner.make_row("scheme_level", q, gold, rag(status="context_overflow"), 0.01, 0.01)
    assert over["failure"] == "context overflow" and over["pending"] == 0
    b = runner.make_row("baseline", q, gold, base(status="runtime_error"), 0.01, 0.01)
    assert b["failure"] == "generation error" and b["retrieval_hit"] is None and b["execution_ms"] == 200.0


def test_pending_rows():
    gold = GoldAnswer(5.0, [(F, "A", 8)])
    q = QUESTIONS[0]
    assert runner.make_row("row_wise", q, gold, rag(status="rate_limited"), 0.01, 0.01)["pending"] == 1
    fb = runner.make_row("row_wise", q, gold, rag(answer=ans("5%", 5.0), fallback="xai: rate_limited"), 0.01, 0.01)
    assert fb["pending"] == 1 and fb["correct"] == 1


# --------------------------------------------------------------------------- the run

class Counting:
    def __init__(self, fn):
        self.fn, self.calls = fn, []

    def __call__(self, text):
        self.calls.append(text)
        return self.fn(text)


def answer_for(text):
    if "expense" in text:
        return ans("The data does not contain this.", insufficient=True)
    if "Which" in text:
        return ans("Fund A holds more than Fund B.")
    return ans("5%", 5.0)


def test_run_scores_resumes_and_writes_manifest(settings, qfile):
    rw = Counting(lambda t: rag(answer=answer_for(t)))
    bl = Counting(lambda t: base(answer=answer_for(t)))
    s = run(settings, qfile, {"row_wise": rw, "baseline": bl})
    assert (s.asked, s.skipped, s.complete) == (6, 0, True)
    rows = runner.read_results(settings.paths.results / runner.RESULTS_FILE)
    assert [(r["method"], r["qid"], r["correct"]) for r in rows] == [
        ("row_wise", "Q01", "1"), ("row_wise", "Q02", "1"), ("row_wise", "Q03", "1"),
        ("baseline", "Q01", "1"), ("baseline", "Q02", "1"), ("baseline", "Q03", "1")]
    m = json.loads((settings.paths.results / runner.MANIFEST_FILE).read_text(encoding="utf-8"))
    assert m["complete"] and m["llm"]["provider"] == "mock" and m["embedding_model"] == settings.embedding.model
    assert m["setup"]["questions_sha256"] == runner.sha256_file(qfile) and len(m["sessions"]) == 1
    assert "api_key" not in json.dumps(m).lower()

    s2 = run(settings, qfile, {"row_wise": rw, "baseline": bl})        # resume: nothing left to ask
    assert (s2.asked, s2.skipped) == (0, 6) and len(rw.calls) == 3
    m = json.loads((settings.paths.results / runner.MANIFEST_FILE).read_text(encoding="utf-8"))
    assert len(m["sessions"]) == 2


def test_pending_rows_are_retried(settings, qfile):
    first = {"n": 0}

    def flaky(text):
        first["n"] += 1
        return rag(status="rate_limited") if first["n"] == 2 else rag(answer=answer_for(text))

    s = run(settings, qfile, {"row_wise": flaky})
    assert s.pending == [("row_wise", "Q02")] and not s.complete
    s2 = run(settings, qfile, {"row_wise": lambda t: rag(answer=answer_for(t))})
    assert s2.asked == 1 and s2.complete
    rows = runner.read_results(settings.paths.results / runner.RESULTS_FILE)
    assert len(rows) == 3 and all(r["status"] == "ok" and r["pending"] == "0" for r in rows)


def test_resume_refuses_other_setup_and_fresh_starts_over(settings, qfile):
    run(settings, qfile, {"row_wise": lambda t: rag(answer=answer_for(t))})
    other = replace(settings, retrieval=replace(settings.retrieval, top_k=9))
    with pytest.raises(runner.ResumeMismatch):
        run(other, qfile, {"row_wise": lambda t: rag(answer=answer_for(t))})
    calls = Counting(lambda t: rag(answer=answer_for(t)))
    s = run(other, qfile, {"row_wise": calls}, fresh=True)
    assert s.asked == 3 and len(calls.calls) == 3


# --------------------------------------------------------------------------- report

def test_report(settings, qfile):
    def wrong_lookup(t):
        return ans("3%", 3.0) if "What %" in t else answer_for(t)

    run(settings, qfile, {"row_wise": lambda t: rag(answer=wrong_lookup(t), rows=[("B", 8)]),
                          "baseline": lambda t: base(answer=answer_for(t))})
    path = report.write_report(settings.paths.results)
    text = path.read_text(encoding="utf-8")
    df, _ = report.load(settings.paths.results)
    acc = report.accuracy_table(df)
    assert acc.loc["row_wise", "overall"] == pytest.approx(2 / 3) and acc.loc["baseline", "overall"] == 1.0
    assert "| **row_wise** | 0% (0/1) | 100% (1/1) | 100% (1/1) | **67% (2/3)** |" in text
    assert "*retrieval miss*" in text and "Not a complete run" not in text
    assert (settings.paths.results / report.CHART_FILE).stat().st_size > 1000


def test_rescore_matches_live_scores_and_records_reason(settings, qfile):
    run(settings, qfile, {"row_wise": lambda t: rag(answer=answer_for(t)),
                          "baseline": lambda t: base(answer=ans("Result: A", items=["A"]) if "Which" in t
                                                     else answer_for(t))})
    path = settings.paths.results / runner.RESULTS_FILE
    before = runner.read_results(path)
    assert runner.rescore(settings, QUESTIONS, HOLDINGS, settings.paths.results, "test") == 0
    after = runner.read_results(path)
    assert [(r["correct"], r["failure"], r["retrieval_hit"]) for r in after] == \
           [(r["correct"], r["failure"], r["retrieval_hit"]) for r in before]
    assert next(r for r in after if r["method"] == "baseline" and r["qid"] == "Q02")["correct"] == "1"
    m = json.loads((settings.paths.results / runner.MANIFEST_FILE).read_text(encoding="utf-8"))
    assert m["rescored"][0]["reason"] == "test" and m["rescored"][0]["changed"] == []


def test_report_names_methods_not_run(settings, qfile):
    run(settings, qfile, {"row_wise": lambda t: rag(answer=answer_for(t))})
    text = report.write_report(settings.paths.results).read_text(encoding="utf-8")
    assert "**Not run in this run:**" in text and "`scheme_level`" in text and "`row_wise`," not in text
