"""fixed_size: flatten the sheet to text and cut every N tokens with overlap (spec §6.3, chunker 1).

Hypothesis: the naive baseline everyone starts with. It ignores the table's
structure, so it is expected to cut rows in half, and every chunk after the
first loses the scheme name, the date and the column header. Kept on purpose
as the "what if you don't think about tables" reference point.

How it works:

1. The scheme's rows are written in the shared table format (exactly the
   text scheme_level uses), recording each holding's character range.
2. That text is tokenized with the embedding model's tokenizer; windows of
   ``chunk_tokens`` word pieces start every ``chunk_tokens - overlap_tokens``
   pieces. The last window ends at the end of the text.
3. A chunk's text is the original text from its first piece's start to its
   last piece's end (so it is a true substring of the flattened sheet).
4. ``source_rows`` (FR-2.0) are all holdings whose character range overlaps
   the chunk's range, even by one character: a row cut in half belongs to
   both chunks.

Windows never cross schemes: each scheme-month is flattened on its own, so a
chunk id still names one scheme. ``chunk_tokens`` counts word pieces only;
``n_tokens`` adds the 2 special tokens like every other chunker.
"""

from __future__ import annotations

import pandas as pd

from src.chunking.base import (
    ALL_SECTIONS, Chunker, ChunkingError, ChunkSet, RowKey, positive_int, format_table, prepare_sheet,
)


def token_windows(n_pieces: int, size: int, overlap: int) -> list[tuple[int, int]]:
    """[start, end) word-piece index windows covering ``n_pieces``."""
    if n_pieces == 0:
        return []
    step = size - overlap
    out = []
    start = 0
    while True:
        end = min(start + size, n_pieces)
        out.append((start, end))
        if end == n_pieces:
            return out
        start += step


def rows_in_range(spans: list[tuple[RowKey, int, int]], start: int, end: int) -> list[RowKey]:
    """Row keys whose [row_start, row_end) overlaps [start, end)."""
    return [k for k, rs, re_ in spans if rs < end and re_ > start]


class FixedSizeChunker(Chunker):
    name = "fixed_size"
    OPTIONS = {"chunk_tokens": int, "overlap_tokens": int}

    def _check_options(self) -> None:
        size, overlap = self.options["chunk_tokens"], self.options["overlap_tokens"]
        positive_int(self.name, "chunk_tokens", size)
        if not 0 <= overlap < size:
            raise ChunkingError(f"chunking.fixed_size.overlap_tokens must be in [0, chunk_tokens), got {overlap}")

    def build(self, sheet: pd.DataFrame) -> ChunkSet:
        info, rows = prepare_sheet(sheet)
        table = format_table(rows, info, ALL_SECTIONS)
        offsets = self.tokenizer.offsets(table.text)
        chunks = []
        for n, (a, b) in enumerate(token_windows(len(offsets), self.options["chunk_tokens"],
                                                 self.options["overlap_tokens"])):
            start, end = offsets[a][0], offsets[b - 1][1]
            chunks.append(self.make_chunk(self.chunk_id(info, n), table.text[start:end], info, ALL_SECTIONS,
                                          rows_in_range(table.row_spans, start, end)))
        return ChunkSet(chunks=chunks)
