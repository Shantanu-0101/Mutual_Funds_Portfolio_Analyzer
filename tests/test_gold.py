"""Gold functions on a tiny hand-built holdings table, answers worked out by hand (task 5.1)."""

import pandas as pd
import pytest

from src.eval import gold
from src.eval.gold import GoldError, compute, normalise_rating, rating_matches, split_rating
from src.eval.questions import QUESTIONS_FILE, QuestionError, TARGET_MIX, load_questions, mix

F = "30092026_TEST.xls"
EQ, DEBT, MM, OTH = "Equity & Equity Related", "Debt Instruments", "Money Market Instruments", "Others"
LISTED, GSEC = "a) Listed", "Government Securities"


def row(code, n, inst, isin, ind, value, pct, section=EQ, sub=LISTED, date="2026-09-30", flag=None):
    return dict(scheme_code=code, as_of_date=date, section=section, subsection=sub, instrument=inst, isin=isin,
                industry_or_rating=ind, market_value_lakhs=value, pct_nav=pct, pct_nav_flag=flag,
                source_file=F, source_sheet=code, source_row=n)


@pytest.fixture(scope="module")
def df():
    rows = [
        # equity scheme A
        row("A", 8, "ICICI Bank Ltd.", "INE090A01021", "Banks", 500.0, 5.0),
        row("A", 9, "HDFC Bank Ltd.", "INE040A01034", "Banks", 400.0, 4.0),
        row("A", 10, "Infosys Ltd.", "INE009A01021", "IT - Software", 300.0, 3.0),
        row("A", 11, "Tiny Co Ltd.", "INE000X01011", "Banks", 0.5, 0.004, sub="b) Unlisted", flag="lt_0.01"),
        row("A", 13, "TREPS", None, None, 50.0, 0.5, section=OTH, sub="TREPS"),
        row("A", 8, "ICICI Bank Ltd.", "INE090A01021", "Banks", 450.0, 4.5, date="2026-08-31"),  # other month
        # equity scheme B
        row("B", 8, "Infosys Ltd.", "INE009A01021", "IT - Software", 200.0, 6.0),
        row("B", 9, "ICICI Bank Ltd.", "INE090A01021", "Banks", 100.0, 3.0),
        row("B", 10, "Unlisted Startup", None, "Retailing", 10.0, 0.3),
        row("B", 11, "Reliance Industries Ltd.", "INE002A01018", "Petroleum Products", 50.0, 1.5),
        # debt scheme D
        row("D", 8, "7.1% Bond X **", "INE111A07001", "CRISIL AAA", 100.0, 10.0, section=DEBT),
        row("D", 9, "7.2% Bond Y", "INE222A07002", "[ICRA]AAA", 50.0, 5.0, section=DEBT),
        row("D", 10, "Securitised Z", "INE333A15003", "CRISIL AAA(SO)", 30.0, 3.0, section=DEBT, sub="Securitised"),
        row("D", 11, "8% Bond W", "INE444A07004", "CARE AA-", 20.0, 2.0, section=DEBT),
        row("D", 12, "Government of India (2033)", "IN0020230001", "Sovereign", 60.0, 6.0, section=DEBT, sub=GSEC),
        row("D", 13, "State Govt (2030)", "IN1920230002", "Sovereign", 40.0, 4.0, section=DEBT, sub=GSEC),
        row("D", 14, "CD Bank Q", "INE555A16005", "CARE A1+", 10.0, 1.0, section=MM, sub="Certificate of Deposits"),
        row("D", 15, "InvIT P", "INE666A23006", "Power", 15.0, 1.5, section=OTH, sub="InvIT"),
    ]
    return pd.DataFrame(rows)


def keys(sheet, *rows):
    return [(F, sheet, r) for r in rows]


# --------------------------------------------------------------------------- ratings (FR-5.3)

@pytest.mark.parametrize("raw, norm", [("[ICRA]AAA", "ICRA AAA"), ("ICRA  AAA", "ICRA AAA"), ("crisil aaa", "CRISIL AAA"),
                                       ("[ ICRA ] AA+", "ICRA AA+"), (None, ""), (float("nan"), "")])
def test_normalise_rating(raw, norm):
    assert normalise_rating(raw) == norm


def test_split_and_match_rating():
    assert split_rating("CRISIL AAA(SO)") == ("CRISIL", "AAA(SO)")
    assert split_rating("Sovereign") == (None, "SOVEREIGN")
    assert rating_matches("[ICRA]AAA", "ICRA AAA") and rating_matches("[ICRA]AAA", "AAA")
    assert not rating_matches("CRISIL AAA(SO)", "AAA")
    assert not rating_matches("CRISIL AAA", "ICRA AAA")
    assert not rating_matches("CRISIL AA+", "AA")
    assert rating_matches("Sovereign", "sovereign")
    assert not rating_matches(None, "AAA")


# --------------------------------------------------------------------------- functions

def test_holding_pct_and_value_by_isin_and_name(df):
    g = gold.holding_pct(df, "A", "2026-09-30", isin="INE090A01021")
    assert g.value == pytest.approx(5.0) and g.rows == keys("A", 8)          # other month ignored
    assert gold.holding_pct(df, "A", "2026-09-30", instrument="icici  bank ltd.").value == pytest.approx(5.0)
    assert gold.holding_value(df, "A", "2026-09-30", isin="INE009A01021").value == pytest.approx(300.0)


