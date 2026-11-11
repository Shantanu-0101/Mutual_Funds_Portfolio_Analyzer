"""Shared pieces for every chunker (task 2.1, spec §6.3).

Why one shared module: the experiment compares chunkers, so they must differ
**only** in how they group rows. The chunk object, the way a row is written as
text, the token counter and the truncation rule all live here, and each
chunker file only decides which rows go together.

Text formats
------------
Multi-row chunks (header_window, scheme_level, section_aware, hierarchical
parents) and the flattened sheet that fixed_size cuts up all use one table
format::

    Scheme: ADITYA BIRLA SUN LIFE FLEXI CAP FUND
    As on: 2026-09-30
    Section: Equity & Equity Related
    Instrument | ISIN | Industry/Rating | Qty | Value (Rs L) | % to AUM
    [Equity & Equity Related > a) Listed/awaiting listing on Stock Exchanges]
    ICICI Bank Ltd. | INE090A01021 | Banks | 11849171 | 156610.49 | 5.60

The ``[section > sub-section]`` marker line is written each time the
section or sub-section changes inside a chunk. It is not in the spec's
example; it is added because a chunk that spans sections (scheme_level,
some header_window chunks) would otherwise lose which rows are debt and which
are equity. Every multi-row chunker gets it, so fairness is kept.

row_wise (and the hierarchical children) write one holding per line with
every field labelled, see ``format_row_labelled``.

Percent values are in percent units with 2 decimals (5.60 means 5.60 %).
Rows the file shows as ``$0.00%`` (flag ``lt_0.01``) are written ``<0.01``.

Tokens
------
``n_tokens`` counts what the embedding model actually sees: word pieces from
the bge-small tokenizer **plus** its 2 special tokens ([CLS], [SEP]).
``truncated`` is true when that exceeds ``embedding.max_tokens`` (512): the
model then embeds only the start of the chunk. The full text is still stored
and shown to the LLM.
"""

from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from typing import Any, ClassVar, Iterable, Protocol, Sequence

import pandas as pd

RowKey = tuple[str, str, int]  # (source_file, source_sheet, source_row): FR-1.1

TABLE_HEADER = "Instrument | ISIN | Industry/Rating | Qty | Value (Rs L) | % to AUM"
ALL_SECTIONS = "ALL"
LT_001_FLAG = "lt_0.01"
MISSING = "-"

# Columns a parsed sheet must have (a subset of holdings.parquet).
REQUIRED_COLUMNS = (
    "amc", "scheme_code", "scheme", "as_of_date", "section", "subsection", "instrument", "isin",
    "industry_or_rating", "quantity", "market_value_lakhs", "pct_nav", "pct_nav_flag",
    "source_file", "source_sheet", "source_row",
)


class ChunkingError(ValueError):
    """A chunker got input or options it cannot work with."""


# --------------------------------------------------------------------------- tokens

class Tokenizer(Protocol):
    """What the chunkers need from a tokenizer.

    ``offsets(text)`` returns one (start, end) character range per word piece,
    without special tokens. ``n_special`` is how many special tokens the
    embedding model adds around every input.
    """

    name: str
    n_special: int

    def offsets(self, text: str) -> list[tuple[int, int]]: ...


class HFTokenizer:
    """The embedding model's own tokenizer (bge-small: BERT WordPiece, uncased)."""

    def __init__(self, model: str):
        from transformers import AutoTokenizer  # heavy import, only when really used

        tok = AutoTokenizer.from_pretrained(model)
        backend = tok.backend_tokenizer
        backend.no_truncation()  # we count full length; truncation is what we measure
        backend.no_padding()
        self._backend = backend
        self.name = model
        self.n_special = len(tok("")["input_ids"])

    def offsets(self, text: str) -> list[tuple[int, int]]:
        return list(self._backend.encode(text, add_special_tokens=False).offsets)


@lru_cache(maxsize=2)
def get_tokenizer(model: str) -> HFTokenizer:
    return HFTokenizer(model)


def count_tokens(tokenizer: Tokenizer, text: str) -> int:
    """Tokens the embedding model sees for ``text`` (word pieces + special tokens)."""
    return len(tokenizer.offsets(text)) + tokenizer.n_special


# --------------------------------------------------------------------------- chunk

