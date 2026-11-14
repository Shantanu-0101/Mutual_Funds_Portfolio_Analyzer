"""Every method × every question, same settings (task 5.5, FR-5.5, FR-5.6).

``run_eval`` asks each question through each of the six chunkers and the
pandas baseline, scores the answer against its gold (``metrics.score``), and
writes one row per (method, question) to ``results/results.csv``.

Resumable: rows already in ``results.csv`` are skipped. A row is *done* only
when its answer is final. These are not final and are asked again on the next
run (they stay in the file until replaced, marked by ``pending``):

- ``rate_limited`` / ``provider_unavailable``: the provider could not answer
  now (D9 says only a refused-as-too-large request is a recorded failure);
- ``sandbox_error``: the baseline's sandbox process itself failed;
- any answer given by the **fallback** provider (``fallback_reason`` set): it
  is a different model, so the row is re-run on the main one (task 5.5).

``--fresh`` deletes ``results.csv`` and skips the LLM cache for the recorded
run. A resumed run must use the same config, model and question file as the
run that started the file; otherwise it stops and asks for ``--fresh``, so one
``results.csv`` never mixes two set-ups.

``results/run_manifest.json`` (FR-5.6): date and time, git commit, config,
provider and model, embedding model, data file hashes, question file hash, and
one entry per session that added rows.

``failure`` labels every wrong row for the report (§6.6):

- ``format error``: the reply was not the agreed JSON;
- ``context overflow``: the provider refused the request as too large (D9);
- ``retrieval miss``: RAG answered, but not every gold row was in the context;
- ``generation error``: everything else (all gold rows were there and the
  answer is still wrong, an unanswerable question answered anyway, or the
  baseline's code failed or computed the wrong thing).
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

from src.chunking import REGISTRY
from src.eval.gold import GoldAnswer, compute
from src.eval.metrics import score
from src.eval.questions import QUESTIONS_FILE, Question
from src.parsing.pipeline import HOLDINGS_FILE

IST = timezone(timedelta(hours=5, minutes=30))
BASELINE = "baseline"
METHODS: tuple[str, ...] = (*REGISTRY, BASELINE)
RESULTS_FILE = "results.csv"
MANIFEST_FILE = "run_manifest.json"
PENDING_STATUSES = ("rate_limited", "provider_unavailable", "sandbox_error")

COLUMNS = [
    "method", "qid", "type", "answer_kind", "unit", "question", "gold_value", "n_gold_rows",
    "status", "error", "pending", "failure",
    "correct", "numeric_correct", "list_exact", "jaccard", "choice_correct", "unanswerable_correct",
    "refused", "false_refusal", "retrieval_hit", "gold_row_recall",
    "answer", "value", "answer_unit", "items", "insufficient_context", "n_cited_rows",
    "n_chunks", "n_context_rows", "context_tokens", "retrieved",
    "prompt_tokens", "completion_tokens", "reasoning_tokens",
    "retrieval_ms", "generation_ms", "execution_ms", "total_ms",
    "provider", "model", "fallback_reason", "cached", "code", "raw_text",
]

Answerer = Callable[[str], Any]   # question text → RagResult | BaselineResult


class ResumeMismatch(RuntimeError):
    """results.csv was started with another config, model or question set."""


# --------------------------------------------------------------------------- one row

def failure_label(row: dict) -> str:
    if row["correct"] == 1:
        return ""
    if row["status"] == "format_error":
        return "format error"
    if row["status"] == "context_overflow":
        return "context overflow"
    recall = row.get("gold_row_recall")
    if row["status"] == "ok" and recall is not None and recall < 1:
        return "retrieval miss"
    return "generation error"


def make_row(method: str, q: Question, gold: GoldAnswer, res: Any, rel: float, abs_pts: float) -> dict:
    """Score one method's result on one question into a results.csv row (plain values)."""
    retrieval = getattr(res, "retrieval", None)
    context_rows = [list(k) for k in retrieval.context_rows] if retrieval is not None else None
    answer = res.answer if res.status == "ok" else None
    s = score(q.answer_kind, gold.value, [list(k) for k in gold.rows], answer, unit=q.unit, options=q.options,
              context_rows=context_rows, rel=rel, abs_pts=abs_pts)
    retrieval_ms = retrieval.latency_ms if retrieval is not None else None
    execution_ms = getattr(res, "execution_ms", None) if retrieval is None else None
    row: dict[str, Any] = {
        "method": method, "qid": q.id, "type": q.type, "answer_kind": q.answer_kind, "unit": q.unit,
        "question": q.text, "gold_value": json.dumps(gold.value, ensure_ascii=False),
        "n_gold_rows": len(gold.rows), "status": res.status, "error": res.error,
        "pending": int(res.status in PENDING_STATUSES or bool(res.fallback_reason)),
        **s.as_dict(),
        "answer": answer.get("answer") if answer else None,
        "value": answer.get("value") if answer else None,
        "answer_unit": answer.get("unit") if answer else None,
        "items": json.dumps(answer.get("items") or [], ensure_ascii=False) if answer else None,
        "insufficient_context": answer.get("insufficient_context") if answer else None,
        "n_cited_rows": len(res.cited_rows),
        "n_chunks": len(retrieval.chunks) if retrieval is not None else None,
        "n_context_rows": len(context_rows) if context_rows is not None else None,
        "context_tokens": sum(r.chunk.n_tokens for r in retrieval.chunks) if retrieval is not None else None,
        "retrieved": json.dumps([r.chunk.id for r in retrieval.chunks]) if retrieval is not None else None,
        "prompt_tokens": res.prompt_tokens, "completion_tokens": res.completion_tokens,
        "reasoning_tokens": res.reasoning_tokens,
        "retrieval_ms": retrieval_ms, "generation_ms": res.generation_ms, "execution_ms": execution_ms,
        "total_ms": (retrieval_ms or 0) + (res.generation_ms or 0) + (execution_ms or 0),
        "provider": res.provider, "model": res.model, "fallback_reason": res.fallback_reason,
        "cached": int(bool(res.cached)), "code": getattr(res, "code", None), "raw_text": res.raw_text,
    }
    row["failure"] = failure_label(row)
    return row


