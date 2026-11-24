"""``results/retrieval/results.csv`` → ``retrieval_report.xlsx``: the best retrieval method, and why (R5.3).

Same style as ``results/chunking_report.xlsx`` (``src/eval/excel_report.py``): the same fills, number
formats, one verdict sheet first and the raw rows last, so the two reports read as one pair. The
difference, RD8: the bootstrap "not distinguishable" sentence stays in ``summary.md`` and does **not**
go into the Excel, because the hand-edited chunking Excel dropped its tie caveat.

Sheets:

1. Verdict           the winner, why, caveats, best method per question type
2. Ranking           every shortlisted method with rank, accuracy, recall, tokens, latency, note
3. Accuracy by type  method × question type
4. Retrieval & cost  context after the parent swap, tokens and latency
5. Offline (Stage A) the free comparison of all eight methods on the same questions, for context
6. Per question      every row of results.csv in plain words
7. Run info          LLM, embedding, reranker, cap, spend log (tokens only, RD11)

Numbers are written as numbers (percent / thousands formats), so the sheets sort and filter in Excel.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from src.config import llm_label
from src.eval.excel_report import (BEST_FILL, BOLD, INT, NOTE_FILL, NUM, PCT, TITLE, WRAP, _gold, _given,
                                   _table, _widths)
from src.retrieval.settings import METHOD_IDS
from src.retrieval.verdict import Verdict, verdict_line

EXCEL_FILE = "retrieval_report.xlsx"


def _name(method: str) -> str:
    return f"{METHOD_IDS.get(method, '')} {method}".strip()


def _opts(settings: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(settings.items())) or "–"


def _sheet_verdict(ws: Worksheet, v: Verdict, df: pd.DataFrame, manifest: dict) -> None:
    cfg = manifest.get("config", {})
    months = ", ".join(pd.Timestamp(m).strftime("%d %b %Y")
                       for m in cfg.get("data", {}).get("eval_months", [])) or "–"
    llm = manifest.get("llm", {})
    counts = df.drop_duplicates("qid")["type"].value_counts()
    mix = ", ".join(f"{counts[t]} {t}" for t in dict.fromkeys(df["type"]) if t in counts)
    originals = sum(1 for q in df["qid"].unique() if q.startswith("Q"))

    ws["A1"] = "Best retrieval method for Aditya Birla Sun Life (ABSL) monthly portfolio disclosure data"
    ws["A1"].font = TITLE
    info = [["Dataset", f"Aditya Birla Sun Life (ABSL) monthly portfolio disclosure, month(s) {months}"],
            ["Questions", f"{df['qid'].nunique()} test questions ({mix}); {originals} hand-written, the "
                          f"rest generated from the data; {len(v.qids)} used in the ranking"],
            ["Chunking", "hierarchical (the winner of the chunking benchmark); only retrieval changes "
                         "between the methods compared here"],
            ["LLM", llm_label(llm.get("provider"), llm.get("model"))],
            ["Retrieval", f"{manifest.get('embedding_model')}, candidate_k "
                          f"{manifest.get('candidate_k')}, top_k {manifest.get('top_k')}"],
            ["Rule", "Most correct answers on the test set; a tie goes to higher context gold-row recall, "
                     "then to fewer prompt tokens per question, then to lower retrieval latency. Fixed "
                     "before the paid run (spec §6.5) and applied by code."],
            ["Status", "Final for this run" if v.final else
                       "Provisional: see the caveats below, then run Stage B again and "
                       "`python -m src.retrieval report`"]]
    row = 3
    for k, val in info:
        ws.cell(row=row, column=1, value=k).font = BOLD
        ws.cell(row=row, column=2, value=val).alignment = WRAP
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="Best method").font = BOLD
    cell = ws.cell(row=row, column=2, value=" and ".join(_name(m) for m in v.best))
    cell.font, cell.fill = Font(bold=True, size=13), BEST_FILL
    ws.cell(row=row + 1, column=2, value=verdict_line(v)).alignment = WRAP
    row += 3

    ws.cell(row=row, column=1, value="Why").font = BOLD
    for r in v.reasons:
        ws.cell(row=row, column=2, value="• " + r).alignment = WRAP
        row += 1
    caveats = v.excel_caveats                   # RD8: the bootstrap sentence stays in summary.md
    if caveats:
        row += 1
        ws.cell(row=row, column=1, value="Caveats").font = BOLD
        for c in caveats:
            cell = ws.cell(row=row, column=2, value="• " + c)
            cell.alignment, cell.fill = WRAP, NOTE_FILL
            row += 1

    row += 1
    ws.cell(row=row, column=1, value="Best per question type").font = BOLD
    row += 1
    body = [[b.type, b.n, ", ".join(b.best) or "none", b.accuracy if b.best else None, b.runner_up or "–",
             b.runner_up_accuracy, b.decided_by] for b in v.by_type]
    hdr = ["Question type", "Questions", "Best method", "Accuracy", "Runner-up", "Runner-up accuracy",
           "Decided by"]
    _table(ws, row, hdr, body, {4: PCT, 6: PCT})
    _widths(ws, [22, 100, 18, 12, 18, 16, 40])
    ws.sheet_view.showGridLines = False


def _sheet_ranking(ws: Worksheet, v: Verdict) -> None:
    hdr = ["Rank", "Method", "Settings", "Correct", "Questions", "Accuracy", "Context gold-row recall",
           "Hit rate", "Prompt tokens / question", "Completion tokens / question",
           "Retrieval ms (median)", "Total ms / question", "Cached answers",
           "Unanswerable: correctly refused", "Answerable: falsely refused", "Main failure kind", "Note"]
    body, best = [], set()
    for i, s in enumerate(v.ranking):
        if s.rank == 1:
            best.add(i)
        body.append([s.rank, s.label, _opts(s.settings), s.correct, s.n, s.accuracy, s.context_recall,
                     s.hit, s.prompt_tokens, s.completion_tokens, s.retrieval_ms, s.total_ms, s.cached,
                     f"{s.refusals_ok}/{s.n_unanswerable}" if s.n_unanswerable else "–",
                     f"{s.false_refusals}/{s.n_answerable}", s.main_failure or "none", s.note])
    for m in v.not_run:
        body.append(["–", _name(m), "", None, None, None, None, None, None, None, None, None, None, "",
                     "", "", "shortlisted but no rows in results.csv, so not ranked"])
    nxt = _table(ws, 1, hdr, body, {6: PCT, 7: PCT, 8: PCT, 9: INT, 10: INT, 11: NUM, 12: INT},
                 highlight=best)
    ws.cell(row=nxt, column=1,
            value=f"Ranked on the same {len(v.qids)} questions for every method. Context gold-row recall "
                  "and hit rate count answerable questions only. Retrieval latency is measured after the "
                  "models are loaded.")
    ws.freeze_panes = "D2"
    _widths(ws, [8, 18, 24, 9, 10, 10, 13, 9, 13, 14, 12, 12, 10, 14, 14, 24, 80])


def _sheet_accuracy(ws: Worksheet, v: Verdict, used: pd.DataFrame) -> None:
    types = [b.type for b in v.by_type]
    counts = used.drop_duplicates("qid")["type"].value_counts()
    hdr = ["Method", *[f"{t} ({counts[t]})" for t in types], f"overall ({len(v.qids)})"]
    body = []
    for s in v.ranking:
        sub = used[used["method"] == s.method]
        body.append([s.label, *[sub[sub["type"] == t]["correct"].mean() for t in types],
                     sub["correct"].mean()])
    best = {i for i, s in enumerate(v.ranking) if s.rank == 1}
    nxt = _table(ws, 1, hdr, body, {c: PCT for c in range(2, len(hdr) + 1)}, highlight=best)
    ws.cell(row=nxt, column=1, value="Share of correct answers on the ranking's question set. Unanswerable "
                                     "questions count as correct when the method refuses.")
    _widths(ws, [18] + [15] * (len(hdr) - 1))


def _sheet_cost(ws: Worksheet, v: Verdict, used: pd.DataFrame) -> None:
    hdr = ["Method", "Hit rate", "Context gold-row recall", "Sections in context",
           "Holding rows in context", "Context tokens", "Prompt tokens", "Completion tokens",
           "Retrieval ms (median)", "Retrieval ms (mean)", "Generation ms", "Total ms"]
    body = []
    for s in v.ranking:
        sub = used[used["method"] == s.method]
        body.append([s.label, s.hit, s.context_recall, sub["n_chunks"].mean(),
                     sub["n_context_rows"].mean(), sub["context_tokens"].mean(),
                     sub["prompt_tokens"].mean(), sub["completion_tokens"].mean(),
                     sub["retrieval_ms"].median(), sub["retrieval_ms"].mean(),
                     sub["generation_ms"].mean(), sub["total_ms"].mean()])
    nxt = _table(ws, 1, hdr, body, {2: PCT, 3: PCT, 4: NUM, 5: INT, 6: INT, 7: INT, 8: INT, 9: NUM,
                                    10: NUM, 11: INT, 12: INT})
    ws.cell(row=nxt, column=1,
            value="Means per question on the ranking's question set (retrieval latency also as a median). "
                  "Context tokens use the embedding tokenizer; prompt tokens are the LLM's count of the "
                  "whole prompt. A cached answer carries the generation time of its original call.")
    _widths(ws, [18, 9, 13, 11, 13, 11, 11, 12, 12, 12, 12, 10])


def _sheet_offline(ws: Worksheet, offline: pd.DataFrame | None, shortlist: set[str]) -> None:
    from src.retrieval.offline import rank_methods

    if offline is None or offline.empty:
        ws.cell(row=1, column=1, value="No Stage A rows for this question set in offline.csv.")
        _widths(ws, [80])
        return
    hdr = ["Rank", "Method", "Settings", "Section recall@5", "Hit@5", "MRR@10", "Row recall@5",
           "Scheme recall@5", "Context gold rows", "Context tokens", "Median ms", "p90 ms", "Stage B"]
    ranking = rank_methods(offline)
    body, best = [], set()
    for i, s in enumerate(ranking):
        if s.rank == 1:
            best.add(i)
        body.append([s.rank, f"{METHOD_IDS.get(s.method, '')} {s.method}".strip(), _opts(s.settings),
                     s.section_recall_5, s.hit_5, s.mrr_10, s.row_recall_5, s.scheme_recall_5,
                     s.context_recall, s.context_tokens, s.median_ms, s.p90_ms,
                     "yes" if s.method in shortlist else ""])
    nxt = _table(ws, 1, hdr, body, {4: PCT, 5: PCT, 6: NUM, 7: PCT, 8: PCT, 9: PCT, 10: INT, 11: NUM,
                                    12: NUM}, highlight=best)
    ws.cell(row=nxt, column=1,
            value="Stage A: all eight methods on the same test questions, retrieval only, no LLM call "
                  "(free). Ranked by mean section recall@5; ties by hit@5, then MRR@10, then latency "
                  "(spec §6.5). The top 2 plus M1 dense were paid for in Stage B.")
    _widths(ws, [8, 18, 30, 12, 9, 9, 11, 12, 12, 11, 10, 10, 9])


def _sheet_questions(ws: Worksheet, v: Verdict, df: pd.DataFrame) -> None:
    hdr = ["Method", "Question", "Type", "Hand-written", "Question text", "Gold answer", "Answer given",
           "Correct", "Wrong because", "Status", "In ranking", "Context gold-row recall", "Sections",
           "Holding rows", "Prompt tokens", "Completion tokens", "Retrieval ms", "Total ms", "Cached",
           "Filter match", "Schemes found"]
    order = {m: i for i, m in enumerate(METHOD_IDS)}
    rows = df.assign(_o=df["method"].map(order).fillna(99)).sort_values(["_o", "qid"])
    body = [[_name(r["method"]), r["qid"], r["type"], "yes" if str(r["qid"]).startswith("Q") else "no",
             r["question"], _gold(r["gold_value"], r["unit"]), _given(r),
             "yes" if r["correct"] == 1 else "no",
             "pending (no real answer yet)" if r["pending"] == 1 else r["failure"], r["status"],
             "yes" if r["qid"] in v.qids else "no", r["gold_row_recall"], r["n_chunks"],
             r["n_context_rows"], r["prompt_tokens"], r["completion_tokens"], r["retrieval_ms"],
             r["total_ms"], "yes" if r["cached"] == 1 else "no", r.get("filter_match", ""),
             r.get("schemes_found", "")] for _, r in rows.iterrows()]
    _table(ws, 1, hdr, body, {12: PCT, 13: NUM, 14: INT, 15: INT, 16: INT, 17: NUM, 18: INT})
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(hdr))}{len(body) + 1}"
    _widths(ws, [16, 9, 13, 11, 60, 30, 40, 8, 22, 13, 9, 12, 9, 11, 11, 12, 10, 9, 8, 11, 22])


def _sheet_run(ws: Worksheet, manifest: dict, df: pd.DataFrame, spend: list[dict]) -> None:
    llm, rr = manifest.get("llm", {}), manifest.get("reranker") or {}
    rows = [["Stage", f"{manifest.get('stage')} ({manifest.get('phase')}), question set "
                      f"{manifest.get('question_set')}"],
            ["LLM", llm_label(llm.get("provider"), llm.get("model"))],
            ["Temperature", manifest.get("config", {}).get("llm", {}).get("temperature")],
            ["Embedding model", manifest.get("embedding_model")],
            ["Reranker", f"{rr.get('model')} @ {rr.get('revision')}"],
            ["candidate_k / top_k", f"{manifest.get('candidate_k')} / {manifest.get('top_k')}"],
            ["Methods in this run", ", ".join(_name(m) for m in manifest.get("retrieval_methods",
                                                                            sorted(set(df["method"]))))],
            ["Method settings", json.dumps(manifest.get("method_settings", {}), sort_keys=True)],
            ["Question set sha256", manifest.get("setup", {}).get("questions_sha256")],
            ["Rows", f"{manifest.get('rows', len(df))} of {manifest.get('expected_rows', '–')} expected"],
            ["Pending rows", int(df["pending"].fillna(0).sum())],
            ["Cached answers", int(df["cached"].fillna(0).sum())],
            ["Token cap of the last run", manifest.get("max_tokens")],
            ["Run complete", "yes" if manifest.get("complete") else "no"]]
    if manifest.get("model_check"):
        mc = manifest["model_check"]
        rows.append(["Model check (§12)", f"{mc.get('verdict')} on {len(mc.get('questions', []))} "
                                          f"questions, model {mc.get('model')}, {mc.get('at')}"])
    rows += [[f"Data file: {k}", f"sha256 {v[:16]}…"] for k, v in manifest.get("data_files", {}).items()
             if k.startswith("raw/")]
    nxt = _table(ws, 1, ["Field", "Value"], rows)

    ws.cell(row=nxt, column=1, value="Spend (tokens only; prices are not kept in this repo)").font = BOLD
    hdr = ["At (IST)", "Phase", "Questions", "Calls", "Cached", "Paid calls", "Prompt tokens",
           "Completion tokens", "Total tokens", "Estimated total", "Cap", "Stopped"]
    body = [[str(r.get("at_ist", ""))[:19].replace("T", " "), r.get("phase"), int(r.get("questions") or 0),
             int(r.get("calls") or 0), int(r.get("cached") or 0), int(r.get("paid_calls") or 0),
             int(r.get("prompt_tokens") or 0), int(r.get("completion_tokens") or 0),
             int(r.get("total_tokens") or 0), int(r.get("est_total_tokens") or 0),
             int(r.get("max_tokens") or 0), r.get("stopped") or "–"] for r in spend]
    _table(ws, nxt + 1, hdr, body, {c: INT for c in range(3, 12)})
    _widths(ws, [28, 70, 11, 9, 9, 10, 13, 14, 13, 14, 12, 12])


def write_excel(df: pd.DataFrame, manifest: dict, v: Verdict, offline: pd.DataFrame | None,
                path: Path) -> Path:
    from src.retrieval.report import read_spend

    used = df[df["qid"].isin(v.qids)]
    wb = Workbook()
    _sheet_verdict(wb.active, v, df, manifest)
    wb.active.title = "Verdict"
    _sheet_ranking(wb.create_sheet("Ranking"), v)
    _sheet_accuracy(wb.create_sheet("Accuracy by type"), v, used)
    _sheet_cost(wb.create_sheet("Retrieval & cost"), v, used)
    _sheet_offline(wb.create_sheet("Offline (Stage A)"), offline, {s.method for s in v.ranking})
    _sheet_questions(wb.create_sheet("Per question"), v, df)
    _sheet_run(wb.create_sheet("Run info"), manifest, df, read_spend(path.parent))
    wb.save(path)
    return path
