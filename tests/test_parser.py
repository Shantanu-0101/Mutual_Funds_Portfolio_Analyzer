"""Parser tests on synthetic files in the real ABSL layout (spec §10, plan Phase 1).

Row numbers asserted here are the 1-based Excel rows marked in
tests/fixtures/make_synthetic.py.
"""

from datetime import date

import pandas as pd
import pytest

from src.parsing.mapping import asset_class_for
from src.parsing.pipeline import parse_files, parse_file, write_tables
from src.parsing.reader import RawSheet, read_workbook
from src.parsing.report import build_report
from src.parsing.sheet_parser import (
    FLAG_LT_001,
    FLAG_RECOMPUTED,
    MergedCellsInBlockError,
    ParseError,
    parse_sheet,
    pct_rule,
)
from src.parsing.validate import check_sheet
from src.parsing.values import isin_valid, parse_as_on
from tests.fixtures import make_synthetic as syn


def _sheet(files, key, name):
    wb = read_workbook(files[key])
    raw = next(s for s in wb.sheets if s.name == name)
    return parse_sheet(raw)


def _by_row(res):
    return {h["source_row"]: h for h in res.holdings}


@pytest.fixture(scope="module")
def eq(synthetic_files):
    return _sheet(synthetic_files, "equity", "SYNEQ")


@pytest.fixture(scope="module")
def debt(synthetic_files):
    return _sheet(synthetic_files, "debt_esg", "SYNDEBT")


@pytest.fixture(scope="module")
def nogt(synthetic_files):
    return _sheet(synthetic_files, "debt_esg", "SYNNOGT")


@pytest.fixture(scope="module")
def fof(synthetic_files):
    return _sheet(synthetic_files, "debt_esg", "SYNFOF")


# ------------------------------------------------------------------ title and header


def test_title_block(eq):
    assert eq.scheme_code == "SYNEQ"
    assert eq.scheme == "SYNTHETIC FLEXI CAP FUND"
    assert eq.description.startswith("An open ended dynamic equity scheme")
    assert eq.as_of_date == date(2026, 9, 30)
    assert eq.header_row == 4


def test_header_found_by_text_in_any_column_order():
    # Columns shuffled and shifted: mapping must follow the header text, not the position (FR-1.2).
    rows = [
        ["X1", "", "SOME FUND"], ["", "", "desc"], ["", "", "Portfolio Statement as on August 31, 2026"],
        ["% to AUM", "Name of the Instrument / Issuer", "Market value (Rs. in Lakhs)", "ISIN",
         "Quantity", "Industry^ / Rating"],
        ["", "Equity & Equity Related"],
        ["", "a) Listed/awaiting listing on Stock Exchanges"],
        [1.0, "Only Stock Ltd.", 50.0, "INE000A01010", 5.0, "Banks"],
        [1.0, "GRAND TOTAL (AUM)", 50.0],
    ]
    res = parse_sheet(RawSheet(file="mem.xls", name="X1", rows=rows))
    (h,) = res.holdings
    assert (h["instrument"], h["market_value_lakhs"], h["pct_nav"], h["quantity"], h["industry_or_rating"]) == \
        ("Only Stock Ltd.", 50.0, 100.0, 5.0, "Banks")
    assert h["source_row"] == 7


def test_missing_required_column_raises():
    rows = [["X"], [""], ["Portfolio Statement as on August 31, 2026"],
            ["Name of the Instrument / Issuer", "ISIN", "Market value"]]
    with pytest.raises(ParseError, match="lacks columns"):
        parse_sheet(RawSheet(file="mem.xls", name="X", rows=rows))


def test_sheet_without_header_is_not_a_portfolio(synthetic_files):
    fr = parse_file(synthetic_files["equity"])
    assert fr.not_portfolio == ["Disclaimer"]
    assert fr.index_without_sheet == ["SYNGONE"]


