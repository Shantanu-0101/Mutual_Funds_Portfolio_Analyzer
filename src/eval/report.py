"""``results.csv`` → ``results/summary.md`` + ``results/accuracy_by_method.png`` (task 5.6, spec §6.6).

Read only from ``results.csv`` and ``run_manifest.json``; nothing is re-asked.

Tables:

1. Accuracy by method × question type (and overall).
2. Retrieval next to context size: hit rate and gold-row recall on answerable
   questions, mean chunks / holding rows / context tokens shown to the LLM.
   Context tokens are counted with the embedding model's tokenizer (the chunk
   sizes); prompt tokens are the LLM's own count of the whole prompt.
3. Tokens and latency per method (means per question; latency of a cached
   answer is the latency of its original call).
4. Refusals: correct refusals on the unanswerable questions, false refusals on
   the answerable ones.
5. Status counts (anything not ``ok``).
6. Up to three failure examples per method, labelled as in ``runner.failure_label``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.eval.questions import TYPES
from src.eval.runner import MANIFEST_FILE, METHODS, RESULTS_FILE

SUMMARY_FILE = "summary.md"
CHART_FILE = "accuracy_by_method.png"
NUMERIC = ["correct", "refused", "false_refusal", "unanswerable_correct", "retrieval_hit", "gold_row_recall",
           "jaccard", "n_chunks", "n_context_rows", "context_tokens", "prompt_tokens", "completion_tokens",
           "retrieval_ms", "generation_ms", "execution_ms", "total_ms", "pending", "cached"]

# Reference palette (dataviz skill): one series, so one hue; text in ink colours, not the series colour.
SURFACE, INK, INK_2, GRID, SERIES = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df", "#2a78d6"


def load(results_dir: Path) -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(results_dir / RESULTS_FILE, dtype=str, keep_default_na=False)
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c].replace("", None), errors="coerce")
    path = results_dir / MANIFEST_FILE
    manifest = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return df, manifest


def _methods(df: pd.DataFrame) -> list[str]:
    return [m for m in METHODS if m in set(df["method"])] + sorted(set(df["method"]) - set(METHODS))


def _types(df: pd.DataFrame) -> list[str]:
    return [t for t in TYPES if t in set(df["type"])]


def _md(header: list[str], rows: list[list], right_from: int = 1) -> list[str]:
    align = ["---" if i < right_from else "---:" for i in range(len(header))]
    return ["| " + " | ".join(header) + " |", "| " + " | ".join(align) + " |"] + \
           ["| " + " | ".join(str(c) for c in r) + " |" for r in rows] + [""]


def _frac(s: pd.Series) -> str:
    s = s.dropna()
    return f"{s.mean():.0%} ({int(s.sum())}/{len(s)})" if len(s) else "–"


def _mean(s: pd.Series, fmt: str = "{:,.0f}") -> str:
    s = s.dropna()
    return fmt.format(s.mean()) if len(s) else "–"


def accuracy_table(df: pd.DataFrame) -> pd.DataFrame:
    """method × (types + overall) → accuracy, as numbers (for the chart and tests)."""
    t = df.pivot_table(index="method", columns="type", values="correct", aggfunc="mean")
    t["overall"] = df.groupby("method")["correct"].mean()
    return t.reindex(index=_methods(df), columns=[*_types(df), "overall"])


def _short(text: str, n: int = 160) -> str:
    text = " ".join(str(text).split()).replace("|", "/")
    return text if len(text) <= n else text[: n - 1] + "…"


def _given(r: pd.Series) -> str:
    if r["status"] != "ok":
        return f"status `{r['status']}`" + (f": {_short(r['error'], 120)}" if r["error"] else "")
    if r["value"] != "":
        return f"value {r['value']} {r['answer_unit']}".strip() + f" (\"{_short(r['answer'], 80)}\")"
    items = json.loads(r["items"] or "[]")
    if items:
        return f"items {_short('; '.join(map(str, items)), 140)}"
    return f"\"{_short(r['answer'], 140)}\""


def failure_examples(df: pd.DataFrame, method: str, n: int = 3) -> list[pd.Series]:
    """Up to n wrong rows, one per failure label first (so the examples show different kinds)."""
    wrong = df[(df["method"] == method) & (df["correct"] == 0)]
    picked: list[pd.Series] = []
    for _, r in wrong.iterrows():                       # first example of each label, in question order
        if len(picked) < n and r["failure"] not in {p["failure"] for p in picked}:
            picked.append(r)
    for _, r in wrong.iterrows():                       # then fill up
        if len(picked) < n and r["qid"] not in {p["qid"] for p in picked}:
            picked.append(r)
    return picked


def summary_md(df: pd.DataFrame, manifest: dict) -> str:
    methods, types = _methods(df), _types(df)
    llm = manifest.get("llm", {})
    sessions = manifest.get("sessions", [])
    lines = ["# Evaluation results", "",
             f"Written by `python -m src.eval report` from `results/{RESULTS_FILE}` "
             f"({len(df)} rows: {len(methods)} methods × {df['qid'].nunique()} questions).", ""]
    run_rows = [["LLM", f"{llm.get('provider')} / `{llm.get('model')}` (temperature "
                        f"{manifest.get('config', {}).get('llm', {}).get('temperature')})"],
                ["Embedding", f"`{manifest.get('embedding_model')}`, top_k "
                              f"{manifest.get('config', {}).get('retrieval', {}).get('top_k')}"],
                ["Run", f"started {manifest.get('created_at')}, {len(sessions)} session(s), last finished "
                        f"{sessions[-1].get('finished_at') if sessions else '–'}"],
                ["Commit", f"`{(sessions[-1].get('commit') or '')[:7]}`"
                           + (" (uncommitted changes)" if sessions and sessions[-1].get("dirty") else "")
                           if sessions else "–"],
                ["Cached answers", f"{int(df['cached'].sum())} of {len(df)}"]]
    lines += _md(["", ""], run_rows, right_from=2)

    not_run = [m for m in METHODS if m not in methods]
    if not_run:
        lines += [f"> **Not run in this run:** {', '.join(f'`{m}`' for m in not_run)}. They are missing from "
                  "every table below, so do not compare them by absence.", ""]

    pending = df[df["pending"] == 1]
    other_models = df[(df["model"] != "") & (df["model"] != llm.get("model"))]
    if len(pending) or len(other_models) or not manifest.get("complete", False):
        lines += ["> **Not a complete run.** "
                  + (f"{len(pending)} row(s) still pending (rate limit, provider down, or answered by the "
                     f"fallback model); run `python -m src.eval run` again. " if len(pending) else "")
                  + (f"{len(other_models)} row(s) answered by another model. " if len(other_models) else "")
                  + ("The manifest does not mark the run complete." if not manifest.get("complete") else ""), ""]

    acc = accuracy_table(df)
    lines += ["## 1. Accuracy by method and question type", "",
              "Correct answers / questions. Unanswerable questions count as correct when the method says the "
              "data does not contain the answer.", ""]
    counts = df.groupby("type")["qid"].nunique()
    header = ["Method", *[f"{t} ({counts[t]})" for t in types], f"overall ({df['qid'].nunique()})"]
    body = []
    for m in methods:
        sub = df[df["method"] == m]
        cells = [_frac(sub[sub["type"] == t]["correct"]) for t in types]
        body.append([f"**{m}**", *cells, f"**{_frac(sub['correct'])}**"])
    lines += _md(header, body)
    lines += [f"![Accuracy by method]({CHART_FILE})", ""]

    ans = df[df["answer_kind"] != "not_in_data"]
    lines += ["## 2. Retrieval and context size", "",
              "Answerable questions only. *Hit*: at least one gold row was in the context. *Recall*: share of "
              "gold rows in the context (aggregations need all of them). Context tokens use the embedding "
              "tokenizer; prompt tokens are the LLM's count of the whole prompt.", ""]
    body = []
    for m in methods:
        sub, sub_all = ans[ans["method"] == m], df[df["method"] == m]
        body.append([f"**{m}**", _frac(sub["retrieval_hit"]), _mean(sub["gold_row_recall"], "{:.0%}"),
                     _mean(sub_all["n_chunks"], "{:.1f}"), _mean(sub_all["n_context_rows"], "{:,.0f}"),
                     _mean(sub_all["context_tokens"]), _mean(sub_all["prompt_tokens"]),
                     _frac(sub["correct"])])
    lines += _md(["Method", "Hit", "Gold-row recall", "Chunks", "Holding rows", "Context tokens",
                  "Prompt tokens", "Accuracy (answerable)"], body)
    lines += ["The baseline has no retrieval: its prompt is the table schema, and the code reads the whole "
              "table.", ""]

    lines += ["## 3. Tokens and latency", "", "Means per question. Latency of a cached answer is that of its "
              "original call.", ""]
    body = []
    for m in methods:
        sub = df[df["method"] == m]
        body.append([f"**{m}**", _mean(sub["prompt_tokens"]), _mean(sub["completion_tokens"]),
                     f"{int(sub['prompt_tokens'].sum() + sub['completion_tokens'].sum()):,}",
                     _mean(sub["retrieval_ms"]), _mean(sub["generation_ms"]), _mean(sub["execution_ms"]),
                     _mean(sub["total_ms"])])
    lines += _md(["Method", "Prompt tok", "Completion tok", "Total tok (all questions)", "Retrieval ms",
                  "Generation ms", "Code run ms", "Total ms"], body)

    una = df[df["answer_kind"] == "not_in_data"]
    lines += ["## 4. Refusals", ""]
    body = [[f"**{m}**", _frac(una[una["method"] == m]["unanswerable_correct"]),
             _frac(ans[ans["method"] == m]["false_refusal"])] for m in methods]
    lines += _md(["Method", "Unanswerable: correctly refused", "Answerable: refused anyway (false refusal)"],
                 body)

    lines += ["## 5. Status and failure kinds", "", "Rows whose status is not `ok`, and the label of every "
              "wrong answer.", ""]
    body = []
    for m in methods:
        sub = df[df["method"] == m]
        st = sub[sub["status"] != "ok"]["status"].value_counts()
        fl = sub[sub["failure"] != ""]["failure"].value_counts()
        body.append([f"**{m}**", ", ".join(f"{k} {v}" for k, v in st.items()) or "all ok",
                     ", ".join(f"{k} {v}" for k, v in fl.items()) or "none"])
    lines += _md(["Method", "Non-ok status", "Wrong answers by kind"], body, right_from=3)

    lines += ["## 6. Failure examples", "",
              "Up to three wrong answers per method, different kinds first. *retrieval miss*: not every gold "
              "row reached the LLM; *generation error*: the rows were there (or no retrieval) and the answer "
              "is still wrong; *format error*: the reply broke the JSON format; *context overflow*: the "
              "provider refused the prompt as too large.", ""]
    for m in methods:
        ex = failure_examples(df, m)
        lines += [f"### {m}", ""]
        if not ex:
            lines += ["No wrong answers.", ""]
            continue
        for r in ex:
            recall = "" if pd.isna(r["gold_row_recall"]) else f", gold-row recall {r['gold_row_recall']:.0%}"
            lines += [f"- **{r['qid']}** ({r['type']}) · *{r['failure']}*{recall}  ",
                      f"  Q: {_short(r['question'], 200)}  ",
                      f"  Gold: {_short(r['gold_value'], 160)}{' ' + r['unit'] if r['unit'] else ''}  ",
                      f"  Given: {_given(r)}"]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def accuracy_chart(df: pd.DataFrame, path: Path) -> None:
    """Horizontal bars, one per method, overall accuracy; value at the bar end."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    acc = accuracy_table(df)["overall"]
    methods = list(acc.index)[::-1]                       # first method on top
    n_q = df.groupby("method")["qid"].nunique()
    fig, ax = plt.subplots(figsize=(7.2, 0.5 * len(methods) + 1.3), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    vals = [acc[m] * 100 for m in methods]
    ax.barh(methods, vals, height=0.6, color=SERIES, edgecolor=SURFACE, linewidth=2)
    for y, (m, v) in enumerate(zip(methods, vals)):
        right = df[df["method"] == m]["correct"].sum()
        ax.text(v + 1, y, f"{v:.0f}%  ({int(right)}/{n_q[m]})", va="center", ha="left", fontsize=9, color=INK)
    ax.set_xlim(0, 115)
    ax.set_xticks(range(0, 101, 25))
    ax.set_xticklabels([f"{t}%" for t in range(0, 101, 25)], color=INK_2, fontsize=9)
    ax.tick_params(axis="y", colors=INK, labelsize=10, length=0)
    ax.tick_params(axis="x", length=0)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.set_title("Accuracy by method, all questions", loc="left", color=INK, fontsize=12, pad=10)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def write_report(results_dir: Path) -> Path:
    df, manifest = load(results_dir)
    accuracy_chart(df, results_dir / CHART_FILE)
    path = results_dir / SUMMARY_FILE
    path.write_text(summary_md(df, manifest), encoding="utf-8")
    return path
