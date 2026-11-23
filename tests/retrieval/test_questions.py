"""Phase R1: question generator, question sets, gold sections (SPEC_RETRIEVAL §6.1, §10).

Runs on a synthetic holdings table (``synthetic_*``), never on the real files, except the last test,
which is skipped when ``holdings.parquet`` is missing.
"""

from __future__ import annotations

import json
import random
from collections import Counter

import pandas as pd
import pytest
import yaml

from src.eval.gold import EQUITY_SECTION, compute
from src.eval.metrics import choice_pick
from src.eval.questions import Question, QuestionError, load_questions, mix
from src.retrieval.questions import sets as sets_mod
from src.retrieval.questions.generate import (
    SHORT_SHARE, clean_instrument, generate, scaled_mix, short_upper, title_name, to_yaml, write_sets)
from src.retrieval.questions.sets import gold_sections, load_set, row_parent_map, set_sha256

MONTH = "2026-09-30"
FILE = "synthetic_disclosure.xls"
SIZES = {"dev": 16, "test_new": 24}
PREFIX = "ADITYA BIRLA SUN LIFE "
INDUSTRIES = ["Banks", "IT - Software", "Finance", "Power", "Automobiles", "Retailing"]
DEBT_RATINGS = ["CRISIL AAA", "ICRA AAA", "ICRA AA+", "CARE AA", "IND AA-", "[ICRA]AAA"]
WORDS = ["ALPHA", "BRAVO", "CEDAR", "DELTA", "EMBER", "FALCON", "GROVE", "HARBOR", "IVORY", "JUNIPER",
         "KESTREL", "LOTUS", "MAPLE", "NOVA", "OPAL", "PRISM", "QUARTZ", "RIVER", "SUMMIT", "TIDE",
         "UMBER", "VALLEY", "WILLOW", "XENON", "YARROW", "ZEPHYR", "AMBER", "BIRCH", "CORAL", "DUNE"]


# --------------------------------------------------------------------------- synthetic data

def _synthetic_holdings() -> pd.DataFrame:
    rng = random.Random(7)
    eq_pool = [(f"INE{n:03d}A01011", f"Equity Company {n} Ltd.", INDUSTRIES[n % len(INDUSTRIES)]) for n in range(40)]
    bonds = [(f"INE{n:03d}B07011", f"7.{n:02d}% Bond Issuer {n} Ltd. (01/01/2030) **", DEBT_RATINGS[n % 6])
             for n in range(60)]
    gsecs = [(f"IN00{n:02d}GS0011", f"Government of India (0{n % 9 + 1}/06/2031)") for n in range(10)]
    cps = [(f"INE{n:03d}C14011", f"Issuer {n} Ltd. (15/12/2026) ** #", "CRISIL A1+") for n in range(20)]
    kinds = ["equity"] * 12 + ["debt"] * 8 + ["hybrid"] * 5 + ["other"] * 5
    rows = []
    for i, (kind, word) in enumerate(zip(kinds, WORDS)):
        code, name = f"SYN{i:02d}", f"{PREFIX}{word} {kind.upper()} FUND"
        if i == 3:
            name += f" (FORMERLY KNOWN AS {PREFIX}OLD {word} FUND)"
        r = 5

        def add(section, subsection, inst, isin, ind, pct):
            nonlocal r
            r += 1
            rows.append(dict(scheme_code=code, scheme=name, as_of_date=MONTH, section=section, subsection=subsection,
                             instrument=inst, isin=isin, isin_valid=bool(isin), industry_or_rating=ind,
                             market_value_lakhs=round(pct * 1000, 2), pct_nav=pct, pct_nav_flag="",
                             name_suspect=False, source_file=FILE, source_sheet=code, source_row=r))

        if kind in ("equity", "hybrid"):
            for isin, inst, ind in rng.sample(eq_pool, 20 if kind == "equity" else 12):
                add(EQUITY_SECTION, "a) Listed/awaiting listing on Stock Exchanges", inst, isin, ind,
                    round(rng.uniform(0.2, 6), 4))
        if kind in ("debt", "hybrid"):
            for isin, inst, rating in rng.sample(bonds, 10 if kind == "debt" else 6):
                add("Debt Instruments", "a) Listed/awaiting listing on the stock exchanges", inst, isin, rating,
                    round(rng.uniform(0.5, 5), 4))
            for isin, inst in rng.sample(gsecs, 3):
                add("Debt Instruments", "Government Securities", inst, isin, "Sovereign", round(rng.uniform(1, 8), 4))
            for isin, inst, rating in rng.sample(cps, 3):
                add("Money Market Instruments", "Commercial Paper", inst, isin, rating, round(rng.uniform(0.5, 3), 4))
        if kind == "other":
            add("Others", "Mutual Fund Units", f"Some Other AMC Fund {i} - Direct - Growth", f"INF{i:03d}K01011", "",
                round(rng.uniform(40, 90), 4))
            add("Others", "Mutual Fund Units", f"{PREFIX}{word} OTHER FUND - Growth", f"INF{i:03d}K01099", "",
                round(rng.uniform(5, 20), 4))
        add("Others", "TREPS / Reverse Repo Investments", "TREPS", "", "", 1.0)
    return pd.DataFrame(rows)