def test_esg_columns_ignored_and_noted(debt):
    assert len(debt.extra_columns) == 3
    assert any("ESG Score" in c for c in debt.extra_columns)
    assert any("unmapped header columns" in n for n in debt.notes)
    assert "ESG" not in " ".join(debt.holdings[0].keys())
    # Row 15 has a value only in the ESG column: ignored and listed, not a holding or an error.
    assert [u.row for u in debt.ignored_rows] == [15]
    assert 15 not in _by_row(debt)


# ------------------------------------------------------------------ sections and classes


def test_section_and_subsection_tracking(eq, debt):
    rows = _by_row(eq)
    assert (rows[8]["section"], rows[8]["subsection"]) == \
        ("Equity & Equity Related", "a) Listed/awaiting listing on Stock Exchanges")
    # A sub-heading standing alone after a Total keeps the current main heading.
    assert (rows[14]["section"], rows[14]["subsection"]) == ("Equity & Equity Related", "b) Unlisted")
    assert (rows[19]["section"], rows[19]["subsection"]) == ("Others", "TREPS / Reverse Repo Investments")
    # A new main heading clears the sub-heading.
    assert (rows[23]["section"], rows[23]["subsection"]) == ("Other Current Assets / (Liabilities)", None)
    d = _by_row(debt)
    assert (d[13]["section"], d[13]["subsection"]) == ("Debt Instruments", "Government Securities")
    assert (d[18]["section"], d[18]["subsection"]) == ("Money Market Instruments", "STRIPS")


def test_asset_classes(eq, debt):
    rows, d = _by_row(eq), _by_row(debt)
    assert rows[8]["asset_class"] == "equity"
    assert rows[19]["asset_class"] == "debt"          # TREPS (Q2)
    assert rows[23]["asset_class"] == "other"         # net receivable
    assert d[13]["asset_class"] == "debt" and d[18]["asset_class"] == "debt"
    assert all(h["asset_class_rule"] == "section" for h in eq.holdings + debt.holdings)


def test_no_main_heading_uses_sub_heading_mapping(fof):
    h = _by_row(fof)[7]
    assert h["section"] is None
    assert h["subsection"] == "International Mutual Fund Units"
    assert (h["asset_class"], h["asset_class_rule"]) == ("other", "sub_only")
    assert check_sheet(fof).status == "OK"


def test_mapping_is_case_insensitive_and_falls_back():
    assert asset_class_for("EQUITY & EQUITY RELATED", "A) Listed/Awaiting listing on stock exchanges") == \
        ("equity", "section")
    assert asset_class_for("Debt Instruments", "Some New Sub-heading") == ("debt", "main_fallback")
    assert asset_class_for(None, "Unknown heading") == (None, "none")


# ------------------------------------------------------------------ rows


def test_totals_not_in_holdings_but_in_totals(eq):
    assert sorted(_by_row(eq)) == [8, 9, 10, 14, 19, 23]
    assert [(t["kind"], t["source_row"]) for t in eq.totals] == \
        [("total", 11), ("total", 15), ("total", 20), ("total", 24), ("grand_total", 27)]
    assert eq.grand_total_row == 27 and eq.grand_total_lakhs == 1000.0


def test_rows_without_isin_are_holdings(eq):
    treps, nr = _by_row(eq)[19], _by_row(eq)[23]
    assert treps["instrument"] == "TREPS" and treps["isin"] is None and treps["market_value_lakhs"] == 80.0
    assert nr["isin"] is None and nr["isin_valid"] is False


def test_zero_value_holding_kept(eq):
    h = _by_row(eq)[14]
    assert h["market_value_lakhs"] == 0.0 and h["pct_nav"] == 0.0 and h["pct_nav_flag"] == FLAG_LT_001


def test_fraction_to_percent(eq, debt):
    assert _by_row(eq)[8]["pct_nav"] == pytest.approx(60.0)
    z = _by_row(debt)[9]
    assert z["ytm"] == pytest.approx(7.25) and z["ytc"] == pytest.approx(7.01)
    assert _by_row(debt)[8]["ytc"] is None


