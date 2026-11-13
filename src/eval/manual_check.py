"""Gold answers in a form a person can check against the raw Excel (task 5.3, FR-5.4).

``results/gold_answers.md``: every question with its gold answer.
``results/manual_check.md``: ``eval.manual_check_n`` answerable questions picked
with ``random.Random(eval.seed)``, each with the rows it was computed from and
the raw cell to look at, e.g. ``30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!H8``.

Columns in every portfolio sheet (DATA_NOTES §2): C instrument, D ISIN,
E industry / rating, F quantity, G market value (Rs lakhs), H % to AUM.
Unanswerable questions are left out of the sample: there is nothing to check.
"""

from __future__ import annotations

import random
from typing import Any

import pandas as pd

from src.eval.gold import GoldAnswer, compute
from src.eval.questions import Question

COL = {"instrument": "C", "isin": "D", "rating": "E", "value": "G", "pct": "H"}

# Which cell holds the number each gold function reads.
CHECK_COLUMN = {
    "holding_pct": "pct", "industry_total": "pct", "top_n_share": "pct", "section_total": "pct",
    "rating_share": "pct", "holding_value": "value", "holding_count": "instrument",
    "instruments_by_rating": "rating", "overlap_count": "isin",
}

HOW = {
    "holding_pct": "% to AUM of that holding (column H).",
    "holding_value": "Market value of that holding in Rs lakhs (column G).",
    "industry_total": "Sum of column H over the equity rows whose Industry (column E) is the one asked.",
    "top_n_share": "Sum of column H over the n largest equity rows by % to AUM.",
    "holding_count": "Number of holding rows in the section (Total / heading rows are not counted).",
    "section_total": "Sum of column H over the rows of that section / sub-section.",
    "rating_share": "Sum of column H over non-equity rows whose rating (column E) matches; "
                    "[ICRA]AAA counts as ICRA AAA, AAA(SO) does not count as AAA.",
    "instruments_by_rating": "Instrument names (column C) of the non-equity rows whose rating (column E) matches.",
    "overlap_count": "Number of ISINs (column D) that appear in the equity sections of both schemes.",
    "which_holds_more": "Compare column H (% to AUM) or column G (value) of the holding in each scheme.",
}


def fmt_answer(q: Question, value: Any) -> str:
    if q.answer_kind == "not_in_data":
        return "not in the data"
    if q.answer_kind == "list":
        return f"{len(value)} item(s): " + "; ".join(value)
    if q.answer_kind == "choice":
        return f"{value} ({q.options[value][0]})"
    if q.unit == "pct":
        return f"{value:.4f} %"
    if q.unit == "lakhs":
        return f"{value:,.2f} Rs lakhs"
    return str(value)


def _cell(file: str, sheet: str, col: str, row: int) -> str:
    return f"`{file} › '{sheet}'!{col}{row}`"


def _row_table(q: Question, gold: GoldAnswer, h: pd.DataFrame) -> list[str]:
    idx = h.set_index(["source_file", "source_sheet", "source_row"])
    col = COL.get(CHECK_COLUMN.get(q.gold_fn, "pct"), "H")
    if q.gold_fn == "which_holds_more":
        col = COL["value"] if q.params.get("measure") == "lakhs" else COL["pct"]
    out = ["| # | Cell to check | Scheme | Instrument | ISIN | Industry / Rating | Value (Rs L) | % to AUM |",
           "|---|---|---|---|---|---|---|---|"]
    def isin_of(k):
        v = idx.loc[k, "isin"]
        return v if isinstance(v, str) else ""

    # overlap: the two rows of each shared holding next to each other
    rows = sorted(gold.rows, key=lambda k: (isin_of(k), k)) if q.gold_fn == "overlap_count" else gold.rows
    for n, key in enumerate(rows, 1):
        r = idx.loc[key]  # a Series: use r["isin"], since r.isin is the pandas method

        def text(c):
            return r[c] if isinstance(r[c], str) and r[c] else "-"

        pct = "-" if pd.isna(r["pct_nav"]) else f"{r['pct_nav']:.4f}"
        if r["pct_nav_flag"] == "lt_0.01":
            pct += " (file shows $0.00%; computed)"
        value = "-" if pd.isna(r["market_value_lakhs"]) else f"{r['market_value_lakhs']:,.2f}"
        out.append(f"| {n} | {_cell(key[0], key[1], col, key[2])} | {r['scheme_code']} | {text('instrument')} | "
                   f"{text('isin')} | {text('industry_or_rating')} | {value} | {pct} |")
    return out


def pick(questions: list[Question], n: int, seed: int) -> list[Question]:
    answerable = sorted((q for q in questions if q.answerable), key=lambda q: q.id)
    chosen = random.Random(seed).sample(answerable, min(n, len(answerable)))
    return sorted(chosen, key=lambda q: q.id)


def gold_answers_md(questions: list[Question], h: pd.DataFrame) -> str:
    lines = ["# Gold answers", "",
             "Computed by `src/eval/gold.py` from `holdings.parquet` (no LLM). "
             "Regenerate with `python -m src.eval gold`.", "",
             "| Id | Type | Question | Gold answer | Rows used |", "|---|---|---|---|---|"]
    for q in questions:
        g = compute(h, q.gold_fn, q.params)
        lines.append(f"| {q.id} | {q.type} | {q.text} | {fmt_answer(q, g.value)} | {len(g.rows)} |")
    return "\n".join(lines) + "\n"


def manual_check_md(questions: list[Question], h: pd.DataFrame, n: int, seed: int) -> str:
    chosen = pick(questions, n, seed)
    lines = [
        "# Manual check of gold answers (FR-5.4)", "",
        f"{len(chosen)} of the {sum(q.answerable for q in questions)} answerable questions, picked with "
        f"`random.Random({seed})`. Unanswerable questions are left out (nothing to check).", "",
        "**How to check:** open the file named in each cell reference, go to the sheet (tab) and the cell, "
        "and compare with the table. Then check the gold answer is what the question asks for. "
        "Tick the box, or write what is wrong next to it.", "",
        "Columns in every sheet: C instrument, D ISIN, E industry / rating, F quantity, "
        "G market value (Rs lakhs), H % to AUM. The file stores % as a fraction (0.0560 = 5.60 %); "
        "the tables show percent.", "",
        "| Id | Type | Gold answer | OK? |", "|---|---|---|---|",
    ]
    golds = {q.id: compute(h, q.gold_fn, q.params) for q in chosen}
    lines += [f"| {q.id} | {q.type} | {fmt_answer(q, golds[q.id].value)} | [ ] |" for q in chosen]
    for q in chosen:
        g = golds[q.id]
        lines += ["", f"## {q.id} · {q.type}", "", f"**Question:** {q.text}", "",
                  f"**Gold answer:** {fmt_answer(q, g.value)}", "",
                  f"**How it is computed** (`{q.gold_fn}`): {HOW.get(q.gold_fn, '')} "
                  f"{len(g.rows)} row(s).", ""]
        lines += _row_table(q, g, h)
        lines += ["", "- [ ] checked against the Excel"]
    return "\n".join(lines) + "\n"
