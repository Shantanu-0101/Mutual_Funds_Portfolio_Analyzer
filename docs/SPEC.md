# Mutual Fund Portfolio Analyzer: Specification

| | |
|---|---|
| Status | v0.3, approved. Decisions D1–D11 accepted as recommended (9 Nov 2026). |
| Date | 9 Nov 2026 |
| Changes since v0.1 | Real data now in `data/raw/`. Spec rewritten around what the files actually contain (§3). Decisions in §13 accepted. |
| Next document | `docs/IMPLEMENTATION_PLAN.md` |
| Purpose of this document | Fix *what* we build and *how we judge it*. The implementation plan (order of work, tasks) is built from this spec later. |
| Audience | Me (intern), my supervisor, and whoever reads the code later |

---

## 1. Problem and goal

Indian mutual fund houses (AMCs) publish a monthly portfolio disclosure for every scheme as an Excel file. These files are written for humans: title rows, section headings ("Equity & Equity Related", "Debt Instruments", "Money Market Instruments"), subtotal rows, footnotes and notes blocks. Asking a plain question like "How much of the Flexi Cap fund is in banks?" means reading the sheet by hand.

We build a Python app that answers plain-English questions over these files using **RAG** (retrieve the relevant pieces of the file, then let an LLM answer from only those pieces).

**The main deliverable is an experiment, not the app.** RAG quality depends heavily on how a table is cut into pieces ("chunking"). We implement six chunking strategies on the same parsed data, plus one approach that does no chunking at all (the LLM writes pandas code), and measure with numbers which approach answers which kind of question well.

### 1.1 Research questions the project must answer

1. Which chunker gives the best answers for each question type (lookup, aggregation, debt, cross-scheme, unanswerable)?
2. When an answer is wrong, did retrieval fail (the right rows never reached the LLM) or did generation fail (the right rows arrived, the answer was still wrong)? We measure these separately.
3. What does each chunker cost in tokens and latency?
4. For aggregation questions, does the no-chunking pandas baseline beat every RAG chunker, as we expect?

### 1.2 Success means

- Every number in `results/summary.md` comes from a real, reproducible run.
- Gold answers are computed by code, and 10 of them were checked by hand against the raw Excel cells.
- Weaknesses are reported, not tuned away. "Chunker X fails at aggregation" is a valid finding.

### 1.3 Out of scope (non-goals)

- Downloading files from AMC websites automatically. Files are placed in `data/raw/` by hand.
- Investment advice, returns, NAV history or performance analysis.
- Multi-user deployment, login, hosting. This runs on one laptop.
- Fine-tuning any model.
- A truly secure sandbox for generated code (§9.3: we build a *restricted* runner and state honestly what it does not protect against).
- The notes block under each portfolio (NAV per plan, IDCW declared, derivative exposure tables). It is not holdings data; see §3.4.

---

## 2. Glossary (plain language)

| Term | Meaning |
|---|---|
| AMC | Asset Management Company, the fund house. Our data comes from one AMC: Aditya Birla Sun Life Mutual Fund (ABSL). |
| Scheme | One mutual fund, e.g. "Aditya Birla Sun Life Flexi Cap Fund". In the ABSL files, one sheet per scheme. |
| Scheme code | ABSL's short code for a scheme, used as the sheet name, e.g. `BSLEQTY` = Flexi Cap Fund. |
| Portfolio disclosure | Monthly list of everything a scheme holds, required by SEBI. |
| "As on" date | The date the portfolio snapshot refers to (month end). |
| ISIN | 12-character code that identifies a security, e.g. `INE040A01034` (HDFC Bank). Foreign securities have non-`IN` ISINs. |
| % to AUM | Share of the scheme's total assets held in this item. All items of a scheme add up to 100%. The brief calls this "% to NAV"; ABSL's header says "% to AUM". We store it in the column `pct_nav` (§6.2) and say so in the docs. |
| Rs. Lakhs | Unit for market value. 1 lakh = 100,000 rupees. 100 lakhs = 1 crore. |
| Industry / Rating | One column: the sector for equity (e.g. "Banks"), the credit rating for debt (e.g. "CRISIL AAA", "ICRA AAA", "SOV"). |
| TREPS | Tri-party repo: overnight cash-like lending. Appears as a line without an ISIN. |
| Net Receivable / Payable | Balancing cash item. Can be negative. |
| YTM / YTC | Yield to maturity / yield to call, for debt instruments. |
| Chunk | One piece of text stored in the vector database and retrieved as a unit. |
| Gold answer | The correct answer, computed by code from the parsed data. |

---

## 3. The data (as found on 9 Nov 2026)

This section records what was checked in the real files so the spec does not rest on guesses. Phase 0 turns it into the full `docs/DATA_NOTES.md`.

### 3.1 Files in `data/raw/`