def test_dollar_cell_computed_from_value_and_flagged(eq):
    h = _by_row(eq)[10]
    assert h["pct_nav"] == pytest.approx(0.05)          # 0.5 / 1000 * 100
    assert h["pct_nav_flag"] == FLAG_LT_001
    assert h["pct_nav_file"] is None


def test_other_current_assets_recomputed(eq):
    h = _by_row(eq)[23]
    assert h["pct_nav"] == pytest.approx(1.95)          # 19.5 / 1000, not the file's 2.5
    assert h["pct_nav_file"] == pytest.approx(2.5)
    assert h["pct_nav_flag"] == FLAG_RECOMPUTED


def test_pct_rule_without_grand_total():
    assert pct_rule("Equity & Equity Related", 5.0, "$0.00%", None) == (0.0, FLAG_LT_001)
    assert pct_rule("Other Current Assets / (Liabilities)", 5.0, 0.01, None) == (1.0, None)


def test_unknown_row_reported(eq):
    assert [(u.row, u.reason) for u in eq.unknown_rows] == [(26, "text in value columns but no market value")]
    assert any("row 26 not classified" in e for e in check_sheet(eq).errors)


def test_tail_skipped_as_one_block(eq):
    assert eq.end_rule == "grand_total"
    assert eq.block_last_row == 27
    assert eq.tail_rows == (28, 33)
    assert eq.tail_first_text.startswith("^Industry classification")
    assert all(h["source_row"] < 27 for h in eq.holdings)   # row 32 has numbers but is in the tail


def test_notes_named_holding_does_not_end_the_block(debt):
    h = _by_row(debt)[18]
    assert h["instrument"] == "Notes:" and h["name_suspect"] is True
    assert h["isin_valid"] is True
    assert debt.grand_total_row == 27 and debt.end_rule == "grand_total"
    assert any("looks like a footnote marker" in w for w in check_sheet(debt).warnings)


def test_missing_grand_total_falls_back_to_first_footnote(nogt):
    assert nogt.grand_total_row is None
    assert nogt.end_rule == "footnote"
    assert nogt.block_last_row == 15
    assert nogt.tail_rows == (16, 17)
    rows = _by_row(nogt)
    assert rows[9]["pct_nav"] == 0.0 and rows[9]["pct_nav_flag"] == FLAG_LT_001   # FR-1.3
    assert rows[13]["pct_nav"] == pytest.approx(29.97) and rows[13]["pct_nav_flag"] is None
    ck = check_sheet(nogt)
    assert ck.status == "ERROR"
    assert any("no GRAND TOTAL" in e for e in ck.errors)


def test_exact_source_rows_and_row_key(eq):
    assert [h["source_row"] for h in eq.holdings] == [8, 9, 10, 14, 19, 23]
    assert all(h["source_file"] == "synthetic_equity.xls" and h["source_sheet"] == "SYNEQ" for h in eq.holdings)


def test_isin_validity():
    assert isin_valid(syn.isin("INE000A0101"))
    assert not isin_valid("IDIA00012345")
    assert not isin_valid("GSECREPO1039")
    good = syn.isin("INE000A0101")
    wrong_digit = good[:-1] + str((int(good[-1]) + 1) % 10)
    assert not isin_valid(wrong_digit)
    assert not isin_valid(None)


def test_as_on_date_parsing():
    assert parse_as_on("Portfolio Statement as on September 30, 2026") == date(2026, 9, 30)
    assert parse_as_on("Portfolio Statement as on Sept 30, 2026") is None


# ------------------------------------------------------------------ merged cells (FR-1.9, R9)


def test_merged_cells_outside_block_are_fine(eq):
    assert eq.merged_outside_block == 2


def test_merged_cell_inside_block_fails_loudly(synthetic_files):
    wb = read_workbook(synthetic_files["merged"])
    with pytest.raises(MergedCellsInBlockError, match="rows 8-8"):
        parse_sheet(wb.sheets[0])
    fr = parse_file(synthetic_files["merged"])
    assert fr.sheets == [] and fr.failed and fr.failed[0][0] == "SYNMERGE"


