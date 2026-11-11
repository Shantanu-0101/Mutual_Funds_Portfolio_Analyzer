"""Write small synthetic ``.xls`` files in the real ABSL layout, with made-up values.

Why: parser tests must not need the real AMC files (spec §10), but they should
exercise the same layout: title block in rows 1–3, header in row 4 (columns
C–J, ESG extras in K–M), two heading levels, Total / GRAND TOTAL rows, TREPS
and Net Receivable rows without an ISIN, ``$0.00%`` cells, and a notes block
with numbers in it below the grand total.

Every value here is invented. File names start with ``synthetic_`` (spec §8).

    python -m tests.fixtures.make_synthetic      # writes into tests/fixtures/ to open in Excel

Row numbers in the comments are the 1-based Excel rows the tests assert on.
"""

from __future__ import annotations

import sys
from pathlib import Path

import xlwt

from src.parsing.values import isin_check_digit_ok

HEADER = ["Name of the Instrument / Issuer", "ISIN", "Industry^ / Rating", "Quantity",
          "Market value\n(Rs. in Lakhs)", "% to AUM", "YTM %", "YTC %"]
ESG_HEADER = ["ESG Score\n( Rating & Analystics Ltd)", "BRSR  Core Score #", "Link to BRSR report"]


def isin(body11: str) -> str:
    """Append the check digit that makes ``body11`` a valid ISIN."""
    return next(body11 + str(d) for d in range(10) if isin_check_digit_ok(body11 + str(d)))


# Row helpers: each returns a full row starting at column A.
def title(code: str, name: str, desc: str, as_on: str) -> list[list]:
    return [[code, "", name], ["", "", desc], ["", "", f"Portfolio Statement as on {as_on}"]]


def header(esg: bool = False) -> list:
    return ["", ""] + HEADER + (ESG_HEADER if esg else [])


def heading(text: str) -> list:
    return ["", "", text]


def holding(name, isin_="", rating="", qty="", value="", pct="", ytm="", ytc="", code="", extra=()) -> list:
    return ["", code, name, isin_, rating, qty, value, pct, ytm, ytc, *extra]


def total(value, pct, grand: bool = False) -> list:
    return ["", "", "GRAND TOTAL (AUM)" if grand else "Total", "", "", "", value, pct]


BLANK: list = []


def equity_sheet() -> list[list]:
    """SYNEQ, as on 30 Sep 2026. Grand total 1,000 lakh; % sum exactly 100."""
    return [
        *title("SYNEQ", "SYNTHETIC FLEXI CAP FUND",
               "An open ended dynamic equity scheme (synthetic test data)", "September 30, 2026"),
        header(),                                                                    # 4
        BLANK,                                                                       # 5
        heading("Equity & Equity Related"),                                          # 6
        heading("a) Listed/awaiting listing on Stock Exchanges"),                    # 7
        holding("Alpha Bank Ltd.", isin("INE000A0101"), "Banks", 1000.0, 600.0, 0.6, code="100001"),   # 8
        holding("Beta Software Ltd.", isin("INE000B0101"), "IT - Software", 500.0, 300.0, 0.3),        # 9
        holding("Gamma Tiny Ltd.", isin("INE000C0101"), "Banks", 10.0, 0.5, "$0.00%"),                 # 10
        total(900.5, 0.9),                                                           # 11
        BLANK,                                                                       # 12
        heading("b) Unlisted"),                                                      # 13 sub alone: main stays Equity
        holding("Delta Written Off Ltd.", "IDIA00012345", "Miscellaneous", 100.0, 0.0, "$0.00%"),     # 14
        total(0.0, "$0.00%"),                                                        # 15
        BLANK,                                                                       # 16
        heading("Others"),                                                           # 17
        heading("TREPS / Reverse Repo Investments"),                                 # 18
        holding("TREPS", "", "", "", 80.0, 0.08, code="110260100"),                  # 19
        total(80.0, 0.08),                                                           # 20
        BLANK,                                                                       # 21
        heading("Other Current Assets / (Liabilities)"),                             # 22
        holding("Net Receivable / Payable", "", "", "", 19.5, 0.025),                # 23 file % is a plug (true 1.95)
        total(19.5, 0.025),                                                          # 24
        BLANK,                                                                       # 25
        ["", "", "Odd line without a value", isin("INE000X0101"), "Banks"],          # 26 UNKNOWN row
        total(1000.0, 1.0, grand=True),                                              # 27
        BLANK,                                                                       # 28
        heading("^Industry classification as recommended by AMFI"),                  # 29 tail starts
        heading("$ Less Than 0.01% of Net Asset Value"),                             # 30
        heading("Notes:"),                                                           # 31
        ["", "", "NAV per unit (Regular Growth)", "", "", "", 123.45, 0.5],          # 32 numbers, not a holding
        ["", "", "SYNTHETIC FLEXI CAP FUND", "", "", "NIFTY 500 TRI"],               # 33 benchmark line
    ]