| File | What it is | Used? |
|---|---|---|
| `ABSL_Monthly_Portfolio_Report_July 2026.xls` | ABSL portfolio disclosure, as on 31 Jul 2026 | Yes |
| `31082026_ABSLMF_MonthlyDisclosure.xls` | Same, as on 31 Aug 2026 | Yes |
| `30092026_ABSLMF_MonthlyDisclosure.xls` | Same, as on 30 Sep 2026 | Yes |
| `31102026_ABSLMF_MonthlyDisclosure.xls` | Same, as on 31 Oct 2026 | Yes |
| `am{apr..sep}2026repo.xls` (6 files) | AMFI industry Monthly Reports: one row per fund *category* (flows, folios, AUM in crore), plus a list of new schemes. No holdings, ISINs, sectors or ratings. | **No.** Different kind of data; see decision D2. |

Note the July file uses a different file-name pattern from the other three. The parser identifies files by content (the "Portfolio Statement as on …" line), not by file name.

### 3.2 Layout of the ABSL files (verified)

- **Format:** legacy `.xls` (Excel 97–2003), not `.xlsx`. openpyxl cannot read it; we read it with **xlrd** (§4).
- **Sheets:** an `Index` sheet (scheme code → scheme name), then one sheet per scheme. 104 scheme sheets in Jul/Aug/Sep, 105 in Oct. Schemes come and go: `BTMETF`, `BTMIDX`, `ABSLFSDF` appear only in Oct; `CSNHFS26`, `NSPPBS26` are missing from Oct.
- **Title block** (same position on every sheet): row 1 = scheme code (col A) and scheme name (col C); row 2 = scheme description; row 3 = "Portfolio Statement as on September 30, 2026".
- **Header row:** always row 4. Columns: `Name of the Instrument / Issuer | ISIN | Industry^ / Rating | Quantity | Market value (Rs. in Lakhs) | % to AUM | YTM % | YTC %`. Column B holds an internal ABSL security code (no header). 4 sheets (ESG schemes) add three columns: ESG score, BRSR Core score, link to BRSR report.
- **Merged cells:** none in any of the 417 scheme sheets.
- **% to AUM is a fraction**, not a percent: `0.0559673` means 5.597%. 561 cells hold the text `$0.00%` instead of a number, meaning "less than 0.01%".
- **Section headings** are rows with text in the instrument column and no values. Two levels: a main section (`Equity & Equity Related`, `Debt Instruments`, `Money Market Instruments`, `Government Securities`, `Securitised Debt`, `Others`, `Other Current Assets / (Liabilities)`, …) and a sub-heading (`a) Listed/awaiting listing on Stock Exchanges`, `b) Unlisted`, `Certificate of Deposits`, `Commercial Paper`, `Treasury Bills`, `TREPS / Reverse Repo Investments`, `Mutual Fund Units`, `Infrastructure Investment Trust`, `Alternative Investment Funds`, `Foreign Securities and /or overseas ETF`, `Gold`, `Silver`, …). Which headings are main vs sub is settled in Phase 0.
- **Total rows:** a `Total` row closes each sub-block; its % is rounded to 5 decimals. Each sheet ends with `GRAND TOTAL (AUM)` (% = 1.0).
- **Rows without an ISIN that still carry value:** `TREPS`, `Reverse Repo`, `Net Receivable / Payable`, `Margin amount for Derivative positions`. These are real parts of the portfolio and count toward 100%.
- **Below the grand total:** footnotes (`^Industry classification…`, `$ Less than 0.01%…`), then a `Notes:` block (NAV per plan for this and last month, IDCW declared, derivative exposure tables), then a benchmark line (scheme vs benchmark index name).
- **Size:** about 5,400–5,600 ISIN holdings per month in Jul–Sep, 7,419 in Oct. The jump comes from two new October schemes, `BTMIDX` and `BTMETF` (~1,040 rows each, broad-market index products).
- **Ratings** seen in Oct: `CRISIL AAA`, `ICRA AAA`, `CARE AAA`, `IND AAA`, `IND AAA(SO)`, `CRISIL AAA(SO)`, `ICRA AAA(SO)` and one `[ICRA]AAA`. No `SOV` label was found in the rating column; how government securities are labelled is checked in Phase 0.

### 3.3 Inconsistencies already seen

| What | Where | Effect |
|---|---|---|
| No `GRAND TOTAL (AUM)` row | Sep 2026, sheet `BSLIF` (Corporate Bond Fund) | Validation must not assume the grand total exists; report it. |
| Different file-name patterns | July file vs the others | Detect month from sheet content, not file name. |
| Extra ESG columns | 4 sheets per month | Parser maps columns by header text, not by position. |
| `$0.00%` text instead of a number | 561 cells | Needs a rule (§6.2, FR-1.3). |
| Scheme list changes month to month | Oct adds 3, drops 2 | Cross-month questions must handle schemes that exist in only some months. |
| Rating written two ways | `ICRA AAA` vs `[ICRA]AAA` | Rating normalisation needed for "rated AAA" questions (FR-5.3). |

