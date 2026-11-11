"""Six ways to cut the holdings table into chunks (Phase 2, spec §6.3).

Every chunker takes one scheme-month of ``holdings.parquet`` and returns
chunks in the same shape (``base.Chunk``). They share the text format, the
token counter and the truncation rule, and differ only in how they group rows.

``build_chunker(name, settings)`` makes a chunker with its options from
``config.yaml`` (``chunking.<name>``) and the embedding model's tokenizer.
"""

from __future__ import annotations

from src.chunking.base import Chunk, Chunker, ChunkingError, ChunkSet, Tokenizer, get_tokenizer
from src.chunking.fixed_size import FixedSizeChunker
from src.chunking.header_window import HeaderWindowChunker
from src.chunking.hierarchical import HierarchicalChunker
from src.chunking.row_wise import RowWiseChunker
from src.chunking.scheme_level import SchemeLevelChunker
from src.chunking.section_aware import SectionAwareChunker

# Order = the spec's table order; reports list chunkers in this order.
REGISTRY: dict[str, type[Chunker]] = {
    "fixed_size": FixedSizeChunker,
    "row_wise": RowWiseChunker,
    "header_window": HeaderWindowChunker,
    "scheme_level": SchemeLevelChunker,
    "section_aware": SectionAwareChunker,
    "hierarchical": HierarchicalChunker,
}


def build_chunker(name: str, settings, tokenizer: Tokenizer | None = None) -> Chunker:
    """A configured chunker. ``tokenizer`` defaults to the embedding model's own."""
    if name not in REGISTRY:
        raise ChunkingError(f"unknown chunker {name!r}; known: {list(REGISTRY)}")
    tokenizer = tokenizer or get_tokenizer(settings.embedding.model)
    options = dict(settings.chunking.get(name, {}))
    extra = {}
    if name == "hierarchical":
        extra["parent_max_tokens"] = settings.chunking.get("section_aware", {}).get("max_tokens")
    return REGISTRY[name](tokenizer, settings.embedding.max_tokens, **extra, **options)


__all__ = ["REGISTRY", "build_chunker", "Chunk", "Chunker", "ChunkSet", "ChunkingError", "Tokenizer"]
