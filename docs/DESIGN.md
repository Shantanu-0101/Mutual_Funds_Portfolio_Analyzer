# Design

| | |
|---|---|
| Status | Chunking: final for the recorded run of 20 Nov 2026 (Phase 7, task 7.2). Retrieval (§7): final for the recorded run of 24 Nov 2026 (Phase R5). |
| Read with | [`SPEC.md`](SPEC.md) (what is built and how it is judged), [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) (order of work, decisions D1–D11), [`DATA_NOTES.md`](DATA_NOTES.md) (what the files contain); for §7 also [`SPEC_RETRIEVAL.md`](SPEC_RETRIEVAL.md) and [`IMPLEMENTATION_PLAN_RETRIEVAL.md`](IMPLEMENTATION_PLAN_RETRIEVAL.md) |
| Results | Chunking: [`results/summary.md`](../results/summary.md), [`results/chunking_report.xlsx`](../results/chunking_report.xlsx). Retrieval: [`results/retrieval/summary.md`](../results/retrieval/summary.md), [`results/retrieval/retrieval_report.xlsx`](../results/retrieval/retrieval_report.xlsx) |

This document explains **why** the system is built the way it is. Sections 1–6 cover the chunking experiment: why each chunker exists, what was expected of it and what actually happened, the main design choices, where the project departs from the brief, and the limits of the result. Section 7 covers the second experiment, which holds the chunker fixed and compares eight **retrieval** methods.

---

## 1. The pipeline in one picture

```
data/raw/*.xls ──parse──> holdings.parquet ──chunk──> 6 chunk sets ──embed──> Chroma (one collection per chunker)
                               │                                                   │
                               │                                  question ──retrieve top 5──> LLM ──> answer + cited rows
                               │
                               └──> pandas baseline: LLM writes code ──guard──> sandbox ──> answer
                                                                                     │
                     questions.yaml + gold functions (pandas over the same parquet) ─┴──> score ──> results.csv ──> report
```

Every method answers from the **same parsed table** (`holdings.parquet`). Every gold answer is computed in code from that same table. So the comparison measures only how each method gets rows in front of the LLM, not differences in parsing.

---

## 2. The chunkers: why, expected, actual

