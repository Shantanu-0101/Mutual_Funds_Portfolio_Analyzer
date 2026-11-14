"""Scoring one answer against its gold (task 5.4, spec §6.6).

All functions are pure, so each rule is unit-tested on its edges.

- ``numeric_correct``: percent → ``abs(pred - gold) <= max(rel × |gold|, abs_pts)``
  (1% relative or 0.01 percentage points, whichever is larger, D5);
  lakhs and counts → relative 1% only (a zero gold then needs an exact 0).
- ``list_match``: set equality after ``normalise_text``; Jaccard reported too.
- ``choice_pick``: for "which of A or B" questions. Spec §6.6 asks for a
  normalised exact match, but a free-text answer naturally names *both*
  options ("Large Cap holds more than Flexi Cap"), so exact match would score
  correct answers as wrong. Rule used instead: look at ``items`` first, then
  the ``answer`` text; the option whose alias appears **earliest** is the
  pick. The option's key (the scheme code, e.g. ``BSLFEF``) is always an
  alias too: the pandas baseline answers with codes (fixed 14 Nov 2026, after
  the first full run scored three correct baseline answers as wrong).
  Deterministic, and the same for every method.
- ``refused``: ``insufficient_context`` is true, or the answer has no value
  and no items and its text says the data does not contain it.
- ``retrieval_hit`` / ``gold_row_recall``: ``None`` (not applicable) for
  unanswerable questions and for methods without retrieval (the baseline).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

ANSWER_KINDS = ("number", "list", "choice", "not_in_data")

REFUSAL = re.compile(
    r"insufficient|not (?:enough|sufficient)|"
    r"(?:does|do|did) not (?:contain|include|provide|mention|have|show|list|give|disclose)|"
    r"(?:is|are) not (?:in|available|provided|mentioned|given|disclosed|present|included|listed|shown)|"
    r"not (?:available|provided|mentioned|disclosed|present|included) in|"
    r"no (?:information|data|details|mention)|"
    r"cannot be (?:determined|answered|found|computed|calculated)|"
    r"(?:can ?not|unable to) (?:determine|answer|find|be determined)",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- text

def normalise_text(text: Any) -> str:
    t = str(text).casefold()
    t = re.sub(r"\blimited\b", "ltd", t)
    t = re.sub(r"[^\w\s]", " ", t)          # punctuation → space ("ltd." → "ltd")
    return re.sub(r"\s+", " ", t).strip()


def list_match(pred: Iterable[Any], gold: Iterable[Any]) -> tuple[bool, float]:
    p = {normalise_text(x) for x in pred if normalise_text(x)}
    g = {normalise_text(x) for x in gold if normalise_text(x)}
    union = p | g
    jaccard = len(p & g) / len(union) if union else 1.0
    return p == g, jaccard


def choice_pick(answer: dict, options: dict[str, list[str]]) -> str | None:
    """Which option key the answer picks, or None if it names none of them."""
    texts = [str(i) for i in answer.get("items") or []] + [str(answer.get("answer") or "")]
    for text in texts:
        t = f" {normalise_text(text)} "
        best: tuple[int, str] | None = None
        for key, aliases in options.items():
            for alias in [key, *aliases]:          # the scheme code itself names the option too
                pos = t.find(f" {normalise_text(alias)} ")
                if pos >= 0 and (best is None or pos < best[0]):
                    best = (pos, key)
        if best:
            return best[1]
    return None


# --------------------------------------------------------------------------- numbers

def numeric_correct(pred: Any, gold: float, unit: str | None, rel: float = 0.01, abs_pts: float = 0.01) -> bool:
    if pred is None or isinstance(pred, bool) or not isinstance(pred, (int, float)):
        return False
    diff = abs(float(pred) - float(gold))
    if unit == "pct":
        return diff <= max(rel * abs(gold), abs_pts) + 1e-12
    return diff <= rel * abs(gold) + 1e-12


# --------------------------------------------------------------------------- refusals and retrieval

def refused(answer: dict | None) -> bool:
    if not answer:
        return False
    if answer.get("insufficient_context") is True:
        return True
    if answer.get("value") is None and not answer.get("items"):
        return bool(REFUSAL.search(str(answer.get("answer") or "")))
    return False


def retrieval_hit(gold_rows: list, context_rows: list | None) -> int | None:
    if not gold_rows or context_rows is None:
        return None
    ctx = set(map(tuple, context_rows))
    return int(any(tuple(r) in ctx for r in gold_rows))


def gold_row_recall(gold_rows: list, context_rows: list | None) -> float | None:
    if not gold_rows or context_rows is None:
        return None
    ctx = set(map(tuple, context_rows))
    gold = {tuple(r) for r in gold_rows}
    return len(gold & ctx) / len(gold)


# --------------------------------------------------------------------------- one answer

@dataclass
class Score:
    correct: int
    numeric_correct: int | None = None
    list_exact: int | None = None
    jaccard: float | None = None
    choice_correct: int | None = None
    unanswerable_correct: int | None = None
    refused: int = 0
    false_refusal: int | None = None
    retrieval_hit: int | None = None
    gold_row_recall: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def score(kind: str, gold_value: Any, gold_rows: list, answer: dict | None, *, unit: str | None = None,
          options: dict[str, list[str]] | None = None, context_rows: list | None = None,
          rel: float = 0.01, abs_pts: float = 0.01) -> Score:
    """Score one answer. ``answer`` is None when the method failed (format error, timeout, ...): wrong."""
    if kind not in ANSWER_KINDS:
        raise ValueError(f"unknown answer kind {kind!r}")
    is_refused = refused(answer)
    s = Score(correct=0, refused=int(is_refused),
              retrieval_hit=retrieval_hit(gold_rows, context_rows),
              gold_row_recall=gold_row_recall(gold_rows, context_rows))
    if kind == "not_in_data":
        s.unanswerable_correct = int(is_refused)
        s.correct = s.unanswerable_correct
        return s
    s.false_refusal = int(is_refused)
    if answer is None:
        return s
    if kind == "number":
        s.numeric_correct = int(numeric_correct(answer.get("value"), gold_value, unit, rel, abs_pts))
        s.correct = s.numeric_correct
    elif kind == "list":
        exact, jac = list_match(answer.get("items") or [], gold_value)
        s.list_exact, s.jaccard = int(exact), jac
        s.correct = s.list_exact
    elif kind == "choice":
        s.choice_correct = int(choice_pick(answer, options or {}) == gold_value)
        s.correct = s.choice_correct
    return s
