"""Parse every portfolio file into the three canonical tables (task 1.10, FR-1.8).

Why one function for all files: every later stage (chunkers, gold answers,
baseline) reads the same ``holdings.parquet``, so differences between methods
come from chunking, not from parsing (spec §4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.parsing.reader import read_workbook
from src.parsing.sheet_parser import ParseError, SheetResult, parse_sheet
from src.parsing.validate import SheetChecks, check_sheet

HOLDINGS_FILE = "holdings.parquet"
TOTALS_FILE = "totals.parquet"
SCHEMES_FILE = "schemes.parquet"


@dataclass
class FileResult:
    file: str
    sheets: list[SheetResult] = field(default_factory=list)
    checks: list[SheetChecks] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)       # (sheet, error)
    not_portfolio: list[str] = field(default_factory=list)            # sheets without a header
    index_without_sheet: list[str] = field(default_factory=list)
    sheet_without_index: list[str] = field(default_factory=list)

    @property
    def as_of_date(self):
        dates = sorted({s.as_of_date for s in self.sheets})
        return dates[0] if len(dates) == 1 else None

    @property
    def months_seen(self) -> list:
        return sorted({s.as_of_date for s in self.sheets})


@dataclass
class ParseRun:
    files: list[FileResult]
    holdings: pd.DataFrame
    totals: pd.DataFrame
    schemes: pd.DataFrame

    @property
    def all_checks(self) -> list[SheetChecks]:
        return [c for f in self.files for c in f.checks]

    @property
    def n_errors(self) -> int:
        return sum(c.status == "ERROR" for c in self.all_checks) + sum(len(f.failed) for f in self.files)


def parse_file(path: Path) -> FileResult:
    wb = read_workbook(path)
    out = FileResult(file=wb.file)
    for raw in wb.sheets:
        try:
            res = parse_sheet(raw)
        except ParseError as e:
            out.failed.append((raw.name, str(e)))
            continue
        if res is None:
            out.not_portfolio.append(raw.name)
            continue
        out.sheets.append(res)
        out.checks.append(check_sheet(res))
    names = {s.sheet for s in out.sheets} | {name for name, _ in out.failed}
    if wb.index:
        out.index_without_sheet = sorted(set(wb.index) - names)
        out.sheet_without_index = sorted(names - set(wb.index))
    return out


def _scheme_row(s: SheetResult, ck: SheetChecks) -> dict:
    return {
        "scheme_code": s.scheme_code, "scheme": s.scheme, "description": s.description,
        "as_of_date": s.as_of_date, "source_file": s.file, "source_sheet": s.sheet,
        "header_row": s.header_row, "block_first_row": s.block_first_row,
        "block_last_row": s.block_last_row, "end_rule": s.end_rule,
        "grand_total_row": s.grand_total_row, "grand_total_lakhs": s.grand_total_lakhs,
        "tail_first_row": s.tail_rows[0] if s.tail_rows else None,
        "tail_last_row": s.tail_rows[1] if s.tail_rows else None,
        "n_holdings": len(s.holdings), "extra_columns": " | ".join(s.extra_columns) or None,
        "pct_sum": ck.pct_sum, "status": ck.status,
    }


def parse_files(paths: list[Path]) -> ParseRun:
    files = [parse_file(p) for p in paths]
    files.sort(key=lambda f: (f.months_seen[:1], f.file))
    holdings = [h for f in files for s in f.sheets for h in s.holdings]
    totals = [t for f in files for s in f.sheets for t in s.totals]
    schemes = [_scheme_row(s, c) for f in files for s, c in zip(f.sheets, f.checks)]
    return ParseRun(files=files, holdings=pd.DataFrame(holdings), totals=pd.DataFrame(totals),
                    schemes=pd.DataFrame(schemes))


def write_tables(run: ParseRun, processed_dir: Path) -> list[Path]:
    processed_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for name, df in ((HOLDINGS_FILE, run.holdings), (TOTALS_FILE, run.totals), (SCHEMES_FILE, run.schemes)):
        path = processed_dir / name
        df.to_parquet(path, index=False)
        out.append(path)
    return out
