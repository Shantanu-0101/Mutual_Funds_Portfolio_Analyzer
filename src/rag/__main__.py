"""``python -m src.rag "question" [--chunker all|name] [--fresh] [--scheme CODE] [--month DATE]``

Answers one question through one or every chunker and prints, per chunker,
the answer, the retrieved chunk ids with scores, tokens and latencies. The
same output is written to ``results/rag_sample.md`` (or ``--out``).
Chunkers run one after another; responses are cached (``--fresh`` re-asks).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.chunking import REGISTRY
from src.config import get_settings
from src.llm import LLM
from src.rag.pipeline import RagPipeline, RagResult

IST = timezone(timedelta(hours=5, minutes=30))


def describe(r: RagResult) -> list[str]:
    lines = [f"## {r.chunker}", "", f"- status: **{r.status}**" + (f" ({r.error})" if r.error else "")]
    if r.answer:
        a = r.answer
        lines.append(f"- answer: {a['answer']}")
        lines.append(f"- value: {a['value']} {a['unit'] or ''} | insufficient_context: {a['insufficient_context']}")
        if a["items"]:
            lines.append(f"- items: {a['items']}")
        lines.append(f"- cited rows: {[k[2] for k in r.cited_rows]}"
                     + (f"; unmatched sources: {r.unmatched_sources}" if r.unmatched_sources else ""))
    elif r.raw_text:
        lines.append(f"- raw reply: `{r.raw_text[:300]}`")
    lines.append(f"- tokens: prompt {r.prompt_tokens:,}, completion {r.completion_tokens:,}"
                 + (f" (reasoning {r.reasoning_tokens:,})" if r.reasoning_tokens else "")
                 + (" [cached]" if r.cached else ""))
    lines.append(f"- latency: retrieval {r.retrieval_ms:,.0f} ms, generation {r.generation_ms:,.0f} ms")
    lines.append(f"- context: {len(r.retrieval.chunks)} chunks, {len(r.context_rows)} holding rows")
    lines.append("- retrieved:")
    for x in r.retrieval.chunks:
        via = f" via {len(x.children)} children" if x.children else ""
        lines.append(f"  {x.rank}. `{x.chunk.id}` score {x.score:.3f}, {x.chunk.n_tokens:,} tokens{via}")
    return lines + [""]


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    s = get_settings()
    ap = argparse.ArgumentParser(prog="python -m src.rag", description=__doc__.split("\n\n")[0])
    ap.add_argument("question")
    ap.add_argument("--chunker", default="all", help=f"'all' or one of {list(REGISTRY)}")
    ap.add_argument("--fresh", action="store_true", help="ignore cached LLM responses")
    ap.add_argument("--scheme", help="filter by scheme code (FR-3.4)")
    ap.add_argument("--month", help="filter by as-on date (FR-3.4)")
    ap.add_argument("--out", default=str(s.paths.results / "rag_sample.md"))
    args = ap.parse_args(argv)
    names = list(REGISTRY) if args.chunker == "all" else [args.chunker]

    pipe = RagPipeline(s, llm=LLM.from_settings(s, fresh=args.fresh))
    out = ["# RAG sample (Phase 3)", "", "| | |", "|---|---|",
           f"| Generated | {datetime.now(IST):%d %b %Y %H:%M} IST by `python -m src.rag` |",
           f"| Question | {args.question} |",
           f"| LLM | {s.llm.provider} / {pipe.llm.model}, temperature {s.llm.temperature}, "
           f"reasoning {s.llm.reasoning_effort} |",
           f"| Retrieval | top_k {s.retrieval.top_k}, filter: "
           f"{', '.join(x for x in (args.scheme, args.month) if x) or 'none'} |", ""]
    for name in names:
        r = pipe.answer(args.question, name, scheme_code=args.scheme, as_of_date=args.month)
        block = describe(r)
        print("\n".join(block))
        out += block
    Path(args.out).write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