### 3.4 What the data can and cannot answer

**Can:** holdings lookup (% and value of an instrument in a scheme), sector and rating totals, top-N share, holding counts, cash/TREPS share, debt by rating, overlap between two schemes, which scheme holds more of a stock, and (if D3 allows) changes between months.

**Cannot (good unanswerable questions):** returns, expense ratio, fund manager, exit load, holdings of other AMCs' schemes, anything after 31 Oct 2026. We avoid using NAV-per-plan as an "unanswerable" question, because NAV *is* in the raw file (notes block) even though we do not parse it; it would be a misleading test.

---

## 4. System overview

```
data/raw/*.xls  (ABSL portfolio disclosures)
     │
     ▼
[Parser] ──► data/processed/holdings.parquet   (one row per holding, with source_row)
     │       data/processed/totals.parquet     (Total / GRAND TOTAL rows, for validation)
     │       data/processed/schemes.parquet    (scheme code, name, month, description)
     │       results/parse_report.md
     │
     ├──────────────────────────────┐
     ▼                              ▼
[6 Chunkers]                  [Pandas baseline]
     │                         LLM writes pandas code → restricted run → answer
     ▼
[Embed (bge-small, cached)] ──► ChromaDB: one collection per chunker
     │
     ▼
[RAG: retrieve top_k → prompt → LLM (temp 0) → structured answer]
     │
     ▼
[Eval runner] ── questions.yaml + programmatic gold ──► results.csv, summary.md, chart
     │
     ▼
[Streamlit app]: Ask / Compare / Results pages
```

**Why this shape:** parsing happens exactly once, into one clean table. Every chunker and the baseline read that same table, so differences in the results come from the chunking, not from different parsing.

---

## 5. Stack

| Part | Choice | Why |
|---|---|---|
| Language | Python 3.11 (see D7: only 3.13 is installed on this laptop) | Required by the brief. |
| Excel | **xlrd** for `.xls` (cell-level access, exact row numbers) + pandas for tables. xlwt only to write synthetic `.xls` test fixtures in the real layout (xlrd 2.x reads `.xls` only). | The real files are `.xls`, which openpyxl cannot open. This is a deviation from the brief, forced by the data. |
| Storage | Parquet in `data/processed/` | Keeps column types (numbers stay numbers), fast, one file per table. |
| Embeddings | `BAAI/bge-small-en-v1.5`, local, cached on disk | Free, runs on a laptop CPU, small (384 dims). Max input is 512 tokens, which matters for big chunks (§6.3). |
| Vector DB | ChromaDB, persistent, one collection per chunker | Simple, local, no server. Separate collections keep chunkers from mixing. |
| LLM | Pluggable via env var `LLM_PROVIDER`: `groq` (default), `gemini`, `mock` | Cheap or free tiers; `mock` makes tests free and deterministic. Temperature 0 everywhere. |
| UI | Streamlit | Fastest way to a usable demo in Python. |
| Tests | pytest | Standard. |
| Chart | matplotlib → PNG | Works offline; easy to put in docs and slides. |

### 5.1 Configuration (`config.yaml`)

All tunable values live in one file, so a run is described by one file. Proposed keys (defaults to confirm):

```yaml
paths:
  raw: data/raw
  processed: data/processed
  chroma: data/chroma
  cache: data/cache          # embedding + LLM response cache
  results: results
data:
  file_glob: "*ABSL*.xls"    # only portfolio disclosures; AMFI files ignored
  eval_months: ["2026-09-30"]  # which month(s) the main experiment indexes (D3)
embedding:
  model: BAAI/bge-small-en-v1.5
  max_tokens: 512
  batch_size: 32
retrieval:
  top_k: 5
llm:
  provider: groq             # overridden by env LLM_PROVIDER
  model: <decided when building llm.py, D8>
  temperature: 0
  max_output_tokens: 800
  timeout_s: 60
  retries: 3
chunking:
  fixed_size:    {chunk_tokens: 256, overlap_tokens: 32}
  header_window: {rows_per_chunk: 10}
  scheme_level:  {on_overflow: truncate_and_warn}
  section_aware: {max_tokens: 512}
  hierarchical:  {child: row, parent: section}
baseline:
  timeout_s: 10
eval:
  rel_tolerance: 0.01
  abs_tolerance_pct_points: 0.01
  manual_check_n: 10
  seed: 42
```

Secrets (`GROQ_API_KEY`, `GEMINI_API_KEY`) live only in `.env`, which is git-ignored. `.env.example` lists the names with empty values.

---

## 6. Functional requirements

IDs (FR-x.y) let the implementation plan and the tests refer back to this spec.

### 6.1 Phase 0: Data inspection

