"""Phase R3, Stage A: every method on every question, no LLM call (spec §6.2, §6.4, §6.5).

Three parts, all pure where they can be:

- **Metrics** (§6.4). ``metrics(target, children)`` scores one ranked list of children against one
  question's gold: ``hit@k``, ``row_recall@k``, ``section_recall@k``, ``scheme_recall@k`` for
  k = 1, 3, 5, 10, 20 and ``mrr@10``. ``context_metrics`` adds what the LLM would actually get after the
  parent swap (``context_gold_row_recall``, ``context_tokens``), so the numbers line up with the
  chunking run. Unanswerable questions have no gold rows and are left out of every retrieval metric.
- **The run** (``run_set``). One row per (set, method variant, question): the ranked top-20 child ids and
  scores, every metric, the filter debug and the latency, appended to ``results/retrieval/offline.csv``.
- **Choices** (§6.5). ``choose_variants`` picks each method's settings on **dev** by mean
  ``section_recall@5`` (ties: ``hit@5``, then ``mrr@10``, then lower median latency); ``choose_combo``
  declares M8 (filter yes/no + ranker) from dev the same way; ``write_choices`` writes them into
  config.yaml with the date. ``rank_methods`` / ``shortlist`` then rank the **test** run and pick the
  three methods Stage B pays for (top 2 + M1 dense, RD6), and ``paired_bootstrap`` says whether the
  lead is distinguishable from dense (10,000 resamples, seed 42, RD8).

Nothing here reads a question's gold ``params`` into retrieval: the gold is only ever compared with
what a method returned.
"""

from __future__ import annotations

import csv
import itertools
import json
import math
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from src.chunking.base import RowKey
from src.eval.gold import compute
from src.eval.questions import Question
from src.rag.retrieve import Retrieved, swap_for_parents
from src.retrieval.base import METHOD_NAMES, RetrievalMethod, build_method
from src.retrieval.combo import RANKERS
from src.retrieval.questions.sets import gold_sections, row_parent_map
from src.retrieval.settings import METHOD_IDS

KS: tuple[int, ...] = (1, 3, 5, 10, 20)
PRIMARY = "section_recall@5"
MRR_K = 10
OFFLINE_FILE = "offline.csv"
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 42
REFERENCE = "dense"                       # M1: the method every other one is compared with
LATENCY_TIE_MS = 10                       # latency differences under this are machine noise (Standing.key)
SHORTLIST_N = 3                           # top 2 + M1 (RD6)

METRIC_COLUMNS = [f"{name}@{k}" for name in ("hit", "row_recall", "section_recall", "scheme_recall")
                  for k in KS] + [f"mrr@{MRR_K}"]
COLUMNS = [
    "set", "method", "method_id", "variant", "settings", "qid", "type", "answer_kind", "answerable",
    "original", "short_name", "n_gold_rows", "n_gold_sections", "gold_sections", "gold_schemes",
    "children", "scores", *METRIC_COLUMNS,
    "n_sections", "context_gold_row_recall", "context_tokens", "retrieval_ms",
    "filter_match", "schemes_found", "filter_miss", "filter_wrong", "padded", "debug",
]


# --------------------------------------------------------------------------- what the metrics compare

@dataclass(frozen=True)
class Target:
    """One question's gold, as retrieval sees it: the rows, the sections holding them, their schemes."""
    rows: frozenset[RowKey]
    sections: frozenset[str]

    @property
    def schemes(self) -> frozenset[str]:
        return frozenset(section_scheme(s) for s in self.sections)

    @property
    def answerable(self) -> bool:
        return bool(self.rows)


@dataclass(frozen=True)
class ChildRef:
    """One retrieved child, with only what the metrics need."""
    id: str
    parent_id: str
    scheme_code: str
    rows: tuple[RowKey, ...]


def short_id(child_id: str) -> str:
    """``hierarchical:2026-09-30:ABSLMCF:64`` → ``ABSLMCF:64``: what ``offline.csv`` stores, so the top-20
    lists stay readable and the file small. The chunker and the month are the same for every row of a run
    (``gold_sections`` spells them out), so nothing is lost."""
    return child_id.split(":", 2)[2] if child_id.count(":") >= 3 else child_id