def _parents(h: pd.DataFrame) -> pd.DataFrame:
    out = []
    for code, g in h.groupby("scheme_code", sort=True):
        for n, (section, s) in enumerate(g.groupby("section", sort=False)):
            keys = [[r.source_file, r.source_sheet, int(r.source_row)] for r in s.itertuples()]
            out.append({"id": f"hierarchical:{MONTH}:{code}:p{n}", "scheme_code": code, "section": section,
                        "as_of_date": MONTH, "source_rows": json.dumps(keys)})
    return pd.DataFrame(out)


def _originals(h: pd.DataFrame) -> list[Question]:
    r = h[(h["scheme_code"] == "SYN00") & (h["section"] == EQUITY_SECTION)].iloc[0]
    return [
        Question("Q01", "lookup", f"What % of AUM does SYN00 hold in {r['instrument']} as on 30 Sep 2026?",
                 "number", "holding_pct", {"scheme_code": "SYN00", "as_of_date": MONTH, "isin": r["isin"]}, unit="pct"),
        Question("Q02", "aggregation", "How many holdings in SYN12 as on 30 Sep 2026?", "number", "holding_count",
                 {"scheme_code": "SYN12", "as_of_date": MONTH}, unit="count"),
        Question("Q03", "unanswerable", "Expense ratio of SYN00 as on 30 Sep 2026?", "not_in_data", "not_in_data", {}),
    ]


@pytest.fixture(scope="module")
def synthetic_holdings() -> pd.DataFrame:
    return _synthetic_holdings()


@pytest.fixture(scope="module")
def synthetic_generated(synthetic_holdings):
    h = synthetic_holdings
    return generate(h, _parents(h), _originals(h), MONTH, seed=42, sizes=SIZES)


def _qs(raw: list[dict]) -> list[Question]:
    return [Question(**q) for q in raw]


# --------------------------------------------------------------------------- generator

def test_same_seed_gives_byte_identical_files(synthetic_holdings, synthetic_generated, tmp_path):
    h = synthetic_holdings
    again = generate(h, _parents(h), _originals(h), MONTH, seed=42, sizes=SIZES)
    for name in SIZES:
        assert to_yaml(again.sets[name], name, 42, MONTH) == to_yaml(synthetic_generated.sets[name], name, 42, MONTH)
    a = write_sets(synthetic_generated, 42, MONTH, {"dev": tmp_path / "a_dev.yaml", "test_new": tmp_path / "a_t.yaml"})
    b = write_sets(again, 42, MONTH, {"dev": tmp_path / "b_dev.yaml", "test_new": tmp_path / "b_t.yaml"})
    assert a["dev"].read_bytes() == b["dev"].read_bytes()
    assert a["test_new"].read_bytes() == b["test_new"].read_bytes()
    other = generate(h, _parents(h), _originals(h), MONTH, seed=1, sizes=SIZES)
    assert other.sets["dev"] != synthetic_generated.sets["dev"]


def test_dev_and_test_share_no_scheme(synthetic_holdings, synthetic_generated):
    gen = synthetic_generated
    dev = {s for q in gen.sets["dev"] for s in q["tags"]["schemes"]}
    test = {s for q in gen.sets["test_new"] for s in q["tags"]["schemes"]}
    assert dev and test and not dev & test
    assert {"SYN00", "SYN12"} <= {c for c, side in gen.split.items() if side == "test"}   # originals: test-only
    assert all(gen.split[s] == "dev" for s in dev)
    # every category of scheme has members on both sides
    for cat in ("equity", "debt", "hybrid", "other"):
        sides = {gen.split[c] for c, k in gen.categories.items() if k == cat}
        assert sides == {"dev", "test"}, cat


def test_dev_and_test_share_no_instrument(synthetic_holdings, synthetic_generated):
    def isins(qs):
        return {q["params"]["isin"] for q in qs if q["params"].get("isin")}

    dev, test = isins(synthetic_generated.sets["dev"]), isins(synthetic_generated.sets["test_new"])
    originals = isins([{"params": q.params} for q in _originals(synthetic_holdings)])
    assert dev and test
    assert not dev & test and not dev & originals and not test & originals


