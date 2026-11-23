"""The retrieval benchmark's question sets and gold sections (FR-R1.7, FR-R2.3).

- ``dev``      = ``dev.yaml`` (generated): used only to choose settings.
- ``test``     = the 28 hand-written ``src/eval/questions.yaml`` + ``test_new.yaml`` (generated).
- ``test_new`` = ``test_new.yaml`` alone (manual check, counts).

``set_sha256`` hashes every file of a set together, so a run fingerprint changes when any of them does.
``gold_sections`` maps a question's gold rows to the ``hierarchical`` parent ids (scheme × section) that
hold them: with parent swap, a section reaches the LLM when any of its rows is retrieved.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pandas as pd

from src.chunking.base import RowKey
from src.eval.gold import compute
from src.eval.questions import QUESTIONS_FILE, Question, QuestionError, load_questions

HERE = Path(__file__).parent
DEV_FILE = HERE / "dev.yaml"
TEST_NEW_FILE = HERE / "test_new.yaml"
SET_FILES: dict[str, tuple[Path, ...]] = {
    "dev": (DEV_FILE,),
    "test": (QUESTIONS_FILE, TEST_NEW_FILE),
    "test_new": (TEST_NEW_FILE,),
}


def set_files(name: str) -> tuple[Path, ...]:
    if name not in SET_FILES:
        raise ValueError(f"unknown question set {name!r}; known: {sorted(SET_FILES)}")
    return SET_FILES[name]


def load_set(name: str, eval_months: tuple[str, ...] | None = None) -> list[Question]:
    questions = [q for path in set_files(name) for q in load_questions(path, eval_months)]
    dupes = [i for i, n in Counter(q.id for q in questions).items() if n > 1]
    if dupes:
        raise QuestionError(f"set {name}: duplicate question ids across files: {dupes}")
    return questions


def set_sha256(name: str) -> str:
    """One hash over all files of a set, in order (file name + content of each). Line endings are
    normalised first, so a CRLF checkout (git autocrlf on Windows) hashes the same as the LF original."""
    h = hashlib.sha256()
    for path in set_files(name):
        content = path.read_bytes().replace(b"\r\n", b"\n")
        h.update(path.name.encode("utf-8") + b"\0")
        h.update(hashlib.sha256(content).hexdigest().encode("ascii") + b"\n")
    return h.hexdigest()


def row_parent_map(parents: pd.DataFrame) -> dict[RowKey, str]:
    """Holding row key → id of the ``hierarchical`` parent (section) that contains it."""
    out: dict[RowKey, str] = {}
    for pid, rows in zip(parents["id"], parents["source_rows"]):
        for f, s, r in json.loads(rows):
            out[(str(f), str(s), int(r))] = str(pid)
    return out


def gold_sections(q: Question, holdings: pd.DataFrame, row_parent: dict[RowKey, str]) -> list[str]:
    """Sorted parent ids holding the question's gold rows (empty for unanswerable questions)."""
    if not q.answerable:
        return []
    rows = compute(holdings, q.gold_fn, q.params).rows
    missing = [k for k in rows if k not in row_parent]
    if missing:
        raise KeyError(f"{q.id}: gold rows not in any parent, e.g. {missing[0]}")
    return sorted({row_parent[k] for k in rows})
