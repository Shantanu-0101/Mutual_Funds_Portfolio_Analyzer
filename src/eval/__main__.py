"""``python -m src.eval gold | manual-check | run [--fresh] | report``

- ``gold``          compute every gold answer → ``results/gold_answers.md``
- ``manual-check``  sample questions for the hand check → ``results/manual_check.md``
- ``run``           every method × every question → ``results/results.csv`` + ``run_manifest.json``;
                    resumes where it stopped. ``--fresh`` starts over and skips the LLM cache (the
                    recorded run). ``--methods`` / ``--questions`` limit a run (smoke tests only).
- ``rescore``       re-score the stored answers with the current metrics (no LLM calls); ``--reason`` is
                    recorded in the manifest
- ``report``        ``results.csv`` → ``results/summary.md`` + ``accuracy_by_method.png``
"""

from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

from src.config import get_settings
from src.eval.manual_check import gold_answers_md, manual_check_md
from src.eval.questions import TARGET_MIX, load_questions, mix
from src.parsing.pipeline import HOLDINGS_FILE


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    ap = argparse.ArgumentParser(prog="python -m src.eval", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gold")
    sub.add_parser("manual-check")
    run = sub.add_parser("run")
    run.add_argument("--fresh", action="store_true", help="delete results.csv and skip the LLM cache")
    run.add_argument("--methods", help="comma-separated subset of methods (default: all)")
    run.add_argument("--questions", help="comma-separated subset of question ids (default: all)")
    sub.add_parser("report")
    resc = sub.add_parser("rescore")
    resc.add_argument("--reason", required=True, help="why the scores change (recorded in the manifest)")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    settings = get_settings()
    out_dir = settings.paths.results
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.cmd == "report":
        from src.eval.report import write_report

        print(f"wrote {write_report(out_dir)}")
        return 0

    questions = load_questions(eval_months=settings.data.eval_months)
    holdings = pd.read_parquet(settings.paths.processed / HOLDINGS_FILE)
    print(f"{len(questions)} questions, mix {mix(questions)} (target {TARGET_MIX})")

    if args.cmd == "rescore":
        from src.eval.runner import rescore

        n = rescore(settings, questions, holdings, out_dir, args.reason)
        print(f"re-scored results.csv: {n} row(s) changed correct/incorrect (listed in run_manifest.json)")
        return 0

    if args.cmd == "run":
        from src.eval.runner import METHODS, ResumeMismatch, default_answerers, run_eval

        logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
        methods = args.methods.split(",") if args.methods else list(METHODS)
        unknown = set(methods) - set(METHODS)
        if unknown:
            print(f"unknown methods {sorted(unknown)}; known: {list(METHODS)}", file=sys.stderr)
            return 2
        if args.questions:
            wanted = set(args.questions.split(","))
            questions = [q for q in questions if q.id in wanted]
        print(f"LLM {settings.llm.provider} / {settings.llm.model} (fallback {settings.llm.fallback}); "
              f"methods {methods}")
        try:
            summary = run_eval(settings, questions, holdings, default_answerers(settings, methods, args.fresh),
                               out_dir=out_dir, fresh=args.fresh)
        except ResumeMismatch as e:
            print(str(e), file=sys.stderr)
            return 2
        print(f"asked {summary.asked}, skipped {summary.skipped} already done; "
              f"{summary.total_rows}/{summary.expected_rows} rows, {len(summary.pending)} pending")
        if summary.pending:
            print("pending (run again to retry): " + ", ".join(f"{m}:{q}" for m, q in summary.pending))
        return 0 if summary.complete else 1

    if args.cmd == "gold":
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
