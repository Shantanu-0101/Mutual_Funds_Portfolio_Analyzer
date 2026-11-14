"""``results.csv`` → which chunking method is best for this data, and why (Phase 5c, decisions R1–R5).

Rules (agreed 14 Nov 2026):

- R2 *Best* = most correct answers; a tie is broken by gold-row recall (more of the rows the answer
  needs reached the LLM), then by fewer tokens per question. The same rule picks the best method for
  each question type.
- R3 The pandas baseline does no chunking, so it is compared but never ranked.
- R4 Every reason is a sentence built from the measured numbers; no LLM writes them.
- R5 A chunker that was not run is listed as *not run*, never ranked. A question whose answer is still
  pending for any ranked chunker is left out for all of them, so every chunker is ranked on the same
  questions. Either case makes the verdict *provisional*.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from src.eval.questions import TYPES
from src.eval.runner import BASELINE, METHODS

CHUNKERS: tuple[str, ...] = tuple(m for m in METHODS if m != BASELINE)
SMALL_LEAD = 2          # a lead of this many correct answers or fewer is called out as possibly noise

# Plain-language meaning of each failure label (runner.failure_label).
FAILURE_MEANING = {
    "retrieval miss": "not every row the answer needs reached the LLM",
    "generation error": "the rows were there but the LLM still answered wrong",
    "format error": "the reply broke the JSON answer format",
    "context overflow": "the prompt was too large for the model",
}


@dataclass
class Standing:
    """One method's numbers on the ranking's question set."""
    method: str
    correct: int
    n: int
    recall: float            # mean gold-row recall on answerable questions (nan: none)
    hit: float               # share of answerable questions with at least one gold row retrieved
    tokens: float            # mean prompt + completion tokens per question
    refusals_ok: int         # unanswerable questions correctly refused
    n_unanswerable: int
    false_refusals: int      # answerable questions refused anyway
    n_answerable: int
    failures: dict[str, int]
    rank: int = 0
    note: str = ""

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
class Recommendation:
    best: list[str]                      # one method, or several on a full tie
    final: bool
    reasons: list[str]
    caveats: list[str]
    ranking: list[Standing]
    by_type: list[TypeBest]
    baseline: Standing | None
    baseline_note: str
    qids: list[str]                      # the questions the ranking uses
    left_out: dict[str, list[str]] = field(default_factory=dict)   # qid → methods pending on it
    not_run: list[str] = field(default_factory=list)


def _r(x: float) -> float:
    return -1.0 if pd.isna(x) else round(float(x), 4)


def _key(s: Standing) -> tuple:
    """Sort key for R2: more correct, then higher recall, then fewer tokens."""
    return (-s.correct, -_r(s.recall), math.inf if pd.isna(s.tokens) else round(float(s.tokens)))


def standing(df: pd.DataFrame, method: str) -> Standing:
    sub = df[df["method"] == method]
    ans = sub[sub["answer_kind"] != "not_in_data"]
    una = sub[sub["answer_kind"] == "not_in_data"]
    tok = (sub["prompt_tokens"].fillna(0) + sub["completion_tokens"].fillna(0))[sub["prompt_tokens"].notna()]
    fails = sub[sub["failure"] != ""]["failure"].value_counts()
    return Standing(method=method, correct=int(sub["correct"].fillna(0).sum()), n=len(sub),
                    recall=ans["gold_row_recall"].mean(), hit=ans["retrieval_hit"].mean(),
                    tokens=tok.mean() if len(tok) else math.nan,
                    refusals_ok=int(una["unanswerable_correct"].fillna(0).sum()), n_unanswerable=len(una),
                    false_refusals=int(ans["false_refusal"].fillna(0).sum()), n_answerable=len(ans),
                    failures={str(k): int(v) for k, v in fails.items()})


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
    if _r(a.recall) != _r(b.recall):
        return "gold-row recall (tied on accuracy)"
    if _key(a) != _key(b):
        return "fewer tokens (tied on accuracy and recall)"
    return "full tie"


def _pct(x: float) -> str:
    return "–" if pd.isna(x) else f"{x:.0%}"


def _qrange(qids: list[str]) -> str:
    return ", ".join(qids) if len(qids) <= 6 else f"{qids[0]}–{qids[-1]}"


def _types(df: pd.DataFrame) -> list[str]:
    return [t for t in TYPES if t in set(df["type"])]


def recommend(df: pd.DataFrame) -> Recommendation:
    """Rank the chunkers in ``df`` (a loaded results.csv) and explain the winner."""
    present = set(df["method"])
    run = [m for m in CHUNKERS if m in present]
    not_run = [m for m in CHUNKERS if m not in present]
    if not run:
        raise ValueError("results.csv has no chunker rows to rank")

    chunk = df[df["method"].isin(run)]
    order = list(dict.fromkeys(df["qid"]))
    asked_by_all = set.intersection(*(set(chunk[chunk["method"] == m]["qid"]) for m in run))
    pend = chunk[chunk["pending"].fillna(0) == 1]
    left_out = {q: sorted(set(pend[pend["qid"] == q]["method"]), key=run.index) for q in order
                if q in set(pend["qid"])}
    qids = [q for q in order if q in asked_by_all and q not in left_out]
    if not qids:
        raise ValueError("no question has an answer from every chunker yet; run the evaluation first")
    used = df[df["qid"].isin(qids)]

    ranking = _rank([standing(used, m) for m in run])
    winners = [s for s in ranking if s.rank == 1]
    top = winners[0]
    others = [s for s in ranking if s.rank != 1]
    second = others[0] if others else None
    types = _types(used)

    by_type: list[TypeBest] = []
    type_stand: dict[str, dict[str, Standing]] = {}
    for t in types:
        tr = _rank([standing(used[used["type"] == t], m) for m in run])
        type_stand[t] = {s.method: s for s in tr}
        tw = [s for s in tr if s.rank == 1]
        rest = [s for s in tr if s.rank != 1]
        ru = rest[0] if rest else None
        if tw[0].correct == 0:              # nobody got any right: naming a "best" would mislead
            by_type.append(TypeBest(type=t, n=tw[0].n, best=[], accuracy=0.0, runner_up="",
                                    runner_up_accuracy=math.nan, decided_by="no chunker answered any correctly"))
            continue
        by_type.append(TypeBest(type=t, n=tw[0].n, best=[s.method for s in tw], accuracy=tw[0].accuracy,
                                runner_up=ru.method if ru else "", runner_up_accuracy=ru.accuracy if ru else math.nan,
                                decided_by=_decided_by(tw[0], ru) if len(tw) == 1 else "full tie"))

    # ---- reasons for the winner (R4: numbers only) ----
    reasons: list[str] = []
    n = top.n
    if len(winners) > 1:
        names = ", ".join(s.method for s in winners)
        reasons.append(f"Full tie between {names}: same correct answers ({top.correct}/{n}), same gold-row "
                       f"recall ({_pct(top.recall)}) and the same tokens per question.")
    elif second is None:
        reasons.append(f"Only chunker in this run: {_pct(top.accuracy)} ({top.correct}/{n}).")
    else:
        basis = _decided_by(top, second)
        if basis == "accuracy":
            d = top.correct - second.correct
            reasons.append(f"Most correct answers: {_pct(top.accuracy)} ({top.correct}/{n}), {d} more than the "
                           f"runner-up {second.method} ({_pct(second.accuracy)}, {second.correct}/{n}).")
        elif basis.startswith("gold-row recall"):
            reasons.append(f"Tied with {second.method} on correct answers ({top.correct}/{n}); wins because more "
                           f"of the rows each answer needs reach the LLM (gold-row recall {_pct(top.recall)} vs "
                           f"{_pct(second.recall)}).")
        else:
            reasons.append(f"Tied with {second.method} on correct answers ({top.correct}/{n}) and recall; wins "
                           f"because it uses fewer tokens per question ({top.tokens:,.0f} vs "
                           f"{second.tokens:,.0f}).")

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
            line += f" {k} of its {wrong} wrong answers are labelled {kind}: {FAILURE_MEANING.get(kind, kind)}"
            line += (f" (mean gold-row recall {_pct(t_s.recall)})." if kind == "retrieval miss"
                     and not pd.isna(t_s.recall) else ".")
        best_t = next(b for b in by_type if b.type == t)
        if best_t.best and best_t.accuracy > t_s.accuracy:
            line += f" {', '.join(best_t.best)} does better here ({_pct(best_t.accuracy)})."
        elif not best_t.best:
            line += " No chunker answered any of these correctly."
        reasons.append(line)

    cheapest = min((s for s in ranking if not pd.isna(s.tokens)), key=lambda s: s.tokens, default=None)
    if cheapest is not None and not pd.isna(top.tokens):
        if cheapest.method == top.method:
            reasons.append(f"Cost: {top.tokens:,.0f} tokens per question, the cheapest of the ranked chunkers.")
        else:
            reasons.append(f"Cost: {top.tokens:,.0f} tokens per question; the cheapest ranked chunker is "
                           f"{cheapest.method} ({cheapest.tokens:,.0f}).")
    if top.n_unanswerable:
        reasons.append(f"Refusals: says the data does not contain the answer on {top.refusals_ok} of "
                       f"{top.n_unanswerable} unanswerable questions, and wrongly refuses {top.false_refusals} "
                       f"of {top.n_answerable} answerable ones.")

    # ---- notes for the other methods ----
    for s in ranking:
        if s.rank == 1:
            s.note = "best" if len(winners) == 1 else "joint best"
            continue
        parts = [f"{top.correct - s.correct} fewer correct than {top.method}" if s.correct < top.correct
                 else f"loses to {top.method} on {_decided_by(top, s)}"]
        gaps = [(type_stand[t][top.method].accuracy - type_stand[t][s.method].accuracy, t) for t in types]
        gap, t = max(gaps)
        if gap > 0:
            parts.append(f"biggest gap on {t} ({_pct(type_stand[t][s.method].accuracy)} vs "
                         f"{_pct(type_stand[t][top.method].accuracy)})")
        if s.failures:
            parts.append(f"most wrong answers are {s.main_failure}")
        s.note = "; ".join(parts)

    # ---- caveats (R5) ----
    caveats: list[str] = []
    if not_run:
        caveats.append(f"Not run, so not ranked: {', '.join(not_run)}.")
    if left_out:
        who = sorted({m for ms in left_out.values() for m in ms}, key=run.index)
        caveats.append(f"{len(left_out)} question(s) left out ({_qrange(list(left_out))}) because the answers of "
                       f"{', '.join(who)} are still pending (rate limit or provider down). Every ranked chunker "
                       f"is compared on the same {len(qids)} questions.")
    missing = [q for q in order if q not in asked_by_all]
    if missing:
        caveats.append(f"{len(missing)} question(s) were not asked to every chunker and are left out: "
                       f"{_qrange(missing)}.")
    if second is not None and len(winners) == 1 and top.correct - second.correct <= SMALL_LEAD:
        caveats.append(f"The lead is small ({top.correct - second.correct} correct answer(s) out of {n}); with "
                       "this few questions it could be noise.")
    final = not not_run and not left_out and not missing

    # ---- baseline (R3: compared, not ranked) ----
    base, base_note = None, ""
    if BASELINE in present:
        b_all = df[df["method"] == BASELINE]
        b_pend = int(b_all["pending"].fillna(0).sum())
        b_qids = [q for q in qids if q not in set(b_all[b_all["pending"].fillna(0) == 1]["qid"])]
        if not b_qids:
            base_note = (f"The pandas baseline (no chunking; compared, not ranked) has no answers yet: "
                         f"{b_pend} of {len(b_all)} rows are pending. Run the evaluation again.")
        else:
            b = standing(used[used["qid"].isin(b_qids)], BASELINE)
            t = standing(used[used["qid"].isin(b_qids)], top.method)
            base = b
            base_note = (f"The pandas baseline (no chunking; compared, not ranked) gets {_pct(b.accuracy)} "
                         f"({b.correct}/{b.n}) where {top.method} gets {_pct(t.accuracy)} ({t.correct}/{t.n}) "
                         f"on the same questions.")
            agg = used[(used["type"] == "aggregation") & used["qid"].isin(b_qids)]
            if len(agg):
                ba, ta = standing(agg, BASELINE), standing(agg, top.method)
                base_note += f" On aggregation: baseline {ba.correct}/{ba.n}, {top.method} {ta.correct}/{ta.n}."
            if b_pend:
                base_note += f" {b_pend} baseline row(s) are still pending."

    return Recommendation(best=[s.method for s in winners], final=final, reasons=reasons, caveats=caveats,
                          ranking=ranking, by_type=by_type, baseline=base, baseline_note=base_note, qids=qids,
                          left_out=left_out, not_run=not_run)


def verdict_line(rec: Recommendation) -> str:
    best = " and ".join(rec.best)
    status = "final for this run" if rec.final else "provisional"
    return f"Best chunking method for this data: {best} ({status})."
