"""Stage A: metrics, the dev choices, the ranking and shortlist, the bootstrap, the estimator (spec §10).

Hand-made cases only: no real files, no model, no LLM, no network. The metrics are checked on cases
where the right answer can be read off by hand (duplicate parents, no hit, unanswerable left out), the
bootstrap for determinism and for an interval that holds 0, the shortlist on a tie, and the estimator's
token sums and cache hits on a fake cache.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from src.chunking.base import Chunk
from src.config import load_settings
from src.eval.questions import Question
from src.rag.retrieve import Retrieved
from src.retrieval.estimate import (COMPLETION_TOKENS, PROMPT_OVERHEAD, CacheProbe, Estimate,
                                    MethodEstimate, smoke_questions)
from src.retrieval.offline import (COLUMNS, KS, Standing, Target, bootstrap_note, child_refs,
                                   choose_combo, choose_variants, combo_variants, context_metrics,
                                   filter_flags, frame, grid_variants, load_offline, metrics,
                                   method_line, paired_bootstrap, paired_values, rank_methods,
                                   rank_variants, section_scheme, shortlist, variant_label, write_choices,
                                   write_offline)
from src.retrieval.settings import BenchmarkSettings

NO_ENV = Path("does-not-exist.env")
DATE = "2026-09-30"
FILE = "synthetic_offline.xls"


# --------------------------------------------------------------------------- hand-made children

def child(scheme: str, n: int, section: str = "p0", tokens: int = 40) -> Chunk:
    """One child of scheme ``scheme``, row ``n``, in section ``section``."""
    pid = f"hierarchical:{DATE}:{scheme}:{section}"
    key = (FILE, scheme, n)
    return Chunk(f"hierarchical:{DATE}:{scheme}:{n}", f"row {n} of {scheme}", "hierarchical", "Synthetic AMC",
                 scheme, f"SYNTHETIC {scheme}", DATE, section, (key,), tokens, False, pid)


def found(*chunks: Chunk) -> list[Retrieved]:
    return [Retrieved(c, score=1.0 - 0.01 * i, rank=i + 1) for i, c in enumerate(chunks)]


def target(*rows, sections=None) -> Target:
    secs = sections or {f"hierarchical:{DATE}:{r[1]}:p0" for r in rows}
    return Target(frozenset(rows), frozenset(secs))


# --------------------------------------------------------------------------- metrics (§6.4)

def test_section_recall_counts_unique_parents_not_children():
    """Three children of the same section give that one section; the second gold section is missed."""
    gold = target((FILE, "A", 1), (FILE, "B", 1))
    kids = child_refs(found(child("A", 1), child("A", 2), child("A", 3), child("A", 4), child("A", 5)))
    m = metrics(gold, kids)
    assert m["section_recall@5"] == 0.5          # 1 of 2 gold sections
    assert m["scheme_recall@5"] == 0.5
    assert m["row_recall@5"] == 0.5              # A:1 found, B:1 not
    assert m["hit@5"] == 1.0


def test_section_recall_at_1_and_the_k_steps():
    gold = target((FILE, "A", 7), (FILE, "B", 2))
    kids = child_refs(found(child("C", 1), child("A", 7), child("C", 2), child("C", 3), child("C", 4),
                            *[child("C", i) for i in range(5, 14)], child("B", 2)))
    m = metrics(gold, kids)
    assert [m[f"section_recall@{k}"] for k in KS] == [0.0, 0.5, 0.5, 0.5, 1.0]
    assert [m[f"hit@{k}"] for k in KS] == [0.0, 1.0, 1.0, 1.0, 1.0]
    assert m["row_recall@20"] == 1.0


def test_mrr_is_one_over_the_first_gold_rank_and_zero_without_a_hit():
    gold = target((FILE, "A", 1))
    kids = child_refs(found(child("B", 1), child("B", 2), child("A", 1)))
    assert metrics(gold, kids)["mrr@10"] == pytest.approx(1 / 3)
    far = child_refs(found(*[child("B", i) for i in range(1, 11)], child("A", 1)))
    assert metrics(gold, far)["mrr@10"] == 0.0   # the hit is at rank 11, outside the top 10
    assert metrics(gold, far)["hit@20"] == 1.0


def test_unanswerable_question_is_left_out_of_the_retrieval_metrics():
    with pytest.raises(ValueError, match="unanswerable"):
        metrics(Target(frozenset(), frozenset()), child_refs(found(child("A", 1))))


def test_scheme_recall_separates_wrong_scheme_from_wrong_section():
    gold = Target(frozenset({(FILE, "A", 1)}), frozenset({f"hierarchical:{DATE}:A:p1"}))
    other_section = child_refs(found(child("A", 9, section="p0")))
    assert metrics(gold, other_section)["scheme_recall@1"] == 1.0      # right scheme
    assert metrics(gold, other_section)["section_recall@1"] == 0.0     # wrong section
    wrong_scheme = child_refs(found(child("B", 9)))
    assert metrics(gold, wrong_scheme)["scheme_recall@1"] == 0.0


def test_section_scheme_reads_the_code_out_of_a_parent_id():
    assert section_scheme(f"hierarchical:{DATE}:ABSLMCF:p0") == "ABSLMCF"
    with pytest.raises(ValueError):
        section_scheme("not-a-parent-id")


# --------------------------------------------------------------------------- context after the parent swap

def parents_of(*chunks: Chunk) -> dict[str, Chunk]:
    out: dict[str, Chunk] = {}
    for c in chunks:
        pid = str(c.parent_id)
        rows = out[pid].source_rows if pid in out else ()
        out[pid] = Chunk(pid, "section", "hierarchical", c.amc, c.scheme_code, c.scheme, DATE, c.section,
                         (*rows, *c.source_rows), 200, False)
    return out


def test_context_metrics_count_the_whole_section_the_llm_gets():
    a1, a2, b1 = child("A", 1), child("A", 2), child("B", 1)
    parents = parents_of(a1, a2, b1)
    gold = target((FILE, "A", 2))                # row 2 is not retrieved, but its section is
    ctx = context_metrics(gold, found(a1, b1), parents, top_k=5)
    assert ctx["n_sections"] == 2
    assert ctx["context_gold_row_recall"] == 1.0
    assert ctx["context_tokens"] == 400          # two parents of 200 tokens
    cut = context_metrics(gold, found(b1, a1), parents, top_k=1)
    assert cut["n_sections"] == 1 and cut["context_gold_row_recall"] == 0.0


def test_context_recall_is_none_for_an_unanswerable_question():
    a1 = child("A", 1)
    ctx = context_metrics(Target(frozenset(), frozenset()), found(a1), parents_of(a1), top_k=5)
    assert ctx["context_gold_row_recall"] is None and ctx["context_tokens"] == 200


# --------------------------------------------------------------------------- filter flags (§5.1)

def test_filter_flags_name_the_two_filter_failures():
    gold = target((FILE, "A", 1))
    assert filter_flags({"schemes_found": ["A"]}, gold) == {"filter_miss": 0, "filter_wrong": 0}
    assert filter_flags({"schemes_found": []}, gold) == {"filter_miss": 1, "filter_wrong": 0}
    assert filter_flags({"schemes_found": ["B"]}, gold) == {"filter_miss": 1, "filter_wrong": 1}
    assert filter_flags({"schemes_found": ["A", "B"]}, gold) == {"filter_miss": 0, "filter_wrong": 1}
    assert filter_flags({}, gold) == {"filter_miss": None, "filter_wrong": None}      # method has no filter
    assert filter_flags({"schemes_found": ["A"]}, Target(frozenset(), frozenset()))["filter_miss"] is None


# --------------------------------------------------------------------------- variants and the grid

def test_grid_variants_is_the_product_of_the_config_grid():
    bench = BenchmarkSettings.from_settings(load_settings(env_file=NO_ENV, environ={"LLM_PROVIDER": "mock"}))
    assert grid_variants(bench, "dense") == [{}]
    bm25 = grid_variants(bench, "bm25")
    assert len(bm25) == len(bench.grids["bm25"]["k1"]) * len(bench.grids["bm25"]["b"])
    assert {"k1": 1.5, "b": 0.75} in bm25
    assert variant_label("bm25", {"k1": 1.2, "b": 0.5}) == "bm25[b=0.5,k1=1.2]"
    assert variant_label("dense", {}) == "dense"


def test_combo_variants_are_every_ranker_with_and_without_the_filter():
    cands = combo_variants()
    assert len(cands) == 12 and {"filter": True, "ranker": "hybrid_rerank"} in cands
    assert all(set(c) == {"filter", "ranker"} for c in cands)


# --------------------------------------------------------------------------- a fake offline.csv

def fake_rows(scores: dict[str, list[float]], *, hits: dict[str, list[float]] | None = None,
              ms: dict[str, float] | None = None, set_name: str = "test", settings_json: str = "{}",
              types: list[str] | None = None, originals: int = 0) -> list[dict]:
    """One row per (method, question) with the given per-question ``section_recall@5``."""
    rows = []
    n = len(next(iter(scores.values())))
    for method, values in scores.items():
        for i, v in enumerate(values):
            rows.append({
                "set": set_name, "method": method, "method_id": method, "variant": method,
                "settings": settings_json, "qid": f"Q{i + 1:02d}", "type": (types or ["lookup"] * n)[i],
                "answer_kind": "number", "answerable": 1, "original": int(i < originals), "short_name": 0,
                "n_gold_rows": 1, "n_gold_sections": 1, "gold_sections": "[]", "gold_schemes": "[]",
                "children": json.dumps(["A:1"]), "scores": "[]",
                "section_recall@5": v, "hit@5": (hits or {}).get(method, [1.0] * n)[i],
                "mrr@10": v, "row_recall@5": v, "scheme_recall@5": v,
                "n_sections": 2, "context_gold_row_recall": v, "context_tokens": 1000,
                "retrieval_ms": (ms or {}).get(method, 10.0),
            })
    return rows


def test_ranking_uses_recall_then_hit_then_mrr_then_latency():
    rows = fake_rows({"dense": [1.0, 0.0], "bm25": [1.0, 0.0], "mmr": [0.0, 0.0]},
                     hits={"dense": [1.0, 0.0], "bm25": [1.0, 1.0], "mmr": [1.0, 1.0]})
    ranking = rank_methods(frame(rows))
    assert [s.method for s in ranking] == ["bm25", "dense", "mmr"]     # tied recall, bm25 wins on hit@5
    assert [s.rank for s in ranking] == [1, 2, 3]


def test_latency_noise_does_not_decide_a_tie_but_a_real_cost_difference_does():
    """Two variants tied on every metric: a few ms apart is a tie (settled by name), seconds apart is not."""
    from src.retrieval.offline import LATENCY_TIE_MS

    noise = frame(fake_rows({"bm25": [1.0, 1.0], "mmr": [1.0, 1.0]},
                            ms={"bm25": 10.0, "mmr": 10.0 + LATENCY_TIE_MS / 4}))
    ranking = rank_methods(noise)
    assert [s.rank for s in ranking] == [1, 1]
    assert [s.method for s in ranking] == ["bm25", "mmr"]          # by name, so a re-run picks the same
    real = frame(fake_rows({"bm25": [1.0, 1.0], "mmr": [1.0, 1.0]}, ms={"bm25": 6000.0, "mmr": 10.0}))
    assert [s.method for s in rank_methods(real)] == ["mmr", "bm25"]


def test_a_full_tie_shares_a_rank_and_is_broken_by_latency():
    rows = fake_rows({"dense": [1.0, 1.0], "bm25": [1.0, 1.0], "mmr": [1.0, 1.0]},
                     ms={"dense": 50.0, "bm25": 5.0, "mmr": 5.0})
    ranking = rank_methods(frame(rows))
    assert [s.method for s in ranking] == ["bm25", "mmr", "dense"]
    assert [s.rank for s in ranking] == [1, 1, 3]                      # bm25 and mmr are a full tie


def test_shortlist_is_top_two_plus_dense_and_grows_when_dense_is_already_there():
    rows = fake_rows({"dense": [0.0, 0.0], "bm25": [1.0, 1.0], "mmr": [1.0, 0.0], "hybrid_rrf": [0.5, 0.0]})
    ranking = rank_methods(frame(rows))
    assert shortlist(ranking) == ["bm25", "mmr", "dense"]
    top = fake_rows({"dense": [1.0, 1.0], "bm25": [1.0, 0.0], "mmr": [0.5, 0.0], "hybrid_rrf": [0.0, 0.0]})
    assert shortlist(rank_methods(frame(top))) == ["dense", "bm25", "mmr"]   # dense is in the top 2
    tie = fake_rows({"dense": [1.0, 0.0], "bm25": [1.0, 0.0], "mmr": [1.0, 0.0]})
    # A full tie: all three share rank 1, so the set is the same whichever two are "top"; the order is
    # the leaderboard's (by name within a tie), not "the reference last".
    assert shortlist(rank_methods(frame(tie))) == ["bm25", "dense", "mmr"]


def test_the_leaderboard_refuses_two_variants_of_one_method():
    rows = fake_rows({"bm25": [1.0]})
    rows += [{**r, "variant": "bm25[k1=2.0]"} for r in rows]
    with pytest.raises(ValueError, match="more than one variant"):
        rank_methods(frame(rows))


def test_choose_variants_picks_the_best_dev_variant_per_method():
    dev = frame(fake_rows({"bm25": [0.0, 0.0]}, set_name="dev")
                + [{**r, "variant": "bm25[k1=2.0]", "settings": '{"k1": 2.0}', "section_recall@5": 1.0,
                    "mrr@10": 1.0} for r in fake_rows({"bm25": [1.0, 1.0]}, set_name="dev")])
    chosen = choose_variants(dev, ["bm25"])
    assert chosen["bm25"].variant == "bm25[k1=2.0]" and chosen["bm25"].settings == {"k1": 2.0}


def test_choose_combo_declares_m8_from_dev_rows_only():
    worse = fake_rows({"best_combo": [0.0, 0.0]}, set_name="dev",
                      settings_json='{"filter": false, "ranker": "dense"}')
    better = [{**r, "variant": "best_combo[filter=True,ranker=hybrid_rerank]",
               "settings": '{"filter": true, "ranker": "hybrid_rerank"}', "section_recall@5": 1.0}
              for r in worse]
    combo = choose_combo(frame(worse + better))
    assert combo.settings == {"filter": True, "ranker": "hybrid_rerank"}
    with pytest.raises(ValueError, match="no best_combo rows"):
        choose_combo(frame(fake_rows({"dense": [1.0]}, set_name="dev")))


# --------------------------------------------------------------------------- bootstrap (§6.5, RD8)

def test_bootstrap_is_deterministic_for_a_seed_and_reads_as_a_tie_when_it_holds_zero():
    a = [1.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0]
    b = [1.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0]
    first = paired_bootstrap(a, b)
    assert paired_bootstrap(a, b) == first                       # same seed, same numbers
    mean, lo, hi = first
    assert mean == pytest.approx(0.125) and lo <= mean <= hi
    assert lo <= 0 <= hi
    assert "not distinguishable" in bootstrap_note("M3 hybrid_rrf", "M1 dense", mean, lo, hi)


def test_bootstrap_sees_a_clear_win_and_needs_paired_input():
    mean, lo, hi = paired_bootstrap([1.0] * 30, [0.0] * 30)
    assert (mean, lo, hi) == (1.0, 1.0, 1.0)
    assert "better" in bootstrap_note("M8", "M1 dense", mean, lo, hi)
    with pytest.raises(ValueError, match="same questions"):
        paired_bootstrap([1.0, 0.0], [1.0])


def test_paired_values_uses_only_the_questions_both_methods_answered():
    rows = fake_rows({"dense": [1.0, 0.0, 1.0], "bm25": [0.0, 1.0, 1.0]})
    rows = [r for r in rows if not (r["method"] == "bm25" and r["qid"] == "Q03")]
    a, b = paired_values(frame(rows), "bm25", "dense")
    assert (a, b) == ([0.0, 1.0], [1.0, 0.0])


# --------------------------------------------------------------------------- offline.csv

def test_offline_csv_round_trip_replaces_only_the_set_being_rerun(tmp_path):
    path = tmp_path / "offline.csv"
    write_offline(path, fake_rows({"dense": [1.0, 0.0]}, set_name="dev"))
    write_offline(path, fake_rows({"dense": [1.0, 1.0]}, set_name="test"))
    write_offline(path, fake_rows({"dense": [0.0, 0.0]}, set_name="dev"), replace_sets={"dev"})
    df = load_offline(path)
    assert list(df.columns) == COLUMNS
    assert len(df) == 4
    assert df[df["set"] == "dev"]["section_recall@5"].tolist() == [0.0, 0.0]
    assert df[df["set"] == "test"]["section_recall@5"].tolist() == [1.0, 1.0]


def test_empty_values_come_back_as_nan_not_as_the_string(tmp_path):
    rows = fake_rows({"dense": [1.0]})
    rows[0].update(filter_miss=None, context_gold_row_recall=None)
    df = load_offline(write_offline(tmp_path / "offline.csv", rows))
    assert pd.isna(df["filter_miss"].iloc[0]) and pd.isna(df["context_gold_row_recall"].iloc[0])
    assert df["schemes_found"].iloc[0] == ""


# --------------------------------------------------------------------------- config.yaml (FR-R2.3)

def test_method_line_keeps_the_old_comment_and_adds_the_date():
    line = "    bm25: {k1: 1.5, b: 0.75}                   # M2: own Okapi BM25 (RD3)"
    out = method_line(line, "bm25", {"k1": 1.2, "b": 0.9}, "23 Nov 2026")
    assert out.startswith("    bm25: {k1: 1.2, b: 0.9}")
    assert "# M2: own Okapi BM25 (RD3); chosen on dev 23 Nov 2026" in out
    # Running the dev grid twice must not stack the comment: the old dated note is replaced, not kept.
    again = method_line(out, "bm25", {"k1": 1.5, "b": 0.75}, "24 Nov 2026")
    assert again == "    bm25: {k1: 1.5, b: 0.75}   # M2: own Okapi BM25 (RD3); chosen on dev 24 Nov 2026"
    assert method_line(again, "bm25", {"k1": 1.5, "b": 0.75}, "24 Nov 2026") == again
    null = method_line("    best_combo: null", "best_combo", {"filter": True, "ranker": "mmr"},
                       "23 Nov 2026", "filter + mmr")
    assert null == "    best_combo: {filter: true, ranker: \"mmr\"}   # chosen on dev 23 Nov 2026: filter + mmr"
    with pytest.raises(ValueError):
        method_line(line, "mmr", {}, "23 Nov 2026")


def test_write_choices_edits_only_the_method_lines_and_keeps_every_comment(tmp_path):
    src = Path("config.yaml").read_text(encoding="utf-8")
    path = tmp_path / "config.yaml"
    path.write_text(src, encoding="utf-8")
    write_choices(path, {"mmr": {"depth": 50, "lambda": 0.3},
                         "best_combo": {"filter": True, "ranker": "dense_rerank"}}, "23 Nov 2026")
    new = path.read_text(encoding="utf-8")
    assert "mmr: {depth: 50, lambda: 0.3}" in new
    assert "best_combo: {filter: true, ranker: \"dense_rerank\"}" in new
    assert "chosen on dev 23 Nov 2026" in new
    assert new.count("#") >= src.count("#")                       # no comment lost
    # The edited file still loads, and the grids and the other methods are untouched.
    s = load_settings(config_path=path, env_file=NO_ENV, environ={"LLM_PROVIDER": "mock"})
    bench = BenchmarkSettings.from_settings(s)
    assert bench.methods["mmr"] == {"depth": 50, "lambda": 0.3}
    assert bench.methods["best_combo"] == {"filter": True, "ranker": "dense_rerank"}
    live = BenchmarkSettings.from_settings(load_settings(env_file=NO_ENV, environ={"LLM_PROVIDER": "mock"}))
    assert bench.methods["bm25"] == live.methods["bm25"]          # a method not chosen here is untouched
    assert bench.grids["bm25"]["k1"] == [1.2, 1.5, 2.0]


def test_write_choices_complains_about_a_method_the_config_does_not_have(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(Path("config.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ValueError, match="no retrieval_benchmark.methods line"):
        write_choices(path, {"nonsense": {}}, "23 Nov 2026")


# --------------------------------------------------------------------------- the estimator (FR-R9.1)

def test_estimate_table_counts_cache_hits_as_free_and_sums_the_rest():
    m = MethodEstimate(method="dense", calls=3, cached=1, prompt_tokens=2 * (1000 + PROMPT_OVERHEAD),
                       completion_tokens=2 * COMPLETION_TOKENS, context_tokens=3000)
    est = Estimate(set_name="test", by_method=[m, replace(m, method="bm25")])
    assert est.calls == 6 and est.cached == 2 and est.to_pay == 4
    assert est.prompt_tokens == 4 * (1000 + PROMPT_OVERHEAD)
    assert est.completion_tokens == 4 * COMPLETION_TOKENS
    assert est.total_tokens == est.prompt_tokens + est.completion_tokens
    table = est.table()
    assert "dense" in table and "bm25" in table and f"{est.total_tokens:,}" in table
    assert est.as_dict()["to_pay"] == 4


class FakeLLM:
    """Only what ``CacheProbe`` uses: the real key payload shape and the real cache layout."""

    def __init__(self, tmp_path: Path, known: set[str] = frozenset()):
        self.dir = tmp_path
        self.known = set(known)

    def cache_key(self, messages, json_mode):
        return "k" + str(abs(hash(json.dumps(messages, sort_keys=True))) % 10**8)

    def _cache_path(self, key):
        return self.dir / key[:2] / f"{key}.json"


def test_cache_probe_finds_a_prompt_that_is_already_answered(tmp_path):
    llm = FakeLLM(tmp_path)
    probe = CacheProbe(llm)
    messages = [{"role": "user", "content": "hello"}]
    assert probe.hit(messages) is False
    path = llm._cache_path(probe.key(messages))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    assert probe.hit(messages) is True
    assert probe.hit([{"role": "user", "content": "other"}]) is False


def q(qid: str, qtype: str, kind: str = "number") -> Question:
    return Question(id=qid, type=qtype, text=f"{qid}?", answer_kind=kind, gold_fn="holding_pct")


def test_smoke_questions_are_one_lookup_one_aggregation_one_cross_scheme():
    qs = [q("Q01", "unanswerable", "not_in_data"), q("Q02", "lookup"), q("Q03", "aggregation"),
          q("Q04", "lookup"), q("Q05", "cross_scheme"), q("Q06", "debt")]
    assert [x.id for x in smoke_questions(qs)] == ["Q02", "Q03", "Q05"]
    assert [x.id for x in smoke_questions([q("Q02", "lookup")])] == ["Q02"]


# --------------------------------------------------------------------------- the report reads it back

def test_summary_and_chart_are_written_from_offline_csv_alone(tmp_path):
    from src.retrieval.offline import OFFLINE_FILE
    from src.retrieval.report import CHART_FILE, SUMMARY_FILE, write_offline_report

    rows = fake_rows({"dense": [1.0, 0.0, 1.0, 0.0], "bm25": [1.0, 1.0, 1.0, 0.0],
                      "scheme_filter": [1.0, 1.0, 1.0, 1.0], "mmr": [0.0, 0.0, 1.0, 0.0]},
                     types=["lookup", "aggregation", "debt", "cross_scheme"], originals=2)
    for r in rows:
        if r["method"] == "scheme_filter":
            r.update({"filter_miss": 0, "filter_wrong": int(r["qid"] == "Q02"), "filter_match": "exact",
                      "schemes_found": '["A"]'})
    rows += fake_rows({"bm25": [1.0, 0.0, 0.0, 0.0]}, set_name="dev", settings_json='{"k1": 1.5, "b": 0.75}')
    rows += fake_rows({"best_combo": [1.0, 1.0, 1.0, 0.0]}, set_name="dev",
                      settings_json='{"filter": true, "ranker": "bm25"}')
    write_offline(tmp_path / OFFLINE_FILE, rows)
    path = write_offline_report(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert path.name == SUMMARY_FILE and (tmp_path / CHART_FILE).stat().st_size > 1000
    assert "M6 scheme_filter" in text and "Shortlist for Stage B" in text
    assert "best_combo = filter=True, ranker=bm25" in text or "ranker=bm25" in text
    assert "filter_wrong" in text and "hand-written" in text
    assert "not distinguishable" in text or "better than" in text


# --------------------------------------------------------------------------- one real run (synthetic world)

@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    """The synthetic corpus of test_methods, as ``run_set`` needs it: shared state, parents, questions."""
    from tests.retrieval.test_methods import world_from

    return world_from(tmp_path_factory.mktemp("offline"))


def test_run_set_writes_one_row_per_method_and_question_with_real_metrics(synthetic, tmp_path):
    from src.retrieval.offline import OFFLINE_FILE, run_set

    shared, parents = synthetic["shared"], synthetic["parents"]
    questions = [
        Question(id="S1", type="lookup", text="What % of AUM does the Flexi Cap Fund hold in Infosys Ltd.?",
                 answer_kind="number", gold_fn="holding_pct"),
        Question(id="S2", type="unanswerable", text="What is the AUM of the Gold ETF in 2099?",
                 answer_kind="not_in_data", gold_fn="not_in_data"),
    ]
    gold = {
        "S1": Target(frozenset({(FILE, "SYNFLEXI", 11)}), frozenset({f"hierarchical:{DATE}:SYNFLEXI:p0"})),
        "S2": Target(frozenset(), frozenset()),
    }
    rows = run_set(shared, parents, questions, gold, "dev", [("dense", None), ("bm25", {"k1": 1.5, "b": 0.75})],
                   top_k=5, originals=frozenset({"S1"}))
    assert len(rows) == 4
    df = load_offline(write_offline(tmp_path / OFFLINE_FILE, rows))
    assert set(df["variant"]) == {"dense", "bm25[b=0.75,k1=1.5]"}
    assert json.loads(df["children"].iloc[0])[0].count(":") == 1      # short ids: SCHEME:row
    s1 = df[(df["qid"] == "S1") & (df["variant"] == "dense")].iloc[0]
    assert len(json.loads(s1["children"])) == shared.bench.candidate_k
    assert s1["original"] == 1 and s1["answerable"] == 1
    assert 0.0 <= s1["section_recall@5"] <= 1.0 and s1["context_tokens"] > 0
    assert s1["retrieval_ms"] >= 0 and s1["n_sections"] >= 1
    s2 = df[df["qid"] == "S2"].iloc[0]
    assert pd.isna(s2["section_recall@5"]) and pd.isna(s2["context_gold_row_recall"])
    assert s2["context_tokens"] > 0                                # the context is still counted
    # The scheme filter's own debug reaches the row, so filter_miss / filter_wrong can be counted.
    filtered = run_set(shared, parents, questions[:1], gold, "dev", [("scheme_filter", None)], top_k=5)
    assert filtered[0]["schemes_found"] == '["SYNFLEXI"]' and filtered[0]["filter_miss"] == 0


def test_bm25_grid_changes_the_dev_choice_but_not_the_row_count(synthetic):
    from src.retrieval.offline import frame as to_frame
    from src.retrieval.offline import grid_variants, run_set

    shared, parents = synthetic["shared"], synthetic["parents"]
    q1 = Question(id="S1", type="lookup", text="Gold 995 1KG BAR", answer_kind="number", gold_fn="holding_pct")
    gold = {"S1": Target(frozenset({(FILE, "SYNTINY", 10)}), frozenset({f"hierarchical:{DATE}:SYNTINY:p0"}))}
    variants = [("bm25", ov) for ov in grid_variants(shared.bench, "bm25")]
    rows = run_set(shared, parents, [q1], gold, "dev", variants, top_k=5)
    assert len(rows) == len(variants)
    chosen = choose_variants(to_frame(rows), ["bm25"])["bm25"]
    assert chosen.settings in [dict(ov) for _, ov in variants]
    assert chosen.section_recall_5 == 1.0                          # every grid value finds the one gold row


def test_a_standing_key_is_the_spec_order():
    s = Standing(variant="x", method="dense", settings={}, n=1, section_recall_5=0.5, hit_5=0.5, mrr_10=0.5,
                 median_ms=10.0, p90_ms=20.0, row_recall_5=0.5, scheme_recall_5=0.5, context_recall=0.5,
                 context_tokens=1.0)
    better_recall = replace(s, section_recall_5=0.6)
    faster = replace(s, median_ms=1.0)
    assert better_recall.key < s.key and faster.key < s.key
    assert rank_variants(frame(fake_rows({"dense": [1.0]})), ["dense"])[0].method == "dense"