All six share one chunk object, one way of writing a row as text, one token counter (the embedding model's own tokenizer) and one truncation rule (`src/chunking/base.py`). They differ **only** in which rows go together. Each chunk records the holding rows it covers (`source_rows`). That is what makes it possible to measure retrieval separately from generation.

Numbers below are from the recorded run: Grok `x-ai/grok-4.20`, 28 questions, top_k 5. *Recall* is the share of the rows an answer needs that reached the LLM.

| Chunker | Why it exists | Expected | Actual | Recall |
| --- | --- | --- | --- | ---: |
| `fixed_size` | The naive reference: flatten the sheet, cut every 256 tokens | Worst: cuts rows in half, later chunks lose the scheme name and header | **Better than expected**: 3rd, 16/28. Every wrong answer is a retrieval miss | 58% |
| `row_wise` | One labelled chunk per holding, for precise lookups | Best on lookups, fails aggregations (top 5 rows cannot hold a whole industry) | **As expected**: 7/7 lookups at the lowest cost (about 1,000 prompt tokens), 0/7 aggregations | 51% |
| `header_window` | 10 rows per chunk with the header repeated: a middle ground | Some neighbours, never a cut row | **Weaker than expected**: 11/28, last place tied. Missed a plain lookup (Q02) | 65% |
| `scheme_level` | The whole scheme in one chunk: full context for totals | Weak retrieval, because 75% of chunks exceed the embedding's 512 tokens and it sees only the first ~10 holdings | **Retrieval far better than expected** (92% hit): the questions name the scheme, and the scheme name is at the start of every chunk. Tied 1st, 17/28. Most expensive: about 14,000 prompt tokens per question | 92% |
| `section_aware` | One chunk per section ("Equity", "Debt Instruments", …), as a person reads the sheet | Good for "how much debt" questions | **Not borne out**: 0/5 debt, 11/28. A likely cause: similar sections of many schemes compete for the 5 slots, and the right one often loses | 60% |
| `hierarchical` | Search single rows, answer from their whole section | Precise retrieval plus wide context, at a token cost | **As expected, and the winner**: tied 1st, 17/28, 100% hit rate, half the tokens of scheme_level, and the only chunker with a debt answer right | 96% |
| `baseline` (no chunking) | The LLM writes pandas code over the whole table | Should beat every chunker on aggregations | **Clearly so**: 28/28, including 7/7 aggregations against 3/7 for the best chunker | – |

### What the failures say

- **Small chunks fail at retrieval; big chunks fail at generation.**
  - The four small-chunk methods lose most answers because the needed rows never arrive.
  - scheme_level and hierarchical get 92–96% of the rows in, but then the LLM adds up dozens of rows and gets it slightly wrong. For example, Q08 "total % in Banks" came out 18.23 against the true 19.24.
  - Better chunking cannot fix that second kind. Arithmetic over many rows belongs in code, which is why the baseline wins.
- **The tie at the top is real.** scheme_level and hierarchical both get 17/28. The fixed rule picks hierarchical because more of the needed rows reached the LLM (96% against 92%). That rule was fixed on 14 Nov, before the Grok run (decision R2 in the plan, Phase 5c): most correct answers, then gold-row recall, then fewer tokens. hierarchical also needs half the tokens.
- **6 format errors** are replies that hit the 2,000-token output limit while listing their sources. They count as wrong: 2 each for scheme_level and hierarchical, 1 each for header_window and section_aware.

---

## 3. Main design choices

| Choice | Why |
| --- | --- |
| **Parse once into one clean table** (`src/parsing/`) | Ten parser rules (DATA_NOTES §12) handle the real files: header found by text, five fixed main headings, `$0.00%` cells and the unreliable Net Receivable % recomputed from value ÷ grand total, and every sheet's rows checked against its `GRAND TOTAL (AUM)`. All 417 sheets add up exactly. |
| **One month (30 Sep 2026) in the experiment** (D3) | Each question then has one clear source. October's new 1,000-row index schemes would have turned the comparison into a test of context limits. |
| **No scheme or month filter at retrieval** (D4) | Retrieval must find the scheme itself. That is the harder and more honest test. |
| **Same top_k (5) for every chunker, no context cap** (D9) | As the brief asks. A method that sends too much is recorded as a failure, not rescued. |
| **Local embeddings** (`BAAI/bge-small-en-v1.5`) with a disk cache | Free and reproducible on a laptop CPU. Its 512-token limit is part of what is being tested (truncation is recorded per chunk). |
| **The LLM answers in JSON** (answer, value, unit, items, sources, insufficient_context) | Answers can be scored by code, not by eye. Source rows are resolved in code from the chunk text, not trusted from the model. |
| **Temperature 0 and a response cache** | Runs are repeatable, and a resumed run never pays twice. The recorded run used `--fresh` (no cache) and every answer is stored with its provider and model. |
| **Paid Grok answers, free Groq is only a fallback** | Recorded results must come from one model. A row the fallback answered is flagged *pending* and asked again on Grok. Since 20 Nov a failing fallback also leaves the row pending, so an outage can never be recorded as a method's failure. |
| **Gold answers computed by code** (`src/eval/gold.py`), 10 checked by hand (`results/manual_check.md`) | A gold answer is exact and re-computable. The hand check guards against a wrong gold function. |
| **Numeric tolerance**: 1% relative or 0.01 percentage points (D5) | The sheets' own totals are rounded to 0.001%. |
| **Wrong answers labelled** *retrieval miss*, *generation error*, *format error* or *context overflow* | This answers research question 2 (did retrieval or generation fail?) row by row. |
| **The recommendation is computed, not written** (`src/eval/recommend.py`) | Every sentence in the verdict is built from the measured numbers by a fixed rule, so the report cannot overstate a result. |

---

## 4. Deviations from the brief

| Brief says | Done instead | Why |
| --- | --- | --- |
| openpyxl for Excel | **xlrd** for reading (openpyxl only writes the report) | The disclosure files are `.xls`, which openpyxl cannot read. |
| "% to NAV" | Filled from the files' **"% to AUM"** column | ABSL reports % to AUM. The meaning is documented wherever the value is shown. |
| Handle merged cells and multi-row headers | **Assert there are none inside the portfolio block** | The real files have 1,436 merged ranges, all in titles or below the grand total, none in the data block. Handling code for a case that never occurs would be untested. |
| Several fund houses | **One (ABSL)**, four months parsed, one evaluated | That is the data at hand (D1). A second AMC is listed as optional work. |
| A single LLM provider | **Grok** (`x-ai/grok-4.20`) for the recorded run, Groq as fallback; Gemini is written but untried, and a mock provider runs the tests | The first paid key was rejected, so the earlier partial run used Groq's free tier. That run could not fit scheme_level or hierarchical prompts (8,000 tokens per minute) and was replaced by the full Grok run. |

---

## 5. Limits of the sandbox (pandas baseline)

The baseline runs code that an LLM wrote, so it is checked and isolated (`src/baseline/guard.py`, `sandbox.py`):

- **Before it runs:** a static check rejects imports, `eval`/`exec`/`open` and similar names, anything starting with `_`, pandas I/O (`read_*`, most `to_*`), the pandas sub-modules that reach the OS, and `.eval()` / `.query()`.
- **While it runs:** it runs in a separate `python -I` process, in an empty temp folder, with reduced builtins and **no API keys in its environment**. It only gets a copy of the DataFrame and is killed after 10 seconds.
- **What this does not do:** Python cannot be fully sandboxed inside Python. A determined attacker who controlled the model's output might find a path the check misses, and memory use is not limited. That is acceptable here: the code comes from our own prompt and runs on public data on one laptop. It would **not** be acceptable for a public app or user-uploaded data, which would need a container or VM.

---

## 6. Limits of the result

- **Small question set:** 28 questions. A one-question gap is within noise, and the top two chunkers tie on correct answers.
- **One fund house, one month:** other AMCs lay out their sheets differently. The ranking may not carry over.
- **One LLM, one embedding model:** a model better at arithmetic would raise the big-context methods. A larger embedding window would help scheme_level retrieval.
- **No scheme filter:** with the scheme filter on (D4, optional), retrieval-bound methods like row_wise and section_aware would likely gain the most. The retrieval benchmark (§7) measured this for `hierarchical`: filtering by scheme lifts end-to-end accuracy from 65% to 74% and halves the context, so the expectation held.
- **Token counts include a fixed overhead:** the Grok endpoint adds about 180 prompt tokens to every call. This is the same for every method, so the ranking is unaffected.

**Optional next steps** (IMPLEMENTATION_PLAN, each needs a go-ahead):
- a second run with the scheme and month filter on
- all four months indexed, with cross-month questions
- the `llm_summary` chunker
- a second AMC

---

## 7. The retrieval benchmark (Phases R1–R5)

The chunking benchmark above held retrieval fixed (plain dense search, top 5) and varied the chunker.
This second experiment does the opposite: the chunker is fixed to the winner, `hierarchical`, and the
**way the five chunks are chosen** varies. Read with [`SPEC_RETRIEVAL.md`](SPEC_RETRIEVAL.md) and
[`IMPLEMENTATION_PLAN_RETRIEVAL.md`](IMPLEMENTATION_PLAN_RETRIEVAL.md); results in
[`results/retrieval/summary.md`](../results/retrieval/summary.md) and
[`results/retrieval/retrieval_report.xlsx`](../results/retrieval/retrieval_report.xlsx).

### 7.1 What is compared, and on what

Eight methods, all over the same children and parents of 30 Sep 2026, all sending the top 5 after the
parent swap: M1 `dense` (the reference, what the chunking run used), M2 `bm25`, M3 `hybrid_rrf`,
M4 `dense_rerank`, M5 `hybrid_rerank`, M6 `scheme_filter`, M7 `mmr`, and M8 `best_combo` — a recipe
declared from dev results alone, before any test score, which came out as *scheme filter + MMR*.

Questions: 128 in all, generated by code from `holdings.parquet` with gold answers computed by the
existing gold functions. 40 **dev** questions choose every setting; the 88 **test** questions (the 28
hand-written ones plus 60 generated) carry every reported number. The two sets use disjoint schemes, so
a setting tuned on dev cannot have memorised a test answer. About a third of the generated questions use
a short fund name ("the Flexi Cap fund"), because questions that copy exact names flatter keyword search.

Two stages, so the paid part stays small: **Stage A** runs all eight methods offline, with no LLM call at
all, and ranks them by mean `section_recall@5` — whether the sections holding the gold rows reach the
context. **Stage B** pays for only the top two plus M1 as the reference (3 × 88 = 264 answers) and
measures what actually matters: correct answers.

### 7.2 Stage A: search quality, free

| # | Method | `section_recall@5` | `hit@5` | Median latency | Note |
| --- | --- | ---: | ---: | ---: | --- |
| 1 | M8 `best_combo` (filter + MMR) | **100%** | 89% | 7 ms | Declared from dev before any test score |
| 2 | M6 `scheme_filter` | 99% | 88% | 8 ms | Fuzzy scheme match at 0.85, then dense |
| 3 | M7 `mmr` | 94% | 80% | 6 ms | Diversity alone already beats dense |
| 4 | M3 `hybrid_rrf` | 93% | 84% | 5 ms | Best `mrr@10` of all (0.795) |
| 5 | M1 `dense` | 92% | 86% | 5 ms | The reference |
| 6 | M5 `hybrid_rerank` | 90% | 88% | 8,427 ms | Cross-encoder: no recall gain, 1,000× the cost |
| 7 | M2 `bm25` | 88% | 79% | 1 ms | Weakest on lookups (91%) — abbreviations |
| 8 | M4 `dense_rerank` | 87% | 84% | 4,171 ms | Reranks the wrong 20 candidates |

Two things stand out. **Knowing which fund the question is about is worth more than a better ranker:** the
two methods that filter by scheme lead, and both cut the context roughly in half (about 2,400–2,500
tokens against 4,800 for dense), because they stop sending look-alike funds. **The cross-encoder is not
worth it here** — it costs seconds per question on a laptop CPU and does not improve `section_recall@5`,
because the candidate list it reorders is already the bottleneck.

### 7.3 Stage B: end-to-end answers, paid

Grok `x-ai/grok-4.20` through Velona, temperature 0, 24 Nov 2026. 264 rows, 0 pending; 131 answers came
from the response cache (byte-identical prompt, same model), and the full run cost 519,068 tokens against
an estimate of 840,562. The verdict is computed by `src/retrieval/verdict.py` under the rule the spec
fixed before the run (§6.5): most correct answers, then context gold-row recall, then prompt tokens, then
latency.

| Method | Correct | lookup | aggregation | debt | cross_scheme | unanswerable | Context gold rows | Prompt tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **M8 `best_combo`** | **67/88 (76%)** | 100% | 59% | 38% | 88% | 100% | 100% | 3,121 |
| M6 `scheme_filter` | 65/88 (74%) | 100% | 59% | 25% | 88% | 100% | 99% | 2,965 |
| M1 `dense` | 57/88 (65%) | 100% | 50% | 31% | 44% | 100% | 92% | 5,445 |

- **The winner is M8 `best_combo`**, and its lead over M1 `dense` is real: +10 correct answers, and a
  paired bootstrap (10,000 resamples, seed 42) puts the per-question difference at +0.114 (95% +0.045 to
  +0.193), which excludes 0. Its lead over M6 `scheme_filter` is **two answers** and is reported as
  possibly noise.
- **Stage A predicted Stage B.** The offline order (M8, M6, M1) is the end-to-end order, so the free
  metric was a usable proxy — which is what made paying for only three methods defensible.
- **Where the gain comes from: `cross_scheme`, 44% → 88%.** A "which of these two funds holds more X"
  question needs rows from both funds in one context. Plain dense search spends its five slots on
  whichever fund matches the embedding better; the scheme filter guarantees both are searched.
- **Retrieval is now almost perfect, and that is the point.** M8 reaches 100% context gold-row recall and
  still gets 21 answers wrong — 18 of them *generation errors*, where every needed row was in the prompt
  and the model's arithmetic was off (Q08: 15.21 against the true 19.24). The chunking benchmark's main
  conclusion therefore survives: for totals and counts, code beats context, which is why the pandas
  baseline answers 28/28.
- **It is also cheaper.** 3,121 prompt tokens per question against 5,445 for dense, for 10 more correct
  answers, and 19 ms of median retrieval latency.

### 7.4 Retrieval-specific design choices

| Choice | Why |
| --- | --- |
| **`section_recall@5` is the primary metric**, not row recall | With the parent swap a section reaches the LLM if *any* of its rows is retrieved, so sections are what decide the context. Row recall is capped by design (a 30-row industry cannot fit in 5 slots), so it is reported but never ranked on. |
| **Settings chosen on dev only**, written into `config.yaml` with the date | Test scores are computed once, after the grid search. M8's recipe is declared from dev results before any test number exists. |
| **Two stages, with a token estimate and an explicit yes before each paid run** | A free offline run ranks everything; the paid run is three methods on one set. `--max-tokens` stops the run before the call that would cross the cap, leaving the untouched rows pending. |
| **Every paid run appends to `spend_log.csv`** (tokens only, no prices) | The run's real cost sits next to its estimate; prices stay out of the repository. |
| **The scheme filter is fuzzy (0.85) and falls back to searching everything** | Questions use short names and abbreviations. A miss must degrade to M1's behaviour, never to an empty result, so `filter_miss` and `filter_wrong` are recorded per row. |
| **A fingerprint over config, method settings, reranker revision and the question files** | A resumed paid run whose world has changed stops instead of mixing two runs into one results file. |
| **The verdict is computed, like the chunking one** (`src/retrieval/verdict.py`) | Same reason as §3: every sentence is built from measured numbers under a rule fixed in advance. |

### 7.5 Limits of the retrieval result

- **88 test questions, and the top two differ by two answers.** M8 over M6 is within noise; M8 over M1 is
  not. Treat "filter by scheme, then diversify" as the finding, not the exact ranking of M8 against M6.
- **60 of the 88 questions are generated from the data**, so their phrasing is closer to the sheet's own
  wording than a real user's would be. The 28 hand-written questions are reported separately in
  [`offline_summary.md`](../results/retrieval/offline_summary.md) for exactly that reason.
- **One month, one fund house, one embedding model.** The scheme filter's advantage depends on fund names
  being distinctive enough to match fuzzily; an AMC with near-identical scheme names would see more
  `filter_wrong`.
- **The reranker was tested on a laptop CPU.** On a GPU its seconds would become milliseconds, but its
  recall here was no better than dense, so the conclusion is about quality, not only speed.
- **`debt` is still the weak type (38%)**, and the remaining failures are generation, not retrieval. A
  larger embedding model (`dense_large`), HyDE or multi-query, and a per-type router are all left as
  optional work (§13 of the retrieval spec); none would address arithmetic.
