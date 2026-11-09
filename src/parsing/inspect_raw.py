"""Phase 0: read-only inspection of the raw ABSL portfolio files.

Why this exists: the parser (Phase 1) must rest on facts about the real files,
not on guesses. This script walks every portfolio file and every sheet and
prints what a parser would need to know: title block, header row, section
headings, Total / GRAND TOTAL rows, where the portfolio block ends, text in
numeric columns, rating labels per section, and whether the value rows add up
to the grand total. Its output is the evidence behind ``docs/DATA_NOTES.md``.

It does not parse into tables and writes nothing except to stdout:

    python -m src.parsing.inspect_raw > results/inspect_raw.txt

Row numbers are 1-based Excel row numbers, as you would see them in Excel.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import xlrd

from src.config import get_settings

# Header text -> our column name. Matched on the start of the lower-cased,
# whitespace-collapsed header cell, so "Market value\n(Rs. in Lakhs)" matches.
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
NUMERIC_COLS = ("quantity", "value", "pct", "ytm", "ytc")
HEADER_SEARCH_ROWS = 15
AS_ON_RE = re.compile(r"as on\s+([A-Za-z]+)\s+(\d{1,2}),?\s*(\d{4})", re.IGNORECASE)
ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
# Text that normally marks the end of the portfolio block (footnotes, notes).
FOOTNOTE_RE = re.compile(r"^(\*|#|\$|\^|notes\s*:|fr[bn]\s*-|ytc represents)", re.IGNORECASE)
VALUE_TOL_LAKHS = 1.0      # value sum vs grand total: allowed rounding, in lakhs
PCT_TOL = 0.0005           # % sum vs 1.0, as a fraction (= 0.05 percentage points)


def norm(text: object) -> str:
    """Collapse whitespace (incl. non-breaking spaces and newlines) and strip."""
    return re.sub(r"\s+", " ", str(text).replace("\xa0", " ")).strip()


def is_num(v: object) -> bool:
    return isinstance(v, float) and not isinstance(v, bool)


@dataclass
class Row:
    n: int                     # 1-based Excel row number
    kind: str                  # heading | holding | total | grand_total | blank | other
    text: str
    cells: dict[str, object]


@dataclass
class SheetReport:
    file: str
    sheet: str
    code: str = ""
    name: str = ""
    description: str = ""
    as_on: date | None = None
    header_row: int | None = None
    header_cols: tuple[str, ...] = ()
    extra_cols: tuple[str, ...] = ()
    merged: list[tuple[int, int, int, int]] = field(default_factory=list)  # xlrd: rlo, rhi, clo, chi
    rows: list[Row] = field(default_factory=list)
    grand_total_row: int | None = None
    first_footnote_row: int | None = None
    tail_rows: int = 0
    tail_first: str = ""
    tail_last: str = ""
    problems: list[str] = field(default_factory=list)

    @property
    def holdings(self) -> list[Row]:
        return [r for r in self.rows if r.kind == "holding"]


def find_header(sh: xlrd.sheet.Sheet) -> tuple[int, dict[str, int], list[str]] | None:
    """Return (0-based header row, column map, extra header texts) or None."""
    for r in range(min(HEADER_SEARCH_ROWS, sh.nrows)):
        texts = [norm(v) for v in sh.row_values(r)]
        if not any(t.lower().startswith("name of the instrument") for t in texts):
            continue
        cols: dict[str, int] = {}
        extras: list[str] = []
        for c, t in enumerate(texts):
            if not t:
                continue
            low = t.lower()
            key = next((k for p, k in HEADER_PREFIXES.items() if low.startswith(p)), None)
            if key and key not in cols:
                cols[key] = c
            else:
                extras.append(t)
        return r, cols, extras
    return None


def classify(cells: dict[str, object]) -> str:
    text = norm(cells.get("instrument", ""))
    has_value = is_num(cells.get("value")) or is_num(cells.get("pct"))
    has_any = any(norm(v) for v in cells.values())
    if not has_any:
        return "blank"
    low = text.lower()
    if low.startswith("grand total"):
        return "grand_total"
    if low == "total":
        return "total"
    if has_value:
        return "holding"
    if text and not any(norm(cells.get(k, "")) for k in NUMERIC_COLS + ("isin",)):
        return "heading"
    return "other"


def inspect_sheet(path: Path, sh: xlrd.sheet.Sheet) -> SheetReport | None:
    found = find_header(sh)
    if found is None:
        return None
    hdr, cols, extras = found
    rep = SheetReport(file=path.name, sheet=sh.name, header_row=hdr + 1,
                      header_cols=tuple(sorted(cols, key=cols.get)), extra_cols=tuple(extras),
                      merged=list(sh.merged_cells))

    # Title block: the non-empty cells of the rows above the header.
    title = [[norm(v) for v in sh.row_values(r) if norm(v)] for r in range(hdr)]
    if title and title[0]:
        rep.code = title[0][0]
        rep.name = title[0][-1] if len(title[0]) > 1 else ""
    if len(title) > 1 and title[1]:
        rep.description = title[1][0]
    for line in title:
        for t in line:
            m = AS_ON_RE.search(t)
            if m:
                rep.as_on = datetime.strptime(" ".join(m.groups()), "%B %d %Y").date()
    if rep.as_on is None:
        rep.problems.append("no 'as on' date in the title block")

    # Walk the rows below the header until the grand total.
    for r in range(hdr + 1, sh.nrows):
        values = sh.row_values(r)
        cells = {k: values[c] for k, c in cols.items() if c < len(values)}
        cells["code"] = values[1] if len(values) > 1 else ""
        row = Row(n=r + 1, kind=classify(cells), text=norm(cells.get("instrument", "")), cells=cells)
        if rep.first_footnote_row is None and row.text and FOOTNOTE_RE.match(row.text):
            rep.first_footnote_row = row.n
        if row.kind == "grand_total":
            rep.rows.append(row)
            rep.grand_total_row = row.n
            tail = [norm(v) for rr in range(r + 1, sh.nrows) for v in sh.row_values(rr)[:4] if norm(v)]
            rep.tail_rows = sh.nrows - (r + 1)
            rep.tail_first = tail[0] if tail else ""
            for rr in range(sh.nrows - 1, r, -1):
                last = [norm(v) for v in sh.row_values(rr) if norm(v)]
                if last:
                    rep.tail_last = " | ".join(last)
                    break
            break
        rep.rows.append(row)
    if rep.grand_total_row is None:
        rep.problems.append("no GRAND TOTAL row")
    return rep


def inspect_file(path: Path) -> tuple[list[SheetReport], list[str], dict[str, str]]:
    """Return (scheme sheet reports, names of skipped sheets, Index sheet code->name)."""
    wb = xlrd.open_workbook(str(path), formatting_info=True)
    reports, skipped, index = [], [], {}
    for sh in wb.sheets():
        if sh.name.strip().lower() == "index":
            for r in range(sh.nrows):
                v = [norm(x) for x in sh.row_values(r)]
                if len(v) >= 3 and v[1] and v[1].lower() != "scheme short code":
                    index[v[1]] = v[2]
            continue
        rep = inspect_sheet(path, sh)
        if rep is None:
            skipped.append(sh.name)
        else:
            reports.append(rep)
    return reports, skipped, index


# ---------------------------------------------------------------- checks


def block_checks(rep: SheetReport) -> dict[str, object]:
    """FR-0.3: do the value rows add up to the grand total? Plus each Total."""
    holdings = rep.holdings
    vals = [r.cells["value"] for r in holdings if is_num(r.cells.get("value"))]
    pcts = [r.cells["pct"] for r in holdings if is_num(r.cells.get("pct"))]
    text_pct = [r for r in holdings if isinstance(r.cells.get("pct"), str) and norm(r.cells["pct"])]
    gt = next((r for r in rep.rows if r.kind == "grand_total"), None)
    gt_val = gt.cells.get("value") if gt else None
    gt_pct = gt.cells.get("pct") if gt else None
    out: dict[str, object] = {
        "holdings": len(holdings),
        "with_isin": sum(1 for r in holdings if ISIN_RE.match(norm(r.cells.get("isin", "")))),
        "value_sum": sum(vals),
        "gt_value": gt_val if is_num(gt_val) else None,
        "pct_sum": sum(pcts),
        "gt_pct": gt_pct if is_num(gt_pct) else None,
        "text_pct": len(text_pct),
        "no_value": sum(1 for r in holdings if not is_num(r.cells.get("value"))),
    }
    # % of the "$0.00%" rows if computed as value / grand total (FR-1.3 rule).
    if is_num(gt_val) and gt_val:
        out["text_pct_computed"] = sum(r.cells["value"] for r in text_pct
                                       if is_num(r.cells.get("value"))) / gt_val
        devs = [abs(r.cells["pct"] - r.cells["value"] / gt_val) for r in holdings
                if is_num(r.cells.get("pct")) and is_num(r.cells.get("value"))]
        out["max_pct_dev"] = max(devs, default=0.0)
        out["max_text_pct_computed"] = max(
            (r.cells["value"] / gt_val for r in text_pct if is_num(r.cells.get("value"))), default=0.0)
    # Each Total vs the holdings since the previous Total. A Total whose % is the
    # text "$0.00%" is accepted when its rows really are below 0.01% of AUM.
    mismatches = []
    run_v, run_p, start = 0.0, 0.0, None
    for r in rep.rows:
        if r.kind == "holding":
            start = start or r.n
            run_v += r.cells["value"] if is_num(r.cells.get("value")) else 0.0
            run_p += r.cells["pct"] if is_num(r.cells.get("pct")) else 0.0
        elif r.kind == "total":
            tv, tp = r.cells.get("value"), r.cells.get("pct")
            dv = (tv - run_v) if is_num(tv) else None
            if is_num(tp):
                pct_ok = abs(tp - run_p) <= PCT_TOL
            else:
                pct_ok = (norm(tp) == "$0.00%" and is_num(gt_val) and gt_val
                          and abs(run_v / gt_val) < 0.0001)
            if dv is None or abs(dv) > VALUE_TOL_LAKHS or not pct_ok:
                mismatches.append((r.n, start, run_v, tv, run_p, tp))
            run_v, run_p, start = 0.0, 0.0, None
    out["total_mismatches"] = mismatches
    # Rows whose % cell disagrees with value / grand total by more than 0.01 point.
    out["pct_disagree"] = []
    out["text_pct_big"] = []
    if is_num(gt_val) and gt_val:
        for r in holdings:
            v, p = r.cells.get("value"), r.cells.get("pct")
            if not is_num(v):
                continue
            calc = v / gt_val
            if is_num(p) and abs(p - calc) > 0.0001:
                out["pct_disagree"].append((r, p, calc))
            elif isinstance(p, str) and norm(p) and calc >= 0.0001:
                out["text_pct_big"].append((r, p, calc))
    isins = [norm(r.cells.get("isin", "")) for r in holdings if norm(r.cells.get("isin", ""))]
    out["dup_isins"] = sorted(i for i, n in Counter(isins).items() if n > 1)
    return out


def isin_check_ok(isin: str) -> bool:
    """ISO 6166 check digit: letters -> 10..35, then the Luhn algorithm."""
    if not ISIN_RE.match(isin):
        return False
    digits = "".join(str(int(ch, 36)) for ch in isin[:-1])
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            d = d - 9 if d > 9 else d
        total += d
    return (10 - total % 10) % 10 == int(isin[-1])


def heading_runs(rep: SheetReport) -> list[tuple[int, tuple[str, ...]]]:
    """Group consecutive heading rows (blanks ignored) into runs.

    A run of two means "main heading, then sub-heading". A run of one is
    ambiguous on its own; Phase 0 resolves it from how the text is used elsewhere.
    """
    runs: list[tuple[int, tuple[str, ...]]] = []
    cur: list[str] = []
    first = 0
    for r in rep.rows:
        if r.kind == "blank":
            continue
        if r.kind == "heading":
            if not cur:
                first = r.n
            cur.append(r.text)
        elif cur:
            runs.append((first, tuple(cur)))
            cur = []
    if cur:
        runs.append((first, tuple(cur)))
    return runs


# ---------------------------------------------------------------- printing


def fmt(x: object, nd: int = 2) -> str:
    return f"{x:,.{nd}f}" if is_num(x) else ("-" if x in (None, "") else str(x))


def h1(title: str) -> None:
    print("\n" + "=" * 100 + f"\n{title}\n" + "=" * 100)


def main() -> int:
    # Sheet text has characters outside the Windows console code page (e.g. ‘ in a
    # benchmark name), so write UTF-8 even when stdout is redirected to a file.
    sys.stdout.reconfigure(encoding="utf-8")
    settings = get_settings()
    files = sorted(settings.paths.raw.glob(settings.data.file_glob))
    if not files:
        print(f"No portfolio files matching {settings.data.file_glob!r} in {settings.paths.raw}")
        return 1

    by_file: dict[str, list[SheetReport]] = {}
    month_of: dict[str, date] = {}
    h1("1. FILES")
    for f in files:
        reps, skipped, index = inspect_file(f)
        by_file[f.name] = reps
        dates = Counter(r.as_on for r in reps)
        month_of[f.name] = dates.most_common(1)[0][0]
        print(f"\n{f.name}  ({f.stat().st_size / 1e6:.1f} MB)")
        print(f"  as-on dates in title blocks: {dict((str(k), v) for k, v in dates.items())}")
        print(f"  scheme sheets: {len(reps)}   non-portfolio sheets: {skipped or 'none besides Index'}")
        print(f"  merged cell ranges in scheme sheets: {sum(len(r.merged) for r in reps)} "
              "(where they are: section 8)")
        sheet_names = {r.sheet for r in reps}
        print(f"  Index sheet: {len(index)} schemes; in Index but no sheet: "
              f"{sorted(set(index) - sheet_names) or 'none'}; sheet but not in Index: "
              f"{sorted(sheet_names - set(index)) or 'none'}")
        code_mismatch = [r.sheet for r in reps if r.code != r.sheet]
        print(f"  sheets whose cell A1 code differs from the sheet name: {code_mismatch or 'none'}")
        for r in reps:
            if r.problems:
                print(f"  ! {r.sheet}: {'; '.join(r.problems)}")

    order = sorted(files, key=lambda f: month_of[f.name])
    all_reps = [r for f in order for r in by_file[f.name]]

    h1("2. SCHEME LIST PER MONTH (added / dropped vs previous month)")
    prev: dict[str, str] | None = None
    for f in order:
        cur = {r.sheet: r.name for r in by_file[f.name]}
        print(f"\n{month_of[f.name]}  {len(cur)} schemes  ({f.name})")
        if prev is not None:
            for s in sorted(set(cur) - set(prev)):
                print(f"  + {s:10} {cur[s]}")
            for s in sorted(set(prev) - set(cur)):
                print(f"  - {s:10} {prev[s]}")
            if set(cur) == set(prev):
                print("  no change")
        prev = cur

    h1("3. HEADER ROWS")
    variants: dict[tuple, list[str]] = defaultdict(list)
    for r in all_reps:
        variants[(r.header_row, r.header_cols, r.extra_cols)].append(f"{month_of[r.file]}:{r.sheet}")
    for (row, cols, extra), where in sorted(variants.items(), key=lambda kv: -len(kv[1])):
        print(f"\nheader row {row}, {len(where)} sheets")
        print(f"  mapped columns: {', '.join(cols)}")
        print(f"  other header texts: {list(extra) or 'none'}")
        if len(where) < 40:
            print(f"  sheets: {', '.join(where)}")
    missing = [(f"{month_of[r.file]}:{r.sheet}", c) for r in all_reps
               for c in HEADER_PREFIXES.values() if c not in r.header_cols]
    print(f"\ncolumns missing from a header: {missing or 'none'}")

    h1("4. SECTION HEADINGS (runs of consecutive heading rows; run of 2 = main + sub)")
    as_first, as_second, as_single, deeper = Counter(), Counter(), Counter(), Counter()
    pairs = Counter()
    for r in all_reps:
        for _, run in heading_runs(r):
            if len(run) == 1:
                as_single[run[0]] += 1
            else:
                as_first[run[0]] += 1
                as_second[run[1]] += 1
                pairs[run[:2]] += 1
                if len(run) > 2:
                    deeper[run] += 1
    texts = set(as_first) | set(as_second) | set(as_single)
    print(f"\n{'heading text':55} {'1st of 2':>8} {'2nd of 2':>8} {'alone':>6}")
    for t in sorted(texts, key=lambda t: (-(as_first[t] + as_second[t] + as_single[t]), t)):
        print(f"{t[:55]:55} {as_first[t]:8} {as_second[t]:8} {as_single[t]:6}")
    print("\nmain + sub pairs seen:")
    for (a, b), n in pairs.most_common():
        print(f"  {n:5}  {a}  >  {b}")
    print(f"\nruns of 3 or more headings: {dict(deeper) or 'none'}")

    h1("5. SECTIONS: rows, ISINs and rating-column values (heading run in force -> holdings)")
    sec_rows: Counter = Counter()
    sec_isin: Counter = Counter()
    sec_rating: dict[tuple, Counter] = defaultdict(Counter)
    sec_noisin_names: dict[tuple, Counter] = defaultdict(Counter)
    for r in all_reps:
        run: tuple[str, ...] = ()
        last_kind = None
        for row in r.rows:
            if row.kind == "heading":
                run = run + (row.text,) if last_kind == "heading" else (row.text,)
            if row.kind != "blank":
                last_kind = row.kind
            if row.kind != "holding":
                continue
            sec_rows[run] += 1
            if ISIN_RE.match(norm(row.cells.get("isin", ""))):
                sec_isin[run] += 1
            else:
                sec_noisin_names[run][row.text] += 1
            sec_rating[run][norm(row.cells.get("rating", "")) or "(empty)"] += 1
    for run, n in sorted(sec_rows.items(), key=lambda kv: -kv[1]):
        print(f"\n[{' > '.join(run) or '(no heading)'}]  rows {n}, with ISIN {sec_isin[run]}")
        top = sec_rating[run].most_common(12)
        print(f"  rating/industry column ({len(sec_rating[run])} distinct): "
              + "; ".join(f"{k} x{v}" for k, v in top))
        if sec_noisin_names[run]:
            print("  rows without a valid ISIN: "
                  + "; ".join(f"{k} x{v}" for k, v in sec_noisin_names[run].most_common(10)))

    h1("6. RATING LABELS (all holdings with an ISIN outside equity headings)")
    ratings: Counter = Counter()
    for r in all_reps:
        for row in r.holdings:
            v = norm(row.cells.get("rating", ""))
            if v and re.search(r"\b(AAA|AA|A1|A|BBB|BB|D|SOV|SOVEREIGN)\b|\(SO\)|\(CE\)|\[|\]", v, re.I):
                ratings[v] += 1
    for k, v in sorted(ratings.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {v:6}  {k}")

    h1("7. TEXT IN NUMERIC COLUMNS (inside the portfolio block)")
    text_vals: Counter = Counter()
    text_where: dict[tuple, list[str]] = defaultdict(list)
    for r in all_reps:
        for row in r.rows:
            if row.kind in ("heading", "blank"):
                continue
            for c in NUMERIC_COLS:
                v = row.cells.get(c)
                if isinstance(v, str) and norm(v):
                    text_vals[(c, norm(v))] += 1
                    text_where[(c, norm(v))].append(f"{month_of[r.file]}:{r.sheet}!{row.n}")
    for (c, v), n in text_vals.most_common():
        where = text_where[(c, v)]
        print(f"  {n:6}  {c:9} {v!r}   e.g. {', '.join(where[:3])}")

    h1("8. ROWS THAT LOOK ODD")
    odd = 0
    for r in all_reps:
        for row in r.rows:
            reason = None
            if row.kind == "other":
                reason = "text/ISIN but no value and not a heading"
            elif row.kind == "holding" and FOOTNOTE_RE.match(row.text):
                reason = "holding whose name looks like a footnote/notes marker"
            elif row.kind == "holding" and not row.text:
                reason = "holding with an empty name"
            elif row.kind == "holding" and not is_num(row.cells.get("value")):
                reason = "% present but no market value"
            if reason:
                odd += 1
                c = row.cells
                print(f"  {month_of[r.file]}:{r.sheet}!{row.n}  {reason}: "
                      f"name={row.text[:50]!r} isin={norm(c.get('isin',''))!r} "
                      f"value={fmt(c.get('value'))} pct={c.get('pct')!r}")
    if not odd:
        print("  none")

    checks = {(r.file, r.sheet): block_checks(r) for r in all_reps}
    print("\nHoldings whose % cell differs from value / grand total by more than 0.01 point:")
    n_dis = 0
    for r in all_reps:
        for row, p, calc in checks[(r.file, r.sheet)]["pct_disagree"]:
            n_dis += 1
            print(f"  {month_of[r.file]}:{r.sheet}!{row.n}  {row.text[:45]!r}  value "
                  f"{fmt(row.cells.get('value'))}  % cell {p:.5f}  value/GT {calc:.5f}")
    print(f"  ({n_dis} rows)")
    print("\n'$0.00%' rows (footnote: less than 0.01%) whose value / grand total is 0.01% or more:")
    n_big = 0
    for r in all_reps:
        for row, p, calc in checks[(r.file, r.sheet)]["text_pct_big"]:
            n_big += 1
            print(f"  {month_of[r.file]}:{r.sheet}!{row.n}  {row.text[:45]!r}  value "
                  f"{fmt(row.cells.get('value'))}  value/GT {calc:.5f}")
    print(f"  ({n_big} rows)")
    zero = [(r, row) for r in all_reps for row in r.holdings
            if is_num(row.cells.get("value")) and row.cells["value"] == 0]
    print(f"\nHoldings with market value exactly 0: {len(zero)} rows; sections: "
          f"{dict(Counter(next((h.text for h in reversed(r.rows[:r.rows.index(row)]) if h.kind == 'heading'), '') for r, row in zero))}")
    neg = [(r, row) for r in all_reps for row in r.holdings
           if is_num(row.cells.get("value")) and row.cells["value"] < 0]
    print(f"Holdings with negative market value: {len(neg)} rows; names: "
          f"{dict(Counter(row.text for _, row in neg))}")
    dups = [(r, checks[(r.file, r.sheet)]["dup_isins"]) for r in all_reps
            if checks[(r.file, r.sheet)]["dup_isins"]]
    print(f"Sheets with an ISIN on more than one holding row: {len(dups)}")
    for r, d in dups:
        print(f"  {month_of[r.file]}:{r.sheet}  {', '.join(d)}")

    print("\nISIN column on holding rows:")
    prefixes, bad = Counter(), Counter()
    for r in all_reps:
        for row in r.holdings:
            v = norm(row.cells.get("isin", ""))
            if not v:
                prefixes["(empty)"] += 1
                continue
            prefixes[v[:4] if v.startswith("IDIA") else v[:2]] += 1
            if not isin_check_ok(v):
                bad[v] += 1
    print("  prefixes: " + ", ".join(f"{k} x{v}" for k, v in prefixes.most_common()))
    print(f"  values failing the ISIN check digit: {sum(bad.values())} rows, {len(bad)} distinct; "
          f"e.g. {', '.join(list(bad)[:8])}")

    print("\nMerged cells (row ranges are 1-based):")
    inside = Counter()
    for r in all_reps:
        for (r0, r1, c0, c1) in r.merged:
            where = ("title/header" if r0 + 1 <= (r.header_row or 0)
                     else "portfolio block" if r.grand_total_row and r0 + 1 < r.grand_total_row
                     else "below grand total")
            inside[where] += 1
    print("  " + ", ".join(f"{k}: {v}" for k, v in inside.items()))
    for r in all_reps:
        for (r0, r1, c0, c1) in r.merged:
            if r.grand_total_row and r.header_row < r0 + 1 < r.grand_total_row:
                print(f"  inside block: {month_of[r.file]}:{r.sheet} rows {r0 + 1}-{r1} cols {c0}-{c1 - 1}")

    print("\nFirst footnote-like row BEFORE the grand total (would end the block early "
          "if the parser stopped at the first footnote):")
    early = [(r, r.first_footnote_row) for r in all_reps
             if r.first_footnote_row and r.grand_total_row and r.first_footnote_row < r.grand_total_row]
    for r, n in early:
        print(f"  {month_of[r.file]}:{r.sheet}!{n}  grand total at {r.grand_total_row}")
    if not early:
        print("  none")

    h1("9. FR-0.3 CHECK: holdings vs GRAND TOTAL, per sheet")
    print("value in Rs lakhs; % as fractions of AUM (1.0 = 100%). "
          "'$' = rows whose % is text; '$ calc' = their % if computed as value / grand total.")
    hdr = (f"{'month':10} {'sheet':10} {'rows':>5} {'ISIN':>5} {'value sum':>14} {'grand total':>14} "
           f"{'diff':>9} {'% sum':>8} {'$':>3} {'$ calc':>8} {'% + $calc':>9} {'max dev':>8} {'Tot!':>4}")
    print(hdr)
    flagged = []
    for r in all_reps:
        k = checks[(r.file, r.sheet)]
        diff =(k["value_sum"] - k["gt_value"]) if k["gt_value"] is not None else None
        pct_all = k["pct_sum"] + k.get("text_pct_computed", 0.0)
        print(f"{str(month_of[r.file]):10} {r.sheet:10} {k['holdings']:5} {k['with_isin']:5} "
              f"{k['value_sum']:14,.2f} {fmt(k['gt_value']):>14} {fmt(diff):>9} {k['pct_sum']:8.5f} "
              f"{k['text_pct']:3} {k.get('text_pct_computed', 0):8.5f} {pct_all:9.5f} "
              f"{k.get('max_pct_dev', 0):8.1e} {len(k['total_mismatches']):4}")
        if (diff is None or abs(diff) > VALUE_TOL_LAKHS or abs(pct_all - 1) > PCT_TOL
                or k["total_mismatches"]):
            flagged.append((r, k, diff, pct_all))
    print(f"\nSheets outside tolerance (value diff > {VALUE_TOL_LAKHS} lakh, "
          f"or |% + $calc - 1| > {PCT_TOL}, or a Total that does not match its rows): {len(flagged)}")
    for r, k, diff, pct_all in flagged:
        print(f"\n  {month_of[r.file]}:{r.sheet}  value diff {fmt(diff)}  % sum {pct_all:.5f}")
        for n, start, rv, tv, rp, tp in k["total_mismatches"]:
            print(f"    Total row {n} (rows from {start}): rows sum {rv:,.2f} / {rp:.5f}, "
                  f"Total says {fmt(tv)} / {tp!r}")
    months = Counter()
    isins = Counter()
    for r in all_reps:
        k = checks[(r.file, r.sheet)]
        months[month_of[r.file]] += k["holdings"]
        isins[month_of[r.file]] += k["with_isin"]
    print("\nholding rows per month (rows with a 12-character ISIN-shaped value): "
          + ", ".join(f"{m}: {months[m]} ({isins[m]})" for m in sorted(months)))
    print("largest |% - value/grand total| over all holdings: "
          f"{max(k.get('max_pct_dev', 0) for k in checks.values()):.2e}")
    print("largest computed % among '$0.00%' rows: "
          f"{max(k.get('max_text_pct_computed', 0) for k in checks.values()):.6f}")

    h1("10. END OF THE PORTFOLIO BLOCK AND THE TAIL BELOW IT")
    tails = Counter(r.tail_first[:60] for r in all_reps)
    print("first text below GRAND TOTAL:")
    for t, n in tails.most_common():
        print(f"  {n:5}  {t!r}")
    print("\nlast row of the sheet (benchmark line), 8 examples:")
    for r in all_reps[:8]:
        print(f"  {r.sheet:10} {r.tail_last[:110]!r}")

    h1("11. PER SHEET: title block, headings, Total and GRAND TOTAL rows")
    for f in order:
        for r in by_file[f.name]:
            print(f"\n--- {month_of[f.name]} {r.sheet} | {r.name} | as on {r.as_on} | header row "
                  f"{r.header_row} | {len(r.holdings)} holdings | GT row {r.grand_total_row} | "
                  f"tail {r.tail_rows} rows")
            print(f"    {r.description[:120]}")
            for row in r.rows:
                if row.kind == "heading":
                    print(f"    {row.n:5}  H  {row.text}")
                elif row.kind in ("total", "grand_total"):
                    print(f"    {row.n:5}  {'T' if row.kind == 'total' else 'GT'} {row.text}  "
                          f"{fmt(row.cells.get('value'))}  {row.cells.get('pct')!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
