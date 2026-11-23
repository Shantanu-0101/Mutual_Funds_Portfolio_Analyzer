# Retrieval Method Benchmark: Specification

| | |
|---|---|
| Status | v0.1 draft, 22 Nov 2026. Decisions RD1–RD12 (§13) are **proposed, not yet accepted**. |
| Builds on | The finished chunking project: [`SPEC.md`](SPEC.md), [`DESIGN.md`](DESIGN.md), [`results/summary.md`](../results/summary.md). Same repo, same data, same parser, same gold functions. |
| Next document | `docs/IMPLEMENTATION_PLAN_RETRIEVAL.md` (written from this spec after the decisions are accepted) |
| Purpose | Fix *what* we build and *how we judge it*. Not the order of work. |
| Audience | Me (intern), my supervisor, and a fresh Claude Code chat that picks this up |

---

## 0. How to start (for a new Claude Code chat in this folder)

1. Read this file, then `docs/SPEC.md` (§3 data, §6.3–6.6), `docs/DESIGN.md` and `results/summary.md`. Do not re-derive what they already settle.
2. `phase-7-final` must be merged into `main` first. Start each phase on its own branch (`retrieval-r1-questions`, …) and open a PR into `main`. Commits carry only the user's git identity: **no `Co-Authored-By` trailer**. The `gh` CLI is not logged in, so hand over a prefilled compare link instead of opening the PR yourself.
3. Run Python with `.venv\Scripts\python.exe` (system Python lacks xlrd).
4. **Grok is paid.** Never call it without first showing the cost estimate (§9.2) and getting a clear yes. Free work (offline retrieval metrics, tests) needs no approval.
5. Begin with Phase R0: go through the decisions in §13 with the user, then write the implementation plan. **STOP** after every phase (§8).

---

## 1. Problem and goal

The chunking project found the best way to **cut** the table (`hierarchical`: search single rows, send their whole section to the LLM). It used one fixed way to **find** chunks: embed the question with `bge-small` and take the 5 nearest rows by cosine (dense search).

Dense search is one of several common retrieval methods. This project holds the chunking fixed and compares **retrieval methods**, to say which one gets the right rows to the LLM best, for which question types, and at what cost.

**The main deliverable is a benchmark with a verdict**, like the chunking project: a computed recommendation, `summary.md` and an Excel report. A router that picks a method per question is **not** part of this project (§1.3). The per-type results are written so a later router project can use them.

### 1.1 Research questions

1. Which retrieval method gets the needed rows (and their sections) into the top 5 most often, overall and per question type?
2. Does better retrieval turn into more correct answers? Or is generation the limit? (In the chunking run, `hierarchical` already had 96% gold-row recall; its wrong answers were mostly generation errors. See RQ2 risk, §12.)
3. What does each method cost in retrieval latency, context tokens and LLM tokens?
4. Are the differences bigger than the noise of a small question set?

### 1.2 Success means

- Every number comes from a real, reproducible run. Retrieval metrics are computed by code from gold rows, never judged by an LLM.
- The "best" rule (§6.5) is fixed **before** any results are seen.
- Grok spending stays within the budget agreed at each approval step, and the real spend is logged (§9.2).
- Weaknesses and ties are reported, not tuned away.

### 1.3 Out of scope

