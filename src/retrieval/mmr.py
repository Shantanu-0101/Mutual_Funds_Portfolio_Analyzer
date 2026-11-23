"""M7 ``mmr``: Maximal Marginal Relevance on the dense candidates (spec §5 M7).

Take dense's top ``depth`` children, then pick one at a time the child that maximises

    lambda * sim(question, child)  -  (1 - lambda) * max sim(child, already picked)

with cosine similarity on the **stored** child embeddings (L2-normalised, so cosine = dot product) and
the same question vector dense uses. lambda = 1 gives dense's order; lambda = 0 picks the child least like
those already picked (after the first, which is always the most relevant). Ties: dense order.
Aggregation and cross-scheme questions need different rows, not five near-copies: that is the bet.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from src.retrieval.base import Ranked, RetrievalMethod
from src.retrieval.dense import Dense


def mmr_select(query: np.ndarray, cands: np.ndarray, n: int, lam: float) -> list[tuple[int, float]]:
    """Indices into ``cands`` (rows = candidate vectors, in first-stage order) and their MMR scores."""
    if len(cands) == 0:
        return []
    rel = cands @ query
    sim = cands @ cands.T
    picked: list[tuple[int, float]] = []
    left = list(range(len(cands)))
    max_sim = np.full(len(cands), -np.inf)
    while left and len(picked) < n:
        red = np.where(np.isfinite(max_sim[left]), max_sim[left], 0.0) if picked else np.zeros(len(left))
        score = lam * rel[left] - (1 - lam) * red
        j = left[int(np.argmax(score))]        # argmax keeps the first (best dense rank) on ties
        picked.append((j, float(score[left.index(j)])))
        left.remove(j)
        max_sim = np.maximum(max_sim, sim[j])
    return picked


class MMR(RetrievalMethod):
    name = "mmr"

    def __init__(self, shared, depth: int = 50, lam: float = 0.5):
        super().__init__(shared)
        if not 0.0 <= lam <= 1.0:
            raise ValueError("mmr lambda must be between 0 and 1")
        self.depth, self.lam = depth, float(lam)
        self.dense = Dense(shared)

    def rank(self, question: str, n: int, schemes: Sequence[str] | None = None) -> tuple[Ranked, dict]:
        cands, _ = self.dense.rank(question, max(self.depth, n), schemes)
        idx = [i for i, _ in cands]
        q = np.asarray(self.shared.dense.query_vector(question), dtype=np.float32)
        picked = mmr_select(q, self.corpus.embeddings[idx], n, self.lam)
        return [(idx[j], s) for j, s in picked], {"candidates": len(idx)}
