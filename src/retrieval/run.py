"""Phase R4, Stage B: the shortlisted retrieval methods × the test questions, through the real LLM.

One row per (method, question) in ``results/retrieval/results.csv`` — the chunking run's columns
(``src/eval/runner``) plus ``retrieval_method``, the method's settings and the filter debug. The loop
itself **is** ``run_eval``, so scoring, resume, the manifest and the pending rules are the ones the
chunking run already uses; this module only adds what Stage B needs:

- **Fingerprint** (§9.1, R4.2): config, the shortlisted methods *with their chosen settings*, the
  reranker model and revision, and one hash over all files of the question set (28 hand-written +
  generated). A resumed run whose fingerprint differs stops with ``ResumeMismatch``.
- **Hard cap** (FR-R9.2, R4.3): ``--max-tokens N``. Before each call the method retrieves, the prompt
  is built and looked up in the LLM cache: a cache hit is free, otherwise the call's tokens are
  predicted the way ``src.retrieval.estimate`` does (context + 680 overhead + 460 completion). If that
  would push this session's paid total over N, the run stops cleanly and every row it did not ask is
  written as pending (``status=not_asked``), so a later run picks them up. Retrieval runs twice per
  asked question (once to predict, once inside the pipeline); it is deterministic and costs
  milliseconds, so the recorded row is the same either way.
- **Failure labels** (R4.4): for a method that filters by scheme, a ``retrieval miss`` is refined to
  ``filter_miss`` (the question's own scheme was not found) or ``filter_wrong`` (a scheme the gold rows
  do not use was found). Every other label, and every row of a method without a filter, is unchanged.
- **Cache reuse** (FR-R3.3, RD7): on by default; ``cached`` says which rows cost nothing. Rows the Groq
  fallback answered stay pending and are re-asked on Grok, as in the chunking run.
- **Spend log** (FR-R9.3, R4.6): one appended row per paid run in ``results/retrieval/spend_log.csv``
  with IST time, phase, calls, cached, prompt / completion / reasoning tokens and estimate vs actual.
  Tokens only: prices are not kept in this repo (RD11).
- **Model check** (§12, R4.7): the Velona model is not a pinned snapshot, so ``--check-model`` asks the
  smoke questions once more with the cache switched off and compares those answers with the cached
  ones. Model, date, the check question and the verdict go into ``run_manifest.json``.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from src.eval import runner
from src.eval.questions import Question
from src.llm import LLM, LLMError
from src.rag.pipeline import RagPipeline
from src.rag.prompt import AnswerFormatError, build_messages, parse_answer
from src.rag.retrieve import HIERARCHICAL, swap_for_parents
from src.retrieval.base import build_method
from src.retrieval.estimate import COMPLETION_TOKENS, PROMPT_OVERHEAD, CacheProbe, Estimate, estimate
from src.retrieval.offline import Target, filter_flags
from src.retrieval.settings import METHOD_IDS

OUT_DIR = "retrieval"
SPEND_FILE = "spend_log.csv"
REFERENCE = "dense"                      # M1: the method the model check re-asks
EXTRA_COLUMNS = ["retrieval_method", "method_id", "method_settings", "filter_match", "schemes_found",
                 "filter_miss", "filter_wrong", "padded", "retrieval_debug"]
COLUMNS = [*runner.COLUMNS, *EXTRA_COLUMNS]
SPEND_COLUMNS = ["at_ist", "phase", "set", "methods", "questions", "calls", "cached", "paid_calls",
                 "prompt_tokens", "completion_tokens", "reasoning_tokens", "total_tokens",
                 "est_paid_calls", "est_prompt_tokens", "est_completion_tokens", "est_total_tokens",
                 "max_tokens", "stopped"]


# --------------------------------------------------------------------------- the cap and the ledger

@dataclass
class Ledger:
    """What this session actually spent, and whether the next call still fits under the cap."""

    max_tokens: int | None = None
    calls: int = 0
    cached: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def paid_calls(self) -> int:
        return self.calls - self.cached

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def allows(self, predicted: int) -> bool:
        return self.max_tokens is None or self.total_tokens + predicted <= self.max_tokens

    def record(self, res: Any) -> None:
        """Count one answer. A cached answer carries the original call's token counts; it cost nothing
        now, so it is counted as a call but not as spend."""
        self.calls += 1
        if getattr(res, "cached", False):
            self.cached += 1
            return
        self.prompt_tokens += res.prompt_tokens or 0
        self.completion_tokens += res.completion_tokens or 0
        self.reasoning_tokens += res.reasoning_tokens or 0

    def as_dict(self) -> dict[str, Any]:
        return {"calls": self.calls, "cached": self.cached, "paid_calls": self.paid_calls,
                "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
                "reasoning_tokens": self.reasoning_tokens, "total_tokens": self.total_tokens,
                "max_tokens": self.max_tokens}


class MethodAnswerer:
    """One shortlisted method: predict the call, obey the cap, then ask through ``RagPipeline.answer``."""

    def __init__(self, name: str, method, rag: RagPipeline, probe: CacheProbe, ledger: Ledger, top_k: int):
        self.name, self.method, self.rag = name, method, rag
        self.probe, self.ledger, self.top_k = probe, ledger, top_k

    def messages(self, text: str) -> tuple[list[dict], int]:
        """The exact prompt this method would send, and the retrieved sections' own tokens."""
        res = self.method.retrieve(text, self.top_k)
        sections = swap_for_parents(res.children, self.rag.retriever.parents)
        return build_messages(text, [s.chunk for s in sections]), sum(s.chunk.n_tokens for s in sections)

    def predict(self, text: str) -> tuple[int, bool]:
        """(tokens the call would cost, already in the LLM cache). A cache hit is free (FR-R3.3)."""
        messages, context = self.messages(text)
        if self.probe.hit(messages):
            return 0, True
        return context + PROMPT_OVERHEAD + COMPLETION_TOKENS, False

    def stop_reason(self, text: str) -> str | None:
        tokens, cached = self.predict(text)
        if cached or self.ledger.allows(tokens):
            return None
        return (f"--max-tokens {self.ledger.max_tokens:,}: the next call needs about {tokens:,} tokens and "
                f"{self.ledger.total_tokens:,} are already spent; nothing was asked")

    def __call__(self, text: str):
        res = self.rag.answer(text, HIERARCHICAL, method=self.method)
        self.ledger.record(res)
        return res


