"""M4 ``dense_rerank`` and M5 ``hybrid_rerank``: re-score candidates with a cross-encoder (spec §5, RD4).

A first-stage method (dense for M4, hybrid RRF for M5) gives its top ``depth`` children; the
cross-encoder ``BAAI/bge-reranker-base`` reads the question and each child **together** and scores the
pair; the children are re-ordered by that score. Ties: first-stage order.

Scores are cached on disk (``<paths.cache>/rerank.sqlite``, spec §9.3), keyed by the model and its
pinned revision, the question's hash and the child text's hash (the text, not the id, so a re-indexed
row with new text is scored again). Each (question, child) pair is scored once across all runs and grid
values. The scorer is any ``callable(list of (question, text)) -> list of float``: tests pass a stub,
so no test downloads a model.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path
from typing import Callable, Sequence

from src.retrieval.base import Ranked, RetrievalMethod

Scorer = Callable[[list[tuple[str, str]]], Sequence[float]]


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class CrossEncoderScorer:
    """sentence-transformers ``CrossEncoder`` on CPU, loaded on first use, at a pinned revision."""

    def __init__(self, model: str, revision: str | None, max_length: int = 512, batch_size: int = 16):
        self.model, self.revision = model, revision
        self.max_length, self.batch_size = max_length, batch_size
        self._ce = None

    @property
    def key(self) -> str:
        return f"{self.model}@{self.revision or 'unpinned'}:logit"

    def load(self) -> None:
        if self._ce is None:
            if not self.revision:
                raise RuntimeError(f"retrieval_benchmark.reranker.revision is not set: download {self.model} "
                                   "and pin its revision in config.yaml first")
            from sentence_transformers import CrossEncoder  # heavy: load only when needed

            import torch

            # Raw logits, not the default sigmoid: same order, but the sigmoid saturates near 1.0 and made
            # many rows tie at ~0.999 on the real data (seen in R2). The ":logit" in ``key`` keeps the cache apart.
            self._ce = CrossEncoder(self.model, revision=self.revision, max_length=self.max_length, device="cpu",
                                    activation_fn=torch.nn.Identity())

    def __call__(self, pairs: list[tuple[str, str]]) -> list[float]:
        self.load()
        return [float(s) for s in self._ce.predict(pairs, batch_size=self.batch_size, show_progress_bar=False)]


class Reranker:
    """Scorer + SQLite score cache (one connection, usable from any thread, like the vector cache)."""

    def __init__(self, scorer: Scorer, cache_path: Path | None):
        self.scorer = scorer
        self.key = getattr(scorer, "key", getattr(scorer, "__name__", type(scorer).__name__))
        self.db = None
        self._lock = threading.Lock()
        self.scored = 0                       # pairs sent to the model (cache misses)
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(str(cache_path), check_same_thread=False)
            self.db.execute("CREATE TABLE IF NOT EXISTS scores (model TEXT, qhash TEXT, dhash TEXT, score REAL, "
                            "PRIMARY KEY (model, qhash, dhash))")
            self.db.commit()

    def load(self) -> None:
        if hasattr(self.scorer, "load"):
            self.scorer.load()

    def scores(self, question: str, texts: Sequence[str]) -> list[float]:
        q = _h(question)
        hashes = [_h(t) for t in texts]
        found: dict[str, float] = {}
        if self.db is not None and hashes:
            with self._lock:
                rows = self.db.execute(
                    f"SELECT dhash, score FROM scores WHERE model = ? AND qhash = ? AND dhash IN "
                    f"({','.join('?' * len(set(hashes)))})", [self.key, q, *dict.fromkeys(hashes)]).fetchall()
            found = dict(rows)
        todo = list(dict.fromkeys(h for h in hashes if h not in found))
        if todo:
            text_of = dict(zip(hashes, texts))
            new = dict(zip(todo, self.scorer([(question, text_of[h]) for h in todo])))
            self.scored += len(todo)
            if self.db is not None:
                with self._lock:
                    self.db.executemany("INSERT OR REPLACE INTO scores VALUES (?, ?, ?, ?)",
                                        [(self.key, q, h, float(s)) for h, s in new.items()])
                    self.db.commit()
            found.update(new)
        return [float(found[h]) for h in hashes]


class Rerank(RetrievalMethod):
    def __init__(self, shared, first: RetrievalMethod, depth: int = 50, name: str = "rerank"):
        super().__init__(shared)
        self.first, self.depth, self.name = first, depth, name

    def load(self) -> None:
        self.first.load()
        self.shared.reranker.load()

    def rank(self, question: str, n: int, schemes: Sequence[str] | None = None) -> tuple[Ranked, dict]:
        cands, _ = self.first.rank(question, max(self.depth, n), schemes)
        cands = cands[:max(self.depth, n)]
        before = self.shared.reranker.scored
        scores = self.shared.reranker.scores(question, [self.corpus.texts[i] for i, _ in cands])
        order = sorted(range(len(cands)), key=lambda j: (-scores[j], j))
        return [(cands[j][0], scores[j]) for j in order][:n], {
            "candidates": len(cands), "pairs_scored": self.shared.reranker.scored - before}
