"""``python -m src.retrieval {questions|demo}``

- ``questions``  generate ``dev.yaml`` and ``test_new.yaml`` from the templates (seed ``eval.seed``,
                 month ``data.eval_months[0]``), check they load, and write the manual check of 10
                 test-new questions → ``results/retrieval/manual_check.md`` (FR-R1.6). Prints the
                 type mix per set, the short-name share and the scheme split.

- ``demo``       (Phase R2 proof) one question through every method: the top children with scheme, section
                 and score, the sections the LLM would get, latency and debug. ``--check-dense`` checks M1
                 against the chunking run: for each of the 28 original questions, M1's parent sections
                 must equal the ``retrieved`` column of ``results/results.csv`` (hierarchical rows).
                 ``--lookalikes`` prints what the scheme filter finds in look-alike bank-fund questions.

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


LOOKALIKES = (
    "What % of AUM does the Banking & PSU Debt Fund hold in HDFC Bank Ltd. as on 30 Sep 2026?",
    "What % of AUM does Aditya Birla Sun Life Banking and Financial Services Fund hold in HDFC Bank Ltd. "
    "as on 30 Sep 2026?",
    "Which holds more ICICI Bank Ltd. as a % of AUM as on 30 Sep 2026: the Nifty Bank ETF or the BSE Top 10 "
    "Banks ETF?",
    "How many holdings does the Aditya Birla Sun Life Ultra Short Term Fund have as on 30 Sep 2026?",
    "What % of AUM does the banking & psu debt fund hold in AAA-rated bonds as on 30 Sep 2026?",
)


def _show(res, parents, k: int) -> None:
    from src.rag.retrieve import swap_for_parents

    kids = res.children[:k]
    print(f"  {res.method:<14} {res.latency_ms:8.1f} ms")
    for c in kids:
        inst = c.chunk.text.split("Instrument: ")[-1].split(" | ")[0][:44]
        print(f"    {c.rank:>2}. {c.chunk.scheme_code:<9} {c.chunk.section[:24]:<24} {inst:<44} {c.score:8.4f}")
    secs = swap_for_parents(kids, parents)
    print(f"     → {len(secs)} section(s): " + ", ".join(p.chunk.id.split(':', 2)[2] for p in secs))
    shown = {k2: v for k2, v in res.debug.items() if v not in (None, {}, [], 0)}
    if shown:
        print(f"     debug: {shown}")


def cmd_demo(settings, args) -> int:
    import json

    from src.index.store import read_parents
    from src.rag.retrieve import swap_for_parents
    from src.retrieval.base import METHOD_NAMES, Shared, build_method
    from src.retrieval.questions.sets import load_set

    shared = Shared.load(settings)
    parents = read_parents(settings.paths.processed / PARENTS_FILE)
    k = settings.retrieval.top_k
    names = args.methods or [m for m in METHOD_NAMES if shared.bench.methods.get(m) is not None]
    print(f"corpus: {len(shared.corpus)} children of {shared.dense.month}; methods: {', '.join(names)}")

    if args.check_dense:
        rec = pd.read_csv(settings.paths.results / "results.csv", encoding="utf-8")
        rec = rec[rec["method"] == "hierarchical"].set_index("qid")["retrieved"]
        dense = build_method("dense", shared)
        same = 0
        for q in load_questions(QUESTIONS_FILE, settings.data.eval_months):
            got = [p.chunk.id for p in swap_for_parents(dense.retrieve(q.text, k).children, parents)]
            want = json.loads(rec[q.id])
            same += got == want
            if got != want:
                print(f"  {q.id} differs: now {got} / recorded {want}")
        print(f"M1 dense vs the chunking run: {same} of {len(rec)} questions give the same sections in the same "
              "order")
        return 0 if same == len(rec) else 1

    if args.lookalikes:
        ex = shared.extractor
        threshold = shared.bench.method_options("scheme_filter")["fuzzy_threshold"]
        for t in LOOKALIKES:
            print(f"- {t}\n    {ex.extract(t, threshold).debug()}")
        return 0

    if args.text:
        text, label = args.text, "(text)"
    else:
        qs = {q.id: q for q in load_set(args.set, settings.data.eval_months)}
        if args.qid not in qs:
            print(f"no question {args.qid} in set {args.set}")
            return 1
        q = qs[args.qid]
        text, label = q.text, f"{q.id} ({q.type})"
        if q.tags.get("gold_sections"):
            label += f", gold sections {[g.split(':', 2)[2] for g in q.tags['gold_sections']]}"
    print(f"\n{label}\n  {text}\n")
    for name in names:
        _show(build_method(name, shared).retrieve(text, k), parents, k)
    return 0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    ap = argparse.ArgumentParser(prog="python -m src.retrieval", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("questions", help="generate dev / test-new questions and the manual check")
    d = sub.add_parser("demo", help="one question through every retrieval method (R2 proof)")
    d.add_argument("--qid", default="Q01", help="question id (default Q01)")
    d.add_argument("--set", default="test", choices=("dev", "test", "test_new"))
    d.add_argument("--text", help="any question text instead of --qid")
    d.add_argument("--methods", nargs="+", help="method names (default: every declared method)")
    d.add_argument("--check-dense", action="store_true", help="M1 vs the recorded chunking run, 28 questions")
    d.add_argument("--lookalikes", action="store_true", help="scheme filter on look-alike bank-fund questions")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    settings = get_settings()
    if args.cmd == "questions":
        return cmd_questions(settings)
    if args.cmd == "demo":
        return cmd_demo(settings, args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
