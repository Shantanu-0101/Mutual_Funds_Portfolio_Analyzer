# Retrieval Method Benchmark: Implementation Plan

| | |
|---|---|
| Status | Draft v1, waiting for review (Phase R0) |
| Date | 23 Nov 2026 |
| Built from | [`SPEC_RETRIEVAL.md`](SPEC_RETRIEVAL.md) v0.2 (decisions RD1–RD12 accepted, §13) |
| How to read it | One section per phase, in build order. Each phase lists its tasks, files, tests, the command that proves it works, the commit and branch, and a **STOP** point where I wait for your OK. `FR-Rx.y`, `RDx` and `Mx` refer to the retrieval spec. |

---

## How every phase ends

Same rule as the chunking project:

1. Run `.venv\Scripts\python.exe -m pytest` (all tests, old and new).
2. Run the phase's proof command on the real data and look at the output.
3. Write a 3–5 line summary: what was built, what the real data showed, anything surprising.
4. Commit on the phase branch with only your git identity (no `Co-Authored-By` line), push, and hand over a prefilled compare link into `main` (`gh` is not logged in).
5. **STOP** and wait for your OK before the next phase.

Anything the spec did not foresee: stop and ask, never work around it quietly. **No Grok call** before R4, and in R4 only after an estimate and your yes (spec §9.2).

---

## Before R1: merge order

| # | Step | Who |
|---|---|---|
| 0.1 | Merge the `phase-7-final` pull request into `main` (spec §0 step 2). On 23 Nov 2026 `origin/main` was still at PR #14, without it. | you |
| 0.2 | Merge the R0 pull request (branch `retrieval-spec`: spec v0.2 + this plan). It is built on `phase-7-final`, so its diff gets small once 0.1 is merged. | you |
| 0.3 | Each later phase branches from the updated `main`. | me |

---

## Facts checked in R0 (so later phases need not re-derive them)

- **Data:** Sep 2026 has 104 schemes, 5,646 holdings; `parents_hierarchical.parquet` has 333 parents with `source_rows`, so a gold row maps to its gold section (parent id `hierarchical:<date>:<scheme>:p<n>`) by a lookup, no re-chunking needed.
- **The 28 original questions use 13 schemes** (ADVG, BBIF, BSL95F, BSLCBF, BSLEQTY, BSLFEF, BSLMTP, BSLNMF, BSLTA1, BTOP100, MIDCAP, PLUS, PURE). They are test-only, so these 13 schemes are test-only too; the other 91 are split between dev and test-new (FR-R1.5). 43 of the 104 schemes have debt-like sections, enough for debt questions in both sets.
- **LLM cache** (`data/cache/llm/`) is keyed by provider + model + exact messages, and `--fresh` skipped reads but still wrote. So M1 on the 28 originals should be served from the cache if retrieval is unchanged (RD7).
- **Packages:** `sentence-transformers` 6.2.0 (has `CrossEncoder`), `chromadb` 1.5.9, `torch` 2.15.0 CPU. No reranker model on disk yet (RD4 download happens in R2). BM25 is written by hand (RD3): no new package so far.
- **Runner limits to handle:** `Question` rejects unknown keys; `setup_fingerprint` hashes **one** questions file; `failure_label` knows no `filter_miss` / `filter_wrong`. Each is dealt with below.

---

## Phase R1: Questions → `dev.yaml`, `test_new.yaml`, gold sections, manual check

Branch `retrieval-r1-questions`. Grok cost: none.

### Design

- Templates in `src/retrieval/questions/templates.yaml`: one entry per template with its `type`, `gold_fn`, `answer_kind`/`unit`, and 2–3 phrasings with slots (`{scheme}`, `{instrument}`, `{industry}`, `{rating}`, `{n}`, `{scheme_b}`, month always written out) (FR-R1.3, R1.4).
- `generate.py` picks slot values from `holdings.parquet` (Sep 2026) with seed 42, computes gold with the **existing** `src/eval/gold.py` functions, and drops a candidate if gold raises `GoldError` or has 0 gold rows (answerable types).
- Scheme split first, then questions: the 13 original schemes go to test; the remaining 91 are shuffled (seed 42) and split ~40 % dev / ~60 % test-new, stratified so both sides have equity, debt and hybrid schemes. Cross-scheme questions draw both schemes from the same side (FR-R1.5).
- Short names: about one in three questions uses the name without "ADITYA BIRLA SUN LIFE" (or "the Flexi Cap fund" style); the choice is recorded per question.
- Extra per-question info (template id, phrasing number, short-name flag, gold sections) goes in a new optional `tags:` key on `Question` (default empty), so the 28 original questions load unchanged.
- IDs: `D001…` (dev), `T001…` (test-new); the originals keep `Q01…Q28`.

