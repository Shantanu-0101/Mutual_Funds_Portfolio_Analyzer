"""The ``retrieval_benchmark:`` block of config.yaml, checked strictly (spec §7).

Same rule as the rest of the config: an unknown or missing key is an error, so a typo cannot quietly
change an experiment. ``method_options(name, overrides)`` gives one method's settings with optional
overrides (R3's dev grid search passes them), and rejects options the method does not have.
"""

from __future__ import annotations

from typing import Any

from src.config import ConfigError

# Every option a method accepts, with its type. ``best_combo`` (M8) is declared in R3.
METHOD_OPTIONS: dict[str, dict[str, type | tuple[type, ...]]] = {
    "dense": {},
    "bm25": {"k1": (int, float), "b": (int, float)},
    "hybrid_rrf": {"depth": int, "rrf_k": int},
    "dense_rerank": {"depth": int},
    "hybrid_rerank": {"depth": int, "hybrid_depth": int},
    "scheme_filter": {"fuzzy_threshold": (int, float), "ranker": str},
    "mmr": {"depth": int, "lambda": (int, float)},
    "best_combo": {"filter": bool, "ranker": str, "fuzzy_threshold": (int, float)},
}
METHOD_IDS = {"dense": "M1", "bm25": "M2", "hybrid_rrf": "M3", "dense_rerank": "M4", "hybrid_rerank": "M5",
              "scheme_filter": "M6", "mmr": "M7", "best_combo": "M8"}
RERANKER_KEYS = {"model": str, "revision": (str, type(None)), "max_length": int, "batch_size": int}
TOP_KEYS = {"candidate_k", "methods", "grids", "reranker"}


def _check_types(values: dict[str, Any], spec: dict[str, Any], where: str, partial: bool = False) -> None:
    unknown = values.keys() - spec.keys()
    if unknown:
        raise ConfigError(f"{where} has unknown keys: {sorted(unknown)}")
    missing = spec.keys() - values.keys()
    if missing and not partial:
        raise ConfigError(f"{where} is missing keys: {sorted(missing)}")
    for k, v in values.items():
        if isinstance(v, bool) and spec[k] is not bool:
            raise ConfigError(f"{where}.{k} must be {spec[k]}, got {v!r}")
        if not isinstance(v, spec[k]):
            raise ConfigError(f"{where}.{k} must be {spec[k]}, got {v!r}")


class BenchmarkSettings:
    """Parsed and checked ``retrieval_benchmark`` block."""

    def __init__(self, raw: dict[str, Any]):
        if not raw:
            raise ConfigError("config.yaml has no retrieval_benchmark section")
        _check_types(raw, {k: object for k in TOP_KEYS}, "retrieval_benchmark")
        self.candidate_k = raw["candidate_k"]
        if not isinstance(self.candidate_k, int) or self.candidate_k < 1:
            raise ConfigError("retrieval_benchmark.candidate_k must be a positive integer")
        methods = raw["methods"] or {}
        if set(methods) != set(METHOD_OPTIONS):
            raise ConfigError(f"retrieval_benchmark.methods must list exactly {sorted(METHOD_OPTIONS)}")
        self.methods: dict[str, dict[str, Any] | None] = {}
        for name, opts in methods.items():
            if opts is None and name == "best_combo":
                self.methods[name] = None          # not declared yet (R3)
                continue
            opts = dict(opts or {})
            spec = METHOD_OPTIONS[name]
            # best_combo's fuzzy_threshold is optional (inherits scheme_filter's).
            _check_types(opts, spec, f"retrieval_benchmark.methods.{name}", partial=name == "best_combo")
            if name == "best_combo" and not {"filter", "ranker"} <= opts.keys():
                raise ConfigError("retrieval_benchmark.methods.best_combo needs filter and ranker")
            self.methods[name] = opts
        self.grids: dict[str, dict[str, list]] = {}
        for name, grid in (raw["grids"] or {}).items():
            if name not in METHOD_OPTIONS:
                raise ConfigError(f"retrieval_benchmark.grids: unknown method {name!r}")
            for opt, values in (grid or {}).items():
                if opt not in METHOD_OPTIONS[name] or not isinstance(values, list) or not values:
                    raise ConfigError(f"retrieval_benchmark.grids.{name}.{opt} must be a non-empty list of "
                                      "values of a real option")
            self.grids[name] = {k: list(v) for k, v in (grid or {}).items()}
        rr = dict(raw["reranker"] or {})
        _check_types(rr, RERANKER_KEYS, "retrieval_benchmark.reranker")
        self.reranker = rr

    @classmethod
    def from_settings(cls, settings) -> "BenchmarkSettings":
        return cls(settings.retrieval_benchmark)

    def method_options(self, name: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        if name not in METHOD_OPTIONS:
            raise ConfigError(f"unknown retrieval method {name!r}; known: {sorted(METHOD_OPTIONS)}")
        base = self.methods.get(name)
        if base is None:
            if name == "best_combo" and overrides and {"filter", "ranker"} <= overrides.keys():
                base = {}
            else:
                raise ConfigError("best_combo (M8) is not declared yet: Phase R3 declares it from dev results")
        opts = {**base, **(overrides or {})}
        _check_types(opts, METHOD_OPTIONS[name], f"method {name}", partial=name == "best_combo")
        return opts