# --------------------------------------------------------------------------- results.csv

def _cell(v: Any) -> Any:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    if isinstance(v, bool):
        return int(v)
    return v


def read_results(path: Path) -> list[dict]:
    """Rows of results.csv as dicts of strings ("" for empty)."""
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_results(path: Path, rows: Iterable[dict]) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: _cell(r.get(k)) for k in COLUMNS})
    tmp.replace(path)


def is_done(row: dict) -> bool:
    return str(row.get("pending", "")) in ("0", "") and row.get("status") not in PENDING_STATUSES


# --------------------------------------------------------------------------- manifest

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def git_state(cwd: Path) -> dict:
    def git(*args: str) -> str:
        try:
            return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    return {"commit": git("rev-parse", "HEAD") or None, "branch": git("rev-parse", "--abbrev-ref", "HEAD") or None,
            "dirty": bool(git("status", "--porcelain", "--untracked-files=no"))}


def setup_fingerprint(settings, questions_file: Path) -> dict:
    """What must stay the same for rows from two sessions to belong to one run."""
    cfg = settings.to_dict()
    cfg.pop("config_file", None)
    cfg["paths"] = {}                           # where files live does not change answers
    return {"config_sha256": hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest(),
            "llm_provider": settings.llm.provider, "llm_model": settings.llm.model,
            "questions_sha256": sha256_file(questions_file)}


def data_hashes(settings) -> dict[str, str]:
    files = sorted(settings.paths.raw.glob(settings.data.file_glob))
    out = {f"raw/{p.name}": sha256_file(p) for p in files}
    parquet = settings.paths.processed / HOLDINGS_FILE
    if parquet.is_file():
        out[f"processed/{HOLDINGS_FILE}"] = sha256_file(parquet)
    return out


def now_ist() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- the run

@dataclass
class RunSummary:
    asked: int
    skipped: int
    pending: list[tuple[str, str]]
    total_rows: int
    expected_rows: int

    @property
    def complete(self) -> bool:
        return not self.pending and self.total_rows == self.expected_rows


