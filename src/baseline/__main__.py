"""``python -m src.baseline "question" [--fresh] [--gold EXPR] [--show-schema]``

Asks the LLM for pandas code, checks it, runs it in the sandbox and prints the
code, the raw result, the answer object, tokens and latencies. The same output
goes to ``results/baseline_sample.md`` (or ``--out``).

``--gold EXPR`` evaluates a hand-written pandas expression over the same
``df`` in this process (trusted: you typed it) and prints it next to the
model's answer, for a quick check until Phase 5 brings the gold functions.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from src.baseline.pipeline import BaselinePipeline, BaselineResult
from src.config import get_settings
from src.llm import LLM

IST = timezone(timedelta(hours=5, minutes=30))


def describe(r: BaselineResult) -> list[str]:
    lines = [f"- status: **{r.status}**" + (f" ({r.error})" if r.error else "")]
    if r.fallback_reason:
        lines.append(f"- answered by fallback {r.provider} / {r.model} because {r.fallback_reason}")
    if r.code:
        lines += ["- code:", "", "```python", r.code, "```", ""]
    elif r.raw_text:
        lines.append(f"- raw reply: `{r.raw_text[:300]}`")
    if r.result is not None:
        lines.append(f"- raw result: `{json.dumps(r.result)[:500]}`")
    if r.answer:
        a = r.answer
        lines.append(f"- answer: {a['answer']}")
        lines.append(f"- value: {a['value']} {a['unit'] or ''} | insufficient_context: {a['insufficient_context']}")
        if a["items"]:
            lines.append(f"- items ({len(a['items'])}): {a['items'][:15]}")
        if r.cited_rows:
            lines.append(f"- cited rows: {[k[2] for k in r.cited_rows][:30]}")
    lines.append(f"- tokens: prompt {r.prompt_tokens:,}, completion {r.completion_tokens:,}"
                 + (f" (reasoning {r.reasoning_tokens:,})" if r.reasoning_tokens else "")
                 + (" [cached]" if r.cached else ""))
    lines.append(f"- latency: generation {r.generation_ms:,.0f} ms, execution {r.execution_ms:,.0f} ms")
    return lines


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    s = get_settings()
    ap = argparse.ArgumentParser(prog="python -m src.baseline", description=__doc__.split("\n\n")[0])
    ap.add_argument("question")
    ap.add_argument("--fresh", action="store_true", help="ignore cached LLM responses")
    ap.add_argument("--gold", help="trusted pandas expression over df, printed for comparison")
    ap.add_argument("--show-schema", action="store_true", help="also print the schema text the LLM gets")
    ap.add_argument("--out", default=str(s.paths.results / "baseline_sample.md"))
    args = ap.parse_args(argv)

    pipe = BaselinePipeline(s, llm=LLM.from_settings(s, fresh=args.fresh))
    r = pipe.answer(args.question)
    out = ["# Text-to-pandas baseline sample (Phase 4)", "", "| | |", "|---|---|",
           f"| Generated | {datetime.now(IST):%d %b %Y %H:%M} IST by `python -m src.baseline` |",
           f"| Question | {args.question} |",
           f"| LLM | {s.llm.provider} / {pipe.llm.model}, temperature {s.llm.temperature}, "
           f"reasoning {s.llm.reasoning_effort}, fallback {pipe.llm.fallback_name or 'none'} |",
           f"| Data | `df` = holdings for {', '.join(pipe.months)}: {len(pipe.frame):,} rows; "
           f"sandbox timeout {s.baseline.timeout_s} s |", "", "## Model", ""]
    out += describe(r)
    if args.gold:
        gold = eval(args.gold, {"__builtins__": {}}, {"df": pipe.frame, "pd": pd})  # noqa: S307 (typed by the user)
        model_value = r.answer["value"] if r.answer else None
        out += ["", "## Check", "", f"- gold expression: `{args.gold}`", f"- gold value: {gold}",
                f"- model value: {model_value}"]
        if isinstance(model_value, (int, float)) and isinstance(gold, (int, float)) and gold:
            rel = abs(model_value - gold) / abs(gold)
            out.append(f"- relative difference: {rel:.4%} ({'within' if rel <= s.eval.rel_tolerance else 'OUTSIDE'} "
                       f"the {s.eval.rel_tolerance:.0%} tolerance)")
    if args.show_schema:
        out += ["", "## Schema given to the LLM", "", "```text", pipe.schema, "```"]
    text = "\n".join(out) + "\n"
    print(text)
    Path(args.out).write_text(text, encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