@dataclass(frozen=True)
class Chunk:
    """One piece of text stored (or, for hierarchical parents, looked up) as a unit."""

    id: str
    text: str
    chunker: str
    amc: str
    scheme_code: str
    scheme: str
    as_of_date: str
    section: str
    source_rows: tuple[RowKey, ...]
    n_tokens: int
    truncated: bool
    parent_id: str | None = None

    def metadata(self) -> dict[str, Any]:
        """Everything except id and text, as plain values (Phase 3 flattens it for Chroma)."""
        return {
            "chunker": self.chunker, "amc": self.amc, "scheme_code": self.scheme_code,
            "scheme": self.scheme, "as_of_date": self.as_of_date, "section": self.section,
            "source_rows": [list(k) for k in self.source_rows], "parent_id": self.parent_id,
            "n_tokens": self.n_tokens, "truncated": self.truncated,
        }


@dataclass
class ChunkSet:
    """Output of one chunker on one scheme-month.

    ``chunks`` are what gets embedded. ``parents`` is empty except for
    hierarchical, whose children point at them through ``parent_id``.
    """

    chunks: list[Chunk]
    parents: list[Chunk] = field(default_factory=list)


@dataclass(frozen=True)
class SheetInfo:
    amc: str
    scheme_code: str
    scheme: str
    as_of_date: str


# --------------------------------------------------------------------------- formatting

def _clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return MISSING
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text.replace("|", "/") if text else MISSING


def fmt_pct(pct: float | None, flag: str | None) -> str:
    if flag == LT_001_FLAG:
        return "<0.01"
    if pct is None or (isinstance(pct, float) and math.isnan(pct)):
        return MISSING
    return f"{pct:.2f}"


def fmt_qty(q: float | None) -> str:
    if q is None or (isinstance(q, float) and math.isnan(q)):
        return MISSING
    if float(q).is_integer():
        return str(int(q))
    return f"{q:.4f}".rstrip("0").rstrip(".")


def fmt_value(v: float | None) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return MISSING
    return f"{v:.2f}"


def row_key(row: Any) -> RowKey:
    return (str(row.source_file), str(row.source_sheet), int(row.source_row))


def group_label(row: Any) -> str:
    sub = _clean(row.subsection)
    return f"[{_clean(row.section)}]" if sub == MISSING else f"[{_clean(row.section)} > {sub}]"


def format_row(row: Any) -> str:
    """One holding as a pipe-separated line under ``TABLE_HEADER``."""
    return " | ".join((
        _clean(row.instrument), _clean(row.isin), _clean(row.industry_or_rating),
        fmt_qty(row.quantity), fmt_value(row.market_value_lakhs), fmt_pct(row.pct_nav, row.pct_nav_flag),
    ))


def format_row_labelled(row: Any, info: SheetInfo) -> str:
    """One holding as a self-contained line with every field named (row_wise, hierarchical children)."""
    return " | ".join((
        f"Scheme: {_clean(info.scheme)}",
        f"As on: {info.as_of_date}",
        f"Section: {_clean(row.section)}",
        f"Sub-section: {_clean(row.subsection)}",
        f"Instrument: {_clean(row.instrument)}",
        f"ISIN: {_clean(row.isin)}",
        f"Industry/Rating: {_clean(row.industry_or_rating)}",
        f"Qty: {fmt_qty(row.quantity)}",
        f"Value (Rs L): {fmt_value(row.market_value_lakhs)}",
        f"% to AUM: {fmt_pct(row.pct_nav, row.pct_nav_flag)}",
    ))


@dataclass
class TableText:
    """Formatted table plus where each holding's line sits in it (needed by fixed_size)."""

    text: str
    row_spans: list[tuple[RowKey, int, int]]  # (row key, start char, end char)


def format_table(rows: Sequence[Any], info: SheetInfo, section: str) -> TableText:
    """The shared multi-row table format (see module docstring)."""
    lines = [f"Scheme: {_clean(info.scheme)}", f"As on: {info.as_of_date}", f"Section: {section}", TABLE_HEADER]
    spans: list[tuple[RowKey, int, int]] = []
    pos = sum(len(x) + 1 for x in lines)  # start of the next line
    current = None
    for row in rows:
        label = group_label(row)
        if label != current:
            lines.append(label)
            pos += len(label) + 1
            current = label
        line = format_row(row)
        spans.append((row_key(row), pos, pos + len(line)))
        lines.append(line)
        pos += len(line) + 1
    return TableText(text="\n".join(lines), row_spans=spans)