def section_scheme(section_id: str) -> str:
    """``hierarchical:2026-09-30:ABSLMCF:p0`` → ``ABSLMCF``."""
    parts = section_id.split(":")
    if len(parts) < 4:
        raise ValueError(f"not a hierarchical parent id: {section_id!r}")
    return parts[2]


def child_refs(children: Sequence[Retrieved]) -> list[ChildRef]:
    return [ChildRef(c.chunk.id, str(c.chunk.parent_id), c.chunk.scheme_code, tuple(c.chunk.source_rows))
            for c in children]


def targets_for(questions: Iterable[Question], holdings: pd.DataFrame,
                row_parent: dict[RowKey, str]) -> dict[str, Target]:
    """Each question's gold rows and gold sections, computed by code (FR-R1.7). Unanswerable questions
    get an empty target. Where a question file already carries ``tags.gold_sections``, it must agree."""
    out: dict[str, Target] = {}
    for q in questions:
        if not q.answerable:
            out[q.id] = Target(frozenset(), frozenset())
            continue
        rows = compute(holdings, q.gold_fn, q.params).rows
        sections = gold_sections(q, holdings, row_parent)
        tagged = q.tags.get("gold_sections")
        if tagged and sorted(tagged) != sections:
            raise ValueError(f"{q.id}: tags.gold_sections {sorted(tagged)} is not what the gold rows give "
                             f"({sections}); regenerate the question set")
        out[q.id] = Target(frozenset(rows), frozenset(sections))
    return out


# --------------------------------------------------------------------------- metrics (§6.4)

def metrics(target: Target, children: Sequence[ChildRef], ks: Sequence[int] = KS) -> dict[str, float]:
    """Retrieval metrics for one question. Answerable questions only: an unanswerable one has no gold
    rows, so recall is undefined (``ValueError``) and the caller leaves it out."""
    if not target.answerable:
        raise ValueError("retrieval metrics need gold rows: unanswerable questions are left out (§6.4)")
    if not target.sections:
        raise ValueError("gold rows without gold sections: re-index hierarchical")
    out: dict[str, float] = {}
    gold_schemes = target.schemes
    for k in ks:
        top = children[:k]
        rows = {r for c in top for r in c.rows}
        out[f"hit@{k}"] = float(bool(rows & target.rows))
        out[f"row_recall@{k}"] = len(rows & target.rows) / len(target.rows)
        out[f"section_recall@{k}"] = len({c.parent_id for c in top} & target.sections) / len(target.sections)
        out[f"scheme_recall@{k}"] = len({c.scheme_code for c in top} & gold_schemes) / len(gold_schemes)
    out[f"mrr@{MRR_K}"] = next((1 / n for n, c in enumerate(children[:MRR_K], 1)
                                if set(c.rows) & target.rows), 0.0)
    return out


def context_metrics(target: Target, children: Sequence[Retrieved], parents: dict,
                    top_k: int) -> dict[str, float | int]:
    """What the LLM would get: the top_k children swapped for their parent sections (FR-3.3).

    ``context_gold_row_recall`` is the chunking run's ``gold_row_recall``; ``context_tokens`` counts the
    parents with the embedding tokenizer, as ``results.csv`` does. Both are ``None`` when the question is
    unanswerable (no gold rows), except ``context_tokens``, which always counts."""
    sections = swap_for_parents(list(children[:top_k]), parents)
    rows = {r for s in sections for r in s.chunk.source_rows}
    recall = len(rows & target.rows) / len(target.rows) if target.answerable else None
    return {"n_sections": len(sections), "context_gold_row_recall": recall,
            "context_tokens": sum(s.chunk.n_tokens for s in sections)}


