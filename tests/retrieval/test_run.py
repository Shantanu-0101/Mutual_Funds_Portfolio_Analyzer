"""Phase R4, Stage B: the token cap, the fingerprint, the failure labels, the spend log, the model check.

No network, no model, no index, no LLM: the pipeline, the method and the cache are hand-made stubs, so
every test here asserts what the runner does with them. The three paid steps (smoke, full) are not
tested here by design — they need Grok and the user's yes (§9.2).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from src.chunking.base import Chunk
from src.config import load_settings
from src.eval import runner
from src.eval.questions import Question
from src.llm import LLMResult, RateLimited
from src.rag.pipeline import RagResult
from src.rag.retrieve import Retrieval, Retrieved
from src.retrieval import run as r4
from src.retrieval.estimate import COMPLETION_TOKENS, PROMPT_OVERHEAD, CacheProbe, Estimate, MethodEstimate
from src.retrieval.offline import Target
from src.retrieval.settings import BenchmarkSettings

NO_ENV = Path("does-not-exist.env")
DATE = "2026-09-30"
FILE = "synthetic_r4.xls"
EQ = "Equity & Equity Related"
CONTEXT_TOKENS = 1_000


# --------------------------------------------------------------------------- hand-made world

def hrow(code, n, inst, pct):
    return dict(scheme_code=code, as_of_date=DATE, section=EQ, subsection="a) Listed", instrument=inst,
                isin=f"INE{n:09d}", industry_or_rating="Banks", market_value_lakhs=pct * 100, pct_nav=pct,
                pct_nav_flag=None, source_file=FILE, source_sheet=code, source_row=n)


HOLDINGS = pd.DataFrame([hrow("A", 8, "ICICI Bank Ltd.", 5.0), hrow("A", 9, "HDFC Bank Ltd.", 4.0),
                         hrow("B", 8, "ICICI Bank Ltd.", 3.0)])

QUESTIONS = [
    Question("T01", "lookup", "What % does A hold in ICICI Bank?", "number", "holding_pct",
             {"scheme_code": "A", "as_of_date": DATE, "instrument": "ICICI Bank Ltd."}, unit="pct"),
    Question("T02", "lookup", "What % does A hold in HDFC Bank?", "number", "holding_pct",
             {"scheme_code": "A", "as_of_date": DATE, "instrument": "HDFC Bank Ltd."}, unit="pct"),
    Question("T03", "lookup", "What % does B hold in ICICI Bank?", "number", "holding_pct",
             {"scheme_code": "B", "as_of_date": DATE, "instrument": "ICICI Bank Ltd."}, unit="pct"),
]


def child(scheme: str, n: int) -> Chunk:
    pid = f"hierarchical:{DATE}:{scheme}:p0"
    return Chunk(f"hierarchical:{DATE}:{scheme}:{n}", f"row {n} of {scheme}", "hierarchical", "Synthetic AMC",
                 scheme, f"SYNTHETIC {scheme}", DATE, EQ, ((FILE, scheme, n),), 40, False, pid)


def parent(scheme: str) -> Chunk:
    rows = tuple((FILE, scheme, n) for n in (8, 9))
    return Chunk(f"hierarchical:{DATE}:{scheme}:p0", f"section of {scheme}", "hierarchical", "Synthetic AMC",
                 scheme, f"SYNTHETIC {scheme}", DATE, EQ, rows, CONTEXT_TOKENS, False, None)


PARENTS = {parent(s).id: parent(s) for s in ("A", "B")}


def ans(value=5.0, text="5%"):
    return {"answer": text, "value": value, "unit": "pct", "items": [], "sources": [],
            "insufficient_context": False}


# --------------------------------------------------------------------------- stubs

class FakeMethod:
    """Returns one child of each scheme the question names, and the filter debug of a filtered method."""

    def __init__(self, name="dense", options=None, schemes_found=None):
        self.name, self.options, self.schemes_found = name, options or {}, schemes_found

    def retrieve(self, text, k=None):
        scheme = "A" if " A " in f" {text} " else "B"
        debug = {} if self.schemes_found is None else {"schemes_found": list(self.schemes_found),
                                                       "match": "exact", "padded": 0}
        kids = [Retrieved(child(scheme, 8), 0.9, 1)]
        return type("MR", (), {"method": self.name, "children": kids, "latency_ms": 7.0, "debug": debug})()


class FakeRetriever:
    parents = PARENTS


class FakeRag:
    """``answer`` records what it was asked and returns a prepared result (never a real call)."""

    def __init__(self, result_for=None):
        self.retriever = FakeRetriever()
        self.asked: list[tuple[str, str]] = []
        self.result_for = result_for or (lambda text, method: rag_result())

    def answer(self, text, chunker, method=None):
        self.asked.append((method.name, text))
        return self.result_for(text, method)


def rag_result(status="ok", answer=None, rows=(("A", 8),), cached=False, fallback=None, debug=None,
               prompt=2_000, completion=400):
    kids = [Retrieved(child(s, n), 0.9, i + 1) for i, (s, n) in enumerate(rows)]
    sections = [Retrieved(PARENTS[k.chunk.parent_id], 0.9, i + 1) for i, k in enumerate(kids)]
    retrieval = Retrieval("hierarchical", sections, 7.0, children=kids, method="dense", debug=debug or {})
    return RagResult(question="q", chunker="hierarchical", status=status,
                     answer=answer if answer is not None else (ans() if status == "ok" else None),
                     error=None if status == "ok" else "boom", raw_text="{}", retrieval=retrieval,
                     prompt_tokens=prompt, completion_tokens=completion, reasoning_tokens=0,
                     generation_ms=900.0, cached=cached, model="grok-test", provider="velona",
                     fallback_reason=fallback)


class FakeProbe:
    """A ``CacheProbe`` over a directory of files, with the real layout (key[:2]/key.json)."""

    def __init__(self, tmp_path: Path):
        self.dir = tmp_path
        self.dir.mkdir(parents=True, exist_ok=True)

    def cache_key(self, messages, json_mode):
        return "k" + str(abs(hash(json.dumps(messages, sort_keys=True))) % 10**8)

    def _cache_path(self, key):
        return self.dir / key[:2] / f"{key}.json"

    def store(self, messages, result: dict) -> Path:
        path = self._cache_path(self.cache_key(messages, True))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"result": result}), encoding="utf-8")
        return path


def answerer(tmp_path, ledger, name="dense", rag=None, schemes_found=None, options=None):
    probe = CacheProbe(FakeProbe(tmp_path / "llmcache"))
    return r4.MethodAnswerer(name, FakeMethod(name, options, schemes_found), rag or FakeRag(), probe,
                             ledger, top_k=5)


@pytest.fixture
def settings(tmp_path):
    s = load_settings(env_file=NO_ENV, environ={"LLM_PROVIDER": "mock", "LLM_FALLBACK": "none"})
    (tmp_path / "raw").mkdir()
    return replace(s, paths=replace(s.paths, raw=tmp_path / "raw", processed=tmp_path / "processed",
                                    results=tmp_path / "results"))


# --------------------------------------------------------------------------- the ledger and the cap (R4.3)

def test_ledger_counts_paid_tokens_and_cached_calls_cost_nothing():
    led = r4.Ledger(max_tokens=10_000)
    led.record(rag_result(prompt=2_000, completion=400))
    led.record(rag_result(prompt=2_000, completion=400, cached=True))
    assert (led.calls, led.cached, led.paid_calls) == (2, 1, 1)
    assert led.total_tokens == 2_400 and led.as_dict()["max_tokens"] == 10_000


def test_the_cap_allows_a_call_that_fits_exactly_and_refuses_the_next_one():
    led = r4.Ledger(max_tokens=2_400)
    assert led.allows(2_400) and not led.allows(2_401)
    led.record(rag_result(prompt=2_000, completion=400))
    assert not led.allows(1)
    assert r4.Ledger().allows(10**9)                      # no cap: nothing is refused


def test_predicted_tokens_are_the_estimator_formula_and_a_cache_hit_is_free(tmp_path):
    a = answerer(tmp_path, r4.Ledger())
    assert a.predict(QUESTIONS[0].text) == (CONTEXT_TOKENS + PROMPT_OVERHEAD + COMPLETION_TOKENS, False)
    messages, context = a.messages(QUESTIONS[0].text)
    assert context == CONTEXT_TOKENS
    a.probe.llm.store(messages, {"text": "{}"})
    assert a.predict(QUESTIONS[0].text) == (0, True)
    assert a.stop_reason(QUESTIONS[0].text) is None       # cached: free, so never stopped


def test_stop_reason_names_the_cap_and_what_the_next_call_needs(tmp_path):
    a = answerer(tmp_path, r4.Ledger(max_tokens=100))
    reason = a.stop_reason(QUESTIONS[0].text)
    assert reason and "--max-tokens 100" in reason and f"{CONTEXT_TOKENS + 1140:,}" in reason


def run_eval(settings, questions, answerers, **kw):
    return runner.run_eval(settings, questions, HOLDINGS, answerers, out_dir=settings.paths.results,
                           progress=lambda _: None, columns=r4.COLUMNS, method_order=list(answerers),
                           fingerprint={"test": 1}, **kw)


def test_the_cap_stops_the_run_and_leaves_the_rows_it_did_not_ask_pending(settings, tmp_path):
    """Two calls fit under the cap; the third is refused, so its row and every later row stay pending."""
    led = r4.Ledger(max_tokens=2 * (2_000 + 400))
    rag = FakeRag()
    a = answerer(tmp_path, led, rag=rag)
    summary = run_eval(settings, QUESTIONS, {"dense": a},
                       before_call=lambda m, q: a.stop_reason(q.text))
    assert summary.asked == 2 and summary.stopped and "--max-tokens" in summary.stopped
    assert not summary.complete and len(rag.asked) == 2
    rows = {r["qid"]: r for r in runner.read_results(settings.paths.results / runner.RESULTS_FILE)}
    assert len(rows) == 3 and rows["T03"]["status"] == "not_asked" and rows["T03"]["pending"] == "1"
    assert "--max-tokens" in rows["T03"]["error"] and rows["T03"]["question"] == QUESTIONS[2].text
    assert [q for _, q in summary.pending] == ["T03"]

    # Resumed with room: the pending row is asked, nothing else is asked again.
    rag2 = FakeRag()
    a2 = answerer(tmp_path, r4.Ledger(max_tokens=10_000), rag=rag2)
    second = run_eval(settings, QUESTIONS, {"dense": a2},
                      before_call=lambda m, q: a2.stop_reason(q.text))
    assert second.asked == 1 and second.skipped == 2 and second.complete
    assert [t for _, t in rag2.asked] == [QUESTIONS[2].text]


def test_a_run_without_a_cap_asks_everything(settings, tmp_path):
    a = answerer(tmp_path, r4.Ledger())
    summary = run_eval(settings, QUESTIONS, {"dense": a}, before_call=lambda m, q: a.stop_reason(q.text))
    assert summary.asked == 3 and summary.stopped is None and summary.complete


def test_fallback_rows_stay_pending_and_cached_rows_are_flagged(settings, tmp_path):
    """RD7 / FR-R3.4: a Groq answer is not recorded as Grok's, a cache hit is marked and costs nothing."""
    def result_for(text, method):
        if text == QUESTIONS[0].text:
            return rag_result(fallback="velona: rate_limited")
        return rag_result(cached=True)

    led = r4.Ledger()
    a = answerer(tmp_path, led, rag=FakeRag(result_for))
    summary = run_eval(settings, QUESTIONS, {"dense": a}, before_call=lambda m, q: a.stop_reason(q.text))
    rows = {r["qid"]: r for r in runner.read_results(settings.paths.results / runner.RESULTS_FILE)}
    assert rows["T01"]["pending"] == "1" and rows["T01"]["fallback_reason"].startswith("velona")
    assert rows["T02"]["cached"] == "1" and rows["T02"]["pending"] == "0"
    assert [q for _, q in summary.pending] == ["T01"] and led.cached == 2 and led.total_tokens == 2_400


