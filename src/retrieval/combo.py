"""M8 ``best_combo``: the scheme filter (or not) in front of any ranker (spec §5 M8, plan R2.8).

Its recipe is **declared in Phase R3 from dev results only**, before any test score, and written to
``retrieval_benchmark.methods.best_combo`` in config.yaml, e.g. ``{filter: true, ranker: hybrid_rerank}``.
Until then building it is an error. The ranker uses its own config.yaml settings (the dev choices).
"""

from __future__ import annotations

from src.retrieval.base import RetrievalMethod, build_method

RANKERS = ("dense", "bm25", "hybrid_rrf", "dense_rerank", "hybrid_rerank", "mmr")


def build_combo(shared, filter: bool, ranker: str, fuzzy_threshold: float | None = None) -> RetrievalMethod:
    if ranker not in RANKERS:
        raise ValueError(f"best_combo.ranker must be one of {RANKERS}, got {ranker!r}")
    inner = build_method(ranker, shared)
    if not filter:
        inner.name = "best_combo"
        return inner
    from src.retrieval.scheme_filter import SchemeFilter

    threshold = shared.bench.method_options("scheme_filter")["fuzzy_threshold"] if fuzzy_threshold is None \
        else fuzzy_threshold
    return SchemeFilter(shared, inner, threshold, name="best_combo")
