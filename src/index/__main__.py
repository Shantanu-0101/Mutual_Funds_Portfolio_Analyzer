"""``python -m src.index [--month YYYY-MM-DD] [--chunkers all|a,b]``: build the Chroma collections (task 3.6).

For each chunker: chunk every scheme of the month, embed (from the disk cache
where possible), and replace that month in the chunker's collection.
Hierarchical parents go to ``data/processed/parents_hierarchical.parquet``.
"""

from __future__ import annotations

import argparse
import sys
import time

import pandas as pd

from src.chunking import REGISTRY, build_chunker
from src.chunking.base import get_tokenizer
from src.config import get_settings
from src.index.embedder import Embedder
from src.index.store import PARENTS_FILE, get_collection, open_client, write_month, write_parents
from src.parsing.pipeline import HOLDINGS_FILE


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    s = get_settings()
    ap = argparse.ArgumentParser(prog="python -m src.index", description=__doc__.split("\n\n")[0])
    ap.add_argument("--month", default=s.data.eval_months[0])
    ap.add_argument("--chunkers", default="all", help=f"'all' or comma list of {list(REGISTRY)}")
    args = ap.parse_args(argv)
    names = list(REGISTRY) if args.chunkers == "all" else [n.strip() for n in args.chunkers.split(",")]

    holdings = pd.read_parquet(s.paths.processed / HOLDINGS_FILE)
    month = holdings[holdings["as_of_date"].astype(str) == args.month]
    if month.empty:
        print(f"No holdings for {args.month}")
        return 1
    sheets = [g for _, g in month.groupby(["source_file", "scheme_code"], sort=True)]
    print(f"{args.month}: {len(sheets)} schemes, {len(month):,} holdings; embedding model {s.embedding.model}")

    tokenizer = get_tokenizer(s.embedding.model)
    embedder = Embedder.from_settings(s)
    client = open_client(s.paths.chroma)
    t_all = time.perf_counter()
    for name in names:
        t0 = time.perf_counter()
        chunker = build_chunker(name, s, tokenizer)
        chunks, parents = [], []
        for sheet in sheets:
            out = chunker.build(sheet)
            chunks += out.chunks
            parents += out.parents
        hits, misses = embedder.hits, embedder.misses
        vectors = embedder.embed_documents([c.text for c in chunks])
        col = get_collection(client, name, s.embedding.model, create=True)
        stored = write_month(col, args.month, chunks, vectors)
        if parents:
            write_parents(s.paths.processed / PARENTS_FILE, args.month, parents)
        print(f"{name:14} {stored:6,} chunks stored ({embedder.misses - misses:,} embedded, "
              f"{embedder.hits - hits:,} from cache)  collection total {col.count():,}"
              + (f"  + {len(parents):,} parents" if parents else "") + f"  {time.perf_counter() - t0:6.1f} s")
    print(f"done in {time.perf_counter() - t_all:.1f} s; chroma at {s.paths.chroma}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