- **FR-0.1** Open every portfolio file and every sheet. If there are none, stop and report.
- **FR-0.2** Confirm and complete §3: the full list of section headings and which are main vs sub; every column variant; every `$`-style text value; every sheet missing a total; scheme list per month; how government securities and T-bills are labelled in the rating column.
- **FR-0.3** Per scheme, check that (all value rows) sum to the `GRAND TOTAL (AUM)` value, so we know the parse rule works before writing the parser.
- **FR-0.4** Write findings to `docs/DATA_NOTES.md` and show them to me **before** any parser code is written.

### 6.2 Phase 1: Parser

**Canonical holdings table** (one row per holding). Columns from the brief, plus a few extras marked *(extra)* that the real files offer and that some questions need.

| Column | Type | Notes |
|---|---|---|
| amc | str | "Aditya Birla Sun Life Mutual Fund". |
| scheme_code | str *(extra)* | Sheet name, e.g. `BSLEQTY`. Stable key across months. |
| scheme | str | Scheme name from row 1, whitespace cleaned. |
| as_of_date | date | From "Portfolio Statement as on …" (row 3). |
| section | str | Main heading, e.g. "Equity & Equity Related". |
| subsection | str or null *(extra)* | Sub-heading, e.g. "a) Listed/awaiting listing on Stock Exchanges". |
| asset_class | str | `equity` / `debt` / `other`, from section by a visible mapping table in code (D6). |
| instrument | str | Name of the instrument / issuer. |
| isin | str or null | Null for TREPS, reverse repo, net receivables, margin. |
| industry_or_rating | str or null | |
| quantity | float or null | |
| market_value_lakhs | float | As in the file (already Rs. lakhs). Can be negative (net payables). |
| pct_nav | float | **Percent units** (5.597 means 5.597%) = file value × 100. Source header is "% to AUM". |
| pct_nav_flag | str or null *(extra)* | `lt_0.01` when the file shows `$0.00%` (FR-1.3). |
| ytm, ytc | float or null *(extra)* | Percent units, debt only. |
| source_file | str | File name. |
| source_sheet | str | Sheet name. |
| source_row | int | The real 1-based Excel row number. |

- **FR-1.1** `(source_file, source_sheet, source_row)` is the **row key**. It uniquely identifies a holding and is how retrieval and gold answers are matched later.
- **FR-1.2** Columns are found by header text, not position, so the 4 ESG sheets parse the same way (ESG columns ignored, noted in the report).
- **FR-1.3** `$0.00%` cells: store `pct_nav = market_value_lakhs / grand_total_lakhs × 100` and set `pct_nav_flag = "lt_0.01"`. Never store null, never store 0 silently. If the grand total is missing, store 0.0 with the flag and list it in the report.
- **FR-1.4** A holding is any row inside the portfolio block with a market value, whether or not it has an ISIN (so TREPS and net receivables are holdings with `isin = null`). `Total` and `GRAND TOTAL (AUM)` rows are **not** holdings; they go to `totals.parquet` with their source row.
- **FR-1.5** The portfolio block ends at `GRAND TOTAL (AUM)` or, if that is missing, at the first footnote (`^`, `$`) or `Notes:` line. Everything after it (footnotes, notes block, benchmark) is skipped **as a block**, recorded once per sheet with its row range.
- **FR-1.6** No silent drops inside the portfolio block. Every non-empty row there that is not a holding, heading or total is listed in the parse report with its row and the reason.
- **FR-1.7** Validation per scheme and month, written to `results/parse_report.md`:
  - sum of `pct_nav` vs 100, with the deviation;
  - sum of `market_value_lakhs` vs the sheet's `GRAND TOTAL (AUM)` value (where it exists);
  - each `Total` row vs the sum of the rows above it;
  - duplicate ISIN within a section (listed, with a reason if justified);
  - null `pct_nav` on any holding (an error);
  - sheets missing a grand total (e.g. Sep `BSLIF`).
- **FR-1.8** The parser handles all four months. Which months go into the experiment is a config choice (D3).
- **FR-1.9** Merged cells: none exist in the real files. The parser does not need special handling for them; a test asserts the assumption so a future file with merged cells fails loudly instead of parsing wrongly. (The brief asked to handle merged cells; this is the honest version of that.)

### 6.3 Phase 2: Chunkers

**Shared interface:** `chunk(parsed_sheet: DataFrame) -> list[Chunk]`, where

```
Chunk:
  id: str                 # stable: f"{chunker}:{as_of_date}:{scheme_code}:{n}"
  text: str               # exactly what gets embedded (and shown to the LLM, unless a parent is used)
  metadata:
    chunker, amc, scheme_code, scheme, as_of_date, section (or "ALL"),
    source_rows: list[row key]     # every holding row this chunk covers, even partly
    parent_id: str | None
    n_tokens: int                  # counted with the embedding model's tokenizer
    truncated: bool                # true if n_tokens > 512 (the model only "sees" the first 512)
```

- **FR-2.0** Every chunker fills `source_rows`, including `fixed_size` (it tracks which rows each text span came from). Without this we cannot measure retrieval.
- **FR-2.1** Every chunker logs: number of chunks, average and max tokens, number truncated.

