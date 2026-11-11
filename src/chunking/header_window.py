"""header_window: N consecutive rows per chunk, header repeated (spec §6.3, chunker 3).

Hypothesis: a middle ground. Each chunk is small enough to embed fully, keeps
some neighbouring rows (helpful for "top holdings" or small groups), and,
unlike fixed_size, never cuts a row in half or loses the column header,
because the scheme, date, section and header line are repeated in every chunk.

Windows run over the whole sheet in file order and do not restart at section
boundaries: that is what separates this chunker from section_aware. A window
that spans two sections lists both on its ``Section:`` line, and the
``[section > sub-section]`` marker shows where the change happens.
"""

from __future__ import annotations

import pandas as pd

from src.chunking.base import Chunker, ChunkSet, format_table, positive_int, prepare_sheet, section_label


class HeaderWindowChunker(Chunker):
    name = "header_window"
    OPTIONS = {"rows_per_chunk": int}

    def _check_options(self) -> None:
        positive_int(self.name, "rows_per_chunk", self.options["rows_per_chunk"])

    def build(self, sheet: pd.DataFrame) -> ChunkSet:
        info, rows = prepare_sheet(sheet)
        size = self.options["rows_per_chunk"]
        chunks = []
        for n, start in enumerate(range(0, len(rows), size)):
            window = rows[start:start + size]
            section = section_label(window)
            table = format_table(window, info, section)
            chunks.append(self.make_chunk(self.chunk_id(info, n), table.text, info, section,
                                          [k for k, _, _ in table.row_spans]))
        return ChunkSet(chunks=chunks)
