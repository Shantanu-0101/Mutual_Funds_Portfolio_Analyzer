"""Retrieval methods: one interface, one shared corpus, one registry (spec §5, plan R2.1).

- ``ChildCorpus``: every child (one holding row) of the ``hierarchical`` collection for the month, with
  its text, metadata and **stored** embedding, loaded once. BM25, MMR and the scheme filter work off it.
- ``DenseSearch``: today's search (embed the question with bge-small, query Chroma by cosine), with an
  optional scheme restriction. M1 uses it unchanged, so M1 returns what the chunking run retrieved.
- ``RetrievalMethod``: ``retrieve(question, k) -> MethodResult`` (ranked children, latency, debug).
  Subclasses implement ``rank(question, n, schemes)``: the top ``n`` children as (corpus index, score),
  searching only inside ``schemes`` when given. That restriction is what lets the scheme filter (M6) and
  the combo (M8) wrap any ranker.
- ``build_method(name, shared, overrides)``: the registry (``METHODS``).

Every method ranks ``candidate_k`` (20) children (FR-R2.2) and ``retrieve`` cuts to ``k``; the RAG
pipeline uses the first ``retrieval.top_k`` (5). Latency is measured after models are loaded, like
``src/rag/retrieve.py``. The parent swap is not done here: the pipeline applies it the same way for all.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Callable, Sequence

import numpy as np
import pandas as pd

from src.chunking.base import Chunk
from src.index.embedder import Embedder
from src.index.store import chunk_from_record, get_collection, open_client
from src.rag.retrieve import HIERARCHICAL, Retrieved
from src.retrieval.settings import BenchmarkSettings

Ranked = list[tuple[int, float]]          # (corpus index, score), best first


@dataclass
class MethodResult:
    method: str
    children: list[Retrieved]             # ranked, rank 1 = best, no duplicates
    latency_ms: float
    debug: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- corpus

def _child_order(chunk_id: str) -> tuple[str, int]:
    """``hierarchical:<date>:<scheme>:<n>`` → (scheme, n), so the corpus has a stable, natural order."""
    head, _, n = chunk_id.rpartition(":")
    return head, int(n) if n.isdigit() else -1


class ChildCorpus:
    """All children of one month, in a fixed order (by scheme, then row number)."""

    def __init__(self, chunks: Sequence[Chunk], embeddings: np.ndarray):
        if len(chunks) != len(embeddings):
            raise ValueError("one embedding per child expected")
        order = sorted(range(len(chunks)), key=lambda i: _child_order(chunks[i].id))
        self.chunks: list[Chunk] = [chunks[i] for i in order]
        self.embeddings = np.asarray(embeddings, dtype=np.float32)[order] if len(order) else \
            np.zeros((0, 0), dtype=np.float32)
        self.ids = [c.id for c in self.chunks]
        self.texts = [c.text for c in self.chunks]
        self.schemes = np.array([c.scheme_code for c in self.chunks])
        self.index = {cid: i for i, cid in enumerate(self.ids)}
        if len(self.index) != len(self.ids):
            raise ValueError("duplicate child ids in the corpus")

    def __len__(self) -> int:
        return len(self.chunks)

    @classmethod
    def from_collection(cls, col, month: str) -> "ChildCorpus":
        res = col.get(where={"as_of_date": month}, include=["documents", "metadatas", "embeddings"])
        if not res["ids"]:
            raise ValueError(f"no children for {month} in {col.name}: run `python -m src.index` first")
        chunks = [chunk_from_record(i, d, m) for i, d, m in zip(res["ids"], res["documents"], res["metadatas"])]
        return cls(chunks, np.asarray(res["embeddings"], dtype=np.float32))

    def positions(self, schemes: Sequence[str] | None) -> np.ndarray:
        """Corpus indices of the children in ``schemes`` (all children when None)."""
        if schemes is None:
            return np.arange(len(self))
        return np.flatnonzero(np.isin(self.schemes, list(schemes)))

    def count(self, schemes: Sequence[str] | None) -> int:
        return len(self) if schemes is None else int(np.isin(self.schemes, list(schemes)).sum())


# --------------------------------------------------------------------------- dense search

class DenseSearch:
    """bge-small + Chroma, exactly as ``Retriever.retrieve`` (cosine, score = 1 - distance)."""

    def __init__(self, embedder: Embedder, collection, corpus: ChildCorpus, month: str, month_filter: bool):
        self.embedder = embedder
        self.collection = collection
        self.corpus = corpus
        self.month = month
        self.month_filter = month_filter       # False when the collection holds only this month (as today)
        self._qvec: dict[str, np.ndarray] = {}

    def load(self) -> None:
        self.embedder.load()

    def query_vector(self, question: str) -> np.ndarray:
        if question not in self._qvec:
            self._qvec[question] = self.embedder.embed_query(question)
        return self._qvec[question]

    def where(self, schemes: Sequence[str] | None) -> dict | None:
        parts = []
        if schemes is not None:
            codes = list(dict.fromkeys(schemes))
            parts.append({"scheme_code": codes[0]} if len(codes) == 1 else {"scheme_code": {"$in": codes}})
        if self.month_filter:
            parts.append({"as_of_date": self.month})
        if not parts:
            return None
        return parts[0] if len(parts) == 1 else {"$and": parts}

    def rank(self, question: str, n: int, schemes: Sequence[str] | None = None) -> Ranked:
        n = min(n, self.corpus.count(schemes))
        if n <= 0:
            return []
        res = self.collection.query(query_embeddings=[self.query_vector(question).tolist()], n_results=n,
                                    where=self.where(schemes), include=["distances"])
        return [(self.corpus.index[i], 1.0 - float(d)) for i, d in zip(res["ids"][0], res["distances"][0])]


# --------------------------------------------------------------------------- shared state

class Shared:
    """What all methods share, loaded once: corpus, dense search, scheme list, and (lazily) the BM25
    index, the scheme extractor and the reranker. Tests build it from synthetic parts."""

    def __init__(self, bench: BenchmarkSettings, corpus: ChildCorpus, dense: DenseSearch,
                 schemes: pd.DataFrame, scorer: Callable | None = None, rerank_cache_path=None):
        self.bench = bench
        self.corpus = corpus
        self.dense = dense
        self.schemes = schemes                 # columns scheme_code, scheme (the month's scheme list)
        self._scorer = scorer
        self._rerank_cache_path = rerank_cache_path

    @classmethod
    def load(cls, settings, month: str | None = None, scorer: Callable | None = None) -> "Shared":
        from src.parsing.pipeline import SCHEMES_FILE

        month = month or settings.data.eval_months[0]
        embedder = Embedder.from_settings(settings)
        col = get_collection(open_client(settings.paths.chroma), HIERARCHICAL, embedder.model)
        corpus = ChildCorpus.from_collection(col, month)
        dense = DenseSearch(embedder, col, corpus, month, month_filter=col.count() != len(corpus))
        schemes = pd.read_parquet(settings.paths.processed / SCHEMES_FILE, columns=["scheme_code", "scheme",
                                                                                     "as_of_date"])
        schemes = schemes[schemes["as_of_date"].astype(str) == month][["scheme_code", "scheme"]]
        return cls(BenchmarkSettings.from_settings(settings), corpus, dense, schemes.reset_index(drop=True),
                   scorer, settings.paths.cache / "rerank.sqlite")

    @cached_property
    def bm25(self):
        from src.retrieval.bm25 import BM25Index

        return BM25Index(self.corpus.texts)

    @cached_property
    def extractor(self):
        from src.retrieval.scheme_filter import SchemeExtractor

        return SchemeExtractor(self.schemes)

    @cached_property
    def reranker(self):
        from src.retrieval.rerank import CrossEncoderScorer, Reranker

        rr = self.bench.reranker
        scorer = self._scorer or CrossEncoderScorer(rr["model"], rr["revision"], rr["max_length"], rr["batch_size"])
        return Reranker(scorer, self._rerank_cache_path)


# --------------------------------------------------------------------------- method interface

class RetrievalMethod:
    name = "?"

    def __init__(self, shared: Shared):
        self.shared = shared
        self.corpus = shared.corpus

    def load(self) -> None:
        """Load models before timing (not counted as retrieval latency)."""
        self.shared.dense.load()

    def rank(self, question: str, n: int, schemes: Sequence[str] | None = None) -> tuple[Ranked, dict]:
        raise NotImplementedError

    def settings(self) -> dict[str, Any]:
        """The method's options, for results and fingerprints."""
        return {}

    def retrieve(self, question: str, k: int | None = None) -> MethodResult:
        k = k or self.shared.bench.candidate_k
        self.load()
        t0 = time.perf_counter()
        ranked, debug = self.rank(question, max(k, self.shared.bench.candidate_k))
        latency = (time.perf_counter() - t0) * 1000
        ranked = ranked[:k]
        if len({i for i, _ in ranked}) != len(ranked):
            raise AssertionError(f"{self.name} returned a child twice")
        children = [Retrieved(self.corpus.chunks[i], score=float(s), rank=r + 1) for r, (i, s) in enumerate(ranked)]
        return MethodResult(self.name, children, latency, debug)