| # | Chunker | What it does | Why it exists (hypothesis) |
|---|---|---|---|
| 1 | fixed_size | Flatten the sheet to text, split every N tokens with overlap. | The naive baseline everyone starts with. Expected to cut rows in half and lose column meaning. |
| 2 | row_wise | One chunk per holding: `Scheme: X \| As on: 2026-09-30 \| Section: Equity \| Instrument: Y \| Industry: Z \| % to AUM: 5.60 ...` | Best for precise lookups. Expected to fail aggregations: top_k=5 cannot hold all 7 bank rows of the Flexi Cap Fund (Oct 2026), let alone its 85 equity rows. |
| 3 | header_window | N rows per chunk, with column header + scheme + date + section repeated in each chunk. | Middle ground: some neighbours, still small. |
| 4 | scheme_level | Whole scheme in one chunk. Over 512 tokens (true for most schemes: the 85-holding Flexi Cap sheet is ~2,500 tokens) → embedding truncated, recorded. | Full context for aggregation, but the embedding only sees the top ~10 holdings, so retrieval should be weak. |
| 5 | section_aware | One chunk per section per scheme; split only if above max tokens. | Matches how humans read the sheet; good for "total debt" style questions. |
| 6 | hierarchical | Embed row-level children; when a child is retrieved, send its parent section chunk to the LLM. Parents deduplicated. | Precise retrieval + wide context. Costs more tokens. |
| opt | llm_summary | LLM writes a summary per section; the summary is embedded; the exact table is attached for the LLM. | Only if time allows (D10). |

**Table text format** for multi-row chunks: `Scheme:`, `As on:`, `Section:` lines, one header line, then one pipe-separated line per row (`Instrument | ISIN | Industry/Rating | Qty | Value (Rs L) | % to AUM`). Same format for chunkers 3, 4, 5 and the parents of 6, so they differ only in *how much* goes into a chunk. Percent values are written in percent units (5.60), not fractions, so the LLM does not have to convert.

### 6.4 Phase 3: Index and RAG

- **FR-3.1** Each chunker gets its own Chroma collection with identical settings (same embedding model, cosine distance).
- **FR-3.2** Embeddings are cached on disk keyed by `(model, hash(text))`, so re-indexing unchanged chunks costs nothing. (row_wise and the hierarchical children can share cached vectors when their text is identical.)
- **FR-3.3** Retrieval returns `top_k` chunks (from config). For `hierarchical`: retrieve top_k children, then replace them with their unique parents.
- **FR-3.4** Optional metadata filter by scheme and month, used by the app when the user picks them. Whether the evaluation uses it is decision D4.
- **FR-3.5** Generation prompt rules: answer only from the given context; if the context is not enough, say so; cite scheme, instrument and row for every number; never use outside knowledge or compute from memory.
- **FR-3.6** The LLM returns a **structured answer** (JSON), so the evaluation does not have to guess numbers out of prose:
  ```json
  {"answer": "plain-English answer",
   "value": 5.6, "unit": "pct | lakhs | count | null",
   "items": ["for list answers"],
   "sources": [{"scheme": "...", "instrument": "...", "row": 8}],
   "insufficient_context": false}
  ```
  Malformed JSON is recorded as a format failure (counts as wrong), not repaired silently.
- **FR-3.7** Each call returns: answer object, retrieved chunks (ids, text, scores), context rows, prompt and completion tokens, retrieval latency, generation latency.

### 6.5 Phase 4: No-chunking baseline (text-to-pandas)

- **FR-4.1** The LLM gets the DataFrame schema (column names, types, a few example values, the list of scheme names, sections and months) and the question, and returns pandas code that sets a variable `result`.
- **FR-4.2** The code runs in a restricted runner:
  - static check (AST) before running: no `import`, no `open/exec/eval/compile/__import__`, no dunder attribute access, no pandas I/O methods (`read_*`, and `to_*` except safe ones like `to_list`);
  - only `df` (a copy) and `pd` in scope, reduced builtins;
  - runs in a separate process with a timeout (default 10 s), killed if it runs over.
- **FR-4.3** Return the code, the result and any error. Failures (bad code, timeout, blocked code) are reported as failures, not retried with hints.
- **FR-4.4** The result is converted to the same answer object as §6.4 so the metrics are identical.

### 6.6 Phase 5: Evaluation

**Question set** (`src/eval/questions.yaml`), 25–30 questions. Target mix:

