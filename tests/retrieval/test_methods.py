"""Retrieval methods M1-M8, scheme extraction, round robin, reranker cache, pipeline hook (spec §10).

Synthetic data only (``synthetic_*`` schemes written here), a bag-of-words fake embedder instead of
bge-small, a stub scorer instead of the cross-encoder, the mock LLM. No network, no model download.
"""

import inspect
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.chunking.base import Chunk
from src.config import ConfigError, load_settings
from src.index.embedder import Embedder
from src.index.store import get_collection, open_client, write_month
from src.llm import LLM
from src.rag.pipeline import RagPipeline
from src.rag.retrieve import Retriever
from src.retrieval.base import METHOD_NAMES, ChildCorpus, DenseSearch, Shared, build_method
from src.retrieval.bm25 import BM25Index, tokenize
from src.retrieval.hybrid import rrf
from src.retrieval.mmr import mmr_select
from src.retrieval.rerank import Reranker
from src.retrieval.scheme_filter import SchemeExtractor, name_variants, round_robin
from src.retrieval.settings import BenchmarkSettings
from tests.test_rag import bow_encode

NO_ENV = Path("does-not-exist.env")
DATE = "2026-09-30"
P = "ADITYA BIRLA SUN LIFE "
FILE = "synthetic_retrieval.xls"

# code -> (name, section, rows: (instrument, industry/rating, % to AUM))
SYNTHETIC_SCHEMES = {
    "SYNPSU": (P + "BANKING & PSU DEBT FUND", "Debt Instruments", [
        ("7.10% NABARD 2030", "CRISIL AAA", 6.1), ("7.40% REC Ltd. 2029", "CRISIL AAA", 5.2),
        ("7.25% Power Finance Corporation 2031", "ICRA AAA", 4.8), ("8.00% HDFC Bank Ltd. 2028", "CARE AAA", 3.9),
        ("7.05% SIDBI 2027", "CRISIL AAA", 3.1), ("6.90% Canara Bank CD", "IND A1+", 2.0)]),
    "SYNBFS": (P + "BANKING AND FINANCIAL SERVICES FUND", "Equity & Equity Related", [
        ("HDFC Bank Ltd.", "Banks", 18.2), ("ICICI Bank Ltd.", "Banks", 16.0), ("Axis Bank Ltd.", "Banks", 7.5),
        ("Bajaj Finance Ltd.", "Finance", 6.2), ("SBI Life Insurance Ltd.", "Insurance", 4.1),
        ("Kotak Mahindra Bank Ltd.", "Banks", 3.9)]),
    "SYNBANKE": (P + "NIFTY BANK ETF", "Equity & Equity Related", [
        ("HDFC Bank Ltd.", "Banks", 28.0), ("ICICI Bank Ltd.", "Banks", 25.0), ("State Bank of India", "Banks", 9.0),
        ("Axis Bank Ltd.", "Banks", 8.5), ("Kotak Mahindra Bank Ltd.", "Banks", 8.0)]),
    "SYNSTF": (P + "SHORT TERM FUND", "Debt Instruments", [
        ("7.20% NABARD 2028", "CRISIL AAA", 5.0), ("7.60% Bajaj Finance Ltd. 2027", "CRISIL AAA", 4.0),
        ("7.90% Tata Capital Ltd. 2029", "ICRA AAA", 3.0), ("8.10% Shriram Finance Ltd. 2027", "CRISIL AA+", 2.5)]),
    "SYNUST": (P + "ULTRA SHORT TERM FUND (FORMERLY KNOWN AS " + P + "SAVINGS FUND)", "Money Market Instruments", [
        ("Axis Bank Ltd. CD", "CRISIL A1+", 6.0), ("Small Industries Dev Bank CP", "CARE A1+", 5.5),
        ("Bharti Telecom Ltd. CP", "CRISIL A1+", 4.0), ("HDFC Bank Ltd. CD", "IND A1+", 3.5)]),
    "SYNFLEXI": (P + "FLEXI CAP FUND", "Equity & Equity Related", [
        ("ICICI Bank Ltd.", "Banks", 8.0), ("Infosys Ltd.", "IT - Software", 6.0), ("HDFC Bank Ltd.", "Banks", 5.5),
        ("Reliance Industries Ltd.", "Petroleum Products", 5.0), ("Bharti Airtel Ltd.", "Telecom - Services", 4.0),
        ("Sun Pharmaceutical Industries Ltd.", "Pharmaceuticals", 3.0), ("Tata Motors Ltd.", "Automobiles", 2.0)]),
    "SYNTINY": (P + "GOLD ETF", "Others", [("Gold 995 1KG BAR", "Gold", 98.5)]),
}


