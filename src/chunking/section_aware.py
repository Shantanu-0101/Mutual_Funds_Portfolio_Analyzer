"""section_aware: one chunk per section per scheme, split only when too long (spec §6.3, chunker 5).

Hypothesis: matches how a person reads the sheet ("Equity", "Debt
Instruments", "Money Market Instruments", ...), so questions like "how much
debt does this fund hold?" find one chunk that holds exactly the rows they
need, and no chunk ever mixes sections.

A section whose text is over ``max_tokens`` (counted like everywhere else:
word pieces + special tokens) is split greedily in file order: rows are
added to a part until the next row would push it over the limit. Every part
repeats the scheme, date, section and header lines, so each part can be
embedded whole. A single row that alone is over the limit (not seen in the
real data) becomes its own part and is flagged ``truncated``.

Sections are kept in order of first appearance; rows keep file order.
"""

from __future__ import annotations

import pandas as pd

from src.chunking.base import (
    Chunker, ChunkSet, SheetInfo, _clean, count_tokens, format_table, positive_int, prepare_sheet, row_key,
)


def group_by_section(rows: list) -> dict[str, list]:
    """Rows per section, sections in order of first appearance, rows in file order."""
    out: dict[str, list] = {}
    for row in rows:
        out.setdefault(_clean(row.section), []).append(row)
    return out


class SectionAwareChunker(Chunker):
    name = "section_aware"
    OPTIONS = {"max_tokens": int}

    def _check_options(self) -> None:
        positive_int(self.name, "max_tokens", self.options["max_tokens"])

    def _split(self, rows: list, info: SheetInfo, section: str) -> list[list]:
        limit = self.options["max_tokens"]
        if count_tokens(self.tokenizer, format_table(rows, info, section).text) <= limit:
            return [rows]
        parts, current = [], []
        for row in rows:
            candidate = current + [row]
            if current and count_tokens(self.tokenizer, format_table(candidate, info, section).text) > limit:
                parts.append(current)
                current = [row]
            else:
                current = candidate
        parts.append(current)
        return parts

    def build(self, sheet: pd.DataFrame) -> ChunkSet:
        info, rows = prepare_sheet(sheet)
        chunks = []
        for section, section_rows in group_by_section(rows).items():
            for part in self._split(section_rows, info, section):
                table = format_table(part, info, section)
                chunks.append(self.make_chunk(self.chunk_id(info, len(chunks)), table.text, info, section,
                                              [row_key(r) for r in part]))
        return ChunkSet(chunks=chunks)
