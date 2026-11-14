"""``results.csv`` → ``results/chunking_report.xlsx``: the best chunking method for this data, and why (Phase 5c).

Sheets:

1. Recommendation   verdict, reasons, caveats, best method per question type, the baseline comparison
2. Ranking          every chunker with rank, accuracy, recall, tokens, refusals, main failure, note
3. Accuracy by type method × question type on the ranking's question set (baseline shown, not ranked)
4. Retrieval & cost retrieval, context size, tokens and latency on the same questions
5. Per question     every row of results.csv in plain words, with a column saying if it is in the ranking
6. Run info         LLM, embedding, run times, data files (from run_manifest.json)

Numbers are written as numbers (percent / thousands formats), so the sheets sort and filter in Excel.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from src.eval.recommend import CHUNKERS, Recommendation, verdict_line
from src.eval.runner import BASELINE

EXCEL_FILE = "chunking_report.xlsx"

HEAD_FILL = PatternFill("solid", fgColor="E8EEF7")
BEST_FILL = PatternFill("solid", fgColor="DCEFD9")
NOTE_FILL = PatternFill("solid", fgColor="FFF4D6")
BOLD = Font(bold=True)
TITLE = Font(bold=True, size=14)
WRAP = Alignment(wrap_text=True, vertical="top")
PCT, INT, NUM = "0%", "#,##0", "#,##0.0"


def _num(x):
    """NaN → empty cell; numpy scalars → plain Python numbers."""
    if x is None or (isinstance(x, float) and math.isnan(x)) or (not isinstance(x, str) and pd.isna(x)):
        return None
    return x.item() if hasattr(x, "item") else x


def _table(ws: Worksheet, row: int, header: list[str], rows: list[list], formats: dict[int, str] | None = None,
           highlight: set[int] | None = None) -> int:
    """Write a header + rows at ``row``; return the next free row. ``highlight`` = body row indexes to fill."""
    for c, h in enumerate(header, 1):
        cell = ws.cell(row=row, column=c, value=h)
        cell.font, cell.fill, cell.alignment = BOLD, HEAD_FILL, WRAP
    for i, r in enumerate(rows):
        for c, v in enumerate(r, 1):
            cell = ws.cell(row=row + 1 + i, column=c, value=_num(v))
            cell.alignment = WRAP
            if formats and c in formats:
                cell.number_format = formats[c]
            if highlight and i in highlight:
                cell.fill = BEST_FILL
    return row + len(rows) + 2


def _widths(ws: Worksheet, widths: list[int]) -> None:
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _gold(text: str, unit: str) -> str:
    try:
        v = json.loads(text)
    except (TypeError, ValueError):
        v = text
    if isinstance(v, list):
        v = "; ".join(map(str, v))
    elif isinstance(v, float):
        v = f"{v:.4g}"
    return f"{v} {unit}".strip() if unit else str(v)


def _given(r: pd.Series) -> str:
    if r["status"] != "ok":
        return f"[{r['status']}] {str(r['error'])[:200]}".strip()
    if r["value"] != "":
        return f"{r['value']} {r['answer_unit']}".strip()
    items = json.loads(r["items"] or "[]")
    return "; ".join(map(str, items)) if items else str(r["answer"])[:300]


def _sheet_recommendation(ws: Worksheet, rec: Recommendation, df: pd.DataFrame, manifest: dict) -> None:
    cfg = manifest.get("config", {})
    months = ", ".join(pd.Timestamp(m).strftime("%d %b %Y") for m in cfg.get("data", {}).get("eval_months", [])) or "–"
    llm = manifest.get("llm", {})
    counts = df.drop_duplicates("qid")["type"].value_counts()
    mix = ", ".join(f"{counts[t]} {t}" for t in dict.fromkeys(df["type"]) if t in counts)

    ws["A1"] = "Best chunking method for this data"
    ws["A1"].font = TITLE
    info = [["Dataset", f"Aditya Birla Sun Life (ABSL) monthly portfolio disclosure, month(s) {months}"],
            ["Questions", f"{df['qid'].nunique()} ({mix}); {len(rec.qids)} used in the ranking"],
            ["LLM", f"{llm.get('provider')} / {llm.get('model')}"],
            ["Retrieval", f"{manifest.get('embedding_model')}, top_k {cfg.get('retrieval', {}).get('top_k')}"],
            ["Rule", "Most correct answers; a tie goes to higher gold-row recall, then to fewer tokens per "
                     "question. The pandas baseline is compared but not ranked (it does no chunking)."],
            ["Status", "Final for this run" if rec.final else
             "Provisional: see the caveats below; re-run the evaluation, then `python -m src.eval report`"]]
    row = 3
    for k, v in info:
        ws.cell(row=row, column=1, value=k).font = BOLD
        ws.cell(row=row, column=2, value=v).alignment = WRAP
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="Best method").font = BOLD
    cell = ws.cell(row=row, column=2, value=" and ".join(rec.best))
    cell.font, cell.fill = Font(bold=True, size=13), BEST_FILL
    ws.cell(row=row + 1, column=2, value=verdict_line(rec)).alignment = WRAP
    row += 3

    ws.cell(row=row, column=1, value="Why").font = BOLD
    for r in rec.reasons:
        ws.cell(row=row, column=2, value="• " + r).alignment = WRAP
        row += 1
    if rec.caveats:
        row += 1
        ws.cell(row=row, column=1, value="Caveats").font = BOLD
        for c in rec.caveats:
            cell = ws.cell(row=row, column=2, value="• " + c)
            cell.alignment, cell.fill = WRAP, NOTE_FILL
            row += 1

    row += 1
    ws.cell(row=row, column=1, value="Best per question type").font = BOLD
    row += 1
    body = [[b.type, b.n, ", ".join(b.best) or "none", b.accuracy if b.best else None, b.runner_up or "–",
             b.runner_up_accuracy, b.decided_by] for b in rec.by_type]
    hdr = ["Question type", "Questions", "Best method", "Accuracy", "Runner-up", "Runner-up accuracy", "Decided by"]
    row = _table(ws, row, hdr, body, {4: PCT, 6: PCT})

    if rec.baseline_note:
        ws.cell(row=row, column=1, value="Pandas baseline").font = BOLD
        ws.cell(row=row, column=2, value=rec.baseline_note).alignment = WRAP
    _widths(ws, [22, 100, 18, 12, 16, 14, 34])
    ws.sheet_view.showGridLines = False


def _sheet_ranking(ws: Worksheet, rec: Recommendation) -> None:
    hdr = ["Rank", "Method", "Correct", "Questions", "Accuracy", "Gold-row recall", "Hit rate",
           "Tokens / question", "Unanswerable: correctly refused", "Answerable: falsely refused",
           "Main failure kind", "Note"]
    body, best = [], set()
    for i, s in enumerate(rec.ranking):
        if s.rank == 1:
            best.add(i)
        body.append([s.rank, s.method, s.correct, s.n, s.accuracy, s.recall, s.hit, s.tokens,
                     f"{s.refusals_ok}/{s.n_unanswerable}" if s.n_unanswerable else "–",
                     f"{s.false_refusals}/{s.n_answerable}", s.main_failure or "none", s.note])
    for m in rec.not_run:
        body.append(["–", m, None, None, None, None, None, None, "", "", "", "not run, so not ranked"])
    b = rec.baseline
    if b is not None:
        body.append(["not ranked", BASELINE, b.correct, b.n, b.accuracy, None, None, b.tokens,
                     f"{b.refusals_ok}/{b.n_unanswerable}" if b.n_unanswerable else "–",
                     f"{b.false_refusals}/{b.n_answerable}", b.main_failure or "none",
                     "no chunking (pandas code); compared only, on the questions it answered"])
    nxt = _table(ws, 1, hdr, body, {5: PCT, 6: PCT, 7: PCT, 8: INT}, highlight=best)
    ws.cell(row=nxt, column=1, value=f"Ranked on the same {len(rec.qids)} questions for every chunker. "
                                      "Gold-row recall and hit rate count answerable questions only.")
    ws.freeze_panes = "C2"
    _widths(ws, [10, 16, 9, 10, 10, 11, 9, 11, 14, 14, 26, 80])


def _sheet_accuracy(ws: Worksheet, rec: Recommendation, used: pd.DataFrame) -> None:
    types = [b.type for b in rec.by_type]
    methods = [s.method for s in rec.ranking] + ([BASELINE] if rec.baseline is not None else [])
    counts = used.drop_duplicates("qid")["type"].value_counts()
    hdr = ["Method", *[f"{t} ({counts[t]})" for t in types], f"overall ({len(rec.qids)})"]
    body = []
    for m in methods:
        sub = used[used["method"] == m]
        if m == BASELINE:
            sub = sub[sub["pending"].fillna(0) == 0]
        body.append([m, *[sub[sub["type"] == t]["correct"].mean() for t in types], sub["correct"].mean()])
    best = {i for i, s in enumerate(rec.ranking) if s.rank == 1}
    nxt = _table(ws, 1, hdr, body, {c: PCT for c in range(2, len(hdr) + 1)}, highlight=best)
    ws.cell(row=nxt, column=1, value="Share of correct answers on the ranking's question set. The baseline row "
                                      "counts only the questions it has answered (pending rows left out).")
    _widths(ws, [16] + [15] * (len(hdr) - 1))


def _sheet_cost(ws: Worksheet, rec: Recommendation, used: pd.DataFrame) -> None:
    hdr = ["Method", "Hit rate", "Gold-row recall", "Chunks", "Holding rows in context", "Context tokens",
           "Prompt tokens", "Completion tokens", "Retrieval ms", "Generation ms", "Total ms"]
    body = []
    for s in rec.ranking:
        sub = used[used["method"] == s.method]
        body.append([s.method, s.hit, s.recall, sub["n_chunks"].mean(), sub["n_context_rows"].mean(),
                     sub["context_tokens"].mean(), sub["prompt_tokens"].mean(), sub["completion_tokens"].mean(),
                     sub["retrieval_ms"].mean(), sub["generation_ms"].mean(), sub["total_ms"].mean()])
    nxt = _table(ws, 1, hdr, body, {2: PCT, 3: PCT, 4: NUM, **{c: INT for c in range(5, 12)}})
    ws.cell(row=nxt, column=1, value="Means per question on the ranking's question set. Context tokens use the "
                                      "embedding tokenizer; prompt tokens are the LLM's count of the whole prompt.")
    _widths(ws, [16, 9, 11, 9, 12, 11, 11, 12, 11, 12, 10])


def _sheet_questions(ws: Worksheet, rec: Recommendation, df: pd.DataFrame) -> None:
    hdr = ["Method", "Question", "Type", "Question text", "Gold answer", "Answer given", "Correct",
           "Wrong because", "Status", "In ranking", "Gold-row recall", "Prompt tokens", "Completion tokens",
           "Total ms"]
    order = {m: i for i, m in enumerate([*CHUNKERS, BASELINE])}
    rows = df.assign(_o=df["method"].map(order).fillna(99)).sort_values(["_o", "qid"])
    body = [[r["method"], r["qid"], r["type"], r["question"], _gold(r["gold_value"], r["unit"]), _given(r),
             "yes" if r["correct"] == 1 else "no",
             "pending (no real answer yet)" if r["pending"] == 1 else r["failure"], r["status"],
             "yes" if r["qid"] in rec.qids and r["method"] != BASELINE else "no",
             r["gold_row_recall"], r["prompt_tokens"], r["completion_tokens"], r["total_ms"]]
            for _, r in rows.iterrows()]
    _table(ws, 1, hdr, body, {11: PCT, 12: INT, 13: INT, 14: INT})
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(hdr))}{len(body) + 1}"
    _widths(ws, [15, 9, 13, 60, 30, 40, 8, 22, 14, 9, 10, 10, 11, 9])


def _sheet_run(ws: Worksheet, manifest: dict, df: pd.DataFrame) -> None:
    sessions = manifest.get("sessions", [])
    rows = [["Started", manifest.get("created_at")],
            ["Sessions", len(sessions)],
            ["Last finished", sessions[-1].get("finished_at") if sessions else None],
            ["Commit", (sessions[-1].get("commit") or "")[:7] if sessions else None],
            ["LLM", f"{manifest.get('llm', {}).get('provider')} / {manifest.get('llm', {}).get('model')}"],
            ["Temperature", manifest.get("config", {}).get("llm", {}).get("temperature")],
            ["Embedding model", manifest.get("embedding_model")],
            ["Methods in this run", ", ".join(manifest.get("methods", sorted(set(df["method"]))))],
            ["Rows", f"{manifest.get('rows', len(df))} of {manifest.get('expected_rows', '–')} expected"],
            ["Pending rows", int(df["pending"].fillna(0).sum())],
            ["Run complete", "yes" if manifest.get("complete") else "no"]]
    rows += [[f"Data file: {k}", f"sha256 {v[:16]}…"] for k, v in manifest.get("data_files", {}).items()]
    _table(ws, 1, ["Field", "Value"], rows)
    _widths(ws, [50, 70])


def write_excel(df: pd.DataFrame, manifest: dict, rec: Recommendation, path: Path) -> Path:
    used = df[df["qid"].isin(rec.qids)]
    wb = Workbook()
    _sheet_recommendation(wb.active, rec, df, manifest)
    wb.active.title = "Recommendation"
    _sheet_ranking(wb.create_sheet("Ranking"), rec)
    _sheet_accuracy(wb.create_sheet("Accuracy by type"), rec, used)
    _sheet_cost(wb.create_sheet("Retrieval & cost"), rec, used)
    _sheet_questions(wb.create_sheet("Per question"), rec, df)
    _sheet_run(wb.create_sheet("Run info"), manifest, df)
    wb.save(path)
    return path