def synthetic_chunks() -> tuple[list[Chunk], dict[str, Chunk]]:
    children, parents = [], {}
    for code, (name, section, rows) in SYNTHETIC_SCHEMES.items():
        pid = f"hierarchical:{DATE}:{code}:p0"
        keys = []
        for n, (inst, ind, pct) in enumerate(rows):
            key = (FILE, code, 10 + n)
            keys.append(key)
            text = (f"Scheme: {name} | As on: {DATE} | Section: {section} | Instrument: {inst} | "
                    f"Industry/Rating: {ind} | % to AUM: {pct:.2f}")
            children.append(Chunk(f"hierarchical:{DATE}:{code}:{n}", text, "hierarchical", "Synthetic AMC", code,
                                  name, DATE, section, (key,), 40, False, pid))
        table = "\n".join(c.text for c in children if c.scheme_code == code)
        parents[pid] = Chunk(pid, table, "hierarchical", "Synthetic AMC", code, name, DATE, section, tuple(keys),
                             200, False)
    return children, parents


def stub_scorer(pairs):
    """Counts words shared by question and row, plus a big bonus for 'icici' (so reranking visibly moves it)."""
    out = []
    for q, t in pairs:
        qw, tw = set(tokenize(q)), set(tokenize(t))
        out.append(len(qw & tw) + (10.0 if "icici" in tw else 0.0))
    return out


stub_scorer.key = "stub-scorer@test"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("retrieval")
    s = load_settings(env_file=NO_ENV, environ={"LLM_PROVIDER": "mock"})
    s = replace(s, paths=replace(s.paths, cache=tmp / "cache", chroma=tmp / "chroma", processed=tmp / "processed"))
    children, parents = synthetic_chunks()
    embedder = Embedder(s.embedding.model, s.paths.cache / "emb.sqlite", encode_fn=bow_encode, query_prefix="")
    client = open_client(s.paths.chroma)
    col = get_collection(client, "hierarchical", s.embedding.model, create=True)
    write_month(col, DATE, children, embedder.embed_documents([c.text for c in children]))
    corpus = ChildCorpus.from_collection(col, DATE)
    schemes = pd.DataFrame({"scheme_code": list(SYNTHETIC_SCHEMES),
                            "scheme": [v[0] for v in SYNTHETIC_SCHEMES.values()]})
    bench = BenchmarkSettings.from_settings(s)
    shared = Shared(bench, corpus, DenseSearch(embedder, col, corpus, DATE, month_filter=False), schemes,
                    scorer=stub_scorer, rerank_cache_path=s.paths.cache / "rerank.sqlite")
    retriever = Retriever(s, embedder=embedder, client=client, parents=parents)
    return dict(s=s, shared=shared, parents=parents, retriever=retriever, n=len(children))


def same_up_to_ties(a, b) -> bool:
    """Same scores in the same order, and the same children within each group of equal scores. The fake
    bag-of-words embedder gives many rows identical scores, and Chroma may order those ties differently for
    5 and 20 results, also at the k cut (on the real index no top-20 score is tied: checked on all 128
    questions in R2)."""
    sa, sb = [round(c.score, 6) for c in a], [round(c.score, 6) for c in b]
    if sa != sb:
        return False
    groups: dict[float, tuple[set, set]] = {}
    for x, y, sc in zip(a, b, sa):
        g = groups.setdefault(sc, (set(), set()))
        g[0].add(x.chunk.id)
        g[1].add(y.chunk.id)
    last = min(groups)                    # the group cut by k may hold different members of a bigger tie
    return all(x == y for sc, (x, y) in groups.items() if sc != last)