# --------------------------------------------------------------------------- the extra columns (R4.1, R4.4)

def test_stage_b_columns_say_which_method_answered_and_what_its_filter_did(settings, tmp_path):
    debug = {"schemes_found": ["A"], "match": "exact", "padded": 0}
    a = answerer(tmp_path, r4.Ledger(), name="best_combo", schemes_found=["A"],
                 rag=FakeRag(lambda text, method: rag_result(debug=debug)))
    target = Target(frozenset([(FILE, "A", 8)]), frozenset([f"hierarchical:{DATE}:A:p0"]))
    summary = run_eval(settings, QUESTIONS[:1], {"best_combo": a},
                       row_hook=lambda row, m, q, res: r4.row_extras(row, m, res, {"filter": True}, target))
    assert summary.asked == 1
    row = runner.read_results(settings.paths.results / runner.RESULTS_FILE)[0]
    assert row["retrieval_method"] == "best_combo" and row["method_id"] == "M8"
    assert json.loads(row["method_settings"]) == {"filter": True}
    assert row["filter_match"] == "exact" and json.loads(row["schemes_found"]) == ["A"]
    assert (row["filter_miss"], row["filter_wrong"]) == ("0", "0")
    assert json.loads(row["retrieval_debug"])["match"] == "exact"


def test_filter_labels_refine_a_retrieval_miss_only_for_a_method_with_a_filter():
    miss = {"correct": 0, "failure": "retrieval miss"}
    assert r4.failure_label(miss, {"filter_miss": 1, "filter_wrong": 0}) == "filter_miss"
    assert r4.failure_label(miss, {"filter_miss": 0, "filter_wrong": 1}) == "filter_wrong"
    assert r4.failure_label(miss, {"filter_miss": 1, "filter_wrong": 1}) == "filter_miss"
    assert r4.failure_label(miss, {"filter_miss": 0, "filter_wrong": 0}) == "retrieval miss"
    assert r4.failure_label(miss, {"filter_miss": None, "filter_wrong": None}) == "retrieval miss"
    # Old labels are unchanged, whatever the filter did (§6.4).
    for label in ("", "generation error", "format error", "context overflow"):
        assert r4.failure_label({"correct": 0, "failure": label}, {"filter_miss": 1}) == label