### Tasks

| # | Task | Spec |
|---|---|---|
| R1.1 | `Question.tags` (optional dict) in `src/eval/questions.py`; loader accepts it; old file still loads | — |
| R1.2 | `templates.yaml`: lookup, aggregation, debt, cross_scheme, unanswerable; 2–3 phrasings each | FR-R1.2, R1.3 |
| R1.3 | `generate.py`: scheme split, slot filling, gold, short names, seed 42; writes `dev.yaml` (~40) and `test_new.yaml` (~60) | FR-R1.1, R1.4, R1.5 |
| R1.4 | Gold sections per question (gold rows → parent ids via `parents_hierarchical.parquet`), stored in `tags.gold_sections` | FR-R1.7 |
| R1.5 | `test` set = `questions.yaml` + `test_new.yaml`, loaded by one helper; a combined hash of both files for fingerprints | FR-R2.3 |
| R1.6 | Manual check: 10 test-new questions (seed 42) with gold and raw Excel cell references → `results/retrieval/manual_check.md`, reusing `src/eval/manual_check.py` | FR-R1.6 |
| R1.7 | `python -m src.retrieval questions` (CLI entry, `__main__.py` started here) | §7 |

### Tests (`tests/retrieval/test_questions.py`)

Fixed seed gives a byte-identical file; dev and test share no scheme; every question names its month; every answerable question has ≥ 1 gold row and ≥ 1 gold section; type mix close to SPEC §6.6; about 1/3 short names; generator never writes a gold value by hand (all through `gold.compute`). Synthetic holdings fixture (`synthetic_*`).

**Proof:** `python -m src.retrieval questions` → counts per set × type, short-name share, and the scheme split printed; `manual_check.md` written.
**Commit:** `retrieval r1: question generator, dev/test sets, gold sections`. **STOP: you do the manual check of 10 (FR-R1.6) before R2.**

---

## Phase R2: Retrieval methods M1–M7 and scheme extraction

Branch `retrieval-r2-methods`. Grok cost: none. One download: `BAAI/bge-reranker-base` (~1.1 GB, yes given in RD4).

### Design

- `base.py`: `RetrievalMethod` with `name`, `retrieve(question, k) -> MethodResult` (ranked `Retrieved` children, `latency_ms`, `debug`), and a registry `METHODS[name] -> factory(settings, shared)`.
- `shared` = one `ChildCorpus`, loaded once: every Sep 2026 child of the `hierarchical` collection with id, text, metadata and stored embedding (`collection.get(include=[documents, metadatas, embeddings])`). BM25, MMR and the scheme filter all work off it; dense still queries Chroma so M1 matches today's results exactly.
- Methods return the top **20** (FR-R2.2); the pipeline uses the first 5.
- Reranker scores are cached on disk (`<paths.cache>/rerank.sqlite`, key: model + revision, question hash, child id) (spec §9.3).
- Scheme extraction (`scheme_filter.py`) follows spec §5.1 exactly; it reads the question text and `schemes.parquet` only, never `params`.
- Round robin split for 2+ schemes: take each scheme's ranked list in turn until 5 (or 20) are picked; a scheme with too few rows gives its share to the others.
- `src/rag/pipeline.py` and `retrieve.py`: `RagPipeline.answer(..., method=None)`. `None` = today's dense call, so the app and old tests are unchanged. A method's children go through the same `swap_for_parents`.

### Tasks