| Type | Count | Examples (scheme names are real ABSL schemes) |
|---|---|---|
| lookup | 7 | "What % of AUM does the Flexi Cap Fund hold in ICICI Bank?" |
| aggregation | 7 | "Total % in Banks in the Flexi Cap Fund", "share of the top 5 holdings", "how many equity holdings" |
| debt | 5 | "What % of the Medium to Long Duration Fund is rated AAA (any agency)?", "list its holdings rated CARE AAA", "total % in Government Securities" |
| cross_scheme | 5 | "Which holds more Infosys: Flexi Cap or Large Cap?", "how many stocks do Flexi Cap and Large & Mid Cap share?" |
| unanswerable | 4 | "What is the expense ratio of the Flexi Cap Fund?" (correct answer: not in the data) |
| cross_month | 0–4 | Only if D3 says yes: "How did ICICI Bank's weight in Flexi Cap change from Jul to Sep?" |

Question schema:
```yaml
- id: Q07
  type: aggregation
  text: "What is the total % of AUM in Banks for Aditya Birla Sun Life Flexi Cap Fund as on 30 Sep 2026?"
  answer_kind: number | text | list | not_in_data
  gold_fn: industry_total        # function in src/eval/gold.py
  params: {scheme_code: BSLEQTY, as_of_date: 2026-09-30, industry: "Banks"}
```

- **FR-5.1** Questions are written **after** Phase 1, from real scheme, instrument, industry and rating names. Every question names its month, so it has one correct answer.
- **FR-5.2** Gold answers and gold source rows are computed by code (`gold.py`) from `holdings.parquet`. Never by an LLM.
- **FR-5.3** "Rated AAA" rules are written down once in `gold.py` (e.g. does `CRISIL AAA(SO)` count as AAA? is `[ICRA]AAA` the same as `ICRA AAA`? yes, after normalising) and the question text says which, so the LLM and the gold use the same rule.
- **FR-5.4** Manual check: 10 questions chosen at random (fixed seed) are exported to `results/manual_check.md` with the gold answer and the raw Excel cell references (e.g. `30092026_ABSLMF_MonthlyDisclosure.xls › 'BSLEQTY'!H8`) so I can verify them by hand. This guards against a parser bug corrupting every gold answer.
- **FR-5.5** Every chunker and the baseline run on every question with the same embedding model, LLM, top_k and temperature.
- **FR-5.6** A run manifest (`results/run_manifest.json`) records: date and time, git commit, config, LLM provider and model, embedding model, data file hashes.

**Metrics** (defined precisely so they can be unit-tested):

| Metric | Definition |
|---|---|
| retrieval_hit | 1 if at least one gold row key is in the rows of the context sent to the LLM. N/A for unanswerable. |
| gold_row_recall | Fraction of gold row keys present in that context. Shows *partial* retrieval, which matters for aggregation. |
| numeric_correct | Correct if `abs(pred − gold) <= max(0.01 × abs(gold), 0.01)` for percentages (relative 1% or 0.01 percentage points, whichever is larger, D5). Lakhs and counts: relative 1% only. |
| text_correct | Normalised exact match (lowercase, trim, remove punctuation, "Ltd"/"Limited" unified). Lists: set equality after normalising; Jaccard also reported. |
| unanswerable_correct | For unanswerable questions: 1 if `insufficient_context` is true or the answer says the data does not contain it. Also tracked: **false refusals** on answerable questions. |
| prompt_tokens, completion_tokens | From the provider's usage data. |
| latency_ms | Retrieval and generation, separately. |

Fairness note: big chunks (scheme_level) will score high on retrieval_hit just because they contain many rows. The summary always shows retrieval next to context tokens, so this is not mistaken for "better retrieval".

**Outputs:**
- `results/results.csv`: one row per (method, question) with all metrics, the answer, and the retrieved chunk ids.
- `results/summary.md`: method × question-type accuracy table, retrieval table, tokens and latency table, and **3 concrete failure examples per method** (question, retrieved chunks, wrong answer, and why: retrieval miss / generation error / format error).
- `results/accuracy_by_method.png`: grouped bar chart.

### 6.7 Phase 6: Streamlit app

- **FR-6.1 Ask page:** sidebar picks month, scheme(s) and one chunker; the user asks a question; the page shows the answer, the cited rows and the retrieved chunks (expandable), plus tokens and latency.
- **FR-6.2 Compare page:** the same question through every chunker (and the baseline) side by side, with latency and tokens.
- **FR-6.3 Results page:** the evaluation tables and chart from `results/`.
- **FR-6.4** The app reads existing indexes; it never re-parses or re-indexes on its own.

### 6.8 Phase 7: Docs

- **README.md:** setup (Python, virtualenv, `.env`), which files to put in `data/raw/` and where to download them, one command per stage, and a **Findings** section filled from the real results.
- **docs/DESIGN.md:** why each chunker exists, expected strengths and weaknesses, what the results actually showed, the main design choices with reasons (including the deviations from the brief: xlrd, `% to AUM`, no merged cells).
- **docs/DATA_NOTES.md:** from Phase 0.
- Short docstrings on every module and chunker explain *why*, not just *what*.

---

## 7. Repo layout