def test_a_method_without_a_filter_gets_no_filter_columns():
    row = {"correct": 0, "failure": "retrieval miss"}
    out = r4.row_extras(row, "dense", rag_result(), {}, Target(frozenset([(FILE, "A", 8)]),
                                                               frozenset([f"hierarchical:{DATE}:A:p0"])))
    assert out["filter_miss"] is None and out["filter_wrong"] is None and out["schemes_found"] is None
    assert out["failure"] == "retrieval miss" and out["retrieval_method"] == "dense"


# --------------------------------------------------------------------------- the fingerprint (R4.2, §9.1)

def bench(**methods) -> BenchmarkSettings:
    base = {"dense": {}, "bm25": {"k1": 1.2, "b": 0.75}, "hybrid_rrf": {"depth": 20, "rrf_k": 60},
            "dense_rerank": {"depth": 20}, "hybrid_rerank": {"depth": 50, "hybrid_depth": 50},
            "scheme_filter": {"fuzzy_threshold": 0.85, "ranker": "dense"}, "mmr": {"depth": 50, "lambda": 0.7},
            "best_combo": {"filter": True, "ranker": "mmr"}}
    base.update(methods)
    return BenchmarkSettings({"candidate_k": 20, "methods": base, "grids": {},
                              "reranker": {"model": "bge-reranker-base", "revision": "abc123",
                                           "max_length": 512, "batch_size": 16}})


