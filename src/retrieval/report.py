"""The two retrieval reports: Stage A offline (R3.5) and Stage B end to end (R5.2), §6.6.

Stage A: ``offline.csv`` → ``results/retrieval/offline_summary.md`` + ``recall_by_method.png``.

Reads only what Stage A wrote; nothing is re-run. Tables, in order:

1. **Leaderboard** (test set): the §6.5 ranking — mean ``section_recall@5``, then ``hit@5``, ``mrr@10``,
   median latency — with row and scheme recall, the context after the parent swap, and the shortlist
   Stage B will pay for.
2. **Per question type**: ``section_recall@5`` by method × type, and the best method per type.
3. **recall@k**: ``section_recall@k`` for k = 1, 3, 5, 10, 20, so the k = 5 cut can be judged.
4. **The 28 hand-written questions on their own** (R3.5): the same leaderboard on that subset, next to
   the 60 generated ones, because the generated questions copy exact names and flatter keyword search.
5. **Dev settings chosen** (FR-R2.3) and the **M8 recipe**, with the dev score of each candidate.
6. **Noise** (§6.5, RD8): paired bootstrap of the winner against M1 dense, in plain language.
7. **The scheme filter**: ``filter_miss`` / ``filter_wrong`` counts per filtering method.

The chart is ``section_recall@5`` by method and question type (grouped bars).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Sequence

import pandas as pd

from src.eval.questions import TYPES
from src.eval.report import GRID, INK, INK_2, SURFACE, _md   # the same markdown table helper
from src.retrieval.offline import (KS, MRR_K, PRIMARY, REFERENCE, Standing, bootstrap_note, choose_combo,
                                   choose_variants, load_offline, paired_bootstrap, paired_values,
                                   rank_methods, rank_variants, shortlist)
from src.retrieval.settings import METHOD_IDS

SUMMARY_FILE = "offline_summary.md"
CHART_FILE = "recall_by_method.png"
# One hue per question type (dataviz skill: a small categorical set, ink colours for text).
TYPE_COLOURS = ("#2a78d6", "#1f9d8f", "#c2733c", "#8a63c7", "#b5495b")


def _pct(x: float | None) -> str:
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.0%}"


def _num(x: float | None, fmt: str = "{:,.0f}") -> str:
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else fmt.format(x)


def _label(s: Standing) -> str:
    return f"{METHOD_IDS[s.method]} {s.method}"


def _settings(s: Standing) -> str:
    return "–" if not s.settings else ", ".join(f"{k}={v}" for k, v in sorted(s.settings.items()))


def _types(df: pd.DataFrame) -> list[str]:
    return [t for t in TYPES if t in set(df["type"])]


def leaderboard_rows(ranking: Sequence[Standing], picked: Sequence[str] = ()) -> list[list]:
    return [[s.rank, _label(s), _settings(s), _pct(s.section_recall_5), _pct(s.hit_5), f"{s.mrr_10:.3f}",
             _pct(s.row_recall_5), _pct(s.scheme_recall_5), _pct(s.context_recall),
             _num(s.context_tokens), _num(s.median_ms, "{:,.0f}"), _num(s.p90_ms, "{:,.0f}"),
             "yes" if s.method in set(picked) else ""]
            for s in ranking]


LEADERBOARD_HEAD = ["#", "method", "settings", "section recall@5", "hit@5", f"mrr@{MRR_K}", "row recall@5",
                    "scheme recall@5", "context gold rows", "context tokens", "median ms", "p90 ms",
                    "Stage B"]


def per_type_table(df: pd.DataFrame, ranking: Sequence[Standing]) -> pd.DataFrame:
    """method × question type → mean ``section_recall@5`` (answerable questions only)."""
    ans = df[df["answerable"] == 1]
    t = ans.pivot_table(index="method", columns="type", values=PRIMARY, aggfunc="mean")
    t = t.reindex(index=[s.method for s in ranking], columns=_types(ans))
    t["overall"] = [s.section_recall_5 for s in ranking]
    return t


def recall_at_k_table(df: pd.DataFrame, ranking: Sequence[Standing]) -> pd.DataFrame:
    ans = df[df["answerable"] == 1]
    rows = {s.method: [ans[ans["method"] == s.method][f"section_recall@{k}"].mean() for k in KS]
            for s in ranking}
    return pd.DataFrame(rows, index=[f"k={k}" for k in KS]).T


def filter_table(df: pd.DataFrame) -> list[list]:
    sub = df[df["filter_miss"].notna()]
    out = []
    for method in dict.fromkeys(sub["method"]):
        s = sub[sub["method"] == method]
        out.append([f"{METHOD_IDS[method]} {method}", len(s), int(s["filter_miss"].sum()),
                    int(s["filter_wrong"].sum()), _pct(s[PRIMARY].mean())])
    return out


def summary_md(df: pd.DataFrame, test_set: str = "test", dev_set: str = "dev") -> str:
    """The whole report, from offline.csv alone."""
    test = df[df["set"] == test_set]
    dev = df[df["set"] == dev_set]
    if test.empty:
        raise ValueError(f"offline.csv has no rows of set {test_set!r}: run Stage A on it first")
    ranking = rank_methods(test)
    picked = shortlist(ranking)
    best = ranking[0]
    n_q = test["qid"].nunique()
    n_ans = int(test[test["method"] == best.method]["answerable"].sum())

    out = ["# Retrieval benchmark, Stage A (offline, no LLM call)", "",
           f"Question set `{test_set}`: {n_q} questions, {n_ans} of them answerable (retrieval metrics use "
           f"those). Every method ranks {int(test['children'].map(lambda s: len(json.loads(s))).max())} "
           f"children per question; the pipeline sends the top 5 after the parent swap.", "",
           f"**Best offline (§6.5): {_label(best)}** — mean `{PRIMARY}` {_pct(best.section_recall_5)}, "
           f"`hit@5` {_pct(best.hit_5)}, `mrr@{MRR_K}` {best.mrr_10:.3f}, median "
           f"{_num(best.median_ms)} ms.", "",
           f"**Shortlist for Stage B (RD6): {', '.join(METHOD_IDS[m] + ' ' + m for m in picked)}** "
           f"— the top 2 plus M1 `dense` as the reference.", ""]

    out += ["## 1. Leaderboard (set `%s`)" % test_set, ""]
    out += _md(LEADERBOARD_HEAD, leaderboard_rows(ranking, picked), right_from=3)
    out += ["Ranked by mean `section_recall@5`; ties by `hit@5`, then `mrr@10`, then lower median latency "
            "(§6.5). Latency is measured after the models are loaded, so the reranker's cost is the "
            "uncached one. `context gold rows` and `context tokens` describe the top 5 **after** the "
            "parent swap: the context the LLM would see.", ""]

    out += ["## 2. `section_recall@5` by question type", ""]
    t = per_type_table(test, ranking)
    out += _md(["method", *t.columns], [[_label(s), *[_pct(t.loc[s.method, c]) for c in t.columns]]
                                        for s in ranking])
    best_per_type = []
    for col in _types(test):
        sub = test[test["type"] == col]
        if not sub[sub["answerable"] == 1].empty:
            r = rank_methods(sub)
            best_per_type.append([col, int(sub["qid"].nunique()), _label(r[0]), _pct(r[0].section_recall_5),
                                  _label(r[1]) if len(r) > 1 else "–",
                                  _pct(r[1].section_recall_5) if len(r) > 1 else "–"])
    out += ["**Best method per type** (same rule; input for a router later, not used now):", ""]
    out += _md(["type", "questions", "best", "its recall@5", "runner-up", "its recall@5"], best_per_type,
               right_from=1)

    out += ["## 3. `section_recall@k`", ""]
    k_table = recall_at_k_table(test, ranking)
    out += _md(["method", *k_table.columns], [[_label(s), *[_pct(k_table.loc[s.method, c])
                                                            for c in k_table.columns]] for s in ranking])
    out += ["The pipeline uses k = 5. A big jump from k=5 to k=10 or 20 means the right section is found "
            "but ranked too low.", ""]

    out += ["## 4. The 28 hand-written questions on their own", ""]
    originals, generated = test[test["original"] == 1], test[test["original"] == 0]
    if originals.empty:
        out += ["This set holds no original questions.", ""]
    else:
        o_rank, g_rank = rank_methods(originals), rank_methods(generated) if not generated.empty else []
        g_by = {s.method: s for s in g_rank}
        out += _md(["method", "28 hand-written: recall@5", "hit@5", f"{len(generated['qid'].unique())} "
                    "generated: recall@5", "hit@5"],
                   [[_label(s), _pct(s.section_recall_5), _pct(s.hit_5),
                     _pct(g_by[s.method].section_recall_5) if s.method in g_by else "–",
                     _pct(g_by[s.method].hit_5) if s.method in g_by else "–"] for s in o_rank])
        out += ["The generated questions copy scheme and instrument names from the data, which flatters "
                "keyword search and the scheme filter (§12); the hand-written ones are the honest check. "
                "The reported verdict uses the whole set, as the spec fixes it.", ""]

    out += ["## 5. Settings chosen on dev, and M8", ""]
    if dev.empty:
        out += ["No dev rows in offline.csv.", ""]
    else:
        chosen = choose_variants(dev)
        rows = []
        for name, s in chosen.items():
            if name == "best_combo":
                continue
            tried = len(set(dev[dev["method"] == name]["variant"]))
            rows.append([f"{METHOD_IDS[name]} {name}", tried, _settings(s), _pct(s.section_recall_5),
                         _pct(s.hit_5), f"{s.mrr_10:.3f}"])
        out += _md(["method", "variants tried", "chosen", "dev recall@5", "dev hit@5", f"dev mrr@{MRR_K}"],
                   rows, right_from=1)
        out += [f"Chosen on dev only, by mean `{PRIMARY}` with the §6.5 tie-breaks, and written into "
                "`config.yaml` with the date (FR-R2.3). Test scores were computed after that.", ""]
        if not dev[dev["method"] == "best_combo"].empty:
            combo = choose_combo(dev)
            cands = rank_variants(dev, list(dict.fromkeys(dev[dev["method"] == "best_combo"]["variant"])))
            out += [f"**M8 `best_combo` = {_settings(combo)}** (declared from dev, before any test score, "
                    "R3.4). The candidates:", ""]
            out += _md(["#", "candidate", "dev recall@5", "dev hit@5", f"dev mrr@{MRR_K}", "median ms"],
                       [[c.rank, _settings(c), _pct(c.section_recall_5), _pct(c.hit_5), f"{c.mrr_10:.3f}",
                         _num(c.median_ms)] for c in cands], right_from=2)
            out += ["The candidates ran after the grid above, so a candidate with a cross-encoder read its "
                    "scores from the disk cache and its `median ms` here is **not** the uncached cost. The "
                    "leaderboard's latency (table 1) is the first, uncached run of each method on this set.",
                    ""]

    out += ["## 6. Is the lead real? (paired bootstrap, 10,000 resamples, seed 42)", ""]
    notes = []
    for s in ranking[:3]:
        if s.method == REFERENCE:
            continue
        a, b = paired_values(test, s.method, REFERENCE)
        notes.append("- " + bootstrap_note(_label(s), METHOD_IDS[REFERENCE] + " dense", *paired_bootstrap(a, b)))
    out += (notes or ["- M1 `dense` is the best offline method here, so there is nothing to compare it with."])
    out += ["", "The same interval for end-to-end `correct` follows in Stage B (§6.5).", ""]

    out += ["## 7. The scheme filter on real questions", ""]
    ft = filter_table(test)
    if ft:
        out += _md(["method", "questions", "filter_miss", "filter_wrong", "recall@5"], ft, right_from=1)
        out += ["`filter_miss`: the question's own scheme was not found (the method then searches "
                "everything, as M1 does). `filter_wrong`: a scheme the gold rows do not use was found — a "
                "fund-of-funds question naming another AMC's fund does this (R2 notes, D031).", ""]
    else:
        out += ["No method in this run filters by scheme.", ""]
    return "\n".join(out).rstrip() + "\n"


def recall_chart(df: pd.DataFrame, path: Path, test_set: str = "test") -> None:
    """``section_recall@5`` by method and question type: grouped bars, one colour per type."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    test = df[df["set"] == test_set]
    ranking = rank_methods(test)
    t = per_type_table(test, ranking)
    types = [c for c in t.columns if c != "overall"]
    methods = [s.method for s in ranking]
    width = 0.8 / (len(types) + 1)
    fig, ax = plt.subplots(figsize=(1.25 * len(methods) + 1.0, 4.6), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    base = range(len(methods))
    for n, col in enumerate([*types, "overall"]):
        vals = [(t.loc[m, col] if not pd.isna(t.loc[m, col]) else 0) * 100 for m in methods]
        colour = INK if col == "overall" else TYPE_COLOURS[n % len(TYPE_COLOURS)]
        ax.bar([x + n * width for x in base], vals, width=width * 0.92, label=col, color=colour,
               edgecolor=SURFACE, linewidth=0.6)
    ax.set_xticks([x + width * len(types) / 2 for x in base])
    ax.set_xticklabels([f"{METHOD_IDS[m]}\n{m}" for m in methods], color=INK, fontsize=8.5)
    ax.set_ylim(0, 108)
    ax.set_yticks(range(0, 101, 25))
    ax.set_yticklabels([f"{v}%" for v in range(0, 101, 25)], color=INK_2, fontsize=9)
    ax.tick_params(length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.set_title(f"Section recall@5 by method and question type (set {test_set})", loc="left", color=INK,
                 fontsize=12, pad=10)
    ax.legend(frameon=False, ncol=len(types) + 1, fontsize=9, loc="upper center",
              bbox_to_anchor=(0.5, -0.11), labelcolor=INK_2)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


def write_offline_report(results_dir: Path, test_set: str = "test") -> Path:
    """offline.csv → offline_summary.md + recall_by_method.png; returns the summary path."""
    from src.retrieval.offline import OFFLINE_FILE

    df = load_offline(results_dir / OFFLINE_FILE)
    recall_chart(df, results_dir / CHART_FILE, test_set)
    path = results_dir / SUMMARY_FILE
    path.write_text(summary_md(df, test_set), encoding="utf-8", newline="\n")
    return path


# =========================================================================== Stage B (R5)
#
# ``results/retrieval/results.csv`` → ``summary.md`` (§6.6, R5.2). Read only; nothing is re-asked and no
# LLM is called. Sections, in order:
#
# 1. **Verdict** (§6.5, computed by ``src.retrieval.verdict``): the winner, why, the per-type best method
#    and the paired-bootstrap note against M1 dense (RD8).
# 2. **Accuracy** by method × question type.
# 3. **Retrieval and context**: context gold-row recall next to the context the LLM actually saw.
# 4. **Tokens and latency** per question.
# 5. **Refusals**, status and failure kinds, including the filter labels (R4.4).
# 6. **Three failure examples per method.**
# 7. **What the run cost** (``spend_log.csv``, tokens only — RD11).

STAGE_B_SUMMARY_FILE = "summary.md"
RESULTS_FILE = "results.csv"
SPEND_FILE = "spend_log.csv"
EXTRA_NUMERIC = ["filter_miss", "filter_wrong", "padded", "reasoning_tokens"]


def load_results(results_dir: Path) -> tuple[pd.DataFrame, dict]:
    """Stage B results.csv + run_manifest.json, with the numeric columns parsed."""
    from src.eval.report import NUMERIC
    from src.eval.runner import MANIFEST_FILE

    df = pd.read_csv(results_dir / RESULTS_FILE, dtype=str, keep_default_na=False)
    for c in [*NUMERIC, *EXTRA_NUMERIC]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c].replace("", None), errors="coerce")
    path = results_dir / MANIFEST_FILE
    manifest = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return df, manifest