def all_methods(shared):
    out = [build_method(m, shared) for m in METHOD_NAMES if m != "best_combo"]
    out.append(build_method("best_combo", shared, {"filter": True, "ranker": "hybrid_rerank"}))
    out.append(build_method("best_combo", shared, {"filter": False, "ranker": "bm25"}))
    return out


# --------------------------------------------------------------------------- every method

@pytest.mark.parametrize("question", [
    "What % of AUM does Aditya Birla Sun Life Flexi Cap Fund hold in ICICI Bank Ltd. as on 30 Sep 2026?",
    "Which holds more HDFC Bank Ltd.: the Nifty Bank ETF or the Banking and Financial Services Fund?",
    "zzz qqq xyzzy",                                     # no word in common with any row
])
@pytest.mark.parametrize("k", [5, 20])
def test_every_method_returns_exactly_k_ranked_unique_and_deterministic(world, question, k):
    for m in all_methods(world["shared"]):
        res = m.retrieve(question, k)
        ids = [c.chunk.id for c in res.children]
        assert len(ids) == min(k, world["n"]), m.name
        assert len(set(ids)) == len(ids), m.name
        assert [c.rank for c in res.children] == list(range(1, len(ids) + 1)), m.name
        assert res.latency_ms >= 0 and res.method == m.name
        assert [c.chunk.id for c in m.retrieve(question, k).children] == ids, f"{m.name} not deterministic"


def test_top5_is_prefix_of_top20(world):
    q = "Which holds more HDFC Bank Ltd.: the Nifty Bank ETF or the Banking and Financial Services Fund?"
    for m in all_methods(world["shared"]):
        assert [c.chunk.id for c in m.retrieve(q, 5).children] == [c.chunk.id for c in m.retrieve(q, 20).children][:5]


def test_dense_equals_todays_retriever(world):
    q = "What % of AUM does the Flexi Cap Fund hold in Infosys Ltd.?"
    today = world["retriever"].retrieve(q, "hierarchical", 5)
    m1 = build_method("dense", world["shared"]).retrieve(q, 5)
    assert same_up_to_ties(m1.children, today.children)


# --------------------------------------------------------------------------- BM25

def test_tokenizer_keeps_short_tokens_and_numbers():
    toks = tokenize("8.56% REC Ltd. (29/11/2028) | CRISIL AAA | Banking & PSU | IT - Software")
    for t in ("8", "56", "rec", "29", "2028", "aaa", "psu", "it"):
        assert t in toks


def test_bm25_hand_computed_order():
    idx = BM25Index(["aaa bond", "aaa aaa psu", "psu bank equity"])
    s = idx.scores("aaa psu", k1=1.5, b=0.75)
    idf = math.log(1.6)                                   # df = 2 of N = 3: ln(1 + 1.5 / 2.5)
    assert idx.idf["aaa"] == pytest.approx(idf)
    assert s[0] == pytest.approx(idf * 2.5 / (1 + 1.21875))                       # dl 2, avgdl 8/3
    assert s[1] == pytest.approx(idf * 2 * 2.5 / (2 + 1.640625) + idf * 2.5 / (1 + 1.640625))
    assert s[2] == pytest.approx(idf * 2.5 / (1 + 1.640625))
    assert list(np.argsort(-s)) == [1, 0, 2]
    assert idx.scores("nothing here", 1.5, 0.75).sum() == 0


def test_bm25_finds_exact_terms(world):
    res = build_method("bm25", world["shared"]).retrieve("Gold 995 1KG BAR", 5)
    assert res.children[0].chunk.scheme_code == "SYNTINY"


# --------------------------------------------------------------------------- RRF

