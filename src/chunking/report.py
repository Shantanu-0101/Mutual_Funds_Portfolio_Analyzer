"""Chunk statistics and samples (task 2.3, FR-2.1).

Why: before anything is embedded, we want to see what each chunker produced:
how many chunks, how big, how many the embedding model will truncate, and
whether every holding landed in at least one chunk. The samples file shows
real chunk text, so the formats can be checked by eye.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from src.chunking.base import Chunk, RowKey

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class ChunkerRun:
    """All chunks one chunker produced for one month."""

    name: str
    chunks: list[Chunk] = field(default_factory=list)
    parents: list[Chunk] = field(default_factory=list)
    seconds: float = 0.0


@dataclass
class Stats:
    chunks: int
    avg_tokens: float
    median_tokens: float
    max_tokens: int
    truncated: int
    total_tokens: int
    avg_rows: float
    rows_covered: int
    rows_missing: int
    rows_in_several: int  # holdings claimed by more than one chunk (fixed_size overlap, cut rows)
    largest: list[Chunk]


def compute_stats(chunks: list[Chunk], all_rows: set[RowKey]) -> Stats:
    tokens = [c.n_tokens for c in chunks] or [0]
    claims = Counter(k for c in chunks for k in c.source_rows)
    covered = set(claims) & all_rows
    return Stats(
        chunks=len(chunks), avg_tokens=statistics.fmean(tokens), median_tokens=statistics.median(tokens),
        max_tokens=max(tokens), truncated=sum(c.truncated for c in chunks), total_tokens=sum(tokens),
        avg_rows=statistics.fmean([len(c.source_rows) for c in chunks]) if chunks else 0.0,
        rows_covered=len(covered), rows_missing=len(all_rows - covered),
        rows_in_several=sum(1 for n in claims.values() if n > 1),
        largest=sorted(chunks, key=lambda c: -c.n_tokens)[:3],
    )


def stats_line(run: ChunkerRun, st: Stats) -> str:
    """One line for the console log (FR-2.1)."""
    return (f"{run.name:14} {st.chunks:6,} chunks  avg {st.avg_tokens:7.1f}  max {st.max_tokens:6,} tokens  "
            f"{st.truncated:5,} truncated  {st.rows_missing} rows uncovered  {run.seconds:5.1f} s")


def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "–"


def build_stats_report(runs: list[ChunkerRun], month: str, n_schemes: int, all_rows: set[RowKey],
                       tokenizer: str, max_tokens: int, options: dict, generated_at: datetime | None = None) -> str:
    generated_at = generated_at or datetime.now(IST)
    lines: list[str] = []
    add = lines.append
    add("# Chunk stats (Phase 2)")
    add("")
    add("| | |")
    add("|---|---|")
    add(f"| Generated | {generated_at:%d %b %Y %H:%M} IST by `python -m src.chunking --month {month}` |")
    add(f"| Month | {month} |")
    add(f"| Schemes | {n_schemes} |")
    add(f"| Holdings | {len(all_rows):,} |")
    add(f"| Tokenizer | `{tokenizer}` (tokens = word pieces + 2 special tokens, what the embedding model sees) |")
    add(f"| Truncated means | more than {max_tokens} tokens: the embedding only sees the start of the chunk |")
    add("")
    add("## 1. Per chunker")
    add("")
    add("| Chunker | Options | Chunks | Avg tokens | Median | Max | Truncated | Total tokens | "
        "Avg rows / chunk | Holdings covered | Holdings in >1 chunk |")
    add("|---|---|---|---|---|---|---|---|---|---|---|")
    stats = {}
    for run in runs:
        st = compute_stats(run.chunks, all_rows)
        stats[run.name] = st
        opts = ", ".join(f"{k}={v}" for k, v in options.get(run.name, {}).items()) or "–"
        cov = f"{st.rows_covered:,}" + ("" if not st.rows_missing else f" (**{st.rows_missing} missing**)")
        add(f"| {run.name} | {opts} | {st.chunks:,} | {st.avg_tokens:,.1f} | {st.median_tokens:,.0f} | "
            f"{st.max_tokens:,} | {st.truncated:,} ({_pct(st.truncated, st.chunks)}) | {st.total_tokens:,} | "
            f"{st.avg_rows:,.1f} | {cov} | {st.rows_in_several:,} |")
    add("")
    for run in runs:
        if run.parents:
            p = compute_stats(run.parents, all_rows)
            add(f"`{run.name}` parents (sent to the LLM, never embedded): {p.chunks:,} parents, "
                f"avg {p.avg_tokens:,.1f} tokens, max {p.max_tokens:,}, {p.avg_rows:,.1f} rows each, "
                f"{p.rows_covered:,} holdings covered.")
            add("")
    add("Truncation only affects the embedding (retrieval). The full chunk text is stored and sent to the LLM.")
    add("")
    add("## 2. Largest chunks per chunker")
    add("")
    add("| Chunker | Chunk id | Scheme | Tokens | Rows |")
    add("|---|---|---|---|---|")
    for run in runs:
        for c in stats[run.name].largest:
            add(f"| {run.name} | `{c.id}` | {c.scheme} | {c.n_tokens:,} | {len(c.source_rows)} |")
    add("")
    return "\n".join(lines)


def _clip(text: str, max_lines: int) -> str:
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[:max_lines] + [f"... ({len(lines) - max_lines} more lines)"])


def _chunk_block(c: Chunk, max_lines: int, label: str = "") -> list[str]:
    head = f"**`{c.id}`**{label}: {c.n_tokens:,} tokens, {len(c.source_rows)} holding rows"
    head += ", truncated" if c.truncated else ""
    head += f", parent `{c.parent_id}`" if c.parent_id else ""
    rows = c.source_rows
    if rows:
        head += f", rows {rows[0][2]}–{rows[-1][2]} of sheet `{rows[0][1]}`"
    return [head, "", "```text", _clip(c.text, max_lines), "```", ""]


def build_samples_report(runs: list[ChunkerRun], month: str, sample_schemes: list[str],
                         per_chunker: int = 2, max_lines: int = 20) -> str:
    lines = ["# Chunk samples (Phase 2)", "",
             f"Month {month}. For each chunker, the first {per_chunker} chunks of each sample scheme "
             f"({', '.join(f'`{s}`' for s in sample_schemes)}). Long chunks are cut after {max_lines} lines "
             "here only; the real chunk keeps all of its text.", ""]
    for run in runs:
        lines += [f"## {run.name}", ""]
        for code in sample_schemes:
            mine = [c for c in run.chunks if c.scheme_code == code]
            if not mine:
                lines += [f"_No chunks for `{code}`._", ""]
                continue
            lines += [f"### {code}: {mine[0].scheme} ({len(mine)} chunks)", ""]
            for c in mine[:per_chunker]:
                lines += _chunk_block(c, max_lines)
            if run.parents and mine[0].parent_id:
                parent = next(p for p in run.parents if p.id == mine[0].parent_id)
                lines += _chunk_block(parent, max_lines, label=" (parent of the first child)")
    return "\n".join(lines)