def test_fingerprint_covers_the_method_settings_the_reranker_and_the_question_files(settings):
    fp = r4.fingerprint(settings, bench(), ["dense", "best_combo"], "test")
    assert set(fp["methods"]) == {"dense", "best_combo"}
    assert fp["methods"]["best_combo"] == {"filter": True, "ranker": "mmr"}
    assert fp["reranker"] == {"model": "bge-reranker-base", "revision": "abc123"}
    assert fp["question_set"] == "test" and len(fp["questions_sha256"]) == 64
    assert fp["llm_provider"] == settings.llm.provider and fp["llm_model"] == settings.llm.model
    # A changed method setting is a different run; the reranker revision too.
    assert r4.fingerprint(settings, bench(best_combo={"filter": False, "ranker": "mmr"}),
                          ["dense", "best_combo"], "test") != fp
    other = bench()
    other.reranker["revision"] = "zzz"
    assert r4.fingerprint(settings, other, ["dense", "best_combo"], "test") != fp
    # The question set is hashed over all its files, so dev and test differ.
    assert r4.fingerprint(settings, bench(), ["dense"], "dev")["questions_sha256"] != fp["questions_sha256"]


def test_a_resumed_run_with_another_fingerprint_stops(settings, tmp_path):
    a = answerer(tmp_path, r4.Ledger())
    run_eval(settings, QUESTIONS[:1], {"dense": a})
    with pytest.raises(runner.ResumeMismatch, match="--fresh"):
        runner.run_eval(settings, QUESTIONS[:1], HOLDINGS, {"dense": a}, out_dir=settings.paths.results,
                        progress=lambda _: None, columns=r4.COLUMNS,
                        fingerprint={"test": 2})
    manifest = json.loads((settings.paths.results / runner.MANIFEST_FILE).read_text(encoding="utf-8"))
    assert manifest["setup"] == {"test": 1}


