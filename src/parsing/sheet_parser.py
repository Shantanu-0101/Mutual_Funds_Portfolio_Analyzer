"""Parse one scheme sheet into holdings and total rows (tasks 1.2–1.6).

Why a row classifier + state machine instead of ``pd.read_excel(header=3)``:
section headings are rows *inside* the table, so what a row means depends on
the rows above it, and pandas would lose the real Excel row numbers that every
later stage uses as the row key (FR-1.1).

A sheet is read top to bottom:

    title block (rows above the header) -> header row (found by text)
    -> portfolio block -> GRAND TOTAL (AUM) -> tail (skipped as one block)

Inside the block every row is one of:

    HEADING  text in the name column, nothing else    -> sets section / subsection
    HOLDING  has a numeric market value (ISIN or not) -> holdings
    TOTAL    "Total" or "GRAND TOTAL (AUM)"           -> totals
    BLANK    nothing at all                           -> counted
    UNKNOWN  anything else                            -> listed in the report (FR-1.6)

The rules come from DATA_NOTES §12 (R1–R9), with Q1–Q3 answered as recommended.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from src.parsing.mapping import AMC, MAIN_OTHER_CURRENT, asset_class_for, is_main_heading, key
from src.parsing.reader import RawSheet
from src.parsing.values import (
    fraction_to_pct,
    is_num,
    isin_valid,
    looks_like_footnote,
    norm,
    num_or_none,
    parse_as_on,
)

HEADER_SEARCH_ROWS = 15
# Header text -> our column. Matched on the start of the lower-cased,
# whitespace-collapsed header cell, so "Market value\n(Rs. in Lakhs)" matches (R1).
HEADER_PREFIXES = {
    "name of the instrument": "instrument",
    "isin": "isin",
    "industry": "rating",          # "Industry^ / Rating": industry for equity, rating for debt
    "quantity": "quantity",
    "market value": "value",
    "% to aum": "pct",
    "ytm": "ytm",
    "ytc": "ytc",
}
REQUIRED_COLUMNS = ("instrument", "isin", "rating", "quantity", "value", "pct")
VALUE_COLUMNS = ("isin", "rating", "quantity", "value", "pct", "ytm", "ytc")

# pct_nav_flag values (spec §6.2, DATA_NOTES R6)
FLAG_LT_001 = "lt_0.01"        # file shows "$0.00%": % computed from value / grand total
FLAG_RECOMPUTED = "recomputed"  # Other Current Assets row: file % is a plug, recomputed (Q1)
FLAG_COMPUTED = "computed"      # any other non-numeric % cell: computed from value / grand total


class ParseError(Exception):
    """The sheet cannot be parsed safely. Raised, never swallowed silently."""


class MergedCellsInBlockError(ParseError):
    """FR-1.9 / R9: a merged cell inside the portfolio block would shift values."""


@dataclass
class UnknownRow:
    row: int
    reason: str
    text: str


@dataclass
class SheetResult:
    file: str
    sheet: str
    scheme_code: str
    scheme: str
    description: str
    as_of_date: date
    header_row: int                     # 1-based Excel rows from here on
    block_first_row: int
    block_last_row: int                 # the GRAND TOTAL row, or the row before the fallback end
    end_rule: str                       # "grand_total" | "footnote" | "end_of_sheet"
    grand_total_row: int | None
    grand_total_lakhs: float | None
    grand_total_pct: float | None       # percent units, as in the file
    tail_rows: tuple[int, int] | None   # skipped block below the portfolio (FR-1.5)
    tail_first_text: str
    extra_columns: list[str]            # header texts we do not map (ESG columns)
    merged_outside_block: int
    holdings: list[dict] = field(default_factory=list)
    totals: list[dict] = field(default_factory=list)
    unknown_rows: list[UnknownRow] = field(default_factory=list)
    ignored_rows: list[UnknownRow] = field(default_factory=list)   # only unmapped (ESG) columns filled
    blank_rows: int = 0
    notes: list[str] = field(default_factory=list)  # informational, for the report


def find_header(sheet: RawSheet) -> tuple[int, dict[str, int], list[str]] | None:
    """Return (0-based header row, column map, unmapped header texts), or None."""
    for r in range(min(HEADER_SEARCH_ROWS, len(sheet.rows))):
        texts = [norm(v) for v in sheet.rows[r]]
        if not any(t.lower().startswith("name of the instrument") for t in texts):
            continue
        cols: dict[str, int] = {}
        extras: list[str] = []
        for c, t in enumerate(texts):
            if not t:
                continue
            low = t.lower()
            col = next((k for p, k in HEADER_PREFIXES.items() if low.startswith(p)), None)
            if col and col not in cols:
                cols[col] = c
            else:
                extras.append(t)
        return r, cols, extras
    return None


def _cells(sheet: RawSheet, r: int, cols: dict[str, int]) -> dict[str, object]:
    return {k: sheet.cell(r, c) for k, c in cols.items()}


def classify(cells: dict[str, object], row_has_any: bool) -> str:
    """heading | holding | total | grand_total | blank | unknown"""
    if not row_has_any:
        return "blank"
    low = norm(cells.get("instrument", "")).lower()
    if low.startswith("grand total"):
        return "grand_total"
    if low == "total":
        return "total"
    if is_num(cells.get("value")):
        return "holding"
    if low and not any(norm(cells.get(k, "")) for k in VALUE_COLUMNS):
        return "heading"
    return "unknown"


def _unknown_reason(cells: dict[str, object]) -> str:
    if is_num(cells.get("pct")):
        return "% to AUM present but no numeric market value"
    if norm(cells.get("value", "")):
        return f"market value is text: {norm(cells['value'])!r}"
    if not norm(cells.get("instrument", "")):
        return "values but no instrument name"
    return "text in value columns but no market value"


def pct_rule(main: str | None, value: float, pct_cell: object,
             grand_total: float | None) -> tuple[float, str | None]:
    """Return (pct_nav in percent units, pct_nav_flag). DATA_NOTES R6, FR-1.3.

    - Rows under "Other Current Assets / (Liabilities)": ABSL's % cell is a
      balancing plug (wrong in 22 July rows), so % = value / grand total (Q1).
    - Numeric % cell: fraction -> percent.
    - Text such as "$0.00%" ("less than 0.01%"): value / grand total, flagged,
      never null and never a silent 0 (0.0 only if the grand total is missing).
    """
    gt_ok = grand_total is not None and grand_total != 0
    if key(main) == MAIN_OTHER_CURRENT and gt_ok:
        return value / grand_total * 100.0, FLAG_RECOMPUTED
    if is_num(pct_cell):
        return float(pct_cell) * 100.0, None
    flag = FLAG_LT_001 if norm(pct_cell).startswith("$") else FLAG_COMPUTED
    return (value / grand_total * 100.0 if gt_ok else 0.0), flag


def _find_block_end(sheet: RawSheet, hdr: int, cols: dict[str, int]) -> tuple[int, str, int | None]:
    """Return (0-based last block row, end rule, 0-based grand total row or None). R2.

    The block ends at GRAND TOTAL (AUM). Only if a sheet has none do we fall back
    to the first footnote / "Notes:" row *without a market value*: Sep BSLIF row
    207 is a real holding whose name cell says "Notes:" (DATA_NOTES §9).
    """
    c_name = cols["instrument"]
    for r in range(hdr + 1, len(sheet.rows)):
        if norm(sheet.cell(r, c_name)).lower().startswith("grand total"):
            return r, "grand_total", r
    for r in range(hdr + 1, len(sheet.rows)):
        text = norm(sheet.cell(r, c_name))
        if text and looks_like_footnote(text) and not is_num(sheet.cell(r, cols["value"])):
            return r - 1, "footnote", None
    return len(sheet.rows) - 1, "end_of_sheet", None


def parse_sheet(sheet: RawSheet) -> SheetResult | None:
    """Parse one sheet. Returns None for a sheet without a portfolio header."""
    found = find_header(sheet)
    if found is None:
        return None
    hdr, cols, extras = found
    missing = [c for c in REQUIRED_COLUMNS if c not in cols]
    if missing:
        raise ParseError(f"{sheet.file} › {sheet.name}: header row {hdr + 1} lacks columns {missing}")

    # ---- title block (rows above the header)
    title = [[norm(v) for v in sheet.rows[r] if norm(v)] for r in range(hdr)]
    code = norm(sheet.cell(0, 0)) or sheet.name
    row1 = title[0] if title else []
    scheme = next((t for t in reversed(row1) if t != code), "")
    description = title[1][0] if len(title) > 1 and title[1] else ""
    as_of = next((d for line in title for t in line if (d := parse_as_on(t))), None)
    if as_of is None:
        raise ParseError(f"{sheet.file} › {sheet.name}: no 'Portfolio Statement as on …' date in rows 1–{hdr}")

    # ---- where the block ends, and the merged-cell assertion (R9)
    last, end_rule, gt_r = _find_block_end(sheet, hdr, cols)
    in_block = [m for m in sheet.merged if m[0] <= last and m[1] - 1 >= hdr + 1]
    if in_block:
        where = ", ".join(f"rows {m[0] + 1}-{m[1]} cols {m[2] + 1}-{m[3]}" for m in in_block)
        raise MergedCellsInBlockError(
            f"{sheet.file} › {sheet.name}: merged cells inside the portfolio block ({where}); "
            "values could be shifted, so this sheet is not parsed")

    gt_cells = _cells(sheet, gt_r, cols) if gt_r is not None else {}
    grand_total = num_or_none(gt_cells.get("value"))
    tail_first = last + 1
    tail = (tail_first + 1, len(sheet.rows)) if tail_first < len(sheet.rows) else None
    tail_text = ""
    if tail:
        tail_text = next((norm(v) for r in range(tail_first, len(sheet.rows))
                          for v in sheet.rows[r] if norm(v)), "")

    res = SheetResult(
        file=sheet.file, sheet=sheet.name, scheme_code=code, scheme=scheme, description=description,
        as_of_date=as_of, header_row=hdr + 1, block_first_row=hdr + 2, block_last_row=last + 1,
        end_rule=end_rule, grand_total_row=gt_r + 1 if gt_r is not None else None,
        grand_total_lakhs=grand_total, grand_total_pct=fraction_to_pct(gt_cells.get("pct")),
        tail_rows=tail, tail_first_text=tail_text, extra_columns=extras,
        merged_outside_block=len(sheet.merged) - len(in_block),
    )
    if extras:
        res.notes.append(f"unmapped header columns ignored: {extras}")

    # ---- walk the block
    main: str | None = None
    sub: str | None = None
    run_rows: list[dict] = []          # holdings since the previous Total, for validation
    base = {"amc": AMC, "scheme_code": code, "scheme": scheme, "as_of_date": as_of}
    src = {"source_file": sheet.file, "source_sheet": sheet.name}
    for r in range(hdr + 1, last + 1):
        cells = _cells(sheet, r, cols)
        excel_row = r + 1
        has_mapped = any(norm(v) for v in cells.values())
        if not has_mapped:
            others = [norm(v) for v in sheet.rows[r] if norm(v)] if r < len(sheet.rows) else []
            if others:
                # e.g. ABSLESG Sep/Oct row 61: a weighted ESG score under the equity
                # Total, in an ESG column we do not map (FR-1.2). Not a holding.
                res.ignored_rows.append(UnknownRow(excel_row, "only unmapped columns filled",
                                                   " | ".join(others)[:60]))
            else:
                res.blank_rows += 1
            continue
        kind = classify(cells, has_mapped)
        text = norm(cells.get("instrument", ""))

        if kind == "blank":
            res.blank_rows += 1
        elif kind == "heading":
            if is_main_heading(text):
                main, sub = text, None
            else:
                sub = text
        elif kind == "holding":
            value = float(cells["value"])
            pct, flag = pct_rule(main, value, cells.get("pct"), grand_total)
            isin = norm(cells.get("isin", "")) or None
            asset_class, how = asset_class_for(main, sub)
            holding = {
                **base,
                "section": main,
                "subsection": sub,
                "asset_class": asset_class,
                "asset_class_rule": how,
                "instrument": text,
                "isin": isin,
                "isin_valid": isin_valid(isin),
                "industry_or_rating": norm(cells.get("rating", "")) or None,
                "quantity": num_or_none(cells.get("quantity")),
                "market_value_lakhs": value,
                "pct_nav": pct,
                "pct_nav_flag": flag,
                "pct_nav_file": fraction_to_pct(cells.get("pct")),
                "ytm": fraction_to_pct(cells.get("ytm")),
                "ytc": fraction_to_pct(cells.get("ytc")),
                "name_suspect": (not text) or looks_like_footnote(text),   # R7
                **src,
                "source_row": excel_row,
            }
            for col in ("quantity", "ytm", "ytc"):
                if norm(cells.get(col, "")) and not is_num(cells.get(col)):
                    res.notes.append(f"row {excel_row}: {col} is text {norm(cells[col])!r}, stored as null")
            res.holdings.append(holding)
            run_rows.append(holding)
        elif kind in ("total", "grand_total"):
            rows = res.holdings if kind == "grand_total" else run_rows
            res.totals.append({
                **base,
                "kind": kind,
                "section": main,
                "subsection": sub,
                "market_value_lakhs": num_or_none(cells.get("value")),
                "pct_nav": fraction_to_pct(cells.get("pct")),
                "pct_nav_text": None if is_num(cells.get("pct")) else (norm(cells.get("pct", "")) or None),
                "rows_counted": len(rows),
                "rows_first": rows[0]["source_row"] if rows else None,
                "rows_value_sum": sum(h["market_value_lakhs"] for h in rows),
                "rows_pct_file_sum": sum(h["pct_nav_file"] or 0.0 for h in rows),
                "rows_pct_sum": sum(h["pct_nav"] for h in rows),
                **src,
                "source_row": excel_row,
            })
            if kind == "total":
                run_rows = []
        else:
            res.unknown_rows.append(UnknownRow(excel_row, _unknown_reason(cells), text[:60]))

    return res
