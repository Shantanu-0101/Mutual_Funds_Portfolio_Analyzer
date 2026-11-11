"""Per-sheet validation (task 1.8, FR-1.7).

Why: a parser bug would corrupt every gold answer in the same way and the
results would still look plausible (spec §12). These checks compare what we
parsed with the sheet's own Total and GRAND TOTAL rows, so such a bug shows up
here first.

Tolerances (DATA_NOTES R10): market values 1 lakh; percentages 0.05 points.

Severity:
  error    the parsed holdings may be wrong or incomplete (status ERROR)
  warning  worth a look, the holdings are still usable (status WARN)
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from src.parsing.sheet_parser import FLAG_RECOMPUTED, SheetResult

VALUE_TOL_LAKHS = 1.0
PCT_TOL_POINTS = 0.05
LT_001_POINTS = 0.01


@dataclass
class SheetChecks:
    file: str
    sheet: str
    as_of_date: object
    n_holdings: int
    pct_sum: float
    pct_dev: float                       # pct_sum - 100
    value_sum: float
    grand_total: float | None
    value_diff: float | None             # value_sum - grand_total
    totals_checked: int = 0
    total_value_mismatches: list[str] = field(default_factory=list)
    total_pct_mismatches: list[str] = field(default_factory=list)
    dup_isins: list[str] = field(default_factory=list)
    null_pct_rows: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "ERROR" if self.errors else "WARN" if self.warnings else "OK"


def check_sheet(res: SheetResult) -> SheetChecks:
    h = res.holdings
    pct_sum = sum(x["pct_nav"] for x in h if x["pct_nav"] is not None)
    value_sum = sum(x["market_value_lakhs"] for x in h)
    gt = res.grand_total_lakhs
    ck = SheetChecks(
        file=res.file, sheet=res.sheet, as_of_date=res.as_of_date, n_holdings=len(h),
        pct_sum=pct_sum, pct_dev=pct_sum - 100.0, value_sum=value_sum, grand_total=gt,
        value_diff=(value_sum - gt) if gt is not None else None,
    )

    # Grand total present, and the value rows add up to it
    if res.grand_total_row is None:
        ck.errors.append(f"no GRAND TOTAL (AUM) row; block ended by rule '{res.end_rule}' "
                         f"at row {res.block_last_row}; % of '$' rows stored as 0.0")
    elif gt is None:
        ck.errors.append(f"GRAND TOTAL row {res.grand_total_row} has no numeric market value")
    elif abs(ck.value_diff) > VALUE_TOL_LAKHS:
        ck.errors.append(f"value rows sum to {value_sum:,.2f} lakh, grand total says {gt:,.2f} "
                         f"(diff {ck.value_diff:,.2f})")

    # % sum vs 100
    if not h:
        ck.errors.append("no holdings parsed")
    elif abs(ck.pct_dev) > PCT_TOL_POINTS:
        ck.warnings.append(f"% to AUM sums to {pct_sum:.4f} (off by {ck.pct_dev:+.4f} points)")

    # Each Total row vs the holdings above it
    for t in res.totals:
        if t["kind"] != "total":
            continue
        ck.totals_checked += 1
        tv = t["market_value_lakhs"]
        if tv is None or abs(tv - t["rows_value_sum"]) > VALUE_TOL_LAKHS:
            ck.total_value_mismatches.append(
                f"Total row {t['source_row']}: rows {t['rows_first']}–{t['source_row'] - 1} sum to "
                f"{t['rows_value_sum']:,.2f} lakh, Total says {tv if tv is None else f'{tv:,.2f}'}")
        tp = t["pct_nav"]
        if tp is not None:
            # Compare with ABSL's own % cells (what its Total adds up); for the
            # recomputed Other Current Assets rows also accept our recomputed sum.
            ok = abs(tp - t["rows_pct_file_sum"]) <= PCT_TOL_POINTS or \
                abs(tp - t["rows_pct_sum"]) <= PCT_TOL_POINTS
            if not ok:
                ck.total_pct_mismatches.append(
                    f"Total row {t['source_row']}: Total % {tp:.4f}, rows' file % sum "
                    f"{t['rows_pct_file_sum']:.4f}, parsed % sum {t['rows_pct_sum']:.4f}")
        elif (t["pct_nav_text"] or "").startswith("$") and t["rows_pct_sum"] >= LT_001_POINTS:
            ck.total_pct_mismatches.append(
                f"Total row {t['source_row']}: Total % is {t['pct_nav_text']!r} but rows sum to "
                f"{t['rows_pct_sum']:.4f}%")
    for m in ck.total_value_mismatches:
        ck.errors.append(m)
    for m in ck.total_pct_mismatches:
        ck.warnings.append(m)

    # Duplicate ISIN within a section
    by_section = Counter((x["section"], x["isin"]) for x in h if x["isin"])
    ck.dup_isins = sorted(f"{isin} in {sec}" for (sec, isin), n in by_section.items() if n > 1)
    for d in ck.dup_isins:
        ck.warnings.append(f"duplicate ISIN {d}")

    # Null %, unknown rows, mapping and name problems
    ck.null_pct_rows = [x["source_row"] for x in h if x["pct_nav"] is None]
    if ck.null_pct_rows:
        ck.errors.append(f"null pct_nav on rows {ck.null_pct_rows}")
    for u in res.unknown_rows:
        ck.errors.append(f"row {u.row} not classified ({u.reason}): {u.text!r}")
    no_class = [x["source_row"] for x in h if x["asset_class"] is None]
    if no_class:
        ck.errors.append(f"no asset_class mapping for rows {no_class}")
    fallback = Counter((x["section"], x["subsection"]) for x in h if x["asset_class_rule"] == "main_fallback")
    for (sec, sub), n in fallback.items():
        ck.warnings.append(f"{n} rows under new heading pair ({sec!r}, {sub!r}): asset_class taken from main heading")
    for x in h:
        if x["name_suspect"]:
            ck.warnings.append(f"row {x['source_row']}: instrument name {x['instrument']!r} looks like "
                               f"a footnote marker (ISIN {x['isin']}); kept as written (R7)")
    return ck


def recomputed_rows(res: SheetResult, min_diff_points: float = 0.01) -> list[dict]:
    """Other Current Assets rows whose file % differed from value / grand total."""
    return [x for x in res.holdings if x["pct_nav_flag"] == FLAG_RECOMPUTED and
            (x["pct_nav_file"] is None or abs(x["pct_nav_file"] - x["pct_nav"]) > min_diff_points)]