def filter_flags(debug: dict, target: Target) -> dict[str, int | None]:
    """``filter_miss`` / ``filter_wrong`` for a method that filters by scheme (§5.1), else ``None``.

    Not finding any scheme counts as ``filter_miss``: the method then searches everything (plain M1), so
    the right scheme was not found. Finding a scheme the gold rows do not use is ``filter_wrong``, even
    when the right one was found too (D031's FoF case, R2 notes)."""
    if "schemes_found" not in debug or not target.answerable:
        return {"filter_miss": None, "filter_wrong": None}
    found = set(debug["schemes_found"] or [])
    return {"filter_miss": int(bool(target.schemes - found)), "filter_wrong": int(bool(found - target.schemes))}


# --------------------------------------------------------------------------- one run

def variant_label(name: str, overrides: dict[str, Any] | None) -> str:
    """``bm25`` with no overrides, ``bm25[k1=1.2,b=0.5]`` with them: the row's ``variant``."""
    if not overrides:
        return name
    return f"{name}[" + ",".join(f"{k}={overrides[k]}" for k in sorted(overrides)) + "]"


def grid_variants(bench, name: str) -> list[dict[str, Any]]:
    """Every combination of the method's grid in config.yaml (empty dict when it has no grid)."""
    grid = bench.grids.get(name) or {}
    if not grid:
        return [{}]
    keys = sorted(grid)
    return [dict(zip(keys, values)) for values in itertools.product(*(grid[k] for k in keys))]


def combo_variants() -> list[dict[str, Any]]:
    """M8's candidates: every ranker, with and without the scheme filter (declared on dev only)."""
    return [{"filter": f, "ranker": r} for r in RANKERS for f in (False, True)]


def run_question(method: RetrievalMethod, q: Question, target: Target, parents: dict, candidate_k: int,
                 top_k: int) -> dict[str, Any]:
    """One (method, question) row: the ranked children, the metrics, the latency and the debug."""
    res = method.retrieve(q.text, candidate_k)
    refs = child_refs(res.children)
    row: dict[str, Any] = {
        "qid": q.id, "type": q.type, "answer_kind": q.answer_kind, "answerable": int(q.answerable),
        "short_name": int(bool(q.tags.get("short_name"))),
        "n_gold_rows": len(target.rows), "n_gold_sections": len(target.sections),
        "gold_sections": json.dumps(sorted(target.sections)), "gold_schemes": json.dumps(sorted(target.schemes)),
        "children": json.dumps([short_id(c.id) for c in refs]),
        "scores": json.dumps([round(c.score, 6) for c in res.children]),
        "retrieval_ms": round(res.latency_ms, 3),
        "filter_match": res.debug.get("match"),
        "schemes_found": json.dumps(res.debug.get("schemes_found")) if "schemes_found" in res.debug else None,
        "padded": res.debug.get("padded"),
        "debug": json.dumps({k: v for k, v in res.debug.items() if v not in (None, {}, [], 0)},
                            ensure_ascii=False),
    }
    row.update(metrics(target, refs) if target.answerable else {c: None for c in METRIC_COLUMNS})
    row.update(context_metrics(target, res.children, parents, top_k))
    row.update(filter_flags(res.debug, target))
    return row


def run_set(shared, parents: dict, questions: Sequence[Question], targets: dict[str, Target], set_name: str,
            variants: Sequence[tuple[str, dict[str, Any] | None]], top_k: int,
            originals: frozenset[str] = frozenset(), on_method=None) -> list[dict[str, Any]]:
    """Every (method variant, question) of one set. ``variants`` is (method name, overrides or None);
    ``top_k`` (5) is what the pipeline sends the LLM, so the context metrics match Stage B."""
    candidate_k = shared.bench.candidate_k
    rows: list[dict[str, Any]] = []
    for name, overrides in variants:
        method = build_method(name, shared, overrides)
        label = variant_label(name, overrides)
        if on_method:
            on_method(label, len(questions))
        for q in questions:
            row = run_question(method, q, targets[q.id], parents, candidate_k, top_k)
            rows.append({"set": set_name, "method": name, "method_id": METHOD_IDS[name], "variant": label,
                         "settings": json.dumps(method.options, sort_keys=True),
                         "original": int(q.id in originals), **row})
    return rows


# --------------------------------------------------------------------------- offline.csv

def _cell(v: Any) -> Any:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, float):
        return round(v, 6)
    return v


