"""``python -m src.retrieval questions``

- ``questions``  generate ``dev.yaml`` and ``test_new.yaml`` from the templates (seed ``eval.seed``,
                 month ``data.eval_months[0]``), check they load, and write the manual check of 10
                 test-new questions → ``results/retrieval/manual_check.md`` (FR-R1.6). Prints the
                 type mix per set, the short-name share and the scheme split.

Later phases add ``offline``, ``estimate``, ``run`` and ``report`` here.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

import pandas as pd

from src.config import get_settings
from src.eval.manual_check import manual_check_md
from src.eval.questions import QUESTIONS_FILE, load_questions, mix
from src.parsing.pipeline import HOLDINGS_FILE

PARENTS_FILE = "parents_hierarchical.parquet"


def cmd_questions(settings) -> int:
    from src.retrieval.questions.generate import TYPE_ORDER, generate, write_sets
    from src.retrieval.questions.sets import load_set, set_sha256

    month = settings.data.eval_months[0]
    seed = settings.eval.seed
    holdings = pd.read_parquet(settings.paths.processed / HOLDINGS_FILE)
    parents = pd.read_parquet(settings.paths.processed / PARENTS_FILE)
    parents = parents[parents["as_of_date"].astype(str) == month]
    originals = load_questions(QUESTIONS_FILE, settings.data.eval_months)

    gen = generate(holdings, parents, originals, month, seed)
    files = write_sets(gen, seed, month)
    for name, path in files.items():
        print(f"wrote {path}")

    # Load back through the normal loader: catches anything the generator wrote wrong.
    sets = {name: load_set(name, settings.data.eval_months) for name in ("dev", "test_new", "test")}

    print(f"\nmonth {month}, seed {seed}")
    print(f"{'set':<9}" + "".join(f"{t:>14}" for t in TYPE_ORDER) + f"{'total':>8}{'short names':>14}")
    for name, qs in sets.items():
        m = mix(qs)
        short = sum(bool(q.tags.get("short_name")) for q in qs)
        print(f"{name:<9}" + "".join(f"{m.get(t, 0):>14}" for t in TYPE_ORDER)
              + f"{len(qs):>8}{f'{short} ({short / len(qs):.0%})':>14}")

    sides = Counter((gen.split[c], gen.categories[c]) for c in gen.split)
    print("\nscheme split (category: dev / test):")
    for cat in sorted({k for _, k in sides}):
        print(f"  {cat:<7} {sides[('dev', cat)]:>3} / {sides[('test', cat)]:>3}")
    used = {name: {s for q in qs for s in q.tags.get("schemes", [])} for name, qs in sets.items() if name != "test"}
    print(f"schemes used by questions: dev {len(used['dev'])}, test-new {len(used['test_new'])}, "
          f"shared {len(used['dev'] & used['test_new'])}")
    for name in ("dev", "test"):
        print(f"set_sha256({name}) = {set_sha256(name)[:16]}…")

    out_dir = settings.paths.results / "retrieval"
    out_dir.mkdir(parents=True, exist_ok=True)
    md = manual_check_md(sets["test_new"], holdings, settings.eval.manual_check_n, seed)
    md = md.replace("# Manual check of gold answers (FR-5.4)",
                    "# Manual check of gold answers: new test questions (FR-R1.6)", 1)
    path = out_dir / "manual_check.md"
    path.write_text(md, encoding="utf-8", newline="\n")
    print(f"\nwrote {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    ap = argparse.ArgumentParser(prog="python -m src.retrieval", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("questions", help="generate dev / test-new questions and the manual check")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    settings = get_settings()
    if args.cmd == "questions":
        return cmd_questions(settings)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
