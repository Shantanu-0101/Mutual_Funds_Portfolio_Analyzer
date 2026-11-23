# Design

| | |
|---|---|
| Status | Final for the recorded run of 20 Nov 2026 (Phase 7, task 7.2) |
| Read with | [`SPEC.md`](SPEC.md) (what is built and how it is judged), [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) (order of work, decisions D1–D11), [`DATA_NOTES.md`](DATA_NOTES.md) (what the files contain) |
| Results | [`results/summary.md`](../results/summary.md), [`results/chunking_report.xlsx`](../results/chunking_report.xlsx) |

This document explains **why** the system is built the way it is. It covers why each chunker exists, what was expected of it and what actually happened, the main design choices, where the project departs from the brief, and the limits of the result.

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
- **No scheme filter:** with the scheme filter on (D4, optional), retrieval-bound methods like row_wise and section_aware would likely gain the most.
- **Token counts include a fixed overhead:** the Grok endpoint adds about 180 prompt tokens to every call. This is the same for every method, so the ranking is unaffected.

**Optional next steps** (IMPLEMENTATION_PLAN, each needs a go-ahead):
- a second run with the scheme and month filter on
- all four months indexed, with cross-month questions
- the `llm_summary` chunker
- a second AMC