# --------------------------------------------------------------------------- rows

def failure_label(row: dict, flags: dict[str, int | None]) -> str:
    """``runner.failure_label`` refined for a method that filters by scheme (R4.4, §6.4).

    Only a ``retrieval miss`` is refined, and only when the filter is to blame: the context did not hold
    every gold row *and* the filter missed the question's scheme (``filter_miss``) or found one the gold
    rows do not use (``filter_wrong``). Every other label is the chunking run's."""
    label = row["failure"]
    if label != "retrieval miss":
        return label
    if flags.get("filter_miss"):
        return "filter_miss"
    if flags.get("filter_wrong"):
        return "filter_wrong"
    return label


def row_extras(row: dict, method: str, res: Any, settings_used: dict, target: Target | None) -> dict:
    """The Stage B columns: which method answered, with which settings, and what its filter did."""
    debug = dict(getattr(res.retrieval, "debug", {}) or {})
    flags = filter_flags(debug, target) if target is not None else {"filter_miss": None, "filter_wrong": None}
    out = {
        "retrieval_method": method, "method_id": METHOD_IDS.get(method),
        "method_settings": json.dumps(settings_used, sort_keys=True),
        "filter_match": debug.get("match"),
        "schemes_found": json.dumps(debug.get("schemes_found")) if "schemes_found" in debug else None,
        "padded": debug.get("padded"),
        "retrieval_debug": json.dumps({k: v for k, v in debug.items() if v not in (None, {}, [], 0)},
                                      sort_keys=True),
        **flags,
    }
    return {**row, **out, "failure": failure_label(row, flags)}


# --------------------------------------------------------------------------- fingerprint (R4.2, §9.1)