def debt_esg_sheet() -> list[list]:
    """SYNDEBT, as on 31 Oct 2026, with ESG columns K–M. Grand total 1,000 lakh."""
    return [
        *title("SYNDEBT", "SYNTHETIC CORPORATE BOND FUND",
               "An open ended debt scheme (synthetic test data)", "October 31, 2026"),
        header(esg=True),                                                            # 4
        BLANK,                                                                       # 5
        heading("Debt Instruments"),                                                 # 6
        heading("a) Listed/awaiting listing on the stock exchanges"),                # 7
        holding("Epsilon Finance Ltd.", isin("INE000E0701"), "CRISIL AAA", 500.0, 400.0, 0.4, 0.0712,
                extra=(70.0, 72.0, "https://example.invalid/brsr")),                 # 8
        holding("Zeta Housing Ltd.", isin("INE000Z0701"), "[ICRA]AAA", 200.0, 200.0, 0.2, 0.0725, 0.0701),  # 9
        total(600.0, 0.6),                                                           # 10
        BLANK,                                                                       # 11
        heading("Government Securities"),                                            # 12 sub alone: main stays Debt
        holding("7.10% GOI 2034", isin("IN002024001"), "Sovereign", 1000.0, 250.0, 0.25, 0.0655),     # 13
        total(250.0, 0.25),                                                          # 14
        ["", "", "", "", "", "", "", "", "", "", 68.2],                              # 15 ESG score only: ignored
        heading("Money Market Instruments"),                                         # 16
        heading("STRIPS"),                                                           # 17
        holding("Notes:", isin("IN000438C04"), "Sovereign", 100.0, 50.0, 0.05),      # 18 trap: a real holding
        total(50.0, 0.05),                                                           # 19
        heading("Others"),                                                           # 20
        heading("TREPS / Reverse Repo Investments"),                                 # 21
        holding("TREPS", "", "", "", 90.0, 0.09),                                    # 22
        total(90.0, 0.09),                                                           # 23
        heading("Other Current Assets / (Liabilities)"),                             # 24
        holding("Net Receivable / Payable", "", "", "", 10.0, 0.01),                 # 25
        total(10.0, 0.01),                                                           # 26
        total(1000.0, 1.0, grand=True),                                              # 27
        heading("Notes:"),                                                           # 28
    ]


def no_grand_total_sheet() -> list[list]:
    """SYNNOGT, as on 30 Sep 2026, with no GRAND TOTAL row: the block ends at the first footnote."""
    return [
        *title("SYNNOGT", "SYNTHETIC NO GRAND TOTAL FUND", "synthetic test data", "September 30, 2026"),
        header(),                                                                    # 4
        BLANK,                                                                       # 5
        heading("Equity & Equity Related"),                                          # 6
        heading("a) Listed/awaiting listing on Stock Exchanges"),                    # 7
        holding("Eta Motors Ltd.", isin("INE000H0101"), "Automobiles", 10.0, 700.0, 0.7),             # 8
        holding("Theta Micro Ltd.", isin("INE000T0101"), "Retailing", 1.0, 0.3, "$0.00%"),            # 9
        total(700.3, 0.7),                                                           # 10
        BLANK,                                                                       # 11
        heading("Other Current Assets / (Liabilities)"),                             # 12
        holding("Net Receivable / Payable", "", "", "", 299.7, 0.2997),              # 13
        total(299.7, 0.2997),                                                        # 14
        BLANK,                                                                       # 15
        heading("$ Less Than 0.01% of Net Asset Value"),                             # 16 block ends above
        heading("Notes:"),                                                           # 17
    ]