def test_holding_not_found_or_no_scheme_raises(df):
    with pytest.raises(GoldError):
        gold.holding_pct(df, "A", "2026-09-30", instrument="Nothing Ltd.")
    with pytest.raises(GoldError):
        gold.holding_pct(df, "Z", "2026-09-30", isin="INE090A01021")
    with pytest.raises(GoldError):
        gold.holding_pct(df, "A", "2026-09-30")


def test_industry_total_includes_flagged_row(df):
    g = gold.industry_total(df, "A", "2026-09-30", "Banks")
    assert g.value == pytest.approx(9.004) and g.rows == keys("A", 8, 9, 11)


def test_industry_total_equity_section_only(df):
    with pytest.raises(GoldError):            # InvIT "Power" sits in Others, not equity
        gold.industry_total(df, "D", "2026-09-30", "Power")


def test_top_n_share(df):
    g = gold.top_n_share(df, "A", "2026-09-30", 2)
    assert g.value == pytest.approx(9.0) and g.rows == keys("A", 8, 9)
    with pytest.raises(GoldError):
        gold.top_n_share(df, "A", "2026-09-30", 10)


def test_holding_count_and_section_total(df):
    assert gold.holding_count(df, "A", "2026-09-30").value == 4             # TREPS (Others) not counted
    assert gold.holding_count(df, "A", "2026-09-30", subsection=LISTED).value == 3
    g = gold.section_total(df, "D", "2026-09-30", DEBT, GSEC)
    assert g.value == pytest.approx(10.0) and g.rows == keys("D", 12, 13)


def test_rating_share_any_agency_excludes_so(df):
    g = gold.rating_share(df, "D", "2026-09-30", "AAA")
    assert g.value == pytest.approx(15.0) and g.rows == keys("D", 8, 9)
    assert gold.rating_share(df, "D", "2026-09-30", "ICRA AAA").value == pytest.approx(5.0)
    assert gold.rating_share(df, "D", "2026-09-30", "AAA(SO)").value == pytest.approx(3.0)
    assert gold.rating_share(df, "D", "2026-09-30", "Sovereign").value == pytest.approx(10.0)
    assert gold.rating_share(df, "D", "2026-09-30", "AA").value == 0.0       # AA- is not AA


def test_instruments_by_rating(df):
    g = gold.instruments_by_rating(df, "D", "2026-09-30", "CARE AA-")
    assert g.value == ["8% Bond W"] and g.rows == keys("D", 11)
    with pytest.raises(GoldError):
        gold.instruments_by_rating(df, "D", "2026-09-30", "IND AAA")


def test_overlap_count(df):
    g = gold.overlap_count(df, ["A", "B"], "2026-09-30")
    assert g.value == 2                                                      # ICICI + Infosys
    assert sorted(g.rows) == sorted(keys("A", 8, 10) + keys("B", 8, 9))
    with pytest.raises(GoldError):
        gold.overlap_count(df, ["A"], "2026-09-30")


def test_which_holds_more_pct_vs_value(df):
    by_pct = gold.which_holds_more(df, ["A", "B"], "2026-09-30", isin="INE009A01021", measure="pct")
    by_val = gold.which_holds_more(df, ["A", "B"], "2026-09-30", isin="INE009A01021", measure="lakhs")
    assert by_pct.value == "B" and by_val.value == "A"
    assert sorted(by_pct.rows) == sorted(keys("A", 10) + keys("B", 8))
    # a scheme without the holding counts as 0
    assert gold.which_holds_more(df, ["A", "B"], "2026-09-30", isin="INE002A01018").value == "B"


def test_which_holds_more_errors(df):
    with pytest.raises(GoldError):
        gold.which_holds_more(df, ["A", "B"], "2026-09-30", isin="NOPE")
    with pytest.raises(GoldError):
        gold.which_holds_more(df, ["A", "B"], "2026-09-30", isin="INE009A01021", measure="qty")


def test_not_in_data_and_compute(df):
    assert compute(df, "not_in_data", {}).value is None
    with pytest.raises(GoldError):
        compute(df, "no_such_fn", {})
    with pytest.raises(GoldError):
        compute(df, "holding_pct", {"scheme": "A"})


# --------------------------------------------------------------------------- questions.yaml

def test_questions_file_loads_with_target_mix():
    qs = load_questions(QUESTIONS_FILE, eval_months=("2026-09-30",))
    assert len(qs) == 28 and mix(qs) == TARGET_MIX


def test_questions_reject_bad_entries(tmp_path):
    bad = tmp_path / "q.yaml"
    bad.write_text("- {id: Q1, type: lookup, text: x, answer_kind: number, gold_fn: holding_pct, params: {}}\n")
    with pytest.raises(QuestionError, match="unit"):
        load_questions(bad)
    bad.write_text("- {id: Q1, type: lookup, text: x, answer_kind: number, unit: pct, gold_fn: holding_pct,"
                   " params: {as_of_date: '2026-07-31'}}\n")
    with pytest.raises(QuestionError, match="eval_months"):
        load_questions(bad, eval_months=("2026-09-30",))
    bad.write_text("- {id: Q1, type: lookup, text: x, answer_kind: number, unit: pct, gold_fn: nope, params: {}}\n")
    with pytest.raises(QuestionError, match="gold_fn"):
        load_questions(bad)