def test_rrf_hand_computed():
    fused = rrf([[(1, 0.9), (2, 0.8), (3, 0.7)], [(3, 5.0), (4, 4.0)]], rrf_k=60)
    assert [i for i, _ in fused] == [3, 1, 2, 4]          # 2 and 4 tie at 1/62: same best rank, then id
    assert dict(fused)[3] == pytest.approx(1 / 63 + 1 / 61)
    assert dict(fused)[4] == pytest.approx(1 / 62)        # in one list only: still ranked


# --------------------------------------------------------------------------- MMR

def test_mmr_lambda_one_is_dense_order(world):
    q = "HDFC Bank Ltd. banks holdings"
    dense = [c.chunk.id for c in build_method("dense", world["shared"]).retrieve(q, 10).children]
    mmr = [c.chunk.id for c in build_method("mmr", world["shared"], {"lambda": 1.0}).retrieve(q, 10).children]
    assert mmr == dense


def test_mmr_lambda_zero_picks_diverse():
    a = np.array([1.0, 0.0])
    b = np.array([0.99, 0.141]) / np.linalg.norm([0.99, 0.141])        # near copy of a
    c = np.array([0.6, 0.8])
    cands = np.stack([a, b, c]).astype(np.float32)
    q = np.array([1.0, 0.0], dtype=np.float32)
    assert [j for j, _ in mmr_select(q, cands, 3, 1.0)] == [0, 1, 2]
    assert [j for j, _ in mmr_select(q, cands, 3, 0.0)] == [0, 2, 1]


def test_mmr_rejects_bad_lambda(world):
    with pytest.raises(ValueError):
        build_method("mmr", world["shared"], {"lambda": 1.5})


# --------------------------------------------------------------------------- scheme extraction

@pytest.fixture(scope="module")
def ex(world):
    return world["shared"].extractor


@pytest.mark.parametrize("text, want", [
    ("What % does Aditya Birla Sun Life Flexi Cap Fund hold in Infosys?", ["SYNFLEXI"]),         # full name
    ("What % does the Flexi Cap Fund hold in Infosys?", ["SYNFLEXI"]),                           # short name
    ("aditya birla sun life flexi cap fund, infosys weight", ["SYNFLEXI"]),                      # lower case
    ("How big is the Savings Fund's CD exposure?", ["SYNUST"]),                                  # former name
    ("SYNFLEXI holdings in Infosys", ["SYNFLEXI"]),                                              # scheme code
    ("the Banking & PSU Debt Fund AAA share", ["SYNPSU"]),                                       # & form
    ("the banking and psu debt fund AAA share", ["SYNPSU"]),                                     # and form
    ("the Banking and Financial Services Fund top holdings", ["SYNBFS"]),                        # look-alike
    ("the Nifty Bank ETF top holdings", ["SYNBANKE"]),                                           # look-alike
    ("Ultra Short Term Fund CP holdings", ["SYNUST"]),                       # not also "Short Term Fund"
    ("Short Term Fund or Ultra Short Term Fund: which holds more NABARD?", ["SYNSTF", "SYNUST"]),
    ("Which holds more HDFC Bank: the Nifty Bank ETF or the Flexi Cap Fund?", ["SYNBANKE", "SYNFLEXI"]),
    ("What is the expense ratio of a bank fund?", []),                                           # none
    ("the flexi-cap fnd holdings", ["SYNFLEXI"]),                                                # fuzzy typo
])
def test_extraction(ex, text, want):
    got = ex.extract(text, 0.85)
    assert list(got.schemes) == want, got.debug()
    assert got.match == ("none" if not want else got.match)


def test_extraction_kinds(ex):
    assert ex.extract("the Flexi Cap Fund").match == "exact"
    assert ex.extract("the flexi-cap fnd").match == "fuzzy"
    assert ex.extract("the flexi-cap fnd", fuzzy_threshold=0.99).match == "none"
    assert ex.extract("nothing to see").debug() == {"schemes_found": [], "match": "none", "matched": []}