def section_label(rows: Iterable[Any]) -> str:
    """The ``Section:`` value for a group of rows: the one section, or all of them joined by '; '."""
    seen: list[str] = []
    for r in rows:
        s = _clean(r.section)
        if s not in seen:
            seen.append(s)
    return "; ".join(seen)


# --------------------------------------------------------------------------- input

def _iso(value: Any) -> str:
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()[:10]
    return str(value)[:10]


def prepare_sheet(sheet: pd.DataFrame) -> tuple[SheetInfo, list[Any]]:
    """Check that ``sheet`` is one scheme-month and return its info and rows in file order."""
    missing = [c for c in REQUIRED_COLUMNS if c not in sheet.columns]
    if missing:
        raise ChunkingError(f"sheet is missing columns: {missing}")
    if sheet.empty:
        raise ChunkingError("sheet has no holdings")
    for col in ("scheme_code", "as_of_date", "source_file"):
        values = sheet[col].astype(str).unique()
        if len(values) != 1:
            raise ChunkingError(f"a chunker takes one scheme-month at a time; got {col} values {sorted(values)}")
    first = sheet.iloc[0]
    info = SheetInfo(amc=str(first["amc"]), scheme_code=str(first["scheme_code"]),
                     scheme=str(first["scheme"]), as_of_date=_iso(first["as_of_date"]))
    rows = list(sheet.sort_values("source_row", kind="stable").itertuples(index=False))
    keys = [row_key(r) for r in rows]
    if len(set(keys)) != len(keys):
        raise ChunkingError(f"duplicate row keys in {info.scheme_code} {info.as_of_date}")
    return info, rows


# --------------------------------------------------------------------------- base class

class Chunker(ABC):
    """Base class. Subclasses set ``name``, ``OPTIONS`` and implement ``build``.

    ``OPTIONS`` maps each config key under ``chunking.<name>`` to its type.
    Unknown or missing keys are errors, like in src/config.py, so a typo in
    config.yaml cannot quietly change an experiment.
    """

    name: ClassVar[str]
    OPTIONS: ClassVar[dict[str, type]] = {}

    def __init__(self, tokenizer: Tokenizer, embed_max_tokens: int = 512, **options: Any):
        unknown = options.keys() - self.OPTIONS.keys()
        missing = self.OPTIONS.keys() - options.keys()
        if unknown or missing:
            raise ChunkingError(f"chunking.{self.name}: unknown keys {sorted(unknown)}, missing keys {sorted(missing)}")
        for key, typ in self.OPTIONS.items():
            if not isinstance(options[key], typ) or isinstance(options[key], bool) and typ is not bool:
                raise ChunkingError(f"chunking.{self.name}.{key} must be {typ.__name__}, got {options[key]!r}")
        self.tokenizer = tokenizer
        self.embed_max_tokens = embed_max_tokens
        self.options = options
        self._check_options()

    def _check_options(self) -> None:
        """Value checks beyond types; override where needed."""

    @abstractmethod
    def build(self, sheet: pd.DataFrame) -> ChunkSet:
        """Chunk one scheme-month (rows of holdings.parquet for one sheet)."""

    def chunk(self, sheet: pd.DataFrame) -> list[Chunk]:
        """The spec's interface: the chunks that get embedded."""
        return self.build(sheet).chunks

    # helpers for subclasses
    def chunk_id(self, info: SheetInfo, n: int | str) -> str:
        return f"{self.name}:{info.as_of_date}:{info.scheme_code}:{n}"

    def make_chunk(self, chunk_id: str, text: str, info: SheetInfo, section: str,
                   rows: Iterable[RowKey], parent_id: str | None = None) -> Chunk:
        n = count_tokens(self.tokenizer, text)
        return Chunk(id=chunk_id, text=text, chunker=self.name, amc=info.amc, scheme_code=info.scheme_code,
                     scheme=info.scheme, as_of_date=info.as_of_date, section=section,
                     source_rows=tuple(rows), n_tokens=n, truncated=n > self.embed_max_tokens, parent_id=parent_id)


def positive_int(chunker: str, key: str, value: int) -> None:
    if value <= 0:
        raise ChunkingError(f"chunking.{chunker}.{key} must be > 0, got {value}")