# ------------------------------------------------------------------ validation


def test_validation_clean_sheet(debt, fof):
    for res in (debt, fof):
        ck = check_sheet(res)
        assert ck.pct_sum == pytest.approx(100.0)
        assert ck.value_diff == pytest.approx(0.0)
        assert ck.total_value_mismatches == [] and ck.total_pct_mismatches == []
        assert ck.null_pct_rows == []


def test_validation_counts_every_total(eq):
    ck = check_sheet(eq)
    assert ck.totals_checked == 4
    assert ck.pct_sum == pytest.approx(100.0)


def test_validation_detects_total_mismatch_and_duplicate_isin():
    rows = [
        ["D1", "", "DUP FUND"], ["", "", "desc"], ["", "", "Portfolio Statement as on August 31, 2026"],
        ["", "", *syn.HEADER],
        ["", "", "Equity & Equity Related"],
        ["", "", "a) Listed/awaiting listing on Stock Exchanges"],
        ["", "", "A Ltd.", "INE000A01010", "Banks", 1.0, 50.0, 0.5],
        ["", "", "A Ltd. (second lot)", "INE000A01010", "Banks", 1.0, 40.0, 0.4],
        ["", "", "Total", "", "", "", 95.0, 0.9],         # rows sum to 90, Total says 95
        ["", "", "Other Current Assets / (Liabilities)"],
        ["", "", "Net Receivable / Payable", "", "", "", 10.0, 0.1],
        ["", "", "GRAND TOTAL (AUM)", "", "", "", 100.0, 1.0],
    ]
    ck = check_sheet(parse_sheet(RawSheet(file="mem.xls", name="D1", rows=rows)))
    assert ck.status == "ERROR"
    assert len(ck.total_value_mismatches) == 1
    assert ck.dup_isins == ["INE000A01010 in Equity & Equity Related"]


# ------------------------------------------------------------------ pipeline and report


def test_pipeline_writes_parquet_round_trip(synthetic_files, tmp_path):
    run = parse_files([synthetic_files["equity"], synthetic_files["debt_esg"]])
    write_tables(run, tmp_path)
    h = pd.read_parquet(tmp_path / "holdings.parquet")
    assert len(h) == 6 + 6 + 3 + 3
    assert not h.duplicated(["source_file", "source_sheet", "source_row"]).any()   # FR-1.1 row key
    assert h["pct_nav"].notna().all()
    assert set(h["as_of_date"].astype(str)) == {"2026-07-31", "2026-09-30", "2026-10-31"}
    for col in ("amc", "scheme_code", "scheme", "as_of_date", "section", "subsection", "asset_class",
                "instrument", "isin", "industry_or_rating", "quantity", "market_value_lakhs", "pct_nav",
                "pct_nav_flag", "ytm", "ytc", "source_file", "source_sheet", "source_row"):
        assert col in h.columns
    t = pd.read_parquet(tmp_path / "totals.parquet")
    assert set(t["kind"]) == {"total", "grand_total"}
    s = pd.read_parquet(tmp_path / "schemes.parquet")
    assert sorted(s["scheme_code"]) == ["SYNDEBT", "SYNEQ", "SYNFOF", "SYNNOGT"]
    assert run.n_errors == 2   # SYNEQ (unknown row 26) and SYNNOGT (no grand total)


def test_report_mentions_every_problem(synthetic_files):
    run = parse_files([synthetic_files["equity"], synthetic_files["debt_esg"], synthetic_files["merged"]])
    text = build_report(run)
    for needle in ("row 26 not classified", "no GRAND TOTAL", "SYNMERGE", "merged cells inside",
                   "'Notes:'", "SYNGONE", "Disclaimer", "only in unmapped columns", "28–33"):
        assert needle in text, needle