```
config.yaml
.env.example
.gitignore
requirements.txt
README.md
src/
  parsing/     Excel → canonical tables + validation
  chunking/    base.py + one file per chunker
  index/       embedding (with disk cache) + Chroma
  rag/         retrieve + prompt + generate
  baseline/    text-to-pandas + restricted runner
  eval/        questions.yaml, gold.py, runner.py, metrics.py, report.py
  llm.py       provider interface + groq / gemini / mock
app/streamlit_app.py
tests/         unit tests; synthetic fixtures named tests/fixtures/synthetic_*
data/raw/      ABSL portfolio files (placed by hand)
data/processed/
results/
docs/          SPEC.md (this), DATA_NOTES.md, DESIGN.md
```

One command per stage (exact form decided in the plan, e.g. `python -m src.parsing`, `python -m src.index`, `python -m src.eval`, `streamlit run app/streamlit_app.py`).

---

## 8. Working process (from the brief)

- Build phase by phase. After each phase: run the tests, summarise in 3–5 lines, commit, and **stop for approval** before the next phase.
- Ask before any big decision not covered here.
- Never invent data. Synthetic data only in `tests/`, with files named `synthetic_*`.

---

## 9. Non-functional requirements

### 9.1 Reproducibility
- Temperature 0, fixed seeds, versions pinned in `requirements.txt`.
- LLM responses cached on disk keyed by `(provider, model, prompt hash)`, so re-running the report does not re-call the API. A flag forces fresh calls for the final "real run".
- Temperature 0 on hosted LLMs is *nearly* but not perfectly deterministic. The final numbers come from one recorded run.

### 9.2 Cost and limits
- About 30 questions × (6 chunkers + 1 baseline) ≈ 210 LLM calls per full evaluation (more if llm_summary is built).
- **Context size is the real risk.** One equity scheme is ~2,500 tokens of table text (the two new index schemes are ~30,000); scheme_level with top_k = 5 sends ~12,000 tokens per call, far more if an index scheme is retrieved. Free tiers limit tokens per minute and per day, so big-chunk methods may be throttled or rejected. The runner needs retry with backoff and must be resumable (skip finished rows). Exact limits are checked when choosing the model (D8).
- Embedding is local and free. Index size for one month: ~5,500 row chunks per row-level collection (~7,400 for Oct), a few minutes on CPU, done once thanks to the cache.

### 9.3 Safety of generated code
The baseline's restricted runner blocks the obvious dangerous operations and kills slow code, but Python cannot be fully sandboxed inside Python. This is acceptable because the code runs locally on our own data, and DESIGN.md says so plainly.

### 9.4 Secrets
API keys only in `.env` (git-ignored). Nothing secret in logs, results or docs.

---

## 10. Testing

| Area | What is tested | Data |
|---|---|---|
| Parser | Title block, header found by text, ESG extra columns, section and sub-section tracking, Total / GRAND TOTAL excluded from holdings, `$0.00%` rule, fraction → percent, missing grand total, notes block skipped, correct `source_row`, no-merged-cells assertion | `tests/fixtures/synthetic_*.xls` copying the real ABSL layout with made-up values |
| Each chunker | Chunk count, every holding covered by at least one chunk, `source_rows` correct, truncation flag, parent links (hierarchical) | Small synthetic DataFrame |
| Metrics | Tolerance edges, small and zero gold values, list matching, refusal detection, recall | Hand-written cases |
| Baseline runner | Blocks import / open / dunder / pandas I/O, timeout kills, valid code returns a result | Small snippets |
| LLM | `mock` provider returns fixed JSON; no network in tests | — |

Unit tests never call a real LLM and never need the real AMC files. One optional "smoke" test runs the parser on the real files when they are present and is skipped otherwise.

---

## 11. Phase acceptance criteria

| Phase | Done when |
|---|---|
| 0 | `docs/DATA_NOTES.md` covers every portfolio file and sheet; reviewed by me. |
| 1 | Parser tests pass; `parse_report.md` shows per-scheme % deviation, total-row checks and every skipped row/block; parquet files written for all four months. |
| 2 | All 6 chunkers implemented and tested; chunk stats logged for real data. |
| 3 | All collections built; a sample question returns answer + chunks + tokens + latency through each chunker. |
| 4 | Baseline answers a sample aggregation question; restricted-runner tests pass. |
| 5 | 25–30 questions with programmatic gold; `manual_check.md` produced; a full run gives `results.csv`, `summary.md` and the chart. |
| 6 | Ask, Compare and Results pages work when opened in the browser. |
| 7 | README and DESIGN.md filled with real findings; `.env.example` present; no keys in git. |

---

## 12. Risks

