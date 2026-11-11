"""hierarchical: embed rows, answer from their sections (spec §6.3, chunker 6).

Hypothesis: get row_wise's precise retrieval **and** section_aware's wide
context. Small row-level children are embedded and searched; when a child
is retrieved, the LLM gets its parent section chunk instead (Phase 3, FR-3.3),
with parents deduplicated. Expected cost: more context tokens per question.

- Children: the same text as row_wise, so their embeddings come from the
  same disk cache (FR-3.2). Ids ``hierarchical:<date>:<scheme>:<n>``.
- Parents: the same text as section_aware chunks (including its split of
  sections over ``chunking.section_aware.max_tokens``). Ids
  ``hierarchical:<date>:<scheme>:p<n>``. Parents are never embedded, so
  their ``truncated`` flag is informational only.
- Every child's ``parent_id`` is the parent part that contains its row.

Config: ``{child: row, parent: section}`` names the two levels. Those are the
only levels built, so any other value is an error.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from src.chunking.base import Chunker, ChunkingError, ChunkSet, Tokenizer
from src.chunking.row_wise import RowWiseChunker
from src.chunking.section_aware import SectionAwareChunker

LEVELS = {"child": "row", "parent": "section"}


class HierarchicalChunker(Chunker):
    name = "hierarchical"
    OPTIONS = {"child": str, "parent": str}

    def __init__(self, tokenizer: Tokenizer, embed_max_tokens: int = 512,
                 parent_max_tokens: int | None = None, **options):
        super().__init__(tokenizer, embed_max_tokens, **options)
        self._children = RowWiseChunker(tokenizer, embed_max_tokens)
        self._parents = SectionAwareChunker(tokenizer, embed_max_tokens,
                                            max_tokens=parent_max_tokens or embed_max_tokens)

    def _check_options(self) -> None:
        for key, expected in LEVELS.items():
            if self.options[key] != expected:
                raise ChunkingError(f"chunking.hierarchical.{key} must be {expected!r}, got {self.options[key]!r}")

    def build(self, sheet: pd.DataFrame) -> ChunkSet:
        parents = []
        parent_of = {}
        for n, p in enumerate(self._parents.chunk(sheet)):
            parent = replace(p, id=f"{self.name}:{p.as_of_date}:{p.scheme_code}:p{n}", chunker=self.name)
            parents.append(parent)
            for key in parent.source_rows:
                parent_of[key] = parent.id
        children = []
        for n, c in enumerate(self._children.chunk(sheet)):
            (key,) = c.source_rows
            children.append(replace(c, id=f"{self.name}:{c.as_of_date}:{c.scheme_code}:{n}",
                                    chunker=self.name, parent_id=parent_of[key]))
        return ChunkSet(chunks=children, parents=parents)