def test_every_question_names_its_month(synthetic_generated):
    for qs in synthetic_generated.sets.values():
        for q in qs:
            assert "30 Sep 2026" in q["text"] or "30 September 2026" in q["text"], q["text"]


def test_gold_is_computed_with_rows_and_sections(synthetic_holdings, synthetic_generated):
    h = synthetic_holdings
    rp = row_parent_map(_parents(h))
    for name, raw in synthetic_generated.sets.items():
        for q in _qs(raw):
            g = compute(h, q.gold_fn, q.params)          # raises if the params do not match the data
            if q.answerable:
                assert g.rows, q.id
                assert q.tags["gold_sections"] and q.tags["gold_sections"] == gold_sections(q, h, rp), q.id
                schemes = {p.split(":")[2] for p in q.tags["gold_sections"]}
                assert schemes <= set(q.tags["schemes"]), q.id
            else:
                assert q.tags["gold_sections"] == [] and g.value is None


def test_no_gold_value_is_written(synthetic_generated):
    allowed = {"id", "type", "text", "answer_kind", "unit", "options", "gold_fn", "params", "tags"}
    for qs in synthetic_generated.sets.values():
        for q in qs:
            assert set(q) <= allowed
            assert set(q["tags"]) == {"template", "phrasing", "short_name", "schemes", "gold_sections"}


def test_type_mix_follows_spec(synthetic_generated):
    assert scaled_mix(40) == {"lookup": 10, "aggregation": 10, "debt": 7, "cross_scheme": 7, "unanswerable": 6}
    assert scaled_mix(60) == {"lookup": 15, "aggregation": 15, "debt": 11, "cross_scheme": 11, "unanswerable": 8}
    for name, size in SIZES.items():
        assert mix(_qs(synthetic_generated.sets[name])) == scaled_mix(size)


def test_about_a_third_use_short_names(synthetic_generated):
    for name, raw in synthetic_generated.sets.items():
        short = [q for q in raw if q["tags"]["short_name"]]
        assert len(short) == round(len(raw) * SHORT_SHARE)
        for q in raw:
            assert ("Aditya Birla Sun Life" in q["text"]) != q["tags"]["short_name"], q["text"]


def test_ids_and_choice_options(synthetic_generated):
    assert [q["id"] for q in synthetic_generated.sets["dev"]][:2] == ["D001", "D002"]
    assert [q["id"] for q in synthetic_generated.sets["test_new"]][-1] == f"T{SIZES['test_new']:03d}"
    choices = [q for qs in synthetic_generated.sets.values() for q in qs if q["answer_kind"] == "choice"]
    assert choices
    for q in choices:
        assert list(q["options"]) == q["params"]["schemes"]
        for code, (alias,) in q["options"].items():
            assert choice_pick({"answer": f"The {alias} holds more."}, q["options"]) == code


def test_instrument_slot_is_never_an_own_amc_fund(synthetic_generated):
    for qs in synthetic_generated.sets.values():
        for q in qs:
            if q["params"].get("isin"):
                assert not q["params"]["isin"].endswith("K01099")


def test_written_files_load_through_the_question_loader(synthetic_generated, tmp_path):
    files = write_sets(synthetic_generated, 42, MONTH, {"dev": tmp_path / "dev.yaml", "test_new": tmp_path / "t.yaml"})
    for name, path in files.items():
        qs = load_questions(path, (MONTH,))
        assert len(qs) == SIZES[name] and all(q.tags for q in qs)
    assert yaml.safe_load(files["dev"].read_text(encoding="utf-8"))[0]["id"] == "D001"


# --------------------------------------------------------------------------- names

@pytest.mark.parametrize("upper, title", [
    ("LARGE & MID CAP FUND", "Large & Mid Cap Fund"),
    ("RETIREMENT FUND - THE 30S PLAN", "Retirement Fund - The 30s Plan"),
    ("CRISIL-IBX AAA NBFC-HFC INDEX - SEP 2026 FUND", "CRISIL-IBX AAA NBFC-HFC Index - Sep 2026 Fund"),
    ("ELSS TAX SAVER FUND", "ELSS Tax Saver Fund"),
    ("MEDIUM TO LONG TERM FUND", "Medium to Long Term Fund"),
    ("TRANSPORTATION AND LOGISTICS FUND", "Transportation and Logistics Fund"),
    ("FIXED TERM PLAN - SERIES TQ (1879 DAYS)", "Fixed Term Plan - Series TQ (1879 Days)"),
])
def test_title_name(upper, title):
    assert title_name(upper) == title


def test_short_name_drops_prefix_and_former_name():
    assert short_upper("ADITYA BIRLA SUN LIFE GILT FUND (FORMERLY KNOWN AS ADITYA BIRLA SUN LIFE GOVERNMENT "
                       "SECURITIES FUND)") == "GILT FUND"
    assert short_upper("ADITYA BIRLA SUN LIFE FLEXI CAP FUND") == "FLEXI CAP FUND"