# --------------------------------------------------------------------------- the spend log (R4.6, FR-R9.3)

def an_estimate(paid=2, prompt=3_000, completion=900) -> Estimate:
    return Estimate(set_name="test", by_method=[MethodEstimate(method="dense", calls=paid + 1, cached=1,
                                                               prompt_tokens=prompt,
                                                               completion_tokens=completion)])


def test_spend_log_appends_one_row_per_run_with_estimate_next_to_actual(tmp_path):
    path = tmp_path / "retrieval" / r4.SPEND_FILE
    led = r4.Ledger(max_tokens=50_000)
    led.record(rag_result(prompt=2_000, completion=400))
    led.record(rag_result(cached=True))
    row = r4.append_spend(path, "smoke", "test", ["dense", "best_combo"], 3, led, an_estimate(), None)
    assert row["phase"] == "smoke" and row["methods"] == "dense best_combo"
    assert row["prompt_tokens"] == 2_000 and row["total_tokens"] == 2_400
    assert row["est_total_tokens"] == 3_900 and row["max_tokens"] == 50_000
    r4.append_spend(path, "full", "test", ["dense"], 88, r4.Ledger(), None, "cap reached")
    written = list(pd.read_csv(path).to_dict("records"))
    assert [w["phase"] for w in written] == ["smoke", "full"]
    assert written[1]["stopped"] == "cap reached" and written[0]["at_ist"].endswith("+05:30")
    assert list(pd.read_csv(path).columns) == r4.SPEND_COLUMNS


def test_the_spend_log_holds_no_money_only_tokens(tmp_path):
    """RD11: prices are not in this repo, so nothing in the log may look like one."""
    path = tmp_path / r4.SPEND_FILE
    r4.append_spend(path, "smoke", "test", ["dense"], 3, r4.Ledger(), an_estimate(), None)
    text = path.read_text(encoding="utf-8").lower()
    assert not any(w in text for w in ("price", "cost", "usd", "inr", "$", "credit"))


# --------------------------------------------------------------------------- the model check (R4.7, §12)