def fingerprint(settings, bench, methods: Sequence[str], set_name: str) -> dict:
    """What must stay the same for two sessions' rows to belong to one Stage B run."""
    from src.retrieval.questions.sets import set_sha256

    cfg = settings.to_dict()
    cfg.pop("config_file", None)
    cfg["paths"] = {}                                  # where files live does not change answers
    cfg.pop("retrieval_benchmark", None)               # the method settings below are the precise part
    return {"config_sha256": hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest(),
            "llm_provider": settings.llm.provider, "llm_model": settings.llm.model,
            "question_set": set_name, "questions_sha256": set_sha256(set_name),
            "methods": {m: bench.method_options(m) for m in methods},
            "reranker": {"model": bench.reranker["model"], "revision": bench.reranker["revision"]}}


# --------------------------------------------------------------------------- spend log (R4.6, FR-R9.3)

def append_spend(path: Path, phase: str, set_name: str, methods: Sequence[str], n_questions: int,
                 ledger: Ledger, est: Estimate | None, stopped: str | None) -> dict:
    """One row per paid run: what it cost, next to what the estimate said (tokens only, RD11)."""
    row = {"at_ist": runner.now_ist(), "phase": phase, "set": set_name, "methods": " ".join(methods),
           "questions": n_questions, **ledger.as_dict(),
           "est_paid_calls": est.to_pay if est else "", "est_prompt_tokens": est.prompt_tokens if est else "",
           "est_completion_tokens": est.completion_tokens if est else "",
           "est_total_tokens": est.total_tokens if est else "", "stopped": stopped or ""}
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.is_file()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SPEND_COLUMNS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in SPEND_COLUMNS})
    return row


# --------------------------------------------------------------------------- model check (R4.7, §12)

def cached_answer(llm: LLM, messages: list[dict]) -> dict | None:
    """The answer the LLM cache already holds for this prompt (None when it holds none)."""
    path = llm._cache_path(llm.cache_key(messages, True))
    if not path or not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("result")


def _value(text: str | None) -> dict | None:
    try:
        return parse_answer(text or "")
    except AnswerFormatError:
        return None


def model_check(settings, answerer: MethodAnswerer, questions: Sequence[Question],
                progress=print) -> dict:
    """Ask M1's smoke prompts again with the cache off and compare with the cached answers (§12).

    The Velona model is not a pinned snapshot, so an unchanged prompt that now answers differently means
    the model moved under the benchmark. Writes nothing to the cache (``cache=False``), so the recorded
    answers stay the baseline for the next run."""
    fresh = LLM(settings, cache=False, fallback=None)
    out: list[dict] = []
    for q in questions:
        messages, context = answerer.messages(q.text)
        before = cached_answer(answerer.probe.llm, messages)
        entry: dict[str, Any] = {"qid": q.id, "question": q.text,
                                 "cached_model": (before or {}).get("model"), "cached": bool(before)}
        tokens = context + PROMPT_OVERHEAD + COMPLETION_TOKENS
        if not answerer.ledger.allows(tokens):
            entry["skipped"] = "token cap reached"
            out.append(entry)
            break
        try:
            res = fresh.generate(messages, json=True)
        except LLMError as e:
            entry["error"] = f"{e.kind}: {e}"
            out.append(entry)
            continue
        answerer.ledger.record(res)
        a, b = _value(res.text), _value((before or {}).get("text"))
        entry.update(fresh_model=res.model, fresh_value=(a or {}).get("value"),
                     cached_value=(b or {}).get("value"),
                     same_value=None if (a is None or b is None) else a.get("value") == b.get("value"),
                     same_text=None if (a is None or b is None) else a.get("answer") == b.get("answer"))
        progress(f"  model check {q.id}: cached {entry['cached_value']} vs fresh {entry['fresh_value']} "
                 f"({'same' if entry['same_value'] else 'DIFFERENT'})")
        out.append(entry)
    compared = [e for e in out if e.get("same_value") is not None]
    verdict = ("no cached answer to compare" if not compared else
               "same answers" if all(e["same_value"] for e in compared) else "answers differ: model may have changed")
    return {"at": runner.now_ist(), "method": answerer.name, "model": settings.llm.model,
            "check_question": questions[0].text if questions else None, "questions": [q.id for q in questions],
            "verdict": verdict, "per_question": out}