def fund_of_funds_sheet() -> list[list]:
    """SYNFOF, as on 31 Jul 2026: starts with a sub-heading and no main heading (Jul/Aug NSDAQ100 style)."""
    return [
        *title("SYNFOF", "SYNTHETIC GLOBAL FOF", "synthetic test data", "July 31, 2026"),
        header(),                                                                    # 4
        BLANK,                                                                       # 5
        heading("International Mutual Fund Units"),                                  # 6
        holding("Synthetic Global Equity Fund", isin("LU000000001"), "", 1000.0, 950.0, 0.95),        # 7
        total(950.0, 0.95),                                                          # 8
        BLANK,                                                                       # 9
        heading("Others"),                                                           # 10
        heading("TREPS / Reverse Repo Investments"),                                 # 11
        holding("TREPS", "", "", "", 40.0, 0.04),                                    # 12
        total(40.0, 0.04),                                                           # 13
        heading("Other Current Assets / (Liabilities)"),                             # 14
        holding("Net Receivable / Payable", "", "", "", 10.0, 0.01),                 # 15
        total(10.0, 0.01),                                                           # 16
        total(1000.0, 1.0, grand=True),                                              # 17
    ]


def _write_sheet(wb: xlwt.Workbook, name: str, rows: list[list],
                 merges: list[tuple[int, int, int, int]] = ()) -> None:
    """``merges`` are 0-based inclusive (r1, r2, c1, c2), as xlwt expects."""
    ws = wb.add_sheet(name, cell_overwrite_ok=True)
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            if v != "":
                ws.write(r, c, v)
    for r1, r2, c1, c2 in merges:
        ws.merge(r1, r2, c1, c2)


def _index(wb: xlwt.Workbook, codes: list[tuple[str, str]]) -> None:
    rows = [["Scheme Code", "Scheme Short code", "Scheme Name"]]
    rows += [[f"SY{i:03}", code, name] for i, (code, name) in enumerate(codes, 1)]
    _write_sheet(wb, "Index", rows)


def write_equity(path: Path) -> Path:
    wb = xlwt.Workbook()
    _index(wb, [("SYNEQ", "SYNTHETIC FLEXI CAP FUND"), ("SYNGONE", "LISTED BUT NO SHEET")])
    # Merges in the title block (C1:H1) and below the grand total (C29:J29) are allowed (R9).
    _write_sheet(wb, "SYNEQ", equity_sheet(), merges=[(0, 0, 2, 7), (28, 28, 2, 9)])
    _write_sheet(wb, "Disclaimer", [["", "", "This sheet has no portfolio."]])
    wb.save(str(path))
    return path


def write_debt_esg(path: Path) -> Path:
    wb = xlwt.Workbook()
    _index(wb, [("SYNDEBT", "SYNTHETIC CORPORATE BOND FUND"), ("SYNNOGT", "SYNTHETIC NO GRAND TOTAL FUND"),
                ("SYNFOF", "SYNTHETIC GLOBAL FOF")])
    _write_sheet(wb, "SYNDEBT", debt_esg_sheet())
    _write_sheet(wb, "SYNNOGT", no_grand_total_sheet())
    _write_sheet(wb, "SYNFOF", fund_of_funds_sheet())
    wb.save(str(path))
    return path


def write_merged(path: Path) -> Path:
    """The equity sheet with one merged cell inside the block (C8:D8): must fail loudly (FR-1.9)."""
    wb = xlwt.Workbook()
    _write_sheet(wb, "SYNMERGE", equity_sheet(), merges=[(7, 7, 2, 3)])
    wb.save(str(path))
    return path


def write_all(folder: Path) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    return {
        "equity": write_equity(folder / "synthetic_equity.xls"),
        "debt_esg": write_debt_esg(folder / "synthetic_debt_esg.xls"),
        "merged": write_merged(folder / "synthetic_merged.xls"),
    }


if __name__ == "__main__":
    out = write_all(Path(__file__).parent)
    for p in out.values():
        print(f"wrote {p}")
    sys.exit(0)
