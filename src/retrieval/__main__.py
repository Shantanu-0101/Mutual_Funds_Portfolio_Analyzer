"""``python -m src.retrieval {questions|demo|offline|estimate}``

- ``questions``  generate ``dev.yaml`` and ``test_new.yaml`` from the templates (seed ``eval.seed``,
                 month ``data.eval_months[0]``), check they load, and write the manual check of 10
                 test-new questions → ``results/retrieval/manual_check.md`` (FR-R1.6). Prints the
                 type mix per set, the short-name share and the scheme split.

- ``demo``       (Phase R2 proof) one question through every method: the top children with scheme, section
                 and score, the sections the LLM would get, latency and debug. ``--check-dense`` checks M1
                 against the chunking run: for each of the 28 original questions, M1's parent sections
                 must equal the ``retrieved`` column of ``results/results.csv`` (hierarchical rows).
                 ``--lookalikes`` prints what the scheme filter finds in look-alike bank-fund questions.

- ``offline``   (Phase R3) Stage A, free: every method on a question set, no LLM call.
                ``--set dev`` runs every grid value (§5), picks each method's settings by mean
                ``section_recall@5``, declares M8 from those dev results and writes both into
                ``config.yaml`` with today's date (``--no-write`` to only print them).
                ``--set test`` runs M1–M8 once with the chosen settings and writes ``offline.csv``,
                ``offline_summary.md`` and ``recall_by_method.png``, with the Stage B shortlist.

- ``estimate``  (Phase R3) what a Stage B run would cost in tokens, without one call: real prompts,
                real cache hits, tokens only (RD11). Prints the smoke run (3 questions) and the full run.

- ``run``       (Phase R4) Stage B, **paid**: the shortlisted methods × the question set through the real
                LLM → ``results/retrieval/results.csv`` (+ manifest and ``spend_log.csv``). Prints the
                estimate first and needs ``--max-tokens N``; ``--smoke`` asks only the three smoke
                questions, ``--check-model`` adds the model-drift check (§12). Resumable: run it again
                to pick up pending rows.

Later phases add the Stage B part of ``report`` here.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

import pandas as pd

from src.config import DEFAULT_CONFIG, get_settings
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


def _progress(label: str, n: int) -> None:
    print(f"  {label:<34} on {n} questions …")


def _world(settings, args):
    """Shared state, parents, the question set, its gold targets and the original question ids."""
    from src.retrieval.offline import load_world, targets_for
    from src.retrieval.questions.sets import load_set

    shared, parents, holdings, row_parent = load_world(settings)
    questions = load_set(args.set, settings.data.eval_months)
    targets = targets_for(questions, holdings, row_parent)
    originals = frozenset(q.id for q in load_questions(QUESTIONS_FILE, settings.data.eval_months))
    print(f"corpus: {len(shared.corpus)} children of {shared.dense.month}; set {args.set}: "
          f"{len(questions)} questions, {sum(t.answerable for t in targets.values())} answerable")
    return shared, parents, questions, targets, originals


def _dev_tables(dev, chosen, combo=None) -> None:
    from src.retrieval.offline import MRR_K, rank_variants
    from src.retrieval.settings import METHOD_IDS

    print(f"\n{'method':<16}{'tried':>6}  {'chosen':<34}{'recall@5':>10}{'hit@5':>8}{'mrr@10':>8}{'ms':>8}")
    for name, s in chosen.items():
        tried = len(set(dev[dev["method"] == name]["variant"]))
        opts = ", ".join(f"{k}={v}" for k, v in sorted(s.settings.items())) or "–"
        print(f"{METHOD_IDS[name] + ' ' + name:<16}{tried:>6}  {opts:<34}{s.section_recall_5:>9.1%}"
              f"{s.hit_5:>8.1%}{s.mrr_10:>8.3f}{s.median_ms:>8.0f}")
    if combo is not None:
        cands = rank_variants(dev, list(dict.fromkeys(dev[dev["method"] == "best_combo"]["variant"])))
        print(f"\nM8 best_combo candidates (dev only), by mean section_recall@5 / hit@5 / mrr@{MRR_K}:")
        for c in cands:
            mark = "  <- declared" if c.variant == combo.variant else ""
            opts = ", ".join(f"{k}={v}" for k, v in sorted(c.settings.items()))
            print(f"  {c.rank:>2}. {opts:<40}{c.section_recall_5:>7.1%}{c.hit_5:>8.1%}{c.mrr_10:>8.3f}"
                  f"{c.median_ms:>8.0f} ms{mark}")


def cmd_offline(settings, args) -> int:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from src.retrieval.base import METHOD_NAMES
    from src.retrieval.offline import (OFFLINE_FILE, combo_variants, choose_combo, choose_variants, frame,
                                       grid_variants, load_offline, rank_methods, run_set, shortlist,
                                       write_choices, write_offline)
    from src.retrieval.report import CHART_FILE, write_offline_report
    from src.retrieval.settings import METHOD_IDS

    shared, parents, questions, targets, originals = _world(settings, args)
    top_k = settings.retrieval.top_k
    out_dir = settings.paths.results / "retrieval"
    csv_path = out_dir / OFFLINE_FILE
    rankers = [m for m in METHOD_NAMES if m != "best_combo"]

    if args.set == "dev":
        grid = [(m, ov) for m in rankers for ov in grid_variants(shared.bench, m)]
        print(f"\ndev grid: {len(grid)} method variants × {len(questions)} questions (free, no LLM call)")
        rows = run_set(shared, parents, questions, targets, "dev", grid, top_k, originals, _progress)
        dev = frame(rows)
        chosen = choose_variants(dev, rankers)
        _dev_tables(dev, chosen)

        # The M8 candidates must use the dev choices, so apply them before building the combos.
        for name, s in chosen.items():
            shared.bench.methods[name] = dict(s.settings)
        print(f"\nM8 candidates: {len(combo_variants())} (filter × ranker) × {len(questions)} questions")
        rows += run_set(shared, parents, questions, targets, "dev",
                        [("best_combo", ov) for ov in combo_variants()], top_k, originals, _progress)
        dev = frame(rows)
        combo = choose_combo(dev)
        _dev_tables(dev, chosen, combo)

        write_offline(csv_path, rows, replace_sets={"dev"})
        print(f"\nwrote {csv_path} ({len(rows)} rows)")
        if args.no_write:
            print("config.yaml not touched (--no-write)")
            return 0
        date = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y")
        choices = {name: dict(s.settings) for name, s in chosen.items()}
        choices["best_combo"] = dict(combo.settings)
        note = f"{'filter + ' if combo.settings.get('filter') else 'no filter, '}{combo.settings['ranker']}"
        for line in write_choices(DEFAULT_CONFIG, choices, date, {"best_combo": note}):
            print(f"  config.yaml: {line.strip()}")
        print("\nSTOP 1: check the dev choices and the M8 recipe above (and the config.yaml diff) before "
              "the test run.")
        return 0

    missing = [m for m in METHOD_NAMES if shared.bench.methods.get(m) is None]
    if missing:
        print(f"not declared in config.yaml yet: {missing}. Run `offline --set dev` first (R3.4).")
        return 1
    variants = [(m, None) for m in METHOD_NAMES]
    print(f"\n{args.set} run: {len(variants)} methods × {len(questions)} questions, chosen settings")
    rows = run_set(shared, parents, questions, targets, args.set, variants, top_k, originals, _progress)
    write_offline(csv_path, rows, replace_sets={args.set})
    print(f"\nwrote {csv_path} ({len(rows)} rows for set {args.set})")

    df = load_offline(csv_path)
    ranking = rank_methods(df[df["set"] == args.set])
    picked = shortlist(ranking)
    print(f"\n{'#':>2} {'method':<22}{'recall@5':>10}{'hit@5':>8}{'mrr@10':>8}{'rows@5':>8}{'ctx rows':>9}"
          f"{'ctx tok':>9}{'median ms':>10}  Stage B")
    for s in ranking:
        print(f"{s.rank:>2} {METHOD_IDS[s.method] + ' ' + s.method:<22}{s.section_recall_5:>9.1%}"
              f"{s.hit_5:>8.1%}{s.mrr_10:>8.3f}{s.row_recall_5:>8.1%}{s.context_recall:>9.1%}"
              f"{s.context_tokens:>9,.0f}{s.median_ms:>10,.0f}"
              f"{'  yes' if s.method in set(picked) else ''}")
    print(f"\nshortlist for Stage B (RD6): {', '.join(picked)}")
    summary = write_offline_report(out_dir, args.set)
    print(f"wrote {summary}\nwrote {out_dir / CHART_FILE}")
    print("\nSTOP 2: run `python -m src.retrieval estimate --methods " + " ".join(picked) +
          f" --set {args.set}` and approve the Stage B budget before any paid call.")
    return 0


def cmd_estimate(settings, args) -> int:
    from src.retrieval.estimate import (COMPLETION_TOKENS, PROMPT_OVERHEAD, estimate,
                                        smoke_questions)
    from src.retrieval.offline import load_world
    from src.retrieval.questions.sets import load_set

    shared, parents, _, _ = load_world(settings)
    questions = load_set(args.set, settings.data.eval_months)
    methods = args.methods
    print(f"\nestimate for {len(methods)} method(s) on set {args.set}: {', '.join(methods)}")
    print(f"prompt = retrieved context + {PROMPT_OVERHEAD} overhead tokens; completion "
          f"{COMPLETION_TOKENS} per call; cache hits are free (FR-R9.1, RD11: tokens only)\n")
    smoke = smoke_questions(questions)
    runs = [("smoke", smoke)] if smoke else []
    runs.append((f"full ({len(questions)} questions)", list(questions)))
    for label, qs in runs:
        est = estimate(settings, shared, parents, qs, methods, args.set)
        print(f"{label}: {len(methods)} × {len(qs)} questions"
              + (f" ({', '.join(q.id + ' ' + q.type for q in qs)})" if label == "smoke" else ""))
        print(est.table(), "\n")
    print("No call was made. A paid run needs this estimate, your yes in chat, and `run --max-tokens N` "
          "(§9.2).")
    return 0


def cmd_run(settings, args) -> int:
    """Stage B: paid. Prints the estimate, then asks only what the cap allows (§9.2)."""
    import logging

    from src.eval.runner import ResumeMismatch
    from src.retrieval.estimate import smoke_questions
    from src.retrieval.offline import load_world
    from src.retrieval.questions.sets import load_set
    from src.retrieval.run import SPEND_FILE, estimate, stage_b

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    world = load_world(settings)
    shared, parents = world[0], world[1]
    questions = load_set(args.set, settings.data.eval_months)
    methods = args.methods
    unknown = [m for m in methods if shared.bench.methods.get(m) is None]
    if unknown:
        print(f"not declared in config.yaml: {unknown}", file=sys.stderr)
        return 2
    phase = "smoke" if args.smoke else "full"
    qs = smoke_questions(questions) if args.smoke else list(questions)

    est = estimate(settings, shared, parents, qs, methods, args.set)
    print(f"\n{phase} run, set {args.set}: {len(methods)} × {len(qs)} questions "
          f"({', '.join(methods)}) on {settings.llm.provider} / {settings.llm.model}")
    print(est.table())
    total = est.total_tokens
    if args.check_model:
        from src.retrieval.run import REFERENCE, check_tokens

        extra = check_tokens(settings, shared, parents, qs, args.set)
        total += extra
        print(f"\n--check-model re-asks {REFERENCE} (M1) on these {len(qs)} questions with the cache off "
              f"(§12): about {extra:,} tokens more, {total:,} in all.")
    if args.max_tokens is None:
        print("\nNo call was made: a paid run needs --max-tokens N (FR-R9.2). "
              f"The estimate above says about {total:,} tokens.", file=sys.stderr)
        return 2
    print(f"\ncap: --max-tokens {args.max_tokens:,}; cache reuse "
          f"{'off (--fresh)' if args.fresh else 'on'}\n")

    try:
        out = stage_b(settings, methods=methods, set_name=args.set, phase=phase, questions=qs,
                      max_tokens=args.max_tokens, fresh=args.fresh, check_model=args.check_model,
                      world=world)
    except ResumeMismatch as e:
        print(str(e), file=sys.stderr)
        return 2
    s, led = out.summary, out.ledger
    print(f"\nasked {s.asked}, skipped {s.skipped} already done; {s.total_rows}/{s.expected_rows} rows, "
          f"{len(s.pending)} pending")
    print(f"spent: {led.paid_calls} paid call(s) of {led.calls}, {led.prompt_tokens:,} prompt + "
          f"{led.completion_tokens:,} completion = {led.total_tokens:,} tokens "
          f"(estimate {out.estimate.total_tokens:,})")
    if out.model_check:
        print(f"model check ({out.model_check['model']}): {out.model_check['verdict']}")
    if s.stopped:
        print(f"stopped: {s.stopped}")
    if s.pending:
        print("pending (run again to ask): " + ", ".join(f"{m}:{q}" for m, q in s.pending[:12])
              + (" …" if len(s.pending) > 12 else ""))
    out_dir = settings.paths.results / "retrieval"
    print(f"wrote {out_dir / 'results.csv'}, {out_dir / SPEND_FILE}")
    return 0 if s.complete else 1


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
    o = sub.add_parser("offline", help="Stage A: every method on a question set, no LLM call (R3)")
    o.add_argument("--set", default="dev", choices=("dev", "test", "test_new"),
                   help="dev: grid search, choices and M8; test: one run with the chosen settings")
    o.add_argument("--no-write", action="store_true", help="dev: print the choices, leave config.yaml alone")
    e = sub.add_parser("estimate", help="tokens a Stage B run would need, without any call (FR-R9.1)")
    e.add_argument("--methods", nargs="+", required=True, help="the shortlisted method names")
    e.add_argument("--set", default="test", choices=("dev", "test", "test_new"))
    r = sub.add_parser("run", help="Stage B (paid): shortlisted methods × questions through the LLM (R4)")
    r.add_argument("--methods", nargs="+", required=True, help="the shortlisted method names (RD6)")
    r.add_argument("--set", default="test", choices=("dev", "test", "test_new"))
    r.add_argument("--smoke", action="store_true", help="only the 3 smoke questions (FR-R3.2)")
    r.add_argument("--max-tokens", type=int, help="hard cap on this session's paid tokens (FR-R9.2)")
    r.add_argument("--fresh", action="store_true", help="start a new results.csv and skip the LLM cache")
    r.add_argument("--check-model", action="store_true",
                   help="re-ask M1's prompts uncached and compare with the cached answers (§12)")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    settings = get_settings()
    if args.cmd == "questions":
        return cmd_questions(settings)
    if args.cmd == "demo":
        return cmd_demo(settings, args)
    if args.cmd == "offline":
        return cmd_offline(settings, args)
    if args.cmd == "estimate":
        return cmd_estimate(settings, args)
    if args.cmd == "run":
        return cmd_run(settings, args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