def test_extraction_reads_text_only():
    """Never the gold params: the extractor and the methods take the question text, nothing else."""
    assert list(inspect.signature(SchemeExtractor.extract).parameters) == ["self", "question", "fuzzy_threshold"]
    from src.retrieval.base import RetrievalMethod
    assert list(inspect.signature(RetrievalMethod.retrieve).parameters) == ["self", "question", "k"]


def test_name_variants():
    v = name_variants(P + "ULTRA SHORT TERM FUND (FORMERLY KNOWN AS " + P + "SAVINGS FUND)")
    assert "ultra short term fund" in v and "savings fund" in v and "aditya birla sun life savings fund" in v
    assert "aditya birla sun life ultra short term fund" in v
    assert name_variants(P + "EQUITY HYBRID '95 FUND")[-1] == "equity hybrid 95 fund"


def test_codes_that_are_name_words_are_not_used():
    ex = SchemeExtractor(pd.DataFrame({"scheme_code": ["NIFTY", "BSLEQTY"],
                                       "scheme": [P + "NIFTY 50 INDEX FUND", P + "FLEXI CAP FUND"]}))
    assert ex.codes == {"BSLEQTY"}
    assert ex.extract("NIFTY rose today").schemes == ()
    assert ex.extract("bsleqty in lower case is not a code").schemes == ()


# --------------------------------------------------------------------------- round robin + filter

def test_round_robin_two_and_three():
    a, b, c = [(1, .9), (2, .8), (3, .7)], [(11, .9), (12, .8), (13, .7)], [(21, .9)]
    assert [i for i, _ in round_robin([a, b], 5)] == [1, 11, 2, 12, 3]
    assert [i for i, _ in round_robin([a, b, c], 5)] == [1, 11, 21, 2, 12]
    assert [i for i, _ in round_robin([c, a], 4)] == [21, 1, 2, 3]       # short list gives its share away
    assert round_robin([[], []], 5) == []


def test_filter_one_scheme(world):
    res = build_method("scheme_filter", world["shared"]).retrieve("the Flexi Cap Fund holding in HDFC Bank", 5)
    assert {c.chunk.scheme_code for c in res.children} == {"SYNFLEXI"}
    # every method ranks candidate_k = 20 first (FR-R2.2); the scheme has 7 rows, so 13 come from outside it
    assert res.debug["schemes_found"] == ["SYNFLEXI"] and res.debug["padded"] == 20 - 7


def test_filter_two_schemes_split(world):
    res = build_method("scheme_filter", world["shared"]).retrieve(
        "Which holds more HDFC Bank Ltd.: the Nifty Bank ETF or the Flexi Cap Fund?", 5)
    codes = [c.chunk.scheme_code for c in res.children]
    assert codes == ["SYNBANKE", "SYNFLEXI", "SYNBANKE", "SYNFLEXI", "SYNBANKE"]
    assert res.debug["split_top5"] == {"SYNBANKE": 3, "SYNFLEXI": 2}


def test_filter_small_scheme_is_padded(world):
    res = build_method("scheme_filter", world["shared"]).retrieve("What does the Gold ETF hold?", 5)
    assert res.children[0].chunk.scheme_code == "SYNTINY" and len(res.children) == 5
    assert res.debug["padded"] == 20 - 1


def test_filter_none_found_is_dense(world):
    q = "What is the expense ratio of a bank fund?"
    f = build_method("scheme_filter", world["shared"]).retrieve(q, 5)
    d = build_method("dense", world["shared"]).retrieve(q, 5)
    assert [c.chunk.id for c in f.children] == [c.chunk.id for c in d.children] and f.debug["match"] == "none"


# --------------------------------------------------------------------------- reranker

def test_rerank_reorders_and_caches(world, tmp_path):
    calls = []

    def scorer(pairs):
        calls.append(len(pairs))
        return stub_scorer(pairs)

    scorer.key = "counting-stub"
    shared = world["shared"]
    rr = Reranker(scorer, tmp_path / "rerank.sqlite")
    texts = shared.corpus.texts[:6]
    first = rr.scores("which bank", texts)
    assert calls == [6] and rr.scored == 6
    assert rr.scores("which bank", texts) == first and calls == [6]          # all from cache
    again = Reranker(scorer, tmp_path / "rerank.sqlite")                       # new process, same file
    assert again.scores("which bank", texts[2:]) == first[2:] and calls == [6]
    again.scores("another question", texts[:1])
    assert calls == [6, 1]


