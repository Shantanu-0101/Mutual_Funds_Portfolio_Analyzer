"""hierarchical: embed rows, answer from their whole sections (spec §6.3, chunker 6).

Hypothesis: get row_wise's precise retrieval **and** a whole section's
context. Small row-level children are embedded and searched; when a child is
retrieved, the LLM gets its parent section instead (Phase 3, FR-3.3), with
parents deduplicated. Expected cost: more context tokens per question.

- Children: the same text as row_wise, so their embeddings come from the
  same disk cache (FR-3.2). Ids ``hierarchical:<date>:<scheme>:<n>``.
- Parents: one per section per scheme, the **whole** section in the shared
  table format, never split. Ids ``hierarchical:<date>:<scheme>:p<n>``.
  Parents are never embedded, so the 512-token embedding limit does not
  apply to them; their ``truncated`` flag is informational only.
  (Decided 11 Nov 2026 after Phase 2: with section_aware's 512-token split,
  the Flexi Cap equity section became 7 parts of ~13 rows, so a parent
  would not have held the whole section.)
- Every child's ``parent_id`` is the section that contains its row.

Config: ``{child: row, parent: section}`` names the two levels. Those are the
only levels built, so any other value is an error.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from src.chunking.base import Chunker, ChunkingError, ChunkSet, Tokenizer, format_table, prepare_sheet, row_key
from src.chunking.row_wise import RowWiseChunker
from src.chunking.section_aware import group_by_section

LEVELS = {"child": "row", "parent": "section"}


class HierarchicalChunker(Chunker):
    name = "hierarchical"
    OPTIONS = {"child": str, "parent": str}

    def __init__(self, tokenizer: Tokenizer, embed_max_tokens: int = 512, **options):
        super().__init__(tokenizer, embed_max_tokens, **options)
        self._children = RowWiseChunker(tokenizer, embed_max_tokens)

    def _check_options(self) -> None:
        for key, expected in LEVELS.items():
            if self.options[key] != expected:
                raise ChunkingError(f"chunking.hierarchical.{key} must be {expected!r}, got {self.options[key]!r}")

    def build(self, sheet: pd.DataFrame) -> ChunkSet:
        info, rows = prepare_sheet(sheet)
        parents = []
        parent_of = {}
        for n, (section, section_rows) in enumerate(group_by_section(rows).items()):
            table = format_table(section_rows, info, section)
            parent = self.make_chunk(self.chunk_id(info, f"p{n}"), table.text, info, section,
                                     [row_key(r) for r in section_rows])
            parents.append(parent)
            for key in parent.source_rows:
                parent_of[key] = parent.id
        children = []
        for n, c in enumerate(self._children.chunk(sheet)):
            (key,) = c.source_rows
            children.append(replace(c, id=self.chunk_id(info, n), chunker=self.name, parent_id=parent_of[key]))
        return ChunkSet(chunks=children, parents=parents)
