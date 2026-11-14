"""Find the chunks to show the LLM (task 3.7, FR-3.3, FR-3.4).

Same rule for every chunker: embed the question, take the ``top_k`` nearest
chunks from that chunker's collection (cosine). The one exception is
``hierarchical``: its top_k children are replaced by their parent sections,
deduplicated and kept in the order their best child was found, so the LLM gets
at most top_k (often fewer) whole sections.

``score`` is cosine similarity (1 - Chroma's cosine distance); for a parent it
is the best score among its retrieved children.

The optional scheme / month filter (FR-3.4) is used by the app (one or several schemes). The main
evaluation runs without it (D4).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from src.chunking.base import Chunk, RowKey
from src.index.embedder import Embedder
from src.index.store import PARENTS_FILE, chunk_from_record, get_collection, open_client, read_parents

HIERARCHICAL = "hierarchical"


@dataclass(frozen=True)
class Retrieved:
    chunk: Chunk
    score: float
    rank: int                                  # 1 = best
    children: tuple[str, ...] = ()             # hierarchical: the retrieved child ids behind this parent


@dataclass
class Retrieval:
    chunker: str
    chunks: list[Retrieved]
    latency_ms: float
    children: list[Retrieved] = field(default_factory=list)   # hierarchical only: what the search returned

    @property
    def context_rows(self) -> list[RowKey]:
        """Union of the source rows of everything shown to the LLM, in retrieval order (FR-3.7)."""
        seen: dict[RowKey, None] = {}
        for r in self.chunks:
            for k in r.chunk.source_rows:
                seen.setdefault(k, None)
        return list(seen)


def where_filter(scheme_code: str | list[str] | tuple[str, ...] | None = None,
                 as_of_date: str | None = None) -> dict | None:
    """Chroma ``where`` for the optional filters. ``scheme_code`` may be one code or several (the app's
    scheme picker); several become ``$in``, one stays a plain match."""
    codes = [scheme_code] if isinstance(scheme_code, str) else list(dict.fromkeys(scheme_code or []))
    if len(codes) == 1:
        parts = [{"scheme_code": codes[0]}]
    else:
        parts = [{"scheme_code": {"$in": codes}}] if codes else []
    parts += [{"as_of_date": as_of_date}] if as_of_date else []
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else {"$and": parts}


class Retriever:
    def __init__(self, settings, embedder: Embedder | None = None, client=None,
                 parents: dict[str, Chunk] | None = None):
        self.settings = settings
        self.embedder = embedder or Embedder.from_settings(settings)
        self.client = client or open_client(settings.paths.chroma)
        self._parents = parents
        self._collections: dict = {}

    @property
    def parents(self) -> dict[str, Chunk]:
        if self._parents is None:
            self._parents = read_parents(self.settings.paths.processed / PARENTS_FILE)
        return self._parents

    def _collection(self, chunker: str):
        if chunker not in self._collections:
            self._collections[chunker] = get_collection(self.client, chunker, self.embedder.model)
        return self._collections[chunker]

    def retrieve(self, question: str, chunker: str, top_k: int | None = None,
                 scheme_code: str | list[str] | None = None, as_of_date: str | None = None) -> Retrieval:
        top_k = top_k or self.settings.retrieval.top_k
        self.embedder.load()                       # model loading is not retrieval latency
        t0 = time.perf_counter()
        vector = self.embedder.embed_query(question)
        res = self._collection(chunker).query(query_embeddings=[vector.tolist()], n_results=top_k,
                                              where=where_filter(scheme_code, as_of_date),
                                              include=["documents", "metadatas", "distances"])
        found = [Retrieved(chunk_from_record(i, d, m), score=1.0 - float(dist), rank=n + 1)
                 for n, (i, d, m, dist) in enumerate(zip(res["ids"][0], res["documents"][0],
                                                         res["metadatas"][0], res["distances"][0]))]
        if chunker != HIERARCHICAL:
            return Retrieval(chunker, found, (time.perf_counter() - t0) * 1000)
        return Retrieval(chunker, swap_for_parents(found, self.parents), (time.perf_counter() - t0) * 1000,
                         children=found)


def swap_for_parents(children: list[Retrieved], parents: dict[str, Chunk]) -> list[Retrieved]:
    """Replace retrieved children by their unique parents, in order of first appearance (FR-3.3)."""
    order: dict[str, list[Retrieved]] = {}
    for child in children:
        pid = child.chunk.parent_id
        if not pid or pid not in parents:
            raise KeyError(f"parent {pid!r} of {child.chunk.id} not found: re-index hierarchical")
        order.setdefault(pid, []).append(child)
    return [Retrieved(parents[pid], score=max(c.score for c in kids), rank=n + 1,
                      children=tuple(c.chunk.id for c in kids))
            for n, (pid, kids) in enumerate(order.items())]
