"""Load and check ``questions.yaml`` (task 5.2, FR-5.1).

A question set that is off (duplicate id, unknown gold function, a month the
experiment does not index, missing unit or options) fails here, before any
gold or LLM work.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.eval.gold import GOLD_FUNCTIONS
from src.eval.metrics import ANSWER_KINDS

QUESTIONS_FILE = Path(__file__).with_name("questions.yaml")
TYPES = ("lookup", "aggregation", "debt", "cross_scheme", "unanswerable", "cross_month")
TARGET_MIX = {"lookup": 7, "aggregation": 7, "debt": 5, "cross_scheme": 5, "unanswerable": 4}
UNITS = ("pct", "lakhs", "count")


class QuestionError(ValueError):
    pass


@dataclass(frozen=True)
class Question:
    id: str
    type: str
    text: str
    answer_kind: str
    gold_fn: str
    params: dict = field(default_factory=dict)
    unit: str | None = None
    options: dict[str, list[str]] | None = None

    @property
    def answerable(self) -> bool:
        return self.answer_kind != "not_in_data"

    @property
    def months(self) -> set[str]:
        return {str(self.params["as_of_date"])} if "as_of_date" in self.params else set()


def _question(raw: dict[str, Any]) -> Question:
    known = {"id", "type", "text", "answer_kind", "gold_fn", "params", "unit", "options"}
    extra = set(raw) - known
    if extra:
        raise QuestionError(f"{raw.get('id')}: unknown keys {sorted(extra)}")
    try:
        q = Question(**{k: raw[k] for k in raw})
    except TypeError as e:
        raise QuestionError(f"{raw.get('id')}: {e}") from None
    if q.type not in TYPES:
        raise QuestionError(f"{q.id}: unknown type {q.type!r}")
    if q.answer_kind not in ANSWER_KINDS:
        raise QuestionError(f"{q.id}: unknown answer_kind {q.answer_kind!r}")
    if q.gold_fn not in GOLD_FUNCTIONS:
        raise QuestionError(f"{q.id}: unknown gold_fn {q.gold_fn!r}")
    if (q.answer_kind == "not_in_data") != (q.type == "unanswerable"):
        raise QuestionError(f"{q.id}: only unanswerable questions have answer_kind not_in_data")
    if q.answer_kind == "number" and q.unit not in UNITS:
        raise QuestionError(f"{q.id}: number answers need unit in {UNITS}")
    if q.answer_kind == "choice":
        if not q.options or len(q.options) < 2:
            raise QuestionError(f"{q.id}: choice answers need at least two options")
        if set(q.options) != set(q.params.get("schemes", [])):
            raise QuestionError(f"{q.id}: options must be the schemes in params")
    return q


def load_questions(path: Path | str = QUESTIONS_FILE, eval_months: tuple[str, ...] | None = None) -> list[Question]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    questions = [_question(r) for r in raw]
    dupes = [i for i, n in Counter(q.id for q in questions).items() if n > 1]
    if dupes:
        raise QuestionError(f"duplicate question ids: {dupes}")
    if eval_months is not None:
        for q in questions:
            off = q.months - set(eval_months)
            if off:
                raise QuestionError(f"{q.id}: month {sorted(off)} is not in data.eval_months {list(eval_months)}")
    return questions


def mix(questions: list[Question]) -> dict[str, int]:
    return dict(Counter(q.type for q in questions))
