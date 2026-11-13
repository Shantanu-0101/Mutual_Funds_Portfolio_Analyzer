"""``python -m src.eval gold | manual-check``

- ``gold``          compute every gold answer → ``results/gold_answers.md``
- ``manual-check``  sample questions for the hand check → ``results/manual_check.md``

``run`` and ``report`` (tasks 5.5, 5.6) come after the manual check (stop A).
"""

from __future__ import annotations

import sys

import pandas as pd

from src.config import get_settings
from src.eval.manual_check import gold_answers_md, manual_check_md
from src.eval.questions import TARGET_MIX, load_questions, mix
from src.parsing.pipeline import HOLDINGS_FILE

USAGE = "usage: python -m src.eval gold | manual-check"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] not in ("gold", "manual-check"):
        print(USAGE, file=sys.stderr)
        return 2
    settings = get_settings()
    questions = load_questions(eval_months=settings.data.eval_months)
    holdings = pd.read_parquet(settings.paths.processed / HOLDINGS_FILE)
    out_dir = settings.paths.results
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"{len(questions)} questions, mix {mix(questions)} (target {TARGET_MIX})")
    if argv[0] == "gold":
        path = out_dir / "gold_answers.md"
        path.write_text(gold_answers_md(questions, holdings), encoding="utf-8")
    else:
        path = out_dir / "manual_check.md"
        path.write_text(manual_check_md(questions, holdings, settings.eval.manual_check_n, settings.eval.seed),
                        encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
