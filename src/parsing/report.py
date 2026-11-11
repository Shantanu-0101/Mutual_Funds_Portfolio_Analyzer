"""Write ``results/parse_report.md`` (task 1.9, FR-1.5–1.7).

Why: the report is how a human checks the parser without reading code. It puts
the summary and anything that needs attention first, and the full per-sheet
table (with each skipped tail block, FR-1.5) last.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.parsing.pipeline import ParseRun
from src.parsing.sheet_parser import FLAG_LT_001, FLAG_RECOMPUTED
from src.parsing.validate import LT_001_POINTS, PCT_TOL_POINTS, VALUE_TOL_LAKHS, recomputed_rows

IST = timezone(timedelta(hours=5, minutes=30))


def _f(x, nd=2) -> str:
    return "–" if x is None else f"{x:,.{nd}f}"


def _month(f) -> str:
    return str(f.as_of_date) if f.as_of_date else ", ".join(map(str, f.months_seen)) or "?"


def build_report(run: ParseRun, generated_at: datetime | None = None) -> str:
    generated_at = generated_at or datetime.now(IST)
    L: list[str] = []
    add = L.append
    checks = run.all_checks
    status = Counter(c.status for c in checks)

    add("# Parse report (Phase 1)\n")
    add("| | |\n|---|---|")
    add(f"| Generated | {generated_at:%d %b %Y %H:%M} IST by `python -m src.parsing` |")
    add(f"| Files | {len(run.files)} |")
    add(f"| Scheme sheets parsed | {len(checks)} (OK {status['OK']}, WARN {status['WARN']}, "
        f"ERROR {status['ERROR']}) |")
    add(f"| Sheets that failed to parse | {sum(len(f.failed) for f in run.files)} |")
    add(f"| Holdings | {len(run.holdings):,} |")
    add(f"| Tolerances | market value {VALUE_TOL_LAKHS} lakh; % to AUM {PCT_TOL_POINTS} points |")
    add("")
    add("% values are in percent units (5.60 = 5.60%). Rows are 1-based Excel rows. "
        "`pct_nav` comes from the file's `% to AUM`, except `$0.00%` cells and rows under "
        "`Other Current Assets / (Liabilities)`, which are value ÷ grand total (DATA_NOTES R6, Q1).\n")

    # ------------------------------------------------------------ 1. per month
    add("## 1. Summary per month\n")
    add("| As on | File | Sheets | Holdings | OK / WARN / ERROR | max abs(value diff) lakh | "
        "max abs(% dev) | `$0.00%` rows | recomputed rows | unknown rows | tail blocks skipped |")
    add("|---|---|---|---|---|---|---|---|---|---|---|")
    for f in run.files:
        st = Counter(c.status for c in f.checks)
        hs = [h for s in f.sheets for h in s.holdings]
        vd = [abs(c.value_diff) for c in f.checks if c.value_diff is not None]
        add(f"| {_month(f)} | `{f.file}` | {len(f.sheets)} | {len(hs):,} | "
            f"{st['OK']} / {st['WARN']} / {st['ERROR']} | {_f(max(vd, default=None))} | "
            f"{_f(max((abs(c.pct_dev) for c in f.checks), default=None), 4)} | "
            f"{sum(h['pct_nav_flag'] == FLAG_LT_001 for h in hs)} | "
            f"{sum(h['pct_nav_flag'] == FLAG_RECOMPUTED for h in hs)} | "
            f"{sum(len(s.unknown_rows) for s in f.sheets)} | {sum(s.tail_rows is not None for s in f.sheets)} |")
    add("")
    for f in run.files:
        extra = []
        if f.failed:
            extra.append(f"**sheets not parsed:** " + "; ".join(f"`{n}`: {e}" for n, e in f.failed))
        if f.not_portfolio:
            extra.append(f"sheets without a portfolio header (skipped): {f.not_portfolio}")
        if f.index_without_sheet:
            extra.append(f"listed in the Index sheet but no sheet: {f.index_without_sheet}")
        if f.sheet_without_index:
            extra.append(f"sheet but not in the Index: {f.sheet_without_index}")
        if extra:
            add(f"- `{f.file}`: " + "; ".join(extra))
    add("")

    # ------------------------------------------------------------ 2. attention
    add("## 2. Sheets with warnings or errors\n")
    bad = [c for c in checks if c.status != "OK"]
    if not bad:
        add("None.\n")
    for c in bad:
        add(f"- **{c.status}** {c.as_of_date} `{c.sheet}`")
        for m in c.errors:
            add(f"  - error: {m}")
        for m in c.warnings:
            add(f"  - warning: {m}")
    add("")

    # ------------------------------------------------------------ 3. % sums
    add(f"## 3. Schemes whose % to AUM sum is off by more than {PCT_TOL_POINTS} points\n")
    off = [c for c in checks if abs(c.pct_dev) > PCT_TOL_POINTS]
    if not off:
        add(f"None. Largest deviation: {max((abs(c.pct_dev) for c in checks), default=0):.4f} points.\n")
    else:
        add("| As on | Sheet | % sum | deviation |\n|---|---|---|---|")
        for c in sorted(off, key=lambda c: -abs(c.pct_dev)):
            add(f"| {c.as_of_date} | `{c.sheet}` | {c.pct_sum:.4f} | {c.pct_dev:+.4f} |")
        add("")

    # ------------------------------------------------------------ 4. recomputed
    add("## 4. `Other Current Assets` rows whose file % was replaced (differs by > 0.01 point)\n")
    add("ABSL's % cell on these rows is a balancing figure (DATA_NOTES §7). "
        "The table lists every row where the stored value differs from the file's cell.\n")
    rows = [(s, h) for f in run.files for s in f.sheets for h in recomputed_rows(s)]
    if not rows:
        add("None.\n")
    else:
        add("| As on | Sheet | Row | Instrument | Value (lakh) | file % | stored % |\n|---|---|---|---|---|---|---|")
        for s, h in rows:
            add(f"| {s.as_of_date} | `{s.sheet}` | {h['source_row']} | {h['instrument']} | "
                f"{_f(h['market_value_lakhs'])} | {_f(h['pct_nav_file'], 4)} | {_f(h['pct_nav'], 4)} |")
        add(f"\n{len(rows)} rows.\n")

    # ------------------------------------------------------------ 5. $ rows
    add("## 5. `$0.00%` holdings (\"less than 0.01%\")\n")
    lt = [(s, h) for f in run.files for s in f.sheets for h in s.holdings if h["pct_nav_flag"] == FLAG_LT_001]
    big = [(s, h) for s, h in lt if h["pct_nav"] >= LT_001_POINTS]
    add(f"{len(lt)} holdings; % stored as value ÷ grand total, flag `{FLAG_LT_001}`. "
        f"Of these, {len(big)} compute to 0.01% or more:\n")
    for s, h in big:
        add(f"- {s.as_of_date} `{s.sheet}` row {h['source_row']} {h['instrument']}: {h['pct_nav']:.4f}%")
    add("")

    # ------------------------------------------------------------ 6. mapping
    add("## 6. Section → asset_class, as applied\n")
    if len(run.holdings):
        g = (run.holdings.fillna({"section": "(none)", "subsection": "(none)"})
             .groupby(["section", "subsection", "asset_class", "asset_class_rule"], dropna=False)
             .size().reset_index(name="rows"))
        add("| Section | Sub-section | asset_class | rule | rows |\n|---|---|---|---|---|")
        for r in g.itertuples(index=False):
            add(f"| {r.section} | {r.subsection} | {r.asset_class} | {r.asset_class_rule} | {r.rows:,} |")
    add("")

    # ------------------------------------------------------------ 7. ISIN + names
    add("## 7. ISIN column and instrument names\n")
    if len(run.holdings):
        hd = run.holdings
        add(f"- Holdings without an ISIN: {int(hd['isin'].isna().sum()):,} "
            f"({dict(Counter(hd.loc[hd['isin'].isna(), 'instrument']).most_common(6))})")
        bad_isin = hd[hd["isin"].notna() & ~hd["isin_valid"]]
        add(f"- Values in the ISIN column that are not real ISINs (`isin_valid = False`): {len(bad_isin):,}; "
            f"prefixes {dict(Counter(bad_isin['isin'].str[:4]))}")
        sus = hd[hd["name_suspect"]]
        add(f"- Instrument names that look like footnote markers (kept as written, R7): {len(sus)}")
        for r in sus.itertuples(index=False):
            add(f"  - {r.as_of_date} `{r.source_sheet}` row {r.source_row}: {r.instrument!r}, "
                f"ISIN {r.isin}, value {r.market_value_lakhs:,.2f}")
        ignored = [(s, u) for f in run.files for s in f.sheets for u in s.ignored_rows]
        add(f"- Block rows with values only in unmapped columns (ignored, FR-1.2): {len(ignored)}")
        for s, u in ignored:
            add(f"  - {s.as_of_date} `{s.sheet}` row {u.row}: {u.text!r}")
        notes = [(s, n) for f in run.files for s in f.sheets for n in s.notes]
        cols = Counter(n for _, n in notes)
        for n, k in cols.items():
            add(f"- {k} sheet(s): {n}")
    add("")

    # ------------------------------------------------------------ 8. per sheet
    add("## 8. Every sheet\n")
    add("Tail = the rows below the portfolio block (footnotes, notes, benchmark), skipped as one block.\n")
    add("| As on | Sheet | Holdings | % sum | value diff (lakh) | Totals checked | Blank rows | Block rows | "
        "Tail skipped | Status |")
    add("|---|---|---|---|---|---|---|---|---|---|")
    for f in run.files:
        for s, c in zip(f.sheets, f.checks):
            tail = f"{s.tail_rows[0]}–{s.tail_rows[1]}" if s.tail_rows else "–"
            add(f"| {s.as_of_date} | `{s.sheet}` | {c.n_holdings} | {c.pct_sum:.4f} | {_f(c.value_diff)} | "
                f"{c.totals_checked} | {s.blank_rows} | {s.block_first_row}–{s.block_last_row} | {tail} | "
                f"{c.status} |")
    add("")
    return "\n".join(L)


def write_report(run: ParseRun, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_report(run), encoding="utf-8")
    return path
