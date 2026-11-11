"""row_wise: one chunk per holding, every field labelled (spec §6.3, chunker 2).

Hypothesis: best for precise lookups ("what % does the Flexi Cap Fund hold in
ICICI Bank?"), because the one row that answers the question is a small,
focused chunk whose embedding is all about that holding. Expected to fail
aggregations: top_k = 5 cannot hold all the bank rows of a scheme, let alone
its 85 equity rows.

Each line repeats the scheme, date and section, so a retrieved row still says
where it came from (the same stock appears in many schemes).
"""

from __future__ import annotations

import pandas as pd

from src.chunking.base import Chunker, ChunkSet, _clean, format_row_labelled, prepare_sheet, row_key


class RowWiseChunker(Chunker):
    name = "row_wise"
    OPTIONS: dict[str, type] = {}

    def build(self, sheet: pd.DataFrame) -> ChunkSet:
        info, rows = prepare_sheet(sheet)
        return ChunkSet(chunks=[
            self.make_chunk(self.chunk_id(info, n), format_row_labelled(row, info), info,
                            _clean(row.section), [row_key(row)])
            for n, row in enumerate(rows)
        ])