def write_offline(path: Path, rows: Sequence[dict[str, Any]], replace_sets: Iterable[str] = ()) -> Path:
    """Append rows to offline.csv, dropping any earlier rows of the sets being re-run."""
    drop = set(replace_sets)
    kept = [r for r in read_offline_rows(path) if r.get("set") not in drop]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in [*kept, *rows]:
            w.writerow({k: _cell(r.get(k)) for k in COLUMNS})
    tmp.replace(path)
    return path


def read_offline_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


NUMERIC_COLUMNS = [*METRIC_COLUMNS, "answerable", "original", "short_name", "n_gold_rows",
                   "n_gold_sections", "n_sections", "context_gold_row_recall", "context_tokens",
                   "retrieval_ms", "filter_miss", "filter_wrong", "padded"]


def frame(rows: Sequence[dict[str, Any]]) -> pd.DataFrame:
    """Rows from ``run_set`` as a DataFrame with the numbers typed as ``load_offline`` types them."""
    df = pd.DataFrame(list(rows), columns=COLUMNS)
    for c in NUMERIC_COLUMNS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def load_offline(path: Path) -> pd.DataFrame:
    """offline.csv as numbers (strings stay strings, "" becomes NaN)."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    for c in NUMERIC_COLUMNS:
        df[c] = pd.to_numeric(df[c].replace("", None), errors="coerce")
    return df


# --------------------------------------------------------------------------- ranking (§6.5)

@dataclass
class Standing:
    """One method variant's numbers on one set: the ranking key and what the report prints."""
    variant: str
    method: str
    settings: dict[str, Any]
    n: int                      # answerable questions scored
    section_recall_5: float
    hit_5: float
    mrr_10: float
    median_ms: float
    p90_ms: float
    row_recall_5: float
    scheme_recall_5: float
    context_recall: float
    context_tokens: float
    rank: int = 0

    @property
    def key(self) -> tuple:
        """§6.5: mean section_recall@5, then hit@5, then mrr@10, then lower median latency.

        Latency is compared in steps of ``LATENCY_TIE_MS``: on this laptop two runs of the same method
        differ by a few milliseconds, and a tie-break that reads that noise would pick different dev
        settings on every run (seen on the scheme filter's threshold, 23 Nov 2026). Methods that really
        differ in cost — anything with the cross-encoder — differ by seconds, so the step changes no real
        comparison. A tie that survives this is settled by the variant name (``rank_variants``), so the
        same dev run always chooses the same settings."""
        return (-round(self.section_recall_5, 6), -round(self.hit_5, 6), -round(self.mrr_10, 6),
                round(self.median_ms / LATENCY_TIE_MS) if not math.isnan(self.median_ms) else math.inf)


def _mean(s: pd.Series) -> float:
    s = s.dropna()
    return float(s.mean()) if len(s) else math.nan


def standing(df: pd.DataFrame, variant: str) -> Standing:
    """One variant's standing from the rows of one set (answerable questions for retrieval metrics)."""
    sub = df[df["variant"] == variant]
    if sub.empty:
        raise ValueError(f"no rows for variant {variant!r}")
    ans = sub[sub["answerable"] == 1]
    ms = sub["retrieval_ms"].dropna()
    settings = json.loads(sub["settings"].iloc[0] or "{}")
    return Standing(variant=variant, method=str(sub["method"].iloc[0]), settings=settings, n=len(ans),
                    section_recall_5=_mean(ans["section_recall@5"]), hit_5=_mean(ans["hit@5"]),
                    mrr_10=_mean(ans[f"mrr@{MRR_K}"]),
                    median_ms=float(ms.median()) if len(ms) else math.nan,
                    p90_ms=float(ms.quantile(0.9)) if len(ms) else math.nan,
                    row_recall_5=_mean(ans["row_recall@5"]), scheme_recall_5=_mean(ans["scheme_recall@5"]),
                    context_recall=_mean(ans["context_gold_row_recall"]),
                    context_tokens=_mean(sub["context_tokens"]))


