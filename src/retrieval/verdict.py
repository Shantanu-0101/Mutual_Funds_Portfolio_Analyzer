"""``results/retrieval/results.csv`` → which retrieval method is best end to end, and why (Phase R5).

The Stage B counterpart of ``src/eval/recommend.py``. Rules, all fixed by the spec before the paid run
(§6.5), so nothing here is a judgement call made after seeing the numbers:

- **Best** = most correct answers on the test set. A tie goes to higher ``context_gold_row_recall``
  (more of the rows an answer needs reached the LLM after the parent swap), then to fewer prompt tokens
  per question, then to lower median retrieval latency.
- **Per question type** the same rule names a best method (input for a router later, FR-R2.3 note).
- Every reason is a sentence built from the measured numbers; no LLM writes them.
- A method whose rows are missing is listed as *not run*, never ranked. A question still pending for any
  method is left out for **all** methods, so every method is ranked on the same questions. Either case
  makes the verdict *provisional*.
- **Noise** (RD8): paired bootstrap (10,000 resamples, seed 42) of the winner against M1 ``dense``, on
  ``correct`` here and on ``section_recall@5`` from Stage A. If an interval includes 0 the report says
  "not distinguishable from dense on this question set". That sentence goes into ``summary.md`` only,
  not into the Excel (RD8).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from src.eval.questions import TYPES
from src.eval.recommend import FAILURE_MEANING, SMALL_LEAD
from src.retrieval.offline import PRIMARY, REFERENCE, bootstrap_note, paired_bootstrap, paired_values
from src.retrieval.settings import METHOD_IDS

METHOD_COLUMN = "retrieval_method"
# Stage B labels that only methods with a scheme filter can carry (R4.4).
FILTER_MEANING = {
    "filter_miss": "the question's own scheme was not found, so the method searched everything",
    "filter_wrong": "a scheme the gold rows do not use was found and searched",
}
MEANING = {**FAILURE_MEANING, **FILTER_MEANING}


@dataclass
class Standing:
    """One method's end-to-end numbers on the ranking's question set."""
    method: str
    correct: int
    n: int
    context_recall: float      # mean context_gold_row_recall on answerable questions (the first tie-break)
    hit: float                 # share of answerable questions with at least one gold row in the context
    prompt_tokens: float       # mean prompt tokens per question (the second tie-break)
    completion_tokens: float
    retrieval_ms: float        # median retrieval latency (the third tie-break)
    total_ms: float
    context_tokens: float
    refusals_ok: int
    n_unanswerable: int
    false_refusals: int
    n_answerable: int
    cached: int
    failures: dict[str, int]
    settings: dict
    rank: int = 0
    note: str = ""

    @property
    def method_id(self) -> str:
        return METHOD_IDS.get(self.method, "–")

    @property
    def label(self) -> str:
        return f"{self.method_id} {self.method}"

    @property
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else math.nan

    @property
    def main_failure(self) -> str:
        if not self.failures:
            return ""
        kind, k = max(self.failures.items(), key=lambda kv: kv[1])
        return f"{kind} ({k} of {sum(self.failures.values())})"


@dataclass
class TypeBest:
    type: str
    n: int
    best: list[str]
    accuracy: float
    runner_up: str
    runner_up_accuracy: float
    decided_by: str


@dataclass
class Noise:
    """One paired bootstrap: the winner against M1 dense on one metric."""
    metric: str
    mean: float
    lo: float
    hi: float
    n: int
    note: str

    @property
    def distinguishable(self) -> bool:
        return not (math.isnan(self.mean) or self.lo <= 0 <= self.hi)


@dataclass
class Verdict:
    best: list[str]                      # one method, or several on a full tie
    final: bool
    reasons: list[str]
    caveats: list[str]
    ranking: list[Standing]
    by_type: list[TypeBest]
    noise: list[Noise]
    qids: list[str]
    left_out: dict[str, list[str]] = field(default_factory=dict)   # qid → methods pending on it
    not_run: list[str] = field(default_factory=list)

    @property
    def top(self) -> Standing:
        return self.ranking[0]

    @property
    def excel_caveats(self) -> list[str]:
        """The caveats minus the bootstrap sentence: it belongs in summary.md only (RD8)."""
        notes = {nz.note for nz in self.noise}
        return [c for c in self.caveats if c not in notes]


def _r(x: float) -> float:
    return -1.0 if pd.isna(x) else round(float(x), 4)


def _t(x: float) -> float:
    return math.inf if pd.isna(x) else round(float(x))


def _key(s: Standing) -> tuple:
    """§6.5: more correct, then higher context gold-row recall, then fewer prompt tokens, then faster."""
    return (-s.correct, -_r(s.context_recall), _t(s.prompt_tokens), _t(s.retrieval_ms))


def _settings(df: pd.DataFrame) -> dict:
    import json

    raw = [v for v in df["method_settings"].dropna().unique() if v not in ("", "{}")]
    try:
        return json.loads(raw[0]) if raw else {}
    except (TypeError, ValueError):
        return {}


def standing(df: pd.DataFrame, method: str) -> Standing:
    sub = df[df[METHOD_COLUMN] == method]
    ans = sub[sub["answer_kind"] != "not_in_data"]
    una = sub[sub["answer_kind"] == "not_in_data"]
    fails = sub[sub["failure"] != ""]["failure"].value_counts()
    return Standing(
        method=method, correct=int(sub["correct"].fillna(0).sum()), n=len(sub),
        context_recall=ans["gold_row_recall"].mean(), hit=ans["retrieval_hit"].mean(),
        prompt_tokens=sub["prompt_tokens"].mean(), completion_tokens=sub["completion_tokens"].mean(),
        retrieval_ms=sub["retrieval_ms"].median(), total_ms=sub["total_ms"].mean(),
        context_tokens=sub["context_tokens"].mean(),
        refusals_ok=int(una["unanswerable_correct"].fillna(0).sum()), n_unanswerable=len(una),
        false_refusals=int(ans["false_refusal"].fillna(0).sum()), n_answerable=len(ans),
        cached=int(sub["cached"].fillna(0).sum()),
        failures={str(k): int(v) for k, v in fails.items()}, settings=_settings(sub))


def _rank(items: list[Standing]) -> list[Standing]:
    items = sorted(items, key=_key)
    for i, s in enumerate(items):
        s.rank = items[i - 1].rank if i and _key(s) == _key(items[i - 1]) else i + 1
    return items


def _decided_by(a: Standing, b: Standing | None) -> str:
    if b is None:
        return "only method"
    if a.correct != b.correct:
        return "accuracy"
    if _r(a.context_recall) != _r(b.context_recall):
        return "context gold-row recall (tied on accuracy)"
    if _t(a.prompt_tokens) != _t(b.prompt_tokens):
        return "fewer prompt tokens (tied on accuracy and recall)"
    if _t(a.retrieval_ms) != _t(b.retrieval_ms):
        return "lower retrieval latency (tied on accuracy, recall and tokens)"
    return "full tie"


def _pct(x: float) -> str:
    return "–" if pd.isna(x) else f"{x:.0%}"


def _qrange(qids: list[str]) -> str:
    return ", ".join(qids) if len(qids) <= 6 else f"{qids[0]}–{qids[-1]}"


def _types(df: pd.DataFrame) -> list[str]:
    return [t for t in TYPES if t in set(df["type"])]


def _noise(df: pd.DataFrame, winner: str, offline: pd.DataFrame | None, label: str) -> list[Noise]:
    """Winner vs M1 dense: `correct` from Stage B, `section_recall@5` from Stage A (§6.5, RD8)."""
    out: list[Noise] = []
    if winner == REFERENCE:
        return out
    ref_label = f"{METHOD_IDS[REFERENCE]} {REFERENCE}"

    a = df[df[METHOD_COLUMN] == winner].set_index("qid")["correct"]
    b = df[df[METHOD_COLUMN] == REFERENCE].set_index("qid")["correct"]
    qids = [q for q in dict.fromkeys(df["qid"]) if q in a.index and q in b.index]
    if qids:
        first = [float(a[q]) for q in qids]
        second = [float(b[q]) for q in qids]
        mean, lo, hi = paired_bootstrap(first, second)
        out.append(Noise("correct", mean, lo, hi, len(qids),
                         bootstrap_note(label, ref_label, mean, lo, hi, "correct")))

    if offline is not None and not offline.empty:
        first, second = paired_values(offline, winner, REFERENCE)
        if first:
            mean, lo, hi = paired_bootstrap(first, second)
            out.append(Noise(PRIMARY, mean, lo, hi, len(first),
                             bootstrap_note(label, ref_label, mean, lo, hi, PRIMARY)))
    return out


def verdict(df: pd.DataFrame, offline: pd.DataFrame | None = None,
            methods: list[str] | None = None) -> Verdict:
    """Rank the Stage B methods in ``df`` (a loaded retrieval results.csv) and explain the winner.

    ``offline`` is the Stage A frame for the same question set (``set == test``), used only for the
    ``section_recall@5`` bootstrap. ``methods`` is the shortlist that was asked, so a method that was
    paid for but wrote no rows is reported as *not run* instead of silently vanishing.
    """
    present = list(dict.fromkeys(df[METHOD_COLUMN]))
    order = [m for m in METHOD_IDS if m in present] + [m for m in present if m not in METHOD_IDS]
    not_run = [m for m in (methods or []) if m not in present]
    if not order:
        raise ValueError("results.csv has no retrieval-method rows to rank")

    q_order = list(dict.fromkeys(df["qid"]))
    asked_by_all = set.intersection(*(set(df[df[METHOD_COLUMN] == m]["qid"]) for m in order))
    pend = df[df["pending"].fillna(0) == 1]
    left_out = {q: sorted(set(pend[pend["qid"] == q][METHOD_COLUMN]), key=order.index) for q in q_order
                if q in set(pend["qid"])}
    qids = [q for q in q_order if q in asked_by_all and q not in left_out]
    if not qids:
        raise ValueError("no question has an answer from every method yet; run Stage B first")
    used = df[df["qid"].isin(qids)]

    ranking = _rank([standing(used, m) for m in order])
    winners = [s for s in ranking if s.rank == 1]
    top = winners[0]
    others = [s for s in ranking if s.rank != 1]
    second = others[0] if others else None
    types = _types(used)

    by_type: list[TypeBest] = []
    type_stand: dict[str, dict[str, Standing]] = {}
    for t in types:
        tr = _rank([standing(used[used["type"] == t], m) for m in order])
        type_stand[t] = {s.method: s for s in tr}
        tw = [s for s in tr if s.rank == 1]
        rest = [s for s in tr if s.rank != 1]
        ru = rest[0] if rest else None
        if tw[0].correct == 0:              # nobody got any right: naming a "best" would mislead
            by_type.append(TypeBest(type=t, n=tw[0].n, best=[], accuracy=0.0, runner_up="",
                                    runner_up_accuracy=math.nan,
                                    decided_by="no method answered any correctly"))
            continue
        by_type.append(TypeBest(type=t, n=tw[0].n, best=[s.label for s in tw], accuracy=tw[0].accuracy,
                                runner_up=ru.label if ru else "",
                                runner_up_accuracy=ru.accuracy if ru else math.nan,
                                decided_by=_decided_by(tw[0], ru) if len(tw) == 1 else "full tie"))

    noise = _noise(used, top.method, offline, top.label) if len(winners) == 1 else []

    # ---- reasons (numbers only) ----
    reasons: list[str] = []
    n = top.n
    if len(winners) > 1:
        names = ", ".join(s.label for s in winners)
        reasons.append(f"Full tie between {names}: same correct answers ({top.correct}/{n}), same context "
                       f"gold-row recall ({_pct(top.context_recall)}), the same prompt tokens per question "
                       "and the same retrieval latency.")
    elif second is None:
        reasons.append(f"Only method in this run: {_pct(top.accuracy)} ({top.correct}/{n}).")
    else:
        basis = _decided_by(top, second)
        if basis == "accuracy":
            d = top.correct - second.correct
            reasons.append(f"Most correct answers: {_pct(top.accuracy)} ({top.correct}/{n}), {d} more than "
                           f"the runner-up {second.label} ({_pct(second.accuracy)}, {second.correct}/{n}).")
        elif basis.startswith("context gold-row recall"):
            reasons.append(f"Tied with {second.label} on correct answers ({top.correct}/{n}); wins because "
                           f"more of the rows each answer needs reach the LLM (context gold-row recall "
                           f"{_pct(top.context_recall)} vs {_pct(second.context_recall)}).")
        elif basis.startswith("fewer prompt tokens"):
            reasons.append(f"Tied with {second.label} on correct answers ({top.correct}/{n}) and context "
                           f"recall; wins on prompt tokens per question ({top.prompt_tokens:,.0f} vs "
                           f"{second.prompt_tokens:,.0f}).")
        else:
            reasons.append(f"Tied with {second.label} on correct answers ({top.correct}/{n}), recall and "
                           f"tokens; wins on retrieval latency ({top.retrieval_ms:,.0f} ms vs "
                           f"{second.retrieval_ms:,.0f} ms median).")

    ref = next((s for s in ranking if s.method == REFERENCE), None)
    if ref is not None and ref.method != top.method:
        reasons.append(f"Against the reference {ref.label} (M1, the method the chunking run used): "
                       f"{top.correct - ref.correct:+d} correct answers, context gold-row recall "
                       f"{_pct(top.context_recall)} vs {_pct(ref.context_recall)}, "
                       f"{top.prompt_tokens:,.0f} vs {ref.prompt_tokens:,.0f} prompt tokens per question.")

    strong = [f"{t} ({_pct(type_stand[t][top.method].accuracy)})" for t in types
              if type_stand[t][top.method].accuracy > 0
              and type_stand[t][top.method].correct == max(x.correct for x in type_stand[t].values())]
    if strong:
        reasons.append("Highest accuracy (alone or tied) on: " + ", ".join(strong) + ".")

    weak = sorted(((t, type_stand[t][top.method]) for t in types if type_stand[t][top.method].accuracy < 1),
                  key=lambda ts: ts[1].accuracy)
    for t, t_s in weak[:2]:
        kind, k = max(t_s.failures.items(), key=lambda kv: kv[1]) if t_s.failures else ("", 0)
        wrong = t_s.n - t_s.correct
        line = f"Weakest on {t}: {_pct(t_s.accuracy)} ({t_s.correct}/{t_s.n})."
        if kind:
            line += f" {k} of its {wrong} wrong answers are labelled {kind}: {MEANING.get(kind, kind)}"
            line += (f" (mean context gold-row recall {_pct(t_s.context_recall)})."
                     if kind == "retrieval miss" and not pd.isna(t_s.context_recall) else ".")
        best_t = next(b for b in by_type if b.type == t)
        if best_t.best and best_t.accuracy > t_s.accuracy:
            line += f" {', '.join(best_t.best)} does better here ({_pct(best_t.accuracy)})."
        elif not best_t.best:
            line += " No method answered any of these correctly."
        reasons.append(line)

    cheapest = min((s for s in ranking if not pd.isna(s.prompt_tokens)),
                   key=lambda s: s.prompt_tokens, default=None)
    if cheapest is not None and not pd.isna(top.prompt_tokens):
        line = (f"Cost: {top.prompt_tokens:,.0f} prompt tokens per question "
                f"({top.context_tokens:,.0f} of them the retrieved sections)")
        line += (", the cheapest of the methods in this run." if cheapest.method == top.method
                 else f"; the cheapest is {cheapest.label} ({cheapest.prompt_tokens:,.0f}).")
        reasons.append(line)
    if not pd.isna(top.retrieval_ms):
        reasons.append(f"Retrieval latency: {top.retrieval_ms:,.0f} ms median per question, measured after "
                       "the models are loaded; the LLM call dominates the rest "
                       f"({top.total_ms:,.0f} ms per question in all).")
    if top.n_unanswerable:
        reasons.append(f"Refusals: says the data does not contain the answer on {top.refusals_ok} of "
                       f"{top.n_unanswerable} unanswerable questions, and wrongly refuses "
                       f"{top.false_refusals} of {top.n_answerable} answerable ones.")

    # ---- notes for the other methods ----
    for s in ranking:
        if s.rank == 1:
            s.note = "best" if len(winners) == 1 else "joint best"
            continue
        parts = [f"{top.correct - s.correct} fewer correct than {top.label}" if s.correct < top.correct
                 else f"loses to {top.label} on {_decided_by(top, s)}"]
        gaps = [(type_stand[t][top.method].accuracy - type_stand[t][s.method].accuracy, t) for t in types]
        gap, t = max(gaps)
        if gap > 0:
            parts.append(f"biggest gap on {t} ({_pct(type_stand[t][s.method].accuracy)} vs "
                         f"{_pct(type_stand[t][top.method].accuracy)})")
        if s.failures:
            parts.append(f"most wrong answers are {s.main_failure}")
        s.note = "; ".join(parts)

    # ---- caveats ----
    caveats: list[str] = []
    if not_run:
        caveats.append(f"Shortlisted but absent from results.csv, so not ranked: {', '.join(not_run)}.")
    if left_out:
        who = sorted({m for ms in left_out.values() for m in ms}, key=order.index)
        caveats.append(f"{len(left_out)} question(s) left out ({_qrange(list(left_out))}) because the "
                       f"answers of {', '.join(who)} are still pending. Every method is compared on the "
                       f"same {len(qids)} questions.")
    missing = [q for q in q_order if q not in asked_by_all]
    if missing:
        caveats.append(f"{len(missing)} question(s) were not asked to every method and are left out: "
                       f"{_qrange(missing)}.")
    if second is not None and len(winners) == 1 and 0 < top.correct - second.correct <= SMALL_LEAD:
        caveats.append(f"The lead over {second.label} is small ({top.correct - second.correct} correct "
                       f"answer(s) out of {n}); with this few questions it could be noise.")
    for nz in noise:
        if not nz.distinguishable:
            caveats.append(nz.note)
    final = not not_run and not left_out and not missing

    return Verdict(best=[s.method for s in winners], final=final, reasons=reasons, caveats=caveats,
                   ranking=ranking, by_type=by_type, noise=noise, qids=qids, left_out=left_out,
                   not_run=not_run)


def verdict_line(v: Verdict) -> str:
    best = " and ".join(f"{METHOD_IDS.get(m, '')} {m}".strip() for m in v.best)
    status = "final for this run" if v.final else "provisional"
    return f"Best retrieval method for this data: {best} ({status})."