| # | Task | Spec |
|---|---|---|
| R2.1 | `base.py`, `ChildCorpus`, registry | §5 |
| R2.2 | M1 `dense.py` (wraps `Retriever`) | M1 |
| R2.3 | M2 `bm25.py`: tokenizer + Okapi BM25, own code (RD3) | M2 |
| R2.4 | M3 `hybrid.py`: RRF (constant 60), candidate depth setting | M3 |
| R2.5 | M4/M5 `rerank.py`: `CrossEncoder` wrapper with disk cache and a stub-able scorer | M4, M5 |
| R2.6 | M7 `mmr.py` on stored child embeddings, λ setting | M7 |
| R2.7 | M6 `scheme_filter.py`: name variants, exact then fuzzy (`difflib`), longest-match rule, round robin; `debug.schemes_found` | M6, §5.1 |
| R2.8 | `combo.py`: M8 as a composition (filter → any ranker); its exact recipe is declared in R3 | M8 |
| R2.9 | Pipeline hook (`method=` argument), default unchanged | §7 |
| R2.10 | `config.yaml`: `retrieval_benchmark:` block (method defaults, reranker name, grids) and `budget:` block (prices `null`, RD11) | §7, §9.2 |
| R2.11 | Download the reranker; record name + revision | RD4 |

### Tests (`tests/retrieval/`)

As spec §10 for: each method (exactly k, ranked, no duplicates, no-overlap question, deterministic), BM25 (keeps "AAA", "PSU", numbers; hand-computed order on a small corpus), RRF (hand-computed fused ranks; one-list doc still ranks), MMR (λ = 1 equals dense order; λ = 0 picks diverse rows), scheme extraction (full, short, former name, code, two schemes, none, the four look-alike bank funds, `and`/`&`/case variants, never reads `params`), round robin (2 and 3 schemes; scheme with too few rows), pipeline default = today's dense (old `test_rag.py` still passes). Reranker tests use a stub scorer; no test downloads a model.

**Proof:** `python -m src.retrieval offline --sample Q01` (or a small `demo` subcommand) prints the 5 children and their schemes for one question through every method, plus the scheme-filter debug for the look-alike bank questions.
**Also:** open the Streamlit app pages once (spec §12 risk: pipeline change).
**Commit:** `retrieval r2: methods M1-M7, scheme extraction, pipeline hook`. **STOP.**

---

## Phase R3: Stage A (offline, free) → leaderboard, shortlist, Stage B estimate

Branch `retrieval-r3-offline`. Grok cost: none.

### Order inside the phase (two stops)

1. **Dev.** Run every method and every grid value (§5 last column) on dev. Pick each setting by mean `section_recall@5` (ties as §6.5), write the chosen values with the date into `config.yaml`. From the dev results, declare **M8** (filter yes/no + ranker) in `config.yaml` and in `offline_summary.md`. **STOP 1:** you see the dev choices and the M8 recipe before any test score is computed.
2. **Test.** One run of all methods M1–M8 with the chosen settings on the test set (88). Leaderboard, per-type table, recall@k curves, bootstrap intervals vs M1 (10,000 resamples, seed 42), shortlist = top 2 + M1 (RD6). Then the Stage B estimate.

### Tasks

| # | Task | Spec |
|---|---|---|
| R3.1 | `offline.py`: run (set, method, question) → top-20 children, scores, schemes, latency (after model load), filter debug | FR-R2.1, R2.2, R2.4 |
| R3.2 | Metrics: `hit@k`, `row_recall@k`, `mrr@10`, `section_recall@k`, `scheme_recall@k` for k = 1, 3, 5, 10, 20; `context_gold_row_recall` and `context_tokens` after parent swap; answerable questions only | §6.4 |
| R3.3 | Dev grid search and choice; `config.yaml` updated with date | FR-R2.3 |
| R3.4 | M8 declared from dev only | M8 |
| R3.5 | `offline.csv`, `offline_summary.md` (leaderboard, per type, recall@k table, dev settings, bootstrap, results on the 28 hand-written questions separately), `recall_by_method.png` | §6.6, §12 |
| R3.6 | Shortlist computed by code (§6.5 ranking) | FR-R3.1, RD6 |
| R3.7 | `estimate.py`: calls, cache hits (by building the real prompts and checking the cache key, no call), prompt tokens = real retrieved context + ~680 overhead, completion 460; tokens only (RD11) | FR-R9.1 |

### Tests

Metrics on hand-made cases (`section_recall` with duplicate parents, `mrr` with no hit, unanswerable excluded); bootstrap deterministic with seed; estimator token sums and cache hits counted as free; shortlist rule with a tie.

**Proof:** `python -m src.retrieval offline --set dev`, then `--set test`, then `python -m src.retrieval estimate --methods <shortlist> --set test` → printed table: calls, cached, prompt and completion tokens for the smoke run (3 × 3) and the full run (3 × 88).
**Commit:** `retrieval r3: offline leaderboard, shortlist, stage B estimate`. **STOP 2: you approve (or change) the R4 budget.**