def order_scores(positions: np.ndarray, scores: np.ndarray, n: int) -> Ranked:
    """Top ``n`` by score (high first); ties by corpus order, so results are deterministic."""
    if len(positions) == 0 or n <= 0:
        return []
    order = np.lexsort((positions, -scores))[:n]
    return [(int(positions[j]), float(scores[j])) for j in order]


# --------------------------------------------------------------------------- registry

def _registry() -> dict[str, Callable[..., RetrievalMethod]]:
    from src.retrieval.bm25 import BM25
    from src.retrieval.combo import build_combo
    from src.retrieval.dense import Dense
    from src.retrieval.hybrid import HybridRRF
    from src.retrieval.mmr import MMR
    from src.retrieval.rerank import Rerank
    from src.retrieval.scheme_filter import SchemeFilter

    def dense_rerank(shared, depth):
        return Rerank(shared, Dense(shared), depth, name="dense_rerank")

    def hybrid_rerank(shared, depth, hybrid_depth):
        return Rerank(shared, HybridRRF(shared, depth=hybrid_depth, rrf_k=shared.bench.method_options(
            "hybrid_rrf")["rrf_k"]), depth, name="hybrid_rerank")

    def scheme_filter(shared, fuzzy_threshold, ranker):
        return SchemeFilter(shared, build_method(ranker, shared), fuzzy_threshold, name="scheme_filter")

    return {
        "dense": lambda shared: Dense(shared),
        "bm25": lambda shared, k1, b: BM25(shared, k1=k1, b=b),
        "hybrid_rrf": lambda shared, depth, rrf_k: HybridRRF(shared, depth=depth, rrf_k=rrf_k),
        "dense_rerank": dense_rerank,
        "hybrid_rerank": hybrid_rerank,
        "scheme_filter": scheme_filter,
        "mmr": lambda shared, depth, **o: MMR(shared, depth=depth, lam=o["lambda"]),
        "best_combo": lambda shared, **o: build_combo(shared, **o),
    }


METHOD_NAMES = ("dense", "bm25", "hybrid_rrf", "dense_rerank", "hybrid_rerank", "scheme_filter", "mmr",
                "best_combo")


def build_method(name: str, shared: Shared, overrides: dict[str, Any] | None = None) -> RetrievalMethod:
    """A method by name, with config.yaml's options (plus optional overrides, e.g. a dev grid value)."""
    opts = shared.bench.method_options(name, overrides)
    method = _registry()[name](shared, **opts)
    method.options = opts
    return method