| Risk | Effect | Mitigation |
|---|---|---|
| Parser bug | All gold answers wrong in the same way; results look fine but are false | Validation report (sums, total rows) + 10-question manual check against raw cells. |
| Only one AMC | The "messy Excel" part is milder than the brief imagines (one consistent layout, no merged cells) | State it honestly; optional second AMC (D1). |
| Same stock in many schemes and months | row_wise retrieval may return HDFC Bank from the wrong scheme or month | This is a real finding, not a bug. Scheme name and date are written into every chunk; D4 adds a filtered run for comparison. |
| Big chunks exceed 512 embedding tokens | Embedding ignores most of the chunk | Record `truncated`; report it as a finding rather than hide it. |
| Free-tier rate and context limits | Eval runs fail halfway, or big-chunk methods are rejected | Backoff, response cache, resumable runner; a rejected request is recorded as "context overflow", not dropped (D9). |
| Few questions (25–30) | Differences between chunkers may be noise | Report counts, not just percentages; avoid over-claiming. |
| LLM ignores the JSON format | Answers cannot be scored | Count as format failures and report how often per method. |
| "% to AUM" vs "% to NAV" confusion | Supervisor or reader thinks numbers are wrong | Glossary + DESIGN.md explain it once, clearly. |

---

## 13. Decisions

All accepted as recommended on 9 Nov 2026. D8 (exact Groq model) is settled when `llm.py` is built.

| # | Decision | Accepted choice |
|---|---|---|
| D1 | **Is one AMC enough, or download a second one?** | The ABSL files are enough to build and evaluate everything. A second AMC for the same month(s) would add real layout differences (the "messy" part of the brief) and cross-AMC questions, but adds parser work. **Recommend: start with ABSL only; add a second AMC only if Phase 1 finishes early.** |
| D2 | What to do with the 6 AMFI files (`am*2026repo.xls`)? | Move them out of `data/raw/` (e.g. to `data/other/amfi/`) so "open every file in data/raw" stays clean. Not used in this project. |
| D3 | **Which months go into the experiment?** | Parse all four. Index and evaluate **one month, Sep 2026**, for the main run, so each question has one obvious source and month confusion does not swamp the chunking comparison. Why not October (the latest)? Its two new ~1,000-row index schemes make scheme_level and section chunks ~30,000 tokens, which would turn the comparison into a test of LLM context limits. September also contains the missing-grand-total case, a useful messy-data example. Optionally a second run with all four months indexed plus 3–4 cross_month questions, as an extra finding. |
| D4 | Does the evaluation use the scheme/month filter? | **No** for the main run (retrieval must find the scheme itself: the harder, more honest test). Optionally a second run with the filter to show how much it helps. |
| D5 | Numeric tolerance for small values | Relative 1% **or** 0.01 percentage points, whichever is larger, because the sheets' totals round to 0.001%. |
| D6 | Section → asset_class mapping for mixed items (InvITs, REITs, AIFs, mutual fund units, gold, silver, TREPS, net receivables) | Decide in Phase 0 after listing all headings; mapping kept as a visible table in code. My starting guess: InvIT/REIT/AIF/MF units/gold/silver → `other`; TREPS, reverse repo, CDs, CPs, T-bills → `debt` (money market); net receivables and margin → `other`. |
| D7 | Python version: the brief says 3.11, this laptop has only 3.13.7 | Install 3.11 and use a virtualenv, to match the brief and avoid library surprises. Alternative: use 3.13 and note it. |
| D8 | Groq model name | A current Llama-class model on Groq with a large context window; I check the live model list and rate limits when building `llm.py` and put the choice in config. |
| D9 | Cap on context tokens for big-chunk methods? | No cap (same top_k for all, as the brief says). If a request exceeds the LLM's limit, record it as a "context overflow" failure. |
| D10 | Build the optional `llm_summary` chunker? | Only after Phase 5 works for the six required ones. |
| D11 | Initialise git in this folder now? Commit the raw files? | Yes to git, with `.gitignore` for `.env`, `data/chroma`, `data/cache`. The ABSL files are public disclosures but large (4–8 MB each): git-ignore `data/raw/` and document where to download them. |

---

## 14. Traceability to the brief

| Brief item | Spec section |
|---|---|
| Inspect data, DATA_NOTES | 3, 6.1 |
| Canonical DataFrame, validation, no silent drops | 6.2 |
| 6 chunkers + optional | 6.3 |
| Chroma per chunker, prompt rules, return fields | 6.4 |
| Text-to-pandas baseline | 6.5 |
| Questions, programmatic gold, manual check, metrics, outputs | 6.6 |
| Streamlit Ask / Compare / Results | 6.7 |
| README, DESIGN | 6.8 |
| Definition of done | 11 |

### 14.1 Deviations from the brief (and why)

| Brief says | Spec does | Why |
|---|---|---|
| openpyxl for Excel | xlrd for reading | The real files are `.xls`; openpyxl only reads `.xlsx`. |
| "% to NAV" | Column named `pct_nav`, filled from "% to AUM" | The ABSL files report % to AUM. Name kept for the brief; meaning documented. |
| Handle merged cells, multi-row headers | Assert there are none | None exist in the real files; building handling for them would be untested code. |
| Several AMCs | One AMC (ABSL), four months | That is the data we have; D1 covers adding more. |