def rank_variants(df: pd.DataFrame, variants: Sequence[str] | None = None) -> list[Standing]:
    """Standings of the given variants (all of them by default), best first, ties sharing a rank."""
    names = list(variants) if variants else list(dict.fromkeys(df["variant"]))
    items = sorted((standing(df, v) for v in names), key=lambda s: (s.key, s.variant))
    for i, s in enumerate(items):
        s.rank = items[i - 1].rank if i and s.key == items[i - 1].key else i + 1
    return items


def rank_methods(df: pd.DataFrame) -> list[Standing]:
    """The leaderboard: one standing per method (M1 … M8), in the §6.5 order."""
    by_method = {m: [v for v in dict.fromkeys(df[df["method"] == m]["variant"])] for m in METHOD_NAMES}
    variants = [vs[0] for m, vs in by_method.items() if vs]
    extra = {m: vs for m, vs in by_method.items() if len(vs) > 1}
    if extra:
        raise ValueError(f"more than one variant per method in this set: {extra}; the leaderboard needs the "
                         "chosen settings only (run the grid on dev, the chosen values on test)")
    return rank_variants(df, variants)


def shortlist(ranking: Sequence[Standing], reference: str = REFERENCE, n: int = SHORTLIST_N) -> list[str]:
    """Stage B's methods: the top 2 by §6.5 plus M1 dense; if dense is in the top 2, the next one joins
    (RD6). In leaderboard order, so the reference is not always last."""
    names = [s.method for s in ranking]
    if reference not in names:
        return names[:n]
    chosen = [m for m in names if m != reference][:n - 1] + [reference]
    return [m for m in names if m in set(chosen)]


# --------------------------------------------------------------------------- dev choices (§6.2, FR-R2.3)

def choose_variants(dev: pd.DataFrame, methods: Sequence[str] = METHOD_NAMES) -> dict[str, Standing]:
    """The best variant of each method on dev, by the §6.5 key. Methods with one variant are included
    too (nothing to choose, but the row is what the report shows)."""
    out: dict[str, Standing] = {}
    for name in methods:
        variants = list(dict.fromkeys(dev[dev["method"] == name]["variant"]))
        if variants:
            out[name] = rank_variants(dev, variants)[0]
    return out


def choose_combo(dev: pd.DataFrame) -> Standing:
    """M8 from dev only: the best (filter, ranker) pair among ``combo_variants`` (§5 M8, R3.4)."""
    variants = list(dict.fromkeys(dev[dev["method"] == "best_combo"]["variant"]))
    if not variants:
        raise ValueError("no best_combo rows on dev: run the combo candidates first")
    return rank_variants(dev, variants)[0]


_METHOD_LINE = re.compile(r"^(?P<indent>\s*)(?P<name>[a-z_0-9]+):\s*(?P<value>\{[^}]*\}|null|~)\s*"
                          r"(?P<comment>#.*)?$")


def method_line(line: str, name: str, options: dict[str, Any], date: str, note: str = "") -> str:
    """One ``methods:`` line of config.yaml with new options and a dated comment, keeping the old one."""
    m = _METHOD_LINE.match(line.rstrip("\n"))
    if not m or m.group("name") != name:
        raise ValueError(f"not the config line of method {name!r}: {line!r}")
    flow = "{" + ", ".join(f"{k}: {json.dumps(options[k])}" for k in options) + "}" if options else "{}"
    old = re.sub(r";?\s*chosen on dev .*$", "", (m.group("comment") or "").rstrip()).rstrip()
    chosen = f"chosen on dev {date}" + (f": {note}" if note else "")
    comment = f"{old}; {chosen}" if old and old != "#" else f"# {chosen}"
    return f"{m.group('indent')}{name}: {flow}" + (f"   {comment}" if comment else "")