class FreshLLM:
    """Stands in for an uncached ``LLM``: answers from a list, counts tokens, writes no cache."""

    def __init__(self, texts):
        self.texts, self.calls = list(texts), 0

    def generate(self, messages, json=True):  # noqa: A002 (the wrapper's own name)
        text = self.texts[self.calls]
        self.calls += 1
        if isinstance(text, Exception):
            raise text
        return LLMResult(text=text, prompt_tokens=1_000, completion_tokens=100, latency_ms=10.0,
                         provider="velona", model="grok-test", reasoning_tokens=0)


def stored(value) -> dict:
    return {"text": json.dumps({"answer": f"{value}%", "value": value, "unit": "pct", "items": [],
                                "sources": [], "insufficient_context": False}),
            "model": "grok-recorded"}


def check(settings, monkeypatch, tmp_path, texts, cached_values, max_tokens=None):
    led = r4.Ledger(max_tokens=max_tokens)
    a = answerer(tmp_path, led)
    for q, value in zip(QUESTIONS, cached_values):
        if value is not None:
            a.probe.llm.store(a.messages(q.text)[0], stored(value))
    fresh = FreshLLM(texts)
    monkeypatch.setattr(r4, "LLM", lambda *args, **kw: fresh)
    return r4.model_check(settings, a, QUESTIONS[:len(texts)], progress=lambda _: None), led, fresh


def test_model_check_says_the_answers_are_the_same(settings, monkeypatch, tmp_path):
    out, led, fresh = check(settings, monkeypatch, tmp_path, [stored(5.0)["text"], stored(4.0)["text"]],
                            [5.0, 4.0])
    assert out["verdict"] == "same answers" and out["model"] == settings.llm.model
    assert out["check_question"] == QUESTIONS[0].text and out["method"] == "dense"
    assert all(e["same_value"] and e["cached_model"] == "grok-recorded" for e in out["per_question"])
    assert fresh.calls == 2 and led.total_tokens == 2 * 1_100     # the check's own calls are counted


def test_model_check_reports_a_changed_answer(settings, monkeypatch, tmp_path):
    out, _, _ = check(settings, monkeypatch, tmp_path, [stored(9.0)["text"]], [5.0])
    assert out["verdict"].startswith("answers differ")
    entry = out["per_question"][0]
    assert (entry["cached_value"], entry["fresh_value"], entry["same_value"]) == (5.0, 9.0, False)


def test_model_check_without_a_cached_answer_compares_nothing(settings, monkeypatch, tmp_path):
    out, _, _ = check(settings, monkeypatch, tmp_path, [stored(5.0)["text"]], [None])
    assert out["verdict"] == "no cached answer to compare"
    assert out["per_question"][0]["cached"] is False


def test_model_check_records_a_provider_failure_and_obeys_the_cap(settings, monkeypatch, tmp_path):
    out, _, _ = check(settings, monkeypatch, tmp_path, [RateLimited("429 too many")], [5.0])
    assert "rate_limited" in out["per_question"][0]["error"]
    capped, led, fresh = check(settings, monkeypatch, tmp_path, [stored(5.0)["text"]], [5.0], max_tokens=10)
    assert fresh.calls == 0 and capped["per_question"][0]["skipped"] == "token cap reached"
    assert led.total_tokens == 0


# --------------------------------------------------------------------------- the manifest (R4.7)

def test_the_session_keeps_its_spend_row_and_the_model_check(settings, tmp_path):
    a = answerer(tmp_path, r4.Ledger())
    run_eval(settings, QUESTIONS[:1], {"dense": a}, manifest_extra={"stage": "B", "phase": "smoke"})
    r4.record_extras(settings.paths.results, {"spend": {"phase": "smoke", "total_tokens": 2_400},
                                              "model_check": {"verdict": "same answers"}})
    manifest = json.loads((settings.paths.results / runner.MANIFEST_FILE).read_text(encoding="utf-8"))
    assert manifest["stage"] == "B" and manifest["phase"] == "smoke"
    assert manifest["sessions"][-1]["spend"]["total_tokens"] == 2_400
    assert manifest["model_check"]["verdict"] == "same answers"
