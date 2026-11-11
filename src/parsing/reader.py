"""Read a legacy ``.xls`` workbook into plain Python rows (task 1.1, FR-1.1).

Why this exists: the parser needs the real Excel row numbers (``source_row``)
and the merged-cell ranges, and it should not care about xlrd details. This
module is the only place that talks to xlrd; everything after it works on
``RawSheet`` objects, which tests can also build by hand.

Cells come out as: ``float`` for numbers (and Excel dates, unconverted),
``str`` for text, ``bool`` for booleans, ``""`` for empty cells and
``"#ERROR"`` for Excel error cells.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import xlrd

from src.parsing.values import norm


@dataclass(frozen=True)
class RawSheet:
    """One worksheet. ``rows[i]`` is Excel row ``i + 1``."""

    file: str
    name: str
    rows: list[list[object]]
    # xlrd convention, 0-based: (first_row, last_row + 1, first_col, last_col + 1)
    merged: list[tuple[int, int, int, int]] = field(default_factory=list)

    def cell(self, r: int, c: int) -> object:
        """Cell at 0-based (r, c), or "" when outside the used range."""
        if r < len(self.rows) and c < len(self.rows[r]):
            return self.rows[r][c]
        return ""


@dataclass(frozen=True)
class RawWorkbook:
    file: str
    sheets: list[RawSheet]
    index: dict[str, str]   # Index sheet: scheme short code -> scheme name (empty if no Index)


def _cell_value(sh: xlrd.sheet.Sheet, r: int, c: int) -> object:
    ctype = sh.cell_type(r, c)
    value = sh.cell_value(r, c)
    if ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return ""
    if ctype in (xlrd.XL_CELL_NUMBER, xlrd.XL_CELL_DATE):
        return float(value)
    if ctype == xlrd.XL_CELL_BOOLEAN:
        return bool(value)
    if ctype == xlrd.XL_CELL_ERROR:
        return "#ERROR"
    return str(value)


def read_sheet(file: str, sh: xlrd.sheet.Sheet) -> RawSheet:
    rows = [[_cell_value(sh, r, c) for c in range(sh.row_len(r))] for r in range(sh.nrows)]
    return RawSheet(file=file, name=sh.name, rows=rows, merged=[tuple(m) for m in sh.merged_cells])


def _read_index(sheet: RawSheet) -> dict[str, str]:
    """Index sheet columns: Scheme Code (AB001…), Scheme Short code, Scheme Name."""
    out: dict[str, str] = {}
    for row in sheet.rows:
        texts = [norm(v) for v in row]
        if len(texts) >= 3 and texts[1] and texts[1].lower() != "scheme short code":
            out[texts[1]] = texts[2]
    return out


def read_workbook(path: Path | str) -> RawWorkbook:
    """Read every sheet. ``formatting_info=True`` is required for merged cells:
    without it xlrd reports none at all (the mistake behind spec §3.2's "no merges")."""
    path = Path(path)
    wb = xlrd.open_workbook(str(path), formatting_info=True)
    sheets: list[RawSheet] = []
    index: dict[str, str] = {}
    for sh in wb.sheets():
        raw = read_sheet(path.name, sh)
        if sh.name.strip().lower() == "index":
            index = _read_index(raw)
        else:
            sheets.append(raw)
    return RawWorkbook(file=path.name, sheets=sheets, index=index)