def check_tokens(settings, shared, parents: dict, questions: Sequence[Question], set_name: str) -> int:
    """Tokens ``--check-model`` adds: M1's prompts asked again with the cache off, so none is free."""
    est = estimate(settings, shared, parents, questions, [REFERENCE], set_name)
    m = est.by_method[0]
    return m.context_tokens + m.calls * (PROMPT_OVERHEAD + COMPLETION_TOKENS)


# --------------------------------------------------------------------------- the run

@dataclass
class StageB:
    phase: str
    summary: runner.RunSummary
    ledger: Ledger
    estimate: Estimate
    spend: dict
    questions: list[Question] = field(default_factory=list)
    model_check: dict | None = None


def answerers_for(settings, shared, methods: Sequence[str], ledger: Ledger, *, fresh: bool = False,
                  llm: LLM | None = None, rag: RagPipeline | None = None) -> dict[str, MethodAnswerer]:
    """One answerer per shortlisted method, all sharing one LLM, cache and pipeline (R4.1)."""
    llm = llm or LLM.from_settings(settings, fresh=fresh)
    rag = rag or RagPipeline(settings, llm=llm)
    probe = CacheProbe(llm)
    top_k = settings.retrieval.top_k
    return {m: MethodAnswerer(m, build_method(m, shared), rag, probe, ledger, top_k) for m in methods}


def stage_b(settings, *, methods: Sequence[str], set_name: str = "test", phase: str = "full",
            questions: Sequence[Question] | None = None, max_tokens: int | None = None, fresh: bool = False,
            check_model: bool = False, progress=print, world=None, llm: LLM | None = None,
            rag: RagPipeline | None = None) -> StageB:
    """Ask ``methods`` × ``questions`` through the real LLM and write ``results/retrieval/results.csv``."""
    from src.retrieval.offline import load_world, targets_for
    from src.retrieval.questions.sets import load_set

    shared, parents, holdings, row_parent = world or load_world(settings)
    all_questions = list(load_set(set_name, settings.data.eval_months))
    qs = list(questions if questions is not None else all_questions)
    targets = targets_for(qs, holdings, row_parent)
    out_dir = settings.paths.results / OUT_DIR

    ledger = Ledger(max_tokens=max_tokens)
    answerers = answerers_for(settings, shared, methods, ledger, fresh=fresh, llm=llm, rag=rag)
    if not methods:
        raise ValueError("Stage B needs at least one method (the R3 shortlist)")
    est = estimate(settings, shared, parents, qs, methods, set_name, llm=answerers[methods[0]].probe.llm)
    settings_used = {m: a.method.options for m, a in answerers.items()}
    fp = fingerprint(settings, shared.bench, methods, set_name)

    def row_hook(row, method, q, res):
        return row_extras(row, method, res, settings_used[method], targets.get(q.id))

    def before_call(method, q):
        return answerers[method].stop_reason(q.text)

    summary = runner.run_eval(
        settings, qs, holdings, answerers, out_dir=out_dir, fresh=fresh, progress=progress,
        fingerprint=fp, columns=COLUMNS, row_hook=row_hook, before_call=before_call, method_order=methods,
        manifest_extra={"stage": "B", "phase": phase, "question_set": set_name,
                        "retrieval_methods": list(methods), "method_settings": settings_used,
                        "reranker": shared.bench.reranker, "candidate_k": shared.bench.candidate_k,
                        "top_k": settings.retrieval.top_k, "max_tokens": max_tokens,
                        "estimate": est.as_dict()})

    checked = None
    if check_model and REFERENCE in answerers:
        checked = model_check(settings, answerers[REFERENCE], qs, progress=progress)
    spend = append_spend(out_dir / SPEND_FILE, phase, set_name, methods, len(qs), ledger, est, summary.stopped)
    record_extras(out_dir, {"spend": spend, **({"model_check": checked} if checked else {})})
    return StageB(phase=phase, summary=summary, ledger=ledger, estimate=est, spend=spend, questions=qs,
                  model_check=checked)


def record_extras(out_dir: Path, extra: dict) -> None:
    """Add this session's spend row (and the model check) to the newest manifest session."""
    path = out_dir / runner.MANIFEST_FILE
    if not path.is_file():
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("sessions"):
        manifest["sessions"][-1].update(extra)
    manifest.update({k: v for k, v in extra.items() if k == "model_check"})
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)
