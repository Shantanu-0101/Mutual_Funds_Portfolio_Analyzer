"""Optional smoke test on the real ABSL files (spec §10). Skipped when data/raw has none.

Expected numbers come from DATA_NOTES §2 and §9 (Phase 0), so this test fails
if the parser drifts from what the inspection found.
"""

from datetime import date

import pytest

from src.config import get_settings
from src.parsing.pipeline import parse_file
from src.parsing.validate import PCT_TOL_POINTS

SEP_FILE = "30092026_ABSLMF_MonthlyDisclosure.xls"
SEP_PATH = get_settings().paths.raw / SEP_FILE

pytestmark = pytest.mark.skipif(not SEP_PATH.is_file(), reason=f"real file {SEP_FILE} not in data/raw")


@pytest.fixture(scope="module")
def sep():
    return parse_file(SEP_PATH)


def test_september_counts(sep):
    assert sep.as_of_date == date(2026, 9, 30)
    assert len(sep.sheets) == 104 and not sep.failed
    assert sum(len(s.holdings) for s in sep.sheets) == 5646


def test_september_every_sheet_balances(sep):
    for ck in sep.checks:
        assert ck.errors == [], (ck.sheet, ck.errors)
        assert abs(ck.value_diff) <= 1.0, ck.sheet
        assert abs(ck.pct_dev) <= PCT_TOL_POINTS, ck.sheet


def test_september_bslif_notes_trap(sep):
    s = next(s for s in sep.sheets if s.sheet == "BSLIF")
    assert s.grand_total_row == 229
    h = next(h for h in s.holdings if h["source_row"] == 207)
    assert h["isin"] == "IN000438C043" and h["name_suspect"]


def test_september_flexi_cap_icici(sep):
    s = next(s for s in sep.sheets if s.sheet == "BSLEQTY")
    h = next(h for h in s.holdings if h["source_row"] == 8)
    assert h["instrument"] == "ICICI Bank Ltd."
    assert h["pct_nav"] == pytest.approx(5.59673, abs=1e-4)   # spec §2: 0.0559673 = 5.597%