def test_dense_rerank_puts_stub_favourite_first(world):
    res = build_method("dense_rerank", world["shared"]).retrieve("HDFC Bank Ltd. holding of the Nifty Bank ETF", 5)
    assert "ICICI" in res.children[0].chunk.text                                # the stub's bonus word


# --------------------------------------------------------------------------- settings

def test_settings_validation(world):
    s = world["s"]
    bench = BenchmarkSettings.from_settings(s)
    with pytest.raises(ConfigError, match="not declared"):
        bench.method_options("best_combo")
    with pytest.raises(ConfigError, match="unknown keys"):
        bench.method_options("mmr", {"lamda": 0.3})
    with pytest.raises(ConfigError, match="unknown retrieval method"):
        bench.method_options("hyde")
    raw = {**s.retrieval_benchmark, "methods": {**s.retrieval_benchmark["methods"], "bm25": {"k1": 1.2}}}
    with pytest.raises(ConfigError, match="missing keys"):
        BenchmarkSettings(raw)
    raw = {**s.retrieval_benchmark, "grids": {"mmr": {"lambda": []}}}
    with pytest.raises(ConfigError, match="grids"):
        BenchmarkSettings(raw)
    assert bench.candidate_k == 20 and bench.reranker["model"] == "BAAI/bge-reranker-base"


def test_combo_rejects_unknown_ranker(world):
    with pytest.raises(ValueError, match="ranker"):
        build_method("best_combo", world["shared"], {"filter": True, "ranker": "scheme_filter"})


def test_chunking_fingerprint_ignores_benchmark_block(tmp_path):
    from src.eval.runner import setup_fingerprint

    s = load_settings(env_file=NO_ENV, environ={})
    q = Path("src/eval/questions.yaml")
    other = replace(s, retrieval_benchmark={"anything": 1})
    assert setup_fingerprint(s, q) == setup_fingerprint(other, q)


# --------------------------------------------------------------------------- pipeline hook

def test_pipeline_default_is_dense_and_method_is_swapped_for_parents(world):
    s = world["s"]
    pipe = RagPipeline(s, retriever=world["retriever"], llm=LLM.from_settings(s), row_names={})
    q = "What % of AUM does the Flexi Cap Fund hold in Infosys Ltd.?"
    default = pipe.retrieve(q, "hierarchical")
    via_m1 = pipe.retrieve(q, "hierarchical", method=build_method("dense", world["shared"]))
    assert [c.chunk.id for c in via_m1.chunks] == [c.chunk.id for c in default.chunks]
    assert same_up_to_ties(via_m1.children, default.children)
    assert default.method is None and via_m1.method == "dense"

    f = pipe.retrieve("Which holds more HDFC Bank Ltd.: the Nifty Bank ETF or the Flexi Cap Fund?", "hierarchical",
                      method=build_method("scheme_filter", world["shared"]))
    assert [p.chunk.id for p in f.chunks] == [f"hierarchical:{DATE}:SYNBANKE:p0", f"hierarchical:{DATE}:SYNFLEXI:p0"]
    assert f.debug["schemes_found"] == ["SYNBANKE", "SYNFLEXI"]

    ans = pipe.answer(q, "hierarchical", method=build_method("bm25", world["shared"]))
    assert ans.retrieval.method == "bm25" and len(ans.retrieval.children) == s.retrieval.top_k

    with pytest.raises(ValueError, match="hierarchical"):
        pipe.retrieve(q, "row_wise", method=build_method("dense", world["shared"]))
    with pytest.raises(ValueError, match="filter"):
        pipe.retrieve(q, "hierarchical", scheme_code="SYNFLEXI", method=build_method("dense", world["shared"]))