---

## Phase R4: Stage B (paid) → `results/retrieval/results.csv`

Branch `retrieval-r4-grok`. Grok cost: **yes, two separate approvals**.

### Tasks

| # | Task | Spec |
|---|---|---|
| R4.1 | `run.py`: wraps `src/eval/runner.run_eval` with one answerer per shortlisted method (`RagPipeline.answer(text, "hierarchical", method=m)`), output to `results/retrieval/`; columns of `results.csv` plus `retrieval_method` and filter debug | FR-R3.1 |
| R4.2 | Fingerprint covers config, method settings, reranker revision and the combined test-file hash; a mismatching resume stops (`ResumeMismatch`) | §9.1 |
| R4.3 | `--max-tokens N` hard cap: stop cleanly before the call that would pass N; row stays pending | FR-R9.2 |
| R4.4 | `failure_label` extended with `filter_miss` / `filter_wrong` (only for methods with a filter; old labels unchanged) | §6.4 |
| R4.5 | Cache reuse on (no `--fresh`), cached rows flagged; Groq-fallback rows stay pending and are re-asked on Grok | FR-R3.3, R3.4, RD7 |
| R4.6 | `spend_log.csv` row after each paid run: IST time, phase, calls, cached, prompt / completion / reasoning tokens, estimate vs actual | FR-R9.3 |
| R4.7 | Manifest: model, date, a fixed check question; compare M1's fresh vs cached answers on the smoke run | §12 |

### Order (each step waits for your yes)

1. Tests for the cap, fingerprint and spend log (no Grok).
2. **Smoke run:** 3 test questions (one lookup, one aggregation, one cross_scheme) × 3 methods, with the estimate shown first and `--max-tokens` set from it. Report actual vs estimate. **STOP.**
3. **Full run:** 3 × 88, estimate shown, your yes, cap set. Resume until 0 pending rows; never re-run the grid to fix a few rows (FR-R9.4). Report actual vs estimate. **STOP.**

**Proof:** `results.csv` with 0 pending rows; `spend_log.csv` rows; actual vs estimate in the phase summary.
**Commit:** `retrieval r4: stage B grok run`.

---

## Phase R5: Verdict, report, docs

Branch `retrieval-r5-report`. Grok cost: none.

| # | Task | Spec |
|---|---|---|
| R5.1 | `report.py`: computed verdict (§6.5 rule, like `recommend.py`), per-type best method, bootstrap note in `summary.md` (RD8) | §6.5 |
| R5.2 | `summary.md`: verdict, accuracy by method × type, retrieval vs context tokens, tokens and latency, 3 failure examples per method | §6.6 |
| R5.3 | `excel_report.py` → `retrieval_report.xlsx` in the chunking Excel's style, without the "not distinguishable" note (RD8) | §6.6 |
| R5.4 | "Retrieval" section in `docs/DESIGN.md` and README with real numbers and limits | §11 |
| R5.5 | Optional, each only with your yes: `dense_large` (RD10), HyDE / multi-query (RD9), Streamlit picker (RD12) | §13 |

**Proof:** `python -m src.retrieval report` writes `summary.md` and the Excel; the verdict line printed.
**Commit:** `retrieval r5: verdict, summary, excel, docs`. **STOP.** If you hand-edit the Excel later, I diff it cell by cell before any regeneration and carry the edits into the code.

---

## Risks to the plan

| Risk | What I do |
|---|---|
| Template questions are too easy (every method near 100 % on dev) | Stop at R3 STOP 1 and propose harder templates (more short names, look-alike schemes) before touching test. |
| Scheme split leaves a type with too few questions on one side | Generator prints the per-set type mix; I stop and ask instead of mixing schemes across sets. |
| Reranker too slow on CPU for 88 + 40 questions × several grid values | Scores are cached, so each (question, child) pair is scored once; latency is reported, not hidden. |
| M1 gives different children than the chunking run (Chroma/HNSW change) | Checked in R2 proof on the 28 originals: the same parent sections, in the same order, as the recorded `retrieved` column of `results/results.csv` (which holds parent ids). If not, I stop and report before any estimate relies on cache hits. |
| Velona model changed since 20 Nov | Smoke run compares fresh vs cached M1 answers (R4.7). |
