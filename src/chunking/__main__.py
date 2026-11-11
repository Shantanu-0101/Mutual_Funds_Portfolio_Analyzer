"""``python -m src.chunking [--month YYYY-MM-DD] [--chunkers all|a,b]``: chunk stats (task 2.3).

Runs every chunker on one month of ``data/processed/holdings.parquet`` and
writes ``results/chunk_stats.md`` and ``results/chunk_samples.md``. Nothing is
embedded or stored here; Phase 3 (``python -m src.index``) does that.

Exit code 1 if any chunker leaves a holding uncovered (FR-2.0).
"""

from __future__ import annotations

import argparse
import sys
import time

import pandas as pd

from src.chunking import REGISTRY, build_chunker
from src.chunking.base import get_tokenizer, row_key
from src.chunking.report import ChunkerRun, build_samples_report, build_stats_report, compute_stats, stats_line
from src.config import get_settings
from src.parsing.pipeline import HOLDINGS_FILE

SAMPLE_SCHEMES = ["BSLEQTY", "BSLCBF"]  # Flexi Cap (equity, the spec's running example), Credit Risk (debt)


def parse_args(argv: list[str] | None, default_month: str) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m src.chunking", description=__doc__.split("\n\n")[0])
    ap.add_argument("--month", default=default_month, help=f"as-on date, default {default_month} (config eval_months)")
    ap.add_argument("--chunkers", default="all", help=f"'all' or comma list of {list(REGISTRY)}")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    s = get_settings()
    args = parse_args(argv, s.data.eval_months[0])
    names = list(REGISTRY) if args.chunkers == "all" else [n.strip() for n in args.chunkers.split(",")]

    holdings_path = s.paths.processed / HOLDINGS_FILE
    if not holdings_path.is_file():
        print(f"{holdings_path} not found: run `python -m src.parsing` first")
        return 1
    holdings = pd.read_parquet(holdings_path)
    month = holdings[holdings["as_of_date"].astype(str) == args.month]
    if month.empty:
        print(f"No holdings for {args.month}; months present: {sorted(holdings['as_of_date'].astype(str).unique())}")
        return 1
    sheets = [g for _, g in month.groupby(["source_file", "scheme_code"], sort=True)]
    all_rows = {row_key(r) for r in month.itertuples(index=False)}
    print(f"{args.month}: {len(sheets)} schemes, {len(all_rows):,} holdings")

    tokenizer = get_tokenizer(s.embedding.model)
    runs = []
    for name in names:
        chunker = build_chunker(name, s, tokenizer)
        run = ChunkerRun(name)
        t0 = time.perf_counter()
        for sheet in sheets:
            out = chunker.build(sheet)
            run.chunks += out.chunks
            run.parents += out.parents
        run.seconds = time.perf_counter() - t0
        ids = [c.id for c in run.chunks + run.parents]
        assert len(ids) == len(set(ids)), f"{name}: duplicate chunk ids"
        runs.append(run)
        print(stats_line(run, compute_stats(run.chunks, all_rows)))

    s.paths.results.mkdir(parents=True, exist_ok=True)
    stats_path = s.paths.results / "chunk_stats.md"
    samples_path = s.paths.results / "chunk_samples.md"
    stats_path.write_text(build_stats_report(runs, args.month, len(sheets), all_rows, tokenizer.name,
                                             s.embedding.max_tokens, s.chunking) + "\n", encoding="utf-8")
    samples_path.write_text(build_samples_report(runs, args.month, SAMPLE_SCHEMES) + "\n", encoding="utf-8")
    print(f"  wrote {stats_path}\n  wrote {samples_path}")

    missing = {r.name: compute_stats(r.chunks, all_rows).rows_missing for r in runs}
    bad = {k: v for k, v in missing.items() if v}
    if bad:
        print(f"Holdings not covered by any chunk (FR-2.0): {bad}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