def read_spend(results_dir: Path) -> list[dict[str, str]]:
    """``spend_log.csv`` as it stands, oldest run first (tokens only, RD11)."""
    import csv

    path = results_dir / SPEND_FILE
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _name(method: str) -> str:
    return f"{METHOD_IDS.get(method, '')} {method}".strip()


def stage_b_methods(df: pd.DataFrame) -> list[str]:
    present = set(df["method"])
    return [m for m in METHOD_IDS if m in present] + sorted(present - set(METHOD_IDS))


def verdict_md(v) -> list[str]:
    """The verdict section: the §6.5 rule applied by code, with the reasons and the bootstrap note."""
    from src.retrieval.verdict import verdict_line

    out = ["## 1. Verdict", "", f"**{verdict_line(v)}**", "",
           "Rule, fixed before the paid run (§6.5): most correct answers on the test set; a tie goes to "
           "higher context gold-row recall, then to fewer prompt tokens per question, then to lower "
           "retrieval latency. The verdict is computed by code (`src/retrieval/verdict.py`), not written "
           "by hand. Full detail: [`retrieval_report.xlsx`](retrieval_report.xlsx).", ""]
    out += [f"- {r}" for r in v.reasons] + [""]
    if v.caveats:
        out += [f"> {c}  " for c in v.caveats] + [""]

    out += _md(["#", "method", "settings", "correct", "accuracy", "context gold rows", "prompt tok",
                "median retrieval ms", "note"],
               [[s.rank, s.label, ", ".join(f"{k}={val}" for k, val in sorted(s.settings.items())) or "–",
                 f"{s.correct}/{s.n}", _pct(s.accuracy), _pct(s.context_recall),
                 _num(s.prompt_tokens), _num(s.retrieval_ms), s.note] for s in v.ranking],
               right_from=4)

    out += ["**Best method per question type** (same rule; input for a router later, not used by the "
            "pipeline):", ""]
    out += _md(["question type", "questions", "best", "accuracy", "runner-up", "its accuracy",
                "decided by"],
               [[b.type, b.n, ", ".join(f"**{m}**" for m in b.best) or "none",
                 _pct(b.accuracy) if b.best else "–", b.runner_up or "–",
                 _pct(b.runner_up_accuracy), b.decided_by] for b in v.by_type], right_from=2)

    if v.noise:
        out += ["**Is the lead real?** Paired bootstrap, 10,000 resamples, seed 42 (§6.5, RD8):", ""]
        out += [f"- {nz.note} ({nz.n} paired questions)" for nz in v.noise] + [""]
    return out