def write_choices(path: Path, choices: dict[str, dict[str, Any]], date: str,
                  notes: dict[str, str] | None = None) -> list[str]:
    """Write the dev choices into config.yaml's ``retrieval_benchmark.methods`` lines (FR-R2.3).

    Line edits, not a YAML rewrite, so every comment in config.yaml survives. Returns the new lines."""
    text = path.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    inside = False
    written: dict[str, str] = {}
    for i, line in enumerate(lines):
        if re.match(r"^\s{2}methods:\s*$", line):
            inside = True
            continue
        if inside:
            if line.strip() and not line.startswith("    "):
                inside = False
                continue
            m = _METHOD_LINE.match(line)
            if m and m.group("name") in choices:
                name = m.group("name")
                lines[i] = method_line(line, name, choices[name], date, (notes or {}).get(name, ""))
                written[name] = lines[i]
    missing = set(choices) - set(written)
    if missing:
        raise ValueError(f"config.yaml has no retrieval_benchmark.methods line for {sorted(missing)}")
    path.write_text(newline.join(lines) + newline, encoding="utf-8", newline="")
    return [written[n] for n in choices if n in written]


# --------------------------------------------------------------------------- noise (§6.5, RD8)

def paired_bootstrap(a: Sequence[float], b: Sequence[float], resamples: int = BOOTSTRAP_RESAMPLES,
                     seed: int = BOOTSTRAP_SEED) -> tuple[float, float, float]:
    """95% interval of the mean per-question difference ``a - b`` (paired, same questions).

    Deterministic for a seed. Returns (mean difference, low, high); an interval holding 0 means "not
    distinguishable on this question set" (RD8)."""
    x, y = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if x.shape != y.shape:
        raise ValueError("paired bootstrap needs the same questions for both methods")
    if not len(x):
        return math.nan, math.nan, math.nan
    diff = x - y
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(diff), size=(resamples, len(diff)))
    means = diff[picks].mean(axis=1)
    return float(diff.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def paired_values(df: pd.DataFrame, a: str, b: str, column: str = PRIMARY) -> tuple[list[float], list[float]]:
    """One value per question for two methods, on the questions both answered (answerable only)."""
    ans = df[df["answerable"] == 1]
    first = ans[ans["method"] == a].set_index("qid")[column]
    second = ans[ans["method"] == b].set_index("qid")[column]
    qids = [q for q in dict.fromkeys(ans["qid"]) if q in first.index and q in second.index]
    return [float(first[q]) for q in qids], [float(second[q]) for q in qids]


def bootstrap_note(name: str, reference: str, mean: float, lo: float, hi: float, metric: str = PRIMARY) -> str:
    """The sentence §6.5 asks for, in plain language."""
    if math.isnan(mean):
        return f"No paired questions for {name} and {reference}: no interval."
    gap = f"{mean:+.3f} (95% {lo:+.3f} to {hi:+.3f})"
    if lo <= 0 <= hi:
        return (f"{name} vs {reference} on {metric}: {gap}. The interval includes 0, so {name} is not "
                f"distinguishable from {reference} on this question set.")
    better = "better" if mean > 0 else "worse"
    return f"{name} vs {reference} on {metric}: {gap}, so {name} is {better} than {reference} here."


# --------------------------------------------------------------------------- latency summary

def latency(df: pd.DataFrame, variant: str) -> tuple[float, float]:
    """Median and 90th percentile retrieval latency of one variant (FR-R2.4)."""
    ms = df[df["variant"] == variant]["retrieval_ms"].dropna()
    if not len(ms):
        return math.nan, math.nan
    return float(statistics.median(ms)), float(ms.quantile(0.9))


# --------------------------------------------------------------------------- loading the pieces

def load_world(settings, month: str | None = None, scorer=None):
    """Shared retrieval state, the parent chunks and the row → section map for one month."""
    from src.index.store import PARENTS_FILE, read_parents
    from src.parsing.pipeline import HOLDINGS_FILE
    from src.retrieval.base import Shared

    month = month or settings.data.eval_months[0]
    shared = Shared.load(settings, month, scorer)
    path = settings.paths.processed / PARENTS_FILE
    parents_df = pd.read_parquet(path)
    parents_df = parents_df[parents_df["as_of_date"].astype(str) == month]
    parents = {pid: c for pid, c in read_parents(path).items() if str(c.as_of_date) == month}
    holdings = pd.read_parquet(settings.paths.processed / HOLDINGS_FILE)
    return shared, parents, holdings, row_parent_map(parents_df)