- **A router / selector model** (a later project; this one only produces its input data).
- Re-doing chunking, parsing or gold logic. They are reused as they are.
- **LLM-based query rewriting** (HyDE, multi-query, LLM self-query) in the main run: each one adds Grok calls per question. Optional only (RD9).
- Fine-tuning any model. Hosted embedding APIs.
- More months, a second AMC, the scheme filter as a *user* choice (that is the app's existing feature, not a retrieval method).

---

## 2. Glossary (additions to SPEC.md §2)

| Term | Meaning |
|---|---|
| Retrieval method | The rule that turns a question into a ranked list of chunks. Here: which rows of the index come back, and in what order. |
| Child / parent | `hierarchical` chunking: a *child* is one holding row (what is searched); a *parent* is that row's whole section in its scheme (what the LLM reads). 333 parents in Sep 2026. |
| Dense search | Embed question and chunks as vectors, rank by cosine similarity. The current method. |
| BM25 | Classic keyword search: ranks chunks that share rare words with the question. No model, no vectors. |
| Hybrid | Run dense and BM25, merge the two ranked lists. |
| RRF | Reciprocal Rank Fusion: merged score = Σ 1 / (60 + rank in each list). Needs no score tuning. |
| Reranker (cross-encoder) | A second, slower model that reads the question and one chunk *together* and scores the pair. Used on the top ~50 candidates only. |
| MMR | Maximal Marginal Relevance: picks results that are relevant **and** not near-duplicates of each other. |
| Scheme filter (self-query, rule-based) | Find scheme names in the question text by matching against the scheme list, then search only inside those schemes. |
| Candidate depth | How many results a first stage passes to a second stage (reranker, MMR, fusion). |
| Dev set / test set | Dev: questions used to pick settings (e.g. MMR λ). Test: questions used only for the final scores. Never mixed. |
| Ceiling effect | When the current method already finds almost everything, a better method has little room to show it. |

---

## 3. What is fixed (the controlled variables)

Only the retrieval method changes. Everything else is the recorded chunking run's setup:

| Fixed | Value | Source |
|---|---|---|
| Data | `holdings.parquet`, month **30 Sep 2026** only (104 schemes, 5,646 holdings) | SPEC D3 |
| Chunker | `hierarchical`: search children (rows), send unique parents (whole sections) | DESIGN §2 verdict; RD1 |
| Index | Existing Chroma collection for `hierarchical` children, `BAAI/bge-small-en-v1.5`, cosine | SPEC §6.4 |
| Final k | **5 children** per question, then parent swap (≤ 5 sections to the LLM) | config `retrieval.top_k` |
| Prompt, JSON answer format, citation rules | Unchanged `src/rag/prompt.py` | FR-3.5, 3.6 |
| LLM | Grok `x-ai/grok-4.20` via Velona, temperature 0, `max_output_tokens` 2000; Groq fallback rows re-run as before | config `llm` |
| Metrics, scoring, failure labels | Unchanged `src/eval/metrics.py`, plus the retrieval metrics in §6.4 | SPEC §6.6 |

Because the chunker, k and parent swap are fixed, any difference in the context the LLM sees comes from **which 5 children** were picked.

---

## 4. System overview

```
holdings.parquet ──(existing)──> hierarchical children in Chroma + parents_hierarchical.parquet
                                         │
question ──> [Retriever: one of M1..M7] ─┴─> top 5 children ──> parent swap ──> context
                    │                                                              │
                    │                                   (Stage B, paid) prompt ──> Grok ──> answer ──> score
                    │
                    └──(Stage A, free)──> retrieval metrics vs gold rows/sections ──> offline leaderboard
```

Two stages, on purpose:

- **Stage A (free):** every method on every question (dev + test), retrieval metrics only. No LLM. Can be run as often as needed.
- **Stage B (paid):** only a **shortlist** of methods (§6.5) on the test set, end to end through Grok. Each run needs a cost estimate and a yes.

---

## 5. Retrieval methods

All methods implement one interface and return **exactly 5 children** (ranked) from the `hierarchical` child collection, plus `latency_ms` and a per-method `debug` dict (e.g. which schemes the filter found).

```
class RetrievalMethod:
    name: str
    def retrieve(question: str, k: int) -> list[Retrieved]   # Retrieved as in src/rag/retrieve.py
```

The parent swap (`swap_for_parents`) is applied **after** the method, the same way for all.

| ID | Method | How it works | Why it is in the benchmark (hypothesis) | Settings tuned on dev |
|---|---|---|---|---|
| M1 | `dense` | Current method: embed question, top 5 by cosine. | Reference point. Its Grok answers for the 28 original questions are already in the LLM cache. | – |
| M2 | `bm25` | Okapi BM25 over the child texts. Tokenizer: lowercase, split on non-alphanumerics, keep numbers and short tokens like "psu", "aaa". | Questions name exact schemes, instruments, industries and ratings; keyword search may match these better than a small embedding model. | k1, b (default 1.5, 0.75) |
| M3 | `hybrid_rrf` | Top 50 from M1 and top 50 from M2, merged by RRF (constant 60), take top 5. | Usually beats either alone; tests whether that holds on table rows. | candidate depth {20, 50, 100} |
| M4 | `dense_rerank` | Top 50 from M1, re-scored by a cross-encoder (RD4), take top 5. | Reads question and row together; should fix "right words, wrong scheme" mistakes. Costs CPU time. | candidate depth {20, 50} |
| M5 | `hybrid_rerank` | Top 50 from M3, re-scored by the same cross-encoder, take top 5. | Best recall going into the reranker. | candidate depth {20, 50} |
| M6 | `scheme_filter` | Find scheme names in the question (§5.1); search dense **only inside those schemes**. One scheme: top 5 in it. Two or more: split 5 across them (round robin by rank). None found: plain M1. | The chunking run showed most misses pick rows of the **wrong scheme**. A rule-based filter is free and explainable. | match threshold |
| M7 | `mmr` | Top 50 from M1, then MMR on the child embeddings, take top 5. | Aggregation and cross-scheme questions need *different* rows, not 5 near-copies. | λ {0.3, 0.5, 0.7} |
| M8 | `best_combo` | **Declared after Stage A on dev, before Stage A on test**: the scheme filter (if it helps) combined with the best ranker (e.g. filter + hybrid + rerank). | The real-world pick is often a combination. Declaring it before seeing test scores keeps it honest. | inherited |
| opt | `dense_large` | Dense with a larger embedding model (e.g. `bge-base`). Needs re-embedding the children (free, local, slower) and a model download. | Separates "better search rule" from "better embedding model". RD10. | – |
| opt | `hyde` / `multi_query` | An LLM writes a fake answer row / 3 rephrasings; search with those. | Common in RAG; **costs one extra LLM call per question**. RD9. | – |

### 5.1 Scheme-name extraction (M6, M8)

- **Input:** the question text and the scheme list for the month (`schemes.parquet`). **Never** the question's gold `params`: that would leak the answer into retrieval.
- **Name variants per scheme:** the full name; the name without the leading "ADITYA BIRLA SUN LIFE"; the "FORMERLY KNOWN AS …" name, where present (11 of the 104 Sep 2026 names carry one, e.g. the Aggressive Hybrid Fund); and the scheme code. Matching is case-insensitive after normalising `&`/`and`, punctuation and spaces.
- **Rule:** longest exact match first; if none, a fuzzy match (stdlib `difflib`, threshold tuned on dev) on word n-grams. A shorter name that is part of a longer matched name (e.g. "BANKING" inside "BANKING & PSU DEBT FUND") does not count separately.
- Checked on real Sep 2026 data: the 104 short names (without the AMC prefix) are all unique. Look-alike pairs to test: `BANKING & PSU DEBT FUND` vs `BANKING AND FINANCIAL SERVICES FUND` vs `NIFTY BANK ETF` vs `BSE TOP 10 BANKS ETF`.
- **Output** goes into `debug` and into the results, so a wrong filter shows up as its own failure kind: `filter_miss` (the right scheme was not found) or `filter_wrong` (a wrong scheme was found).

---

## 6. Evaluation

### 6.1 Question sets

| Set | Use | Contents |
|---|---|---|
| `dev` | Choosing settings (§5 last column), declaring M8 | ~40 new questions from templates |
| `test` | All reported scores | The **28 original questions** (`src/eval/questions.yaml`, unchanged) **+ ~60 new** template questions (RD5) |

- **FR-R1.1** New questions are generated by code from `holdings.parquet` (Sep 2026) with a fixed seed, using the **existing** `gold.py` functions (`holding_pct`, `industry_total`, `top_n_share`, `holding_count`, `section_total`, `rating_share`, `instruments_by_rating`, `overlap_count`, `which_holds_more`, `not_in_data`). Gold stays code-computed (SPEC FR-5.2). New `gold_fn`s are added only if a needed type is missing.
- **FR-R1.2** Same type mix as SPEC §6.6 (lookup, aggregation, debt, cross_scheme, unanswerable), so per-type results compare with the chunking run.
- **FR-R1.3** Each template has **2–3 phrasings**, and about a third of new questions use a **short scheme name** ("the Flexi Cap fund") instead of the full name. Otherwise every question copies exact names, which flatters BM25 and the filter (§12).
- **FR-R1.4** Every question still names its month (one correct answer).
- **FR-R1.5** A question's schemes, instruments and sections must not repeat between dev and test (split by scheme, not by question), so settings tuned on dev do not memorise test answers.
- **FR-R1.6** Manual check: 10 new test questions (fixed seed) exported with gold and raw Excel cell references, as SPEC FR-5.4, to `results/retrieval/manual_check.md`.
- **FR-R1.7** Gold sections: for each question, the set of parent ids (scheme × section) that hold its gold rows, computed by code.

### 6.2 Stage A: offline retrieval (free)

- **FR-R2.1** Every method (M1–M8, plus opt ones if accepted) on every dev and test question. No LLM call.
- **FR-R2.2** For each (method, question) record the ranked top 20 children (ids, scores, schemes), so metrics at k = 1, 3, 5, 10, 20 come from one run. The final pipeline uses k = 5.
- **FR-R2.3** Settings are chosen on **dev only**, by the primary metric (§6.5), from the small grids in §5. Chosen values are written to `config.yaml` with the date. Test scores are computed once, after that.
- **FR-R2.4** Retrieval latency per question, measured after models are loaded (as `src/rag/retrieve.py` does today). Reported as median and 90th percentile.

### 6.3 Stage B: end to end (paid)

- **FR-R3.1** Only the shortlisted methods (§6.5), on the **test** set, through the unchanged RAG pipeline (parent swap → prompt → Grok → JSON → score).
- **FR-R3.2** First a **smoke run**: 3 test questions (one lookup, one aggregation, one cross_scheme) × shortlist. Estimate shown first. Then the full run, with its own estimate and yes.
- **FR-R3.3** Answers are reused from the LLM cache when the prompt is byte-identical (same provider, model and prompt hash). This happens when two methods send the same sections in the same order, and for M1 on the 28 original questions. Cached rows are flagged `cached = 1`. A cached Grok answer from the same model counts as valid (RD7).
- **FR-R3.4** Rows answered by the Groq fallback stay *pending* and are re-asked on Grok, as in the chunking run.

### 6.4 Metrics

Answerable questions only for retrieval metrics (unanswerable has no gold rows). `C_k` = the top-k children; `P(C_k)` = their unique parents.

| Metric | Definition | Why |
|---|---|---|
| `hit@k` | 1 if any gold row is in `C_k`. | Did search find anything relevant? |
| `row_recall@k` | \|gold rows ∩ `C_k`\| / \|gold rows\| | Child-level recall. Capped for aggregations (a 30-row industry cannot fit in 5), so reported but not ranked on. |
| `mrr@10` | 1 / rank of the first gold row in the top 10; 0 if none. | Rewards putting the right row first. |
| **`section_recall@k`** | \|gold sections ∩ `P(C_k)`\| / \|gold sections\| | **Primary.** With parent swap, a section reaches the LLM if *any* of its rows is retrieved. This is what decides the context. |
| `scheme_recall@k` | Share of the question's gold schemes present among `C_k`'s schemes. | Separates "wrong scheme" from "right scheme, wrong section". |
| `context_gold_row_recall` | Existing `gold_row_recall` after parent swap. | Same as the chunking run, so the numbers line up. |
| `context_tokens` | Tokens of the parents sent (embedding tokenizer). | Big sections inflate recall; shown next to it (SPEC fairness note). |
| `retrieval_ms` | As FR-R2.4. | Reranker cost. |
| End to end (Stage B) | `correct`, `false_refusal`, failure kind (retrieval miss / generation error / format error / context overflow / filter_miss / filter_wrong), prompt and completion tokens. | Unchanged from SPEC §6.6. |

### 6.5 Shortlist and the "best" rule (fixed now)

- **Offline ranking (Stage A, test set):** mean `section_recall@5`; ties broken by `hit@5`, then `mrr@10`, then lower median `retrieval_ms`.
- **Shortlist for Stage B:** the top 2 methods by that ranking **plus M1 `dense`** (the reference) (RD6). If M1 is in the top 2, the next one goes in.
- **Final verdict (Stage B):** most correct answers on the test set; ties broken by `context_gold_row_recall`, then fewer prompt tokens per question, then lower retrieval latency. Same shape as the chunking rule R2.
- **Per question type:** best method named per type with the same rule (input for a future router).
- **Noise:** paired bootstrap (10,000 resamples, seed 42) of the per-question difference between the winner and M1, for both `section_recall@5` and `correct`. The report states the 95% interval. If it includes 0, it says plainly: "not distinguishable from dense on this question set" (RD8).
- The verdict is **computed** by code (like `src/eval/recommend.py`), not written by hand.

### 6.6 Outputs (all under `results/retrieval/`, existing `results/` files untouched)

| File | Contents |
|---|---|
| `offline.csv` | One row per (set, method, question): top-20 child ids and scores, all §6.4 retrieval metrics at k = 1, 3, 5, 10, 20, filter debug, latency. |
| `offline_summary.md` | Leaderboard (test), per-type table, recall@k curve table, dev settings chosen, bootstrap intervals. |
| `recall_by_method.png` | `section_recall@5` by method and question type. |
| `results.csv` | Stage B, same columns as `results/results.csv` plus `retrieval_method` and filter debug. |
| `summary.md` | Verdict, accuracy by method × type, retrieval vs context tokens, tokens and latency, 3 failure examples per method. |
| `retrieval_report.xlsx` | Same style as `results/chunking_report.xlsx` (the user hand-edits that file; diff before regenerating, carry edits into code). |
| `spend_log.csv` | One row per paid run (§9.2). |
| `run_manifest.json` | As SPEC FR-5.6, plus method settings and question-set hashes. |
| `manual_check.md` | FR-R1.6. |

---

## 7. Repo layout (additions only)

```
config.yaml                    + retrieval_benchmark: and budget: blocks (§9.2)
src/retrieval/                 new package
  base.py                      RetrievalMethod interface, registry
  dense.py  bm25.py  hybrid.py  rerank.py  mmr.py  scheme_filter.py  combo.py
  questions/                   generate.py, templates.yaml, dev.yaml, test_new.yaml
  offline.py                   Stage A runner + metrics
  estimate.py                  token and cost estimate (§9.2)
  run.py                       Stage B: wraps src/eval/runner with a chosen method
  report.py  excel_report.py   reuse src/eval/report.py and recommend.py where possible
  __main__.py                  python -m src.retrieval {questions|offline|estimate|run|report}
tests/retrieval/               unit tests (§10)
results/retrieval/             outputs (§6.6)
docs/SPEC_RETRIEVAL.md         this file
docs/IMPLEMENTATION_PLAN_RETRIEVAL.md
```

`src/rag/pipeline.py` gets one small change: accept a retrieval method instead of always calling dense search, defaulting to today's behaviour so the app and the old tests are unchanged.

---

## 8. Working process

Same as the chunking project (SPEC §8): phase by phase; after each phase run `pytest` (all tests), run the phase's proof command on real data, write a 3–5 line summary, commit on the phase branch, push, give the PR link, and **STOP** for approval. Ask before any decision not covered here. Never invent data.

Proposed phases (the implementation plan fills in tasks):

| Phase | What | Grok cost |
|---|---|---|
| R0 | Accept decisions (§13), write `IMPLEMENTATION_PLAN_RETRIEVAL.md` | none |
| R1 | Question generator, dev + test sets, gold sections, manual check | none |
| R2 | Retrieval interface, M1–M7, scheme extraction, unit tests | none (reranker model download needs a yes, RD4) |
| R3 | Stage A: tune on dev, declare M8, leaderboard on test, shortlist, **cost estimate for R4** | none |
| R4 | Stage B: smoke run, then full run | **paid, two approvals** |
| R5 | Verdict, `summary.md`, Excel, a "Retrieval" section in DESIGN.md and README | none |

---

## 9. Non-functional requirements

### 9.1 Reproducibility
- Fixed seeds (question generation, bootstrap, any tie-breaks), temperature 0, pinned versions (any new package goes into `requirements.txt` and `requirements-lock.txt`).
- Embedding and reranker scores are deterministic on CPU. The reranker model name and revision go into the manifest.
- A resumed Stage B run must use the same config, method settings and question file, or it stops (as `ResumeMismatch` does today).

### 9.2 Cost and Grok budget

**Rule:** no Grok call without (1) an estimate printed by `python -m src.retrieval estimate`, (2) the user's yes in chat, (3) a hard cap passed to the runner.

- **FR-R9.1 Estimator.** For a planned run (methods × questions) it prints: number of calls, how many are already in the LLM cache (free), and expected prompt and completion tokens for the rest. Prompt tokens = context tokens of the actual retrieved parents (known from Stage A, no call needed) + the fixed prompt overhead measured from the recorded run (about 680 tokens: `hierarchical` mean prompt 7,119 minus mean context 6,435; includes Velona's ~180 extra). Completion = 460 per call (recorded `hierarchical` mean 457). If `budget.price_per_million_input/output` are set in config, it also prints the cost; otherwise tokens only.
- **FR-R9.2 Hard cap.** `run --max-tokens N` stops cleanly (row left pending, resumable) before a call that would push the running total over N. Default: no paid run without the flag.
- **FR-R9.3 Spend log.** After every paid run, append to `results/retrieval/spend_log.csv`: date-time (IST), phase, calls made, cached calls, prompt, completion and reasoning tokens (from the provider), estimate vs actual.
- **FR-R9.4** Never re-run a whole grid to fix a few rows: resume, or re-run only the affected rows.

**Rough numbers** (from the recorded run, to be redone by the estimator on real retrievals):

| Run | Calls | Tokens (approx.) |
|---|---|---|
| Reference: the whole chunking run (7 methods × 28) | 196 | 0.96 M |
| Smoke: 3 methods × 3 questions | 9 | ~70 k |
| Full: 3 methods × 88 test questions | 264 | ~2.0 M before cache hits |
| Full, smaller: 3 methods × 60 test questions | 180 | ~1.4 M |
| M1 on the 28 original questions | 28 | ~0 (already cached, if the prompt is unchanged) |

The Velona price per million tokens is not recorded anywhere in the repo. RD11 asks for it.

### 9.3 Local resources
- The reranker runs on the laptop CPU. Up to 50 pairs per question: expect hundreds of milliseconds to a few seconds per question. Stage A runs it once per question per method and caches scores on disk (key: model, question hash, child id).
- BM25 index: built in memory from the ~5,600 child texts at start-up (seconds). Not stored in git.
- Chroma and cache stay inside OneDrive unless lock errors appear (move via `paths.*` only then).

### 9.4 Secrets
Unchanged: keys only in `.env`; nothing secret in logs, results, the spend log or docs.

---

## 10. Testing

Unit tests never call a real LLM, never download models, and never need the real files (synthetic fixtures named `synthetic_*`). Reranker tests use a stub scorer.

| Area | What is tested |
|---|---|
| Each method | Returns exactly k children, ranked, no duplicates; handles a question with no keyword overlap; deterministic |
| BM25 | Tokenizer keeps "AAA", "PSU", numbers; known small corpus gives the hand-computed order |
| RRF / hybrid | Hand-computed fused ranks; a doc in only one list still ranks |
| MMR | λ = 1 equals plain dense order; λ = 0 picks diverse rows |
| Scheme extraction | full name, short name, former name, scheme code, two schemes, none, look-alike bank funds, lowercase/`and`/`&` variants; never reads gold params |
| Round robin split | 5 across 2 and 3 schemes; a scheme with fewer than its share |
| Metrics | `section_recall` with duplicate parents; `mrr` with no hit; unanswerable excluded |
| Question generator | Fixed seed gives the same file; dev/test share no scheme; every question names its month; gold computed |
| Estimator and cap | Token sums; cache hits counted as free; the cap stops before the call that would exceed it |
| Pipeline change | Default method = today's dense behaviour (existing RAG tests still pass) |

---

## 11. Phase acceptance criteria

| Phase | Done when |
|---|---|
| R0 | Decisions accepted and written into §13; implementation plan reviewed. |
| R1 | dev and test files written by code; every gold computed; manual check of 10 done by the user; no dev/test overlap. |
| R2 | M1–M7 and scheme extraction implemented and tested; a sample question returns 5 children through every method. |
| R3 | `offline.csv`, `offline_summary.md` and chart from the test set; settings chosen on dev and recorded; M8 declared before test scores; shortlist named; Stage B estimate shown. |
| R4 | Smoke run approved and done; full run approved and done; 0 pending rows; spend log written; actual vs estimate reported. |
| R5 | Computed verdict in `summary.md` and Excel; DESIGN.md and README have a retrieval section with real numbers and limits. |

---

## 12. Risks

| Risk | Effect | Mitigation |
|---|---|---|
| **Ceiling effect** | Dense + `hierarchical` already reached 96% gold-row recall on the 28 questions; most wrong answers were generation errors. End-to-end accuracy may barely move whatever the method. | Rank on retrieval metrics (Stage A), where differences show. Add harder questions (short names, look-alike schemes, cross-scheme). Report "retrieval is not the bottleneck here" as a valid finding. |
| Template questions copy exact names | Flatters BM25 and the scheme filter | 2–3 phrasings per template, ~1/3 short names (FR-R1.3); report results for the 28 hand-written questions separately too. |
| Tuning on the test set | Inflated scores | Dev/test split by scheme; settings and M8 fixed before test scores (FR-R2.3). |
| Small test set | Differences are noise | Paired bootstrap intervals; counts beside percentages; say "not distinguishable" when it is (§6.5). |
| Grok cost overrun | Credits wasted | Two-stage design; estimator, hard cap, spend log, cache reuse; smoke run first (§9.2). |
| Groq fallback cannot fit 7k-token prompts (8k tokens/minute) | Rows stay pending during a Velona outage | Rows are resumable; wait and resume rather than accept fallback answers. |
| Velona model is not a pinned snapshot | The model could change between the chunking run and this one | Record model, date and a fixed check question in the manifest; compare M1's fresh answers with the cached ones on the smoke run. |
| Reranker size and speed | Large download, slow CPU | RD4 picks the model; scores cached; latency reported, not hidden. |
| Scheme filter picks a wrong scheme | Confident wrong context | Separate `filter_wrong` / `filter_miss` labels; fallback to unfiltered when no match. |
| Changing `src/rag/pipeline.py` breaks the app | Old pages fail | Default keeps today's behaviour; full `pytest`; open the app pages once after R2. |

---

## 13. Decisions (proposed, to settle in Phase R0)

| # | Decision | Recommendation |
|---|---|---|
| RD1 | Which chunker to hold fixed? | **`hierarchical`** (the winner; the verdict then applies to the pipeline actually used). Alternative: `row_wise` (retrieval matters more there, ~1,200 instead of ~7,600 tokens per call, so ~6× cheaper on Grok; but aggregations fail regardless of retrieval). |
| RD2 | Which methods are in the main benchmark? | **M1–M8** as in §5. |
| RD3 | BM25: own small implementation or the `rank-bm25` package? | **Own** (about 50 lines, unit-tested, no new dependency). |
| RD4 | Reranker model | **`BAAI/bge-reranker-base`** (same family as the embedder; roughly 1 GB download, slower). Lighter option: `cross-encoder/ms-marco-MiniLM-L-6-v2` (under 100 MB, faster, English web-search trained). The download needs a yes. |
| RD5 | Test set size | **~60 new + 28 original = ~88** for Stage A (free). For Stage B, use all 88 or a fixed random 60 (cheaper, see §9.2). |
| RD6 | Shortlist size for Stage B | **Top 2 + M1 dense = 3 methods.** |
| RD7 | Reuse cached Grok answers in the recorded run? | **Yes** when the prompt is byte-identical and the model is the same; flagged `cached`. (The chunking run used `--fresh`; here reuse saves credits.) |
| RD8 | Show the bootstrap "not distinguishable" note in the verdict and Excel? | **Yes** in `summary.md`; in the Excel only if you want it (the chunking Excel had the tie caveat removed by hand). |
| RD9 | LLM query rewriting (HyDE / multi-query)? | **Not in the main run.** Optional later, and if done, with a free model, or with Grok only after a separate estimate. |
| RD10 | Larger embedding model (`dense_large`)? | **Optional** after R3, only if dense-based methods are close at the top. |
| RD11 | Velona price per million input / output tokens | **You fill it in** from the Velona dashboard, so the estimator prints money, not just tokens. |
| RD12 | Streamlit: add a retrieval-method picker to the Compare page? | **Optional**, after R5. |

---

## 14. Traceability

| Need | Section |
|---|---|
| Hold chunking fixed, vary retrieval | 3, 5 |
| Methods and why each exists | 5 |
| Questions with code-computed gold, no leakage | 6.1, 5.1 |
| Free retrieval metrics vs paid end-to-end | 4, 6.2, 6.3 |
| "Best" fixed in advance, noise reported | 6.5 |
| Spend Grok credits wisely | 9.2 |
| Outputs like the chunking project | 6.6 |
| Router later, not now | 1.3 |