def stage_b_summary_md(df: pd.DataFrame, manifest: dict, v=None, offline: pd.DataFrame | None = None,
                       spend: Sequence[dict] = ()) -> str:
    """The Stage B report, from results.csv, run_manifest.json, offline.csv and spend_log.csv."""
    from src.config import llm_label
    from src.eval.report import _frac, _given, _mean, _short, failure_examples

    methods = stage_b_methods(df)
    types = _types(df)
    llm, sessions = manifest.get("llm", {}), manifest.get("sessions", [])
    label = llm_label(llm.get("provider"), f"`{llm.get('model')}`")
    pending = int(df["pending"].fillna(0).sum())

    lines = ["# Retrieval benchmark, Stage B (end to end, real LLM answers)", "",
             f"Written by `python -m src.retrieval report` from `results/retrieval/{RESULTS_FILE}` "
             f"({len(df)} rows: {len(methods)} shortlisted methods × {df['qid'].nunique()} test "
             "questions). Stage A, the free offline comparison of all eight methods, is in "
             f"[`{SUMMARY_FILE}`]({SUMMARY_FILE}).", ""]
    run_rows = [["LLM", f"{label} (temperature "
                        f"{manifest.get('config', {}).get('llm', {}).get('temperature')})"],
                ["Embedding", f"`{manifest.get('embedding_model')}`, candidate_k "
                              f"{manifest.get('candidate_k')}, top_k {manifest.get('top_k')}"],
                ["Reranker", f"`{(manifest.get('reranker') or {}).get('model')}` @ "
                             f"`{str((manifest.get('reranker') or {}).get('revision'))[:12]}`"],
                ["Question set", f"`{manifest.get('question_set')}`, sha256 "
                                 f"`{str(manifest.get('setup', {}).get('questions_sha256'))[:16]}…`"],
                ["Run", f"started {manifest.get('created_at')}, {len(sessions)} session(s), last finished "
                        f"{sessions[-1].get('finished_at') if sessions else '–'}"],
                ["Rows", f"{manifest.get('rows', len(df))} of {manifest.get('expected_rows', '–')}, "
                         f"{pending} pending"],
                ["Cached answers", f"{int(df['cached'].fillna(0).sum())} of {len(df)} (byte-identical "
                                   "prompt, same model — RD7)"]]
    if manifest.get("model_check"):
        mc = manifest["model_check"]
        run_rows.append(["Model check (§12)", f"{mc.get('verdict')} — M1 re-asked with the cache off on "
                                              f"{len(mc.get('questions', []))} questions, "
                                              f"`{mc.get('model')}`"])
    lines += _md(["", ""], run_rows, right_from=2)

    if pending or not manifest.get("complete", False):
        lines += ["> **Not a complete run.** Pending rows mean the token cap stopped the run or the "
                  "provider fell back; run `python -m src.retrieval run` again before reading the "
                  "verdict.", ""]

    if v is not None:
        lines += verdict_md(v)

    lines += ["## 2. Accuracy by method and question type", "",
              "Correct answers / questions. An unanswerable question counts as correct when the method "
              "says the data does not contain the answer.", ""]
    counts = df.groupby("type")["qid"].nunique()
    header = ["Method", *[f"{t} ({counts[t]})" for t in types], f"overall ({df['qid'].nunique()})"]
    body = []
    for m in methods:
        sub = df[df["method"] == m]
        body.append([f"**{_name(m)}**", *[_frac(sub[sub["type"] == t]["correct"]) for t in types],
                     f"**{_frac(sub['correct'])}**"])
    lines += _md(header, body)

    ans = df[df["answer_kind"] != "not_in_data"]
    lines += ["## 3. Retrieval and the context the LLM saw", "",
              "Answerable questions only. *Hit*: at least one gold row reached the LLM. *Context gold-row "
              "recall*: share of the gold rows in the context after the parent swap — the verdict's first "
              "tie-break. Context tokens use the embedding tokenizer; prompt tokens are the LLM's count "
              "of the whole prompt, so the gap between them is the instructions and the question.", ""]
    body = []
    for m in methods:
        sub, sub_all = ans[ans["method"] == m], df[df["method"] == m]
        body.append([f"**{_name(m)}**", _frac(sub["retrieval_hit"]),
                     _mean(sub["gold_row_recall"], "{:.0%}"), _mean(sub_all["n_chunks"], "{:.1f}"),
                     _mean(sub_all["n_context_rows"], "{:,.0f}"), _mean(sub_all["context_tokens"]),
                     _mean(sub_all["prompt_tokens"]), _frac(sub["correct"])])
    lines += _md(["Method", "Hit", "Context gold-row recall", "Sections", "Holding rows",
                  "Context tokens", "Prompt tokens", "Accuracy (answerable)"], body)

    lines += ["## 4. Tokens and latency", "", "Means per question, except the median retrieval latency. "
              "A cached answer carries the latency of its original call, so generation times mix old and "
              "new calls; retrieval latency is this run's own measurement.", ""]
    body = []
    for m in methods:
        sub = df[df["method"] == m]
        total = int(sub["prompt_tokens"].fillna(0).sum() + sub["completion_tokens"].fillna(0).sum())
        body.append([f"**{_name(m)}**", _mean(sub["prompt_tokens"]), _mean(sub["completion_tokens"]),
                     f"{total:,}", _num(sub["retrieval_ms"].median()), _mean(sub["retrieval_ms"]),
                     _mean(sub["generation_ms"]), _mean(sub["total_ms"])])
    lines += _md(["Method", "Prompt tok", "Completion tok", "Total tok (all questions)",
                  "Retrieval ms (median)", "Retrieval ms (mean)", "Generation ms", "Total ms"], body)

    una = df[df["answer_kind"] == "not_in_data"]
    lines += ["## 5. Refusals, status and failure kinds", ""]
    body = [[f"**{_name(m)}**", _frac(una[una["method"] == m]["unanswerable_correct"]),
             _frac(ans[ans["method"] == m]["false_refusal"])] for m in methods]
    lines += _md(["Method", "Unanswerable: correctly refused", "Answerable: refused anyway"], body)
    body = []
    for m in methods:
        sub = df[df["method"] == m]
        st = sub[sub["status"] != "ok"]["status"].value_counts()
        fl = sub[sub["failure"] != ""]["failure"].value_counts()
        body.append([f"**{_name(m)}**", ", ".join(f"{k} {int(x)}" for k, x in st.items()) or "all ok",
                     ", ".join(f"{k} {int(x)}" for k, x in fl.items()) or "none"])
    lines += _md(["Method", "Non-ok status", "Wrong answers by kind"], body, right_from=3)
    lines += ["*retrieval miss*: not every gold row reached the LLM; *generation error*: the rows were "
              "there and the answer is still wrong; *format error*: the reply broke the JSON format; "
              "*context overflow*: the provider refused the prompt as too large. For a method that "
              "filters by scheme, a retrieval miss is refined to *filter_miss* (the question's own scheme "
              "was not found) or *filter_wrong* (a scheme the gold rows do not use was searched) — "
              "R4.4.", ""]
    flt = df[df["filter_miss"].notna()]
    if not flt.empty:
        body = []
        for m in [x for x in methods if x in set(flt["method"])]:
            s = flt[flt["method"] == m]
            body.append([f"**{_name(m)}**", len(s), int(s["filter_miss"].sum()),
                         int(s["filter_wrong"].sum()),
                         _pct(s[s["answer_kind"] != "not_in_data"]["gold_row_recall"].mean()),
                         _pct(s["correct"].mean())])
        lines += _md(["Method", "Rows", "filter_miss", "filter_wrong", "context gold-row recall",
                      "accuracy"], body, right_from=2)

    lines += ["## 6. Failure examples", "",
              "Up to three wrong answers per method, different kinds first.", ""]
    for m in methods:
        lines += [f"### {_name(m)}", ""]
        ex = failure_examples(df, m)
        if not ex:
            lines += ["No wrong answers.", ""]
            continue
        for r in ex:
            recall = ("" if pd.isna(r["gold_row_recall"])
                      else f", context gold-row recall {r['gold_row_recall']:.0%}")
            lines += [f"- **{r['qid']}** ({r['type']}) · *{r['failure']}*{recall}  ",
                      f"  Q: {_short(r['question'], 200)}  ",
                      f"  Gold: {_short(r['gold_value'], 160)}{' ' + r['unit'] if r['unit'] else ''}  ",
                      f"  Given: {_given(r)}"]
        lines.append("")

    lines += ["## 7. What the run cost", "",
              "Tokens only: prices are not kept in this repo (RD11). One row per paid run, from "
              f"[`{SPEND_FILE}`]({SPEND_FILE}).", ""]
    if spend:
        body = [[str(r.get("at_ist", ""))[:16].replace("T", " "), r.get("phase", ""),
                 r.get("questions", ""), r.get("calls", ""), r.get("cached", ""), r.get("paid_calls", ""),
                 f"{int(r.get('prompt_tokens') or 0):,}", f"{int(r.get('completion_tokens') or 0):,}",
                 f"{int(r.get('total_tokens') or 0):,}", f"{int(r.get('est_total_tokens') or 0):,}",
                 f"{int(r.get('max_tokens') or 0):,}", r.get("stopped") or "–"] for r in spend]
        lines += _md(["At (IST)", "Phase", "Questions", "Calls", "Cached", "Paid calls", "Prompt tok",
                      "Completion tok", "Total tok", "Estimated tok", "Cap", "Stopped"], body,
                     right_from=3)
        last = spend[-1]
        est, got = int(last.get("est_total_tokens") or 0), int(last.get("total_tokens") or 0)
        if est:
            lines += [f"The last run used {got:,} tokens against an estimate of {est:,} "
                      f"({got / est:.0%} of it): the estimate assumes every uncached call is paid at the "
                      "predicted prompt size, and answers that came from the cache during the run made "
                      "it cheaper.", ""]
    else:
        lines += ["No spend log yet.", ""]
    return "\n".join(lines).rstrip() + "\n"


def write_stage_b_report(results_dir: Path, test_set: str = "test"):
    """results.csv → summary.md + retrieval_report.xlsx; returns the summary path and the verdict."""
    from src.retrieval.excel_report import EXCEL_FILE, write_excel
    from src.retrieval.offline import OFFLINE_FILE
    from src.retrieval.verdict import verdict as compute_verdict

    df, manifest = load_results(results_dir)
    offline_path = results_dir / OFFLINE_FILE
    offline = None
    if offline_path.is_file():
        off = load_offline(offline_path)
        offline = off[off["set"] == test_set]
    try:
        v = compute_verdict(df, offline, manifest.get("retrieval_methods"))
    except ValueError:                      # no rows to rank, or nothing answered yet
        v = None
    path = results_dir / STAGE_B_SUMMARY_FILE
    path.write_text(stage_b_summary_md(df, manifest, v, offline, read_spend(results_dir)),
                    encoding="utf-8", newline="\n")
    excel = results_dir / EXCEL_FILE
    if v is not None:
        write_excel(df, manifest, v, offline, excel)
    elif excel.exists():
        excel.unlink()                      # never leave a verdict from older results next to new ones
    return path, v