def test_clean_instrument_drops_footnote_markers():
    assert clean_instrument("7.30% Bharti Telecom Ltd. (01/12/2027) **") == "7.30% Bharti Telecom Ltd. (01/12/2027)"
    assert clean_instrument("Issuer 1 Ltd. (15/12/2026) ** #") == "Issuer 1 Ltd. (15/12/2026)"
    assert clean_instrument("ICICI Bank Ltd.") == "ICICI Bank Ltd."


# --------------------------------------------------------------------------- sets and gold sections

def test_gold_sections_map_rows_to_parents(synthetic_holdings):
    h = synthetic_holdings
    rp = row_parent_map(_parents(h))
    assert len(rp) == len(h)
    q = Question("X", "aggregation", "?", "number", "holding_count", {"scheme_code": "SYN20", "as_of_date": MONTH},
                 unit="count")
    assert gold_sections(q, h, rp) == [f"hierarchical:{MONTH}:SYN20:p0"]
    na = Question("Y", "unanswerable", "?", "not_in_data", "not_in_data", {})
    assert gold_sections(na, h, rp) == []


def test_load_set_and_combined_hash(synthetic_generated, tmp_path, monkeypatch):
    files = write_sets(synthetic_generated, 42, MONTH, {"dev": tmp_path / "dev.yaml", "test_new": tmp_path / "t.yaml"})
    orig = tmp_path / "orig.yaml"
    orig.write_text(yaml.safe_dump([{"id": "Q01", "type": "unanswerable", "text": "x 30 Sep 2026",
                                     "answer_kind": "not_in_data", "gold_fn": "not_in_data", "params": {}}]),
                    encoding="utf-8")
    monkeypatch.setitem(sets_mod.SET_FILES, "test", (orig, files["test_new"]))
    monkeypatch.setitem(sets_mod.SET_FILES, "dev", (files["dev"],))
    test = load_set("test")
    assert [q.id for q in test][:2] == ["Q01", "T001"] and len(test) == 1 + SIZES["test_new"]
    before = set_sha256("test")
    assert before != set_sha256("dev")
    orig.write_text(orig.read_text(encoding="utf-8").replace("x 30", "y 30"), encoding="utf-8")
    assert set_sha256("test") != before                      # any file of the set changes the hash
    monkeypatch.setitem(sets_mod.SET_FILES, "test", (files["test_new"], files["test_new"]))
    with pytest.raises(QuestionError, match="duplicate"):
        load_set("test")
    with pytest.raises(ValueError, match="unknown question set"):
        load_set("train")


def test_original_questions_load_unchanged():
    qs = load_questions()
    assert len(qs) == 28 and all(q.tags == {} for q in qs)


# --------------------------------------------------------------------------- real data (optional)

def test_committed_sets_match_the_generator():
    """dev.yaml / test_new.yaml in git are exactly what the generator writes from the real data."""
    from src.config import get_settings

    s = get_settings()
    hp, pp = s.paths.processed / "holdings.parquet", s.paths.processed / "parents_hierarchical.parquet"
    if not (hp.is_file() and pp.is_file()):
        pytest.skip("holdings.parquet / parents_hierarchical.parquet not built")
    month = s.data.eval_months[0]
    parents = pd.read_parquet(pp)
    gen = generate(pd.read_parquet(hp), parents[parents["as_of_date"].astype(str) == month],
                   load_questions(eval_months=s.data.eval_months), month, s.eval.seed)
    assert to_yaml(gen.sets["dev"], "dev", s.eval.seed, month) == sets_mod.DEV_FILE.read_text(encoding="utf-8")
    assert to_yaml(gen.sets["test_new"], "test_new", s.eval.seed, month) == \
        sets_mod.TEST_NEW_FILE.read_text(encoding="utf-8")
    test = load_set("test", s.data.eval_months)
    assert len(test) == 88 and Counter(q.id[0] for q in test) == {"Q": 28, "T": 60}


def test_set_hash_ignores_line_endings(tmp_path, monkeypatch):
    lf, crlf = tmp_path / "lf" / "dev.yaml", tmp_path / "crlf" / "dev.yaml"
    for p, text in ((lf, b"- id: D001\n  text: x\n"), (crlf, b"- id: D001\r\n  text: x\r\n")):
        p.parent.mkdir()
        p.write_bytes(text)
    monkeypatch.setitem(sets_mod.SET_FILES, "dev", (lf,))
    a = set_sha256("dev")
    monkeypatch.setitem(sets_mod.SET_FILES, "dev", (crlf,))
    assert set_sha256("dev") == a