def run_eval(settings, questions: list[Question], holdings: pd.DataFrame, answerers: dict[str, Answerer], *,
             out_dir: Path, fresh: bool = False, project_root: Path | None = None,
             questions_file: Path = QUESTIONS_FILE, progress: Callable[[str], None] = print,
             manifest_extra: dict | None = None) -> RunSummary:
    """Ask every (method, question) not yet done; rewrite results.csv after each answer."""
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path, manifest_path = out_dir / RESULTS_FILE, out_dir / MANIFEST_FILE
    fingerprint = setup_fingerprint(settings, questions_file)
    methods = list(answerers)

    if fresh:
        results_path.unlink(missing_ok=True)
        manifest: dict = {}
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
        if results_path.is_file() and manifest.get("setup") and manifest["setup"] != fingerprint:
            raise ResumeMismatch("results.csv was started with a different config, model or question file; "
                                 "run with --fresh to start a new recorded run")

    rows = {(r["method"], r["qid"]): r for r in read_results(results_path)}
    order = {(m, q.id): i for i, (m, q) in enumerate((m, q) for m in METHODS for q in questions)}

    session = {"started_at": now_ist(), "fresh": fresh, **git_state(project_root or settings.config_file.parent)}
    manifest.setdefault("created_at", session["started_at"])
    manifest.update({
        "setup": fingerprint,
        "llm": {"provider": settings.llm.provider, "model": settings.llm.model, "fallback": settings.llm.fallback,
                "fallback_rows_rerun": True},
        "embedding_model": settings.embedding.model,
        "methods": methods, "questions": [q.id for q in questions],
        "data_files": data_hashes(settings), "config": settings.to_dict(),
        **(manifest_extra or {}),
    })
    manifest.setdefault("sessions", []).append(session)

    def save_manifest() -> None:
        tmp = manifest_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(manifest, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(manifest_path)

    def save_results() -> None:
        write_results(results_path, sorted(rows.values(), key=lambda r: order.get((r["method"], r["qid"]), 1e9)))

    save_manifest()
    golds = {q.id: compute(holdings, q.gold_fn, q.params) for q in questions}
    rel, abs_pts = settings.eval.rel_tolerance, settings.eval.abs_tolerance_pct_points
    asked = skipped = 0
    for method in methods:
        for q in questions:
            key = (method, q.id)
            if key in rows and is_done(rows[key]):
                skipped += 1
                continue
            res = answerers[method](q.text)
            row = make_row(method, q, golds[q.id], res, rel, abs_pts)
            rows[key] = row
            asked += 1
            save_results()
            mark = "PENDING" if row["pending"] else ("ok " if row["correct"] else "x  ")
            progress(f"{mark} {method:<14} {q.id} {row['status']:<17} "
                     f"{row['prompt_tokens']:>7,} tok {row['total_ms']:>8,.0f} ms"
                     + (f"  [{row['failure']}]" if row["failure"] else ""))

    pending = [k for k, r in rows.items() if not is_done(r)]
    session.update(finished_at=now_ist(), asked=asked, skipped=skipped)
    manifest.update(rows=len(rows), expected_rows=len(methods) * len(questions),
                    pending=[f"{m}:{q}" for m, q in pending], complete=not pending
                    and len(rows) == len(methods) * len(questions))
    save_manifest()
    return RunSummary(asked=asked, skipped=skipped, pending=pending, total_rows=len(rows),
                      expected_rows=len(methods) * len(questions))


SCORE_FIELDS = ("correct", "numeric_correct", "list_exact", "jaccard", "choice_correct", "unanswerable_correct",
                "refused", "false_refusal")


def _stored_answer(row: dict) -> dict | None:
    """The answer object as results.csv stored it (None when the method failed)."""
    if row["status"] != "ok":
        return None
    value = row["value"]
    return {"answer": row["answer"], "value": float(value) if value not in ("", None) else None,
            "unit": row["answer_unit"] or None, "items": json.loads(row["items"] or "[]"), "sources": [],
            "insufficient_context": str(row["insufficient_context"]).lower() in ("1", "true")}


def rescore(settings, questions: list[Question], holdings: pd.DataFrame, out_dir: Path, reason: str) -> int:
    """Re-score the stored answers with the current metrics, without asking anything again.

    Retrieval columns are kept (they do not depend on the metrics). Returns how many rows changed
    ``correct``; the manifest records when and why.
    """
    results_path, manifest_path = out_dir / RESULTS_FILE, out_dir / MANIFEST_FILE
    by_id = {q.id: q for q in questions}
    golds = {q.id: compute(holdings, q.gold_fn, q.params) for q in questions}
    rel, abs_pts = settings.eval.rel_tolerance, settings.eval.abs_tolerance_pct_points
    rows, changed = read_results(results_path), []
    for row in rows:
        q, gold = by_id[row["qid"]], golds[row["qid"]]
        s = score(q.answer_kind, gold.value, [list(k) for k in gold.rows], _stored_answer(row), unit=q.unit,
                  options=q.options, rel=rel, abs_pts=abs_pts).as_dict()
        before = row["correct"]
        row.update({k: s[k] for k in SCORE_FIELDS})
        recall = row["gold_row_recall"]
        row["failure"] = failure_label({**row, "gold_row_recall": float(recall) if recall not in ("", None) else None})
        if str(before) != str(row["correct"]):
            changed.append(f"{row['method']}:{row['qid']} {before}->{row['correct']}")
    write_results(results_path, rows)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    manifest.setdefault("rescored", []).append({"at": now_ist(), "reason": reason, "changed": changed,
                                                **git_state(settings.config_file.parent)})
    manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return len(changed)


def default_answerers(settings, methods: Iterable[str], fresh: bool) -> dict[str, Answerer]:
    """The real pipelines, sharing one LLM (same model, cache and settings for every method)."""
    from src.baseline.pipeline import BaselinePipeline
    from src.llm import LLM
    from src.rag.pipeline import RagPipeline

    llm = LLM.from_settings(settings, fresh=fresh)
    methods = list(methods)
    out: dict[str, Answerer] = {}
    chunkers = [m for m in methods if m != BASELINE]
    if chunkers:
        rag = RagPipeline(settings, llm=llm)
        for m in chunkers:
            out[m] = (lambda name: lambda text: rag.answer(text, name))(m)
    if BASELINE in methods:
        base = BaselinePipeline(settings, llm=llm)
        out[BASELINE] = base.answer
    return {m: out[m] for m in methods}
