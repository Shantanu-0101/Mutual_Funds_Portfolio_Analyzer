"""scheme_level: the whole scheme in one chunk (spec §6.3, chunker 4).

Hypothesis: gives the LLM full context, so aggregations ("total % in banks")
can be answered from one chunk. But most schemes are far over the embedding
model's 512 tokens (the 85-holding Flexi Cap sheet is ~2,500), so the
embedding only "sees" roughly the first 10 holdings and retrieval should be
weak. That truncation is recorded on each chunk, not hidden.

``on_overflow: truncate_and_warn`` is the only supported value: the text is
kept whole (the LLM gets all of it), the embedding model truncates, and the
chunk is flagged ``truncated``. No other overflow policy is implemented, so
any other value is an error rather than silently ignored.
"""

from __future__ import annotations

import logging

import pandas as pd

from src.chunking.base import ALL_SECTIONS, Chunker, ChunkingError, ChunkSet, format_table, prepare_sheet

log = logging.getLogger(__name__)

ON_OVERFLOW = ("truncate_and_warn",)


class SchemeLevelChunker(Chunker):
    name = "scheme_level"
    OPTIONS = {"on_overflow": str}

    def _check_options(self) -> None:
        if self.options["on_overflow"] not in ON_OVERFLOW:
            raise ChunkingError(f"chunking.scheme_level.on_overflow must be one of {ON_OVERFLOW}")

    def build(self, sheet: pd.DataFrame) -> ChunkSet:
        info, rows = prepare_sheet(sheet)
        table = format_table(rows, info, ALL_SECTIONS)
        chunk = self.make_chunk(self.chunk_id(info, 0), table.text, info, ALL_SECTIONS,
                                [k for k, _, _ in table.row_spans])
        if chunk.truncated:
            log.debug("%s: %d tokens > %d, embedding truncated", chunk.id, chunk.n_tokens, self.embed_max_tokens)
        return ChunkSet(chunks=[chunk])
