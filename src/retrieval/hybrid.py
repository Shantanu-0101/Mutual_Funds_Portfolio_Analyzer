"""M3 ``hybrid_rrf``: dense and BM25, merged by Reciprocal Rank Fusion (spec §5 M3).

Take the top ``depth`` of each list. A child's fused score is the sum over the lists it appears in of
``1 / (rrf_k + rank)`` (rank 1 = best, ``rrf_k`` = 60). A child found by only one list still gets that
list's share, so it can still rank. Ties: better best rank first, then corpus order.
"""

from __future__ import annotations

from typing import Sequence

from src.retrieval.base import Ranked, RetrievalMethod
from src.retrieval.bm25 import BM25
from src.retrieval.dense import Dense


def rrf(lists: Sequence[Ranked], rrf_k: int = 60) -> Ranked:
    score: dict[int, float] = {}
    best: dict[int, int] = {}
    for ranked in lists:
        for r, (i, _) in enumerate(ranked, start=1):
            score[i] = score.get(i, 0.0) + 1.0 / (rrf_k + r)
            best[i] = min(best.get(i, r), r)
    return sorted(score.items(), key=lambda kv: (-kv[1], best[kv[0]], kv[0]))


class HybridRRF(RetrievalMethod):
    name = "hybrid_rrf"

    def __init__(self, shared, depth: int = 50, rrf_k: int = 60, bm25: BM25 | None = None):
        super().__init__(shared)
        self.depth, self.rrf_k = depth, rrf_k
        self.dense = Dense(shared)
        bm = shared.bench.method_options("bm25")
        self.bm25 = bm25 or BM25(shared, **bm)

    def load(self) -> None:
        self.dense.load()
        self.bm25.load()

    def rank(self, question: str, n: int, schemes: Sequence[str] | None = None) -> tuple[Ranked, dict]:
        depth = max(self.depth, n)
        d, _ = self.dense.rank(question, depth, schemes)
        b, _ = self.bm25.rank(question, depth, schemes)
        fused = rrf([d, b], self.rrf_k)[:n]
        in_d, in_b = {i for i, _ in d}, {i for i, _ in b}
        return fused, {"from_dense_only": sum(i in in_d and i not in in_b for i, _ in fused),
                       "from_bm25_only": sum(i in in_b and i not in in_d for i, _ in fused)}
