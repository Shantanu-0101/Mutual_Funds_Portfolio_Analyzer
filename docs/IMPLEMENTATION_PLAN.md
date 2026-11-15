# Mutual Fund Portfolio Analyzer: Implementation Plan

| | |
|---|---|
| Status | Draft v1, waiting for review |
| Date | 9 Nov 2026 |
| Built from | `docs/SPEC.md` v0.3 (decisions D1–D11 accepted) |
| How to read it | One section per phase, in build order. Each phase lists its tasks, files, tests, the command that proves it works, the commit, and a **STOP** point where I wait for your OK. `FR-x.y` and `Dx` refer to the spec. |

---

## How every phase ends

The brief's working rule, applied the same way each time:

1. Run `pytest` (all tests, not only the new ones).
2. Run the phase's "proof" command on the real data and look at the output.
3. Write a 3–5 line summary: what was built, what the real data showed, anything surprising.
4. Commit on a phase branch (e.g. `phase-1-parser`) with a message like `phase 1: parser + validation report`, push, and open a pull request into `main` (changed 9 Nov 2026: one branch + PR per phase).
5. **STOP** and wait for your OK before the next phase.

If a phase turns up something the spec did not foresee (e.g. a new layout quirk), I stop and ask instead of quietly working around it.

---

## Phase S: Setup (before Phase 0)

Small, but everything later depends on it.

| # | Task | Notes |
|---|---|---|
| S.1 | Install Python 3.11 (D7) | You run the installer (python.org or `winget install Python.Python.3.11`); I don't install system software. Check with `py -3.11 --version`. |
| S.2 | Create a virtualenv `.venv` with 3.11 | `py -3.11 -m venv .venv` |
| S.3 | `requirements.txt` with pinned versions | pandas, xlrd, pyarrow, pyyaml, python-dotenv, sentence-transformers, chromadb, groq, google-genai, streamlit, matplotlib, pytest, xlwt (only to write synthetic `.xls` test fixtures). Exact versions pinned after a clean install. |
| S.4 | `git init`, `.gitignore` (D11) | Ignore `.venv/`, `.env`, `data/raw/`, `data/processed/`, `data/chroma/`, `data/cache/`, `__pycache__/`. `results/` **is** committed (it is a deliverable). |
| S.5 | Move AMFI files out of `data/raw/` (D2) | To `data/other/amfi/` (also git-ignored). Moving, not deleting. |
| S.6 | `config.yaml`, `.env.example`, empty package folders with `__init__.py` | Config exactly as spec §5.1. |
| S.7 | `src/config.py`: load `config.yaml` + `.env` once, expose a typed settings object | Every module reads settings from here, so a run is fully described by one file. |

**OneDrive warning.** The project lives in a OneDrive folder. OneDrive sync can lock files while ChromaDB or the caches write to them, which shows up as random "permission denied" errors. Option: keep `data/chroma` and `data/cache` outside OneDrive via config paths (e.g. `C:\mfpa_data\`). I'll ask when we reach Phase 3 if errors appear; the config already allows it.

**Proof:** `python -c "import xlrd, chromadb, sentence_transformers"` runs inside `.venv`; `pytest` runs (0 tests).
**Commit:** `setup: venv, config, gitignore`. **STOP.**

---

## Phase 0: Inspect the data → `docs/DATA_NOTES.md`

Most of the inspection was done while writing the spec (§3). This phase turns it into a reusable script and fills the gaps.

| # | Task | Spec |
|---|---|---|
| 0.1 | `src/parsing/inspect_raw.py`: for every portfolio file and sheet, print title block, header row and columns, all section and sub-heading rows, Total / GRAND TOTAL rows, the end of the portfolio block, text values in numeric columns | FR-0.1, 0.2 |
| 0.2 | Per sheet: sum of value rows vs `GRAND TOTAL (AUM)` (lakhs and %) | FR-0.3 |
| 0.3 | List main headings vs sub-headings, and draft the section → asset_class mapping table | D6 |
| 0.4 | Find how government securities, T-bills, TREPS and InvITs are labelled in the rating column | FR-0.2 |
| 0.5 | Scheme list per month (added / dropped), and the ESG sheets | §3.3 |
| 0.6 | Write `docs/DATA_NOTES.md` | FR-0.4 |

No parser and no tests yet; this is read-only exploration.

**Proof:** `python -m src.parsing.inspect_raw > results/inspect_raw.txt`, plus DATA_NOTES.md.
**Commit:** `phase 0: data notes`. **STOP: you review DATA_NOTES.md before any parser code (FR-0.4).**

---

## Phase 1: Parser → `holdings.parquet`, `totals.parquet`, `parse_report.md`

### Design

The parser is a small **row classifier + state machine** walking each sheet top to bottom:

```
title block (rows 1–3) → header (found by text) → portfolio block → end marker → skipped tail
inside the block, each row is one of:
  HEADING      text in instrument column, no value       → sets section / subsection
  HOLDING      has market value (with or without ISIN)   → holdings table
  TOTAL        "Total" / "GRAND TOTAL (AUM)"              → totals table
  BLANK        empty                                      → ignored (counted)
  UNKNOWN      anything else                              → listed in report (FR-1.6)
```

Why a state machine instead of `pd.read_excel(header=3)`: section headings are rows *inside* the table, so the meaning of a row depends on the rows above it. pandas would read them as half-empty data rows and lose the real Excel row numbers we need for `source_row`.

### Tasks

| # | Task | File | Spec |
|---|---|---|---|
| 1.1 | Read a sheet with xlrd into a list of raw rows keeping 1-based row numbers | `src/parsing/reader.py` | FR-1.1 |
| 1.2 | Title block: scheme code, scheme name, description, as-on date | `src/parsing/sheet_parser.py` | — |
| 1.3 | Find header row by text; map columns by header name (handles ESG sheets) | same | FR-1.2 |
| 1.4 | Row classifier + section/subsection state | same | FR-1.4 |
| 1.5 | Value rules: fraction → percent; `$0.00%` → computed from value / grand total + flag; YTM/YTC → percent | `src/parsing/values.py` | FR-1.3 |
| 1.6 | End-of-block detection (GRAND TOTAL, else first footnote / `Notes:`); tail skipped as one block | same as 1.4 | FR-1.5 |
| 1.7 | Section → asset_class mapping as a visible dict | `src/parsing/mapping.py` | D6 |
| 1.8 | Validation: % sum vs 100, value sum vs grand total, each Total vs rows above, duplicate ISINs, null %, missing grand totals | `src/parsing/validate.py` | FR-1.7 |
| 1.9 | Report writer → `results/parse_report.md` (summary table first, details after) | `src/parsing/report.py` | FR-1.7 |
| 1.10 | Entry point: all four files → `holdings.parquet`, `totals.parquet`, `schemes.parquet` | `src/parsing/__main__.py` | FR-1.8 |

### Tests (`tests/test_parser.py`)

A script `tests/fixtures/make_synthetic.py` writes small `.xls` files with **the real ABSL layout and made-up values**: `synthetic_equity.xls` (headings, sub-headings, TREPS, net receivable, `$0.00%` cell, Total, GRAND TOTAL, notes block), `synthetic_debt_esg.xls` (ESG columns, missing GRAND TOTAL), `synthetic_merged.xls` (one merged cell, to prove FR-1.9 fails loudly).

Tested: title fields, header-by-text, section tracking, Totals excluded from holdings, TREPS kept with null ISIN, fraction → percent, `$0.00%` rule, exact `source_row` values, tail skipped as a block, UNKNOWN rows reported, merged-cell assertion. Plus `test_real_smoke.py`: parses the real files if present, else skipped.

**Proof:** `python -m src.parsing` → parquet files + `results/parse_report.md`. I read the report and highlight every scheme whose % sum is off by more than 0.05.
**Commit:** `phase 1: parser + validation report`. **STOP.**

---

## Phase 2: Chunkers

### Design

```
src/chunking/
  base.py            Chunk dataclass, Chunker base class, shared table-text formatter, token counter, stats logger
  fixed_size.py      row_wise.py      header_window.py
  scheme_level.py    section_aware.py hierarchical.py
  __init__.py        REGISTRY = {"fixed_size": FixedSizeChunker, ...}
```

Shared pieces live in `base.py` so chunkers differ **only** in how they group rows (spec §6.3). The token counter uses the bge-small tokenizer, so "tokens" means what the embedding model actually sees.

Two tricky parts, decided up front:
- **fixed_size and `source_rows` (FR-2.0):** build the flattened text while recording each row's character range; split by tokens using the tokenizer's character offsets; a chunk's `source_rows` are all rows whose range overlaps the chunk's range.
- **hierarchical:** children = the same text as row_wise (so embeddings come from the cache); parents = section_aware chunks; each child stores `parent_id`. Only children go into Chroma; parents are saved to `data/processed/parents_hierarchical.parquet` and looked up at query time.

### Tasks

| # | Task | Spec |
|---|---|---|
| 2.1 | `base.py`: Chunk, base class, formatter (percent units, header line, Scheme/As on/Section lines), token count, truncation flag, stats | FR-2.0, 2.1 |
| 2.2 | The six chunkers, one file each, each with a docstring explaining its hypothesis | §6.3 table |
| 2.3 | `python -m src.chunking --month 2026-09-30`: runs all chunkers, writes `results/chunk_stats.md` (chunks, avg/max tokens, truncated count per chunker) and a few sample chunks per chunker to `results/chunk_samples.md` | FR-2.1 |

### Tests (`tests/test_chunkers.py`, parametrised over all six)

On a synthetic DataFrame: every holding row appears in at least one chunk's `source_rows`; no chunk claims a row it does not contain; IDs are stable across runs; truncation flag correct at the 512 boundary; header_window repeats the header; section_aware never mixes sections; hierarchical parents are deduplicated and every child's `parent_id` exists; fixed_size overlap behaves as configured.

**Proof:** `results/chunk_stats.md` for September. Expected (to confirm): row_wise ≈ 5,400 chunks; scheme_level ≈ 104 chunks, most truncated.
**Commit:** `phase 2: six chunkers + stats`. **STOP.**

---

## Phase 3: LLM wrapper, index, RAG

### Tasks

| # | Task | File | Spec |
|---|---|---|---|
| 3.1 | LLM interface `generate(messages, json=True) -> LLMResult(text, prompt_tokens, completion_tokens, latency_ms)`; providers `groq`, `gemini`, `mock`; chosen by `LLM_PROVIDER`; temperature 0; retry with backoff on rate limits | `src/llm.py` | §5 |
| 3.2 | Disk cache for LLM responses keyed by (provider, model, prompt hash); `--fresh` flag bypasses it | `src/llm.py` | §9.1 |
| 3.3 | Pick the Groq model: check the live model list and free-tier limits, put the choice and the reason in config (D8). **I'll tell you the choice before using it.** | `config.yaml` | D8 |
| 3.4 | Embedder with disk cache keyed by (model, text hash) | `src/index/embedder.py` | FR-3.2 |
| 3.5 | Chroma store: one collection per chunker, cosine, identical settings; metadata stored per chunk (`source_rows` serialised as JSON since Chroma metadata must be flat) | `src/index/store.py` | FR-3.1 |
| 3.6 | `python -m src.index --month 2026-09-30 --chunkers all` | `src/index/__main__.py` | — |
| 3.7 | Retriever: top_k; hierarchical swaps children for unique parents; optional scheme/month filter | `src/rag/retrieve.py` | FR-3.3, 3.4 |
| 3.8 | Prompt (answer only from context, say when insufficient, cite rows, JSON schema) | `src/rag/prompt.py` | FR-3.5, 3.6 |
| 3.9 | `answer(question, chunker) -> RagResult` with chunks, context rows, tokens, both latencies; malformed JSON → format failure, not repaired | `src/rag/pipeline.py` | FR-3.6, 3.7 |

### Tests

`mock` provider returns fixed JSON; no network. Tested: provider selection by env var, cache hit/miss, JSON parse success and format-failure path, hierarchical parent swap and dedupe, retriever returns `top_k`, context rows = union of `source_rows`. Chroma tested on a tiny temporary collection with a fake embedder (fast, no model download).

**Proof:** `python -m src.rag "What % of AUM does the Flexi Cap Fund hold in ICICI Bank as on 30 Sep 2026?" --chunker all` prints, for each chunker, the answer, retrieved chunk ids and tokens. One real Groq call per chunker (7 calls).
**Commit:** `phase 3: llm wrapper, chroma index, rag pipeline`. **STOP.**

---

## Phase 4: Text-to-pandas baseline

### Design

The runner is a **separate Python process** (`python -I src/baseline/sandbox.py`), so a timeout can kill it cleanly on Windows. *(Built 13 Nov 2026: run as a script, not `-m`, because `-I` keeps the project folder off `sys.path`; the file therefore imports only the standard library and pandas. The child loads the data, says READY, and only then does the timeout clock start. It runs in an empty temp folder with API keys stripped from its environment.)* The parent process sends the generated code over stdin; the child loads the DataFrame itself *before* running the code, then runs it with only `df`, `pd` and a short list of safe builtins in scope. An AST check runs first and blocks imports, `open/exec/eval/compile/__import__`, dunder access and pandas I/O. DESIGN.md will state what this does **not** protect against (§9.3).

### Tasks

| # | Task | File | Spec |
|---|---|---|---|
| 4.1 | Schema description for the prompt: columns, types, example values, scheme names, sections, months | `src/baseline/schema.py` | FR-4.1 |
| 4.2 | Prompt + code extraction from the LLM reply | `src/baseline/text_to_pandas.py` | FR-4.1 |
| 4.3 | AST checker | `src/baseline/guard.py` | FR-4.2 |
| 4.4 | Sandbox process + timeout | `src/baseline/sandbox.py` | FR-4.2 |
| 4.5 | Convert `result` (number, Series, DataFrame, list) to the shared answer object; failures reported, never retried with hints | `src/baseline/pipeline.py` | FR-4.3, 4.4 |

### Tests (`tests/test_baseline.py`)

Blocked: `import os`, `open(...)`, `__class__` tricks, `df.to_csv(...)`, `pd.read_excel(...)`. Killed: `while True: pass` within the timeout. Allowed: a groupby-sum returns the right number. Result conversion for each result type.

**Proof:** `python -m src.baseline "Total % of AUM in Banks in the Flexi Cap Fund as on 30 Sep 2026?"` prints the generated code, the result, and the gold value from the parquet for comparison.
**Commit:** `phase 4: text-to-pandas baseline + restricted runner`. **STOP.**

---

## Phase 5: Evaluation

### Tasks

| # | Task | File | Spec |
|---|---|---|---|
| 5.1 | Gold functions: `holding_pct`, `holding_value`, `industry_total`, `top_n_share`, `holding_count`, `rating_share` (with rating normaliser), `instruments_by_rating`, `section_total`, `overlap_count`, `which_holds_more`, `not_in_data`. Each returns (answer, gold row keys). | `src/eval/gold.py` | FR-5.2, 5.3 |
| 5.2 | Write the 28 questions from real September names (7 lookup, 7 aggregation, 5 debt, 5 cross_scheme, 4 unanswerable). **I show you the list before running anything on it.** | `src/eval/questions.yaml` | FR-5.1 |
| 5.3 | Manual check export: 10 random questions (seed 42) with gold answers and raw cell references | `src/eval/manual_check.py` → `results/manual_check.md` | FR-5.4 |
| 5.4 | Metrics exactly as spec §6.6 | `src/eval/metrics.py` | §6.6 |
| 5.5 | Runner: every method × every question, same settings; resumable (skips rows already in `results.csv`); writes `run_manifest.json`. Records `provider`/`model` per row; a row answered by the fallback provider (`fallback_reason` set) is a different model, so it is flagged and re-run before the report (or the run uses `LLM_FALLBACK=none`) | `src/eval/runner.py` | FR-5.5, 5.6 |
| 5.6 | Report: accuracy by method × question type, retrieval table next to context tokens, tokens and latency table, 3 failure examples per method labelled retrieval miss / generation error / format error, bar chart | `src/eval/report.py` | §6.6 outputs |

### Order inside the phase (two stops)

1. Build 5.1–5.4 and their tests. Produce `questions.yaml` and `manual_check.md`.
   **STOP A: you check the 10 manual-check questions against the raw Excel.** If any gold answer is wrong, the bug is in the parser or gold code; it gets fixed before any LLM run, because otherwise every result would be built on wrong answers.
2. Build 5.5–5.6, then the full run: `python -m src.eval run --fresh` then `python -m src.eval report`. About 28 × 7 ≈ 200 LLM calls; runs in the background and resumes if rate-limited.
   **STOP B: you read `results/summary.md`.**

### Tests (`tests/test_metrics.py`, `tests/test_gold.py`)

Metrics: tolerance edges (just inside / just outside 1%), the 0.01-point floor for small values, zero gold, list matching and Jaccard, refusal detection, false refusals, recall. Gold: each function on the synthetic DataFrame with a hand-computed answer; rating normaliser (`[ICRA]AAA` = `ICRA AAA`).

*Built 13 Nov 2026 (5a):* `python -m src.eval gold` writes `results/gold_answers.md` (all 28); `python -m src.eval manual-check` writes `results/manual_check.md`. The manual sample is drawn from the 24 answerable questions (nothing to check on unanswerable ones). Gold sums were cross-checked against the file's own Total rows (Q12–Q14, Q16).

*Stop A passed 14 Nov 2026:* you checked all 10 manual-check questions against the Excel; all OK (`results/manual_check.md`).

*Built 14 Nov 2026 (5b):* `src/eval/runner.py` and `src/eval/report.py`, tests in `tests/test_eval_run.py`. LLM for the run: xAI `grok-4.20-0309-non-reasoning` (your pick), Groq as fallback; rows the fallback answers are marked pending and re-asked on the main model, so the recorded results come from grok only. Rows that are rate-limited, provider-unavailable or hit a sandbox crash are also pending; `context_overflow` is a final, recorded failure (D9). A resumed run refuses to continue a `results.csv` started with another config, model or question file. Failure labels: *format error*, *context overflow*, *retrieval miss* (RAG answered but not every gold row was in the context), *generation error* (everything else).

*Free-tier run 14 Nov 2026:* the first grok run (all 7 methods) was valid but had 15 replies cut at 800 output tokens; the rerun at 2000 failed because xAI rejected the key. No paid key for now, so the recorded run uses Groq `openai/gpt-oss-120b` (free tier, 8,000 tokens/minute, 1,000 requests/day, and **200,000 tokens/day**, rolling 24 h; the last limit is not in the response headers and stopped the first pass at 107/140 answers) with Gemini as the fallback (inactive until its key is added). `scheme_level` and `hierarchical` are **not run** on the free tier (their prompts are above or near 8,000 tokens). Still to do with a paid key: `python -m src.eval run --fresh` with `provider: xai` for all 7 methods, then `report`.

**Commit:** `phase 5a: gold, questions, metrics` (after stop A) and `phase 5b: full evaluation run` (after stop B, with `results/` committed).

---

## Phase 5c: Recommendation and Excel report (added 14 Nov 2026)

From the supervisor's brief: for our ABSL dataset, name the best chunking method and say why, and deliver it as an Excel file. Decisions agreed 14 Nov 2026:

| # | Decision |
|---|---|
| R1 | Scope: our ABSL dataset (Sep 2026) only. User-uploaded data is later work, not part of this phase. |
| R2 | "Best" rule: highest overall accuracy; ties broken by gold-row recall, then by fewer tokens. Also name the best method per question type. |
| R3 | The pandas baseline is shown for comparison but is not ranked as a chunking method. |
| R4 | The "why" is written by code from the measured numbers (accuracy, recall, failure kinds, tokens), never by the LLM. |
| R5 | Built now on the partial free-tier results; regenerated by `python -m src.eval report` after the paid grok run. A method that was not run, or has pending rows, is flagged in the verdict, never silently ranked. |

| # | Task | File |
|---|---|---|
| 5c.1 | Ranking and reasons from `results.csv` | `src/eval/recommend.py` |
| 5c.2 | `results/chunking_report.xlsx`: Recommendation, Ranking, Accuracy by type, Retrieval & cost, Per question, Run info; written by `python -m src.eval report` together with `summary.md` | `src/eval/excel_report.py`, called from `src/eval/report.py` (`openpyxl==3.1.5` added) |
| 5c.3 | Tests: ranking, tie-breaks, baseline excluded, not-run methods flagged | `tests/test_recommend.py` |

*Built 14 Nov 2026:* `summary.md` now opens with a Recommendation section, and the same verdict goes to `results/chunking_report.xlsx`. One rule added while building, under R5: a question whose answer is still pending for any ranked chunker is left out for **all** of them. In the free-tier run `section_aware`'s Q24–Q28 are rate-limited, so its 0% on unanswerable questions was not a real result; the ranking uses the 23 questions every chunker answered. Current (provisional) verdict: `fixed_size`, 12/23 vs `section_aware` 11/23, flagged as a small lead; `scheme_level` and `hierarchical` not run; baseline has no answers yet.

**Commit:** `phase 5c: recommendation + excel report`. **STOP.**

---

## Phase 6: Streamlit app

| # | Task | Spec |
|---|---|---|
| 6.1 | `app/streamlit_app.py` with three pages (Streamlit multipage: `app/pages/`) | §6.7 |
| 6.2 | Ask: sidebar month, scheme(s), chunker; answer, cited rows as a table, retrieved chunks in expanders, tokens and latency | FR-6.1 |
| 6.3 | Compare: one question through all chunkers + baseline, one column or card each | FR-6.2 |
| 6.4 | Results: tables from `results/summary.md` data (read from `results.csv`, not re-parsed from markdown) + the chart | FR-6.3 |
| 6.5 | Load indexes read-only, cached with `st.cache_resource`; never parse or index | FR-6.4 |
| 6.6 | Results page opens with the recommendation card (Phase 5c) and a download button for `chunking_report.xlsx` | Phase 5c |
| 6.7 | Ask and Compare use Groq until the paid grok key arrives; switching is one change in `config.yaml` | D8b |

UI logic is kept thin: pages call `src.rag.pipeline` and `src.baseline.pipeline`, which are already tested.

*Built 14 Nov 2026:* `app/streamlit_app.py` (navigation) + `app/pages/ask.py`, `compare.py`, `results.py`; shared Streamlit code in `app/common.py`; the table-building logic in `src/app_data.py` (no Streamlit import, tested in `tests/test_app.py`, which also runs the Results page on the committed `results/` with Streamlit's `AppTest`). Three changes outside the app:
- The scheme picker allows several schemes, so `where_filter` / `Retriever.retrieve` accept a list of scheme codes (Chroma `$in`); one code works as before. The evaluation still runs without filters (D4).
- Bug found by opening the real page: the embedding cache's SQLite connection was created on one thread and Streamlit runs each page run on another, which SQLite refuses. `VectorCache` now opens the connection with `check_same_thread=False` and serialises calls with a lock (test added).
- The month picker offers only months found in every Chroma collection (today September 2026). The baseline reads `data.eval_months` and ignores the scheme filter; the page says so when that applies.

Checked in the browser on Groq `openai/gpt-oss-120b` with "What % of AUM does Aditya Birla Sun Life Flexi Cap Fund hold in HDFC Bank Ltd.?": Ask (fixed_size) answered 3.91%, citing row 9 of sheet BSLEQTY (parquet: 3.9095). Compare: fixed_size, row_wise, header_window, section_aware, hierarchical and the baseline all gave 3.91; scheme_level failed with *context_overflow* (19,372 tokens requested, limit 8,000 per minute on the free tier), which the page explains. Results shows the provisional verdict (`fixed_size`), the caveats, the per-type table, the Excel download and all the `summary.md` tables.

**Proof:** `streamlit run app/streamlit_app.py`, then I open each page in the browser, ask one question on Ask and Compare, and take screenshots for you (verification by opening the real page, not only by running tests).
**Commit:** `phase 6: streamlit app`. **STOP.**

---

## Phase 7: Docs

| # | Task |
|---|---|
| 7.1 | `README.md`: setup (Python 3.11, venv, `.env`), which ABSL files to download and where to put them, the five commands, Findings section written from `results/summary.md` |
| 7.2 | `docs/DESIGN.md`: why each chunker exists, expected vs actual results, design choices with reasons, deviations from the brief (xlrd, % to AUM, no merged cells, one AMC), limits of the sandbox |
| 7.3 | Final check against the definition of done (below) |

**Commit:** `phase 7: readme and design doc`. **STOP: project done.**

---

## The five commands (definition of done)

```bash
python -m src.parsing                              # parse all files → data/processed + parse_report.md
python -m src.index --month 2026-09-30 --chunkers all
python -m src.eval run                             # add --fresh for the final recorded run
python -m src.eval report
streamlit run app/streamlit_app.py
```

Definition of done, checked at the end of Phase 7:
- [ ] One command each to parse, index, evaluate and launch the app.
- [ ] `pytest` passes: parser, every chunker, metrics, gold, baseline guard, LLM wrapper.
- [ ] `results/summary.md` produced by a real, recorded run (`run_manifest.json` present).
- [ ] `results/manual_check.md` checked by you.
- [ ] No API keys in git (`git log -p | findstr /i "gsk_ api_key"` finds nothing); `.env.example` present.

---

## Optional work (only after Phase 7, each needs your OK)

| Item | From |
|---|---|
| Second run with scheme/month filter on, to show how much it helps | D4 |
| All four months indexed + 3–4 cross_month questions | D3 |
| `llm_summary` chunker | D10 |
| Second AMC | D1 |

---

## Risks to the plan

| Risk | Where it bites | What I do |
|---|---|---|
| Python 3.11 not installed yet | Setup | You install it; everything else waits. |
| A layout quirk not seen so far | Phase 1 | Stop and ask; add a synthetic fixture for it. |
| Groq free-tier limits too low for scheme_level contexts | Phase 3 / 5 | Record as "context overflow" (D9); tell you the numbers; you decide whether to switch to Gemini or a paid tier. **Update 13 Nov 2026:** xAI (paid) becomes the main provider, Groq the fallback (D8b). |
| Gold answers wrong because of a parser bug | Phase 5 | Stop A: your manual check happens before any LLM run. |
| OneDrive locks Chroma/cache files | Phase 3 | Move those paths outside OneDrive via config. |
| First model download (~130 MB for bge-small) | Phase 3 | One-time; cached by sentence-transformers. |
