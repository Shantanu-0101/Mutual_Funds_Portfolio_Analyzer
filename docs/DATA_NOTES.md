# Data notes (Phase 0)

| | |
|---|---|
| Status | Reviewed. Q1–Q4 answered as recommended (11 Nov 2026); rules R1–R10 implemented in Phase 1 (`src/parsing/`). |
| Date | 9 Nov 2026 |
| Evidence | `results/inspect_raw.txt`, produced by `python -m src.parsing.inspect_raw > results/inspect_raw.txt` (read-only, ~5 s). Section numbers below like "(out §9)" point into that file. |
| Files | The 4 ABSL portfolio disclosures in `data/raw/` (Jul, Aug, Sep, Oct 2026). |

Row numbers are Excel row numbers (1-based). "%" values in the files are fractions (`0.0559` = 5.59%); this note writes them as percent unless it says "fraction".

---

## 1. Summary

The layout is regular and the parse rule from the spec works: in **all 417 scheme sheets the value rows add up exactly to `GRAND TOTAL (AUM)`** (difference 0.00 lakh everywhere). Three things the spec did not foresee need a decision before Phase 1:

1. **The `% to AUM` cell of `Net Receivable / Payable` is not reliable.** ABSL uses it as a balancing figure, and in July it is plainly wrong in 21 sheets (§7). Proposal: compute it from value / grand total.
2. **A holding's name cell can contain `Notes:`** (Sep, BSLIF row 207, a STRIPS holding). A parser that stops at the first `Notes:` cuts the sheet short. This is why the spec thought BSLIF had no grand total; it does (§9).
3. **Merged cells exist** (1,436 ranges), but **none inside a portfolio block**. FR-1.9 ("fail loudly on merged cells") must be limited to the block, or it would fail on every sheet (§3).

Corrections to the spec are listed in §11, proposed parser rules in §12, and questions for you in §13.

---

## 2. Files and months

| File | As on (from title rows) | Scheme sheets | Holding rows* | of which ISIN-shaped |
|---|---|---|---|---|
| `ABSL_Monthly_Portfolio_Report_July 2026.xls` | 2026-07-31 | 104 | 5,864 | 5,600 |
| `31082026_ABSLMF_MonthlyDisclosure.xls` | 2026-08-31 | 104 | 5,749 | 5,523 |
| `30092026_ABSLMF_MonthlyDisclosure.xls` | 2026-09-30 | 104 | 5,646 | 5,421 |
| `31102026_ABSLMF_MonthlyDisclosure.xls` | 2026-10-31 | 105 | 7,646 | 7,419 |

\* every row in the portfolio block that carries a market value, including TREPS, Net Receivable and Margin rows.

- Every sheet in a file has the same as-on date, so **the month comes from the title row**, not the file name (July's name pattern differs).
- Each file has an `Index` sheet (columns: Scheme Code `AB001…`, Scheme Short code, Scheme Name) plus one sheet per scheme. Sheet name = short code = cell A1, in every sheet.
- Oct `Index` lists `FTPVB`, which has no sheet. Otherwise Index and sheets match exactly.

**Scheme changes** (out §2): Jul → Aug → Sep: none. Sep → Oct: added `ABSLFSDF` (Financial Services Sectoral Debt Fund), `BTMETF` (BSE Total Market ETF), `BTMIDX` (BSE Total Market Index Fund); dropped `CSNHFS26`, `NSPPBS26` (both target-maturity index funds that matured in Sep 2026).

Things worth knowing for questions on **September** (the evaluation month):
- `CSNHFS26` and `NSPPBS26` hold **no securities in Sep**, only TREPS / net receivables (2–3 rows each), because they were about to mature. Avoid them in holdings questions.
- `BTMIDX` / `BTMETF` (~1,000 equity rows each) only exist in Oct; they explain the Oct jump.

## 3. Sheet layout

- **Title block**, rows 1–3: A1 = short code, C1 = scheme name (upper case), C2 = description, C3 = `Portfolio Statement as on September 30, 2026`.
- **Header row**: row 4 in all 417 sheets. Same 8 columns in C–J everywhere: `Name of the Instrument / Issuer | ISIN | Industry^ / Rating | Quantity | Market value (Rs. in Lakhs) | % to AUM | YTM % | YTC %`. Column B has no header; it holds an ABSL internal security code (also on TREPS rows; empty on Net Receivable / Margin rows).
- **ESG layout**: only `ABSLESG` (ESG Integration Strategy Fund), i.e. **1 sheet per month, 4 in total**. It adds `ESG Score (Rating & Analystics Ltd)`, `BRSR Core Score #`, `Link to BRSR report` in K–M. Header texts contain line breaks and double spaces, so matching must collapse whitespace.
- **Merged cells** (out §8): 1,251 ranges in rows 1–4 (title/header) and 185 below the grand total; **0 inside a portfolio block**. The spec's "none" came from opening the file without formatting info, where xlrd reports no merges at all.
- **YTM / YTC** are fractions like `%`. YTC is filled on only 5 holdings per month (callable bank bonds).

## 4. Section headings (out §4)

A heading row = text in the name column and nothing in ISIN or any numeric column. There are exactly **two levels**, and the main headings are a fixed list of five, always in this order when present:

| # | Main heading | Sub-headings seen under it (rows in the 4 months) |
|---|---|---|
| 1 | `Equity & Equity Related` | `a) Listed/awaiting listing on Stock Exchanges`, `b) Unlisted`, `Foreign Securities and /or overseas ETF` |
| 2 | `Debt Instruments` | `a) Listed/awaiting listing on the stock exchanges`, `b) Privately Placed/Unlisted`, `Government Securities`, `Securitised Debt` |
| 3 | `Money Market Instruments` | `Commercial Paper`, `Certificate of Deposits`, `Treasury Bills`, `STRIPS` |
| 4 | `Others` | `TREPS / Reverse Repo Investments`, `Mutual Fund Units`, `International Mutual Fund Units`, `Exchange Traded Fund`, `Alternative Investment Funds`, `Infrastructure Investment Trust`, `Gold`, `Silver`, `Foreign Securities and /or overseas ETF` |
| 5 | `Other Current Assets / (Liabilities)` | none: its rows (`Net Receivable / Payable`, `Margin amount for Derivative positions`) sit directly under it |

How they appear:
- A main heading is printed once, followed directly by its first sub-heading. **Later sub-headings in the same main section stand alone** after the previous `Total` (e.g. `Government Securities` 144 times, always inside `Debt Instruments`). So a parser must carry the main heading forward until the next main heading.
- Every sub-heading belongs to exactly one main heading in all 417 sheets, with two exceptions:
  - Fund-of-fund sheets in **Jul/Aug** (`NSDAQ100`, `BSLGRE`) start with a sub-heading (`Foreign Securities and /or overseas ETF`, `International Mutual Fund Units`) and **no main heading**. In Sep/Oct the same holdings sit under `Others`.
  - `Foreign Securities and /or overseas ETF` is under `Equity` for direct foreign shares (e.g. Microsoft in BSLNMF) and under `Others` / no main for overseas ETFs held by a fund of funds.
- `Others` is sometimes printed twice in one sheet (Oct BSLNMF, BSLGRE, BSLGCF). Harmless.
- `Debt Instruments` has two different spellings of "a) Listed…" from Equity's (`the stock exchanges` vs `Stock Exchanges`). Matching should be case-insensitive.
- Every sub-block ends with a `Total` row. `Total` % is sometimes rounded to 5 decimals (`0.97497`), sometimes full precision.

## 5. Draft section → asset_class mapping (D6)

Proposed to be decided by **(main, sub-heading)**, falling back to the sub-heading alone when there is no main, so the same holding gets the same class every month.

| Main | Sub-heading | asset_class | Note |
|---|---|---|---|
| Equity & Equity Related | a) Listed…, b) Unlisted | equity | |
| Equity & Equity Related | Foreign Securities and /or overseas ETF | equity | direct foreign shares |
| Debt Instruments | a) Listed…, b) Privately Placed/Unlisted, Government Securities, Securitised Debt | debt | |
| Money Market Instruments | Commercial Paper, Certificate of Deposits, Treasury Bills, STRIPS | debt | money market |
| Others | TREPS / Reverse Repo Investments | **debt** | D6 guess; see question Q2 |
| Others / none | Mutual Fund Units, International Mutual Fund Units, Exchange Traded Fund, Alternative Investment Funds, Infrastructure Investment Trust, Gold, Silver | other | |
| Others / none | Foreign Securities and /or overseas ETF | other | overseas ETF units held by a fund of funds |
| Other Current Assets / (Liabilities) | (rows directly under it) | other | net receivables, margin |

Anything not in the table is an UNKNOWN heading and goes into the parse report (FR-1.6); none exist in these four months.

## 6. The rating column (FR-0.2, task 0.4)

The `Industry^ / Rating` column holds an **industry for equity** rows and a **rating for debt** rows (out §5, §6).

| Section | What the column holds |
|---|---|
| Government Securities (central + `State Government Securities`) | `Sovereign` (all 2,293 rows) |
| Treasury Bills | `Sovereign` (148) |
| STRIPS | `Sovereign` (400) |
| TREPS rows (391) | empty |
| Reverse Repo rows (69) | `Sovereign` on 68; 18 of them carry a `GSECREPO…` code in the ISIN column |
| Commercial Paper, Certificate of Deposits | short-term ratings: `CRISIL A1+`, `ICRA A1+`, `CARE A1+`, `IND A1+` |
| Corporate debt | long-term: `CRISIL/ICRA/CARE/IND` + `AAA`, `AA+`, `AA`, `AA-`, `A+`, `A-` |
| Securitised Debt | `IND AAA(SO)`, `CRISIL AAA(SO)`, `ICRA AAA(SO)` |
| Infrastructure Investment Trust (InvIT) | an **industry**, not a rating: `Transport Infrastructure`, `Power` |
| Equity `b) Unlisted` | `Miscellaneous` (72), `Beverages` (4) |
| MF units, ETFs, AIFs, Gold, Silver, overseas funds | empty |

- So the government label is **`Sovereign`**, never `SOV`.
- `[ICRA]AAA` appears on 2 rows (vs 1,190 × `ICRA AAA`). The rating normaliser (FR-5.3) must treat them as the same.
- One Debt-listed row is rated `CARE A1+` (a short-term rating on a non-convertible preference share, Jul ADVG row 91).
- Full rating list with counts: out §6.

## 7. The `% to AUM` column

- Numbers are **fractions** of AUM. Holdings agree with value ÷ grand total to within 0.00001 (rounding), **except the rows below**.
- **Text `$0.00%`**: 571 holding cells + 32 `Total` cells (spec said 561). Footnote: "Less Than 0.01% of Net Asset Value". Value ÷ grand total is indeed < 0.01% on all of them **except 3 `Margin amount for Derivative positions` rows** (Jul + Aug BSLNMF: 0.52% and 0.51%; Aug BSL95F: 0.04%).
- **`Net Receivable / Payable` % is a balancing figure.** ABSL sets it so that the numeric % cells sum to exactly 100%, which ignores the `$0.00%` rows. Example: Oct BTMIDX shows −29.42%, value ÷ grand total is −29.80%; the gap (0.38%) equals the 110 `$0.00%` rows. 14 such rows in Aug–Oct are off by 0.01–0.4 points.
- **July is worse**: in 21 July sheets (22 rows), the Net Receivable or Margin % cell holds a number unrelated to its value (often the block's Total %). Example ADVG row 101: cell 1.09%, value ÷ grand total 0.15%. In BSLDAAF the Margin row shows 0.015% instead of 1.54%. As a result, the % column of these sheets sums to up to **101.7%** (ABSLMAAF). Full list: out §8, 36 rows.
- **Market values are always right**: value rows sum to the grand total in every sheet, and every `Total` value matches its rows.
- 77 holdings have market value **0** (`b) Unlisted` equity, written-down companies) with `$0.00%`.
- 188 `Net Receivable / Payable` rows are **negative** (net payable). Oct BTMIDX is the extreme: TREPS +30.1%, net payable −29.8% (a new fund settling its first purchases).

## 8. ISINs and rows without one

- No ISIN appears twice in the same sheet (no duplicates).
- Rows with value but **no ISIN** (942 over 4 months): `TREPS`, `Reverse Repo`, `Net Receivable / Payable` (one per sheet), `Margin amount for Derivative positions` (83). They count toward 100%.
- 56 rows have a value in the ISIN column that **fails the ISIN check digit**: 18 `GSECREPO…` codes (Reverse Repo rows) and 38 of the 44 `IDIA…` codes (dummy codes for unlisted securities; 6 pass the check digit by chance, so test the `IDIA` prefix too). Keep them as given but don't treat them as real ISINs in cross-scheme matching.
- Foreign ISINs: US 225, IE 29, GB 20, JP 16, LU 9 and a few others (out §8).

## 9. End of the portfolio block

- **Every one of the 417 sheets has a `GRAND TOTAL (AUM)` row** with % = 1.0.
- Below it: footnotes (`^Industry classification…`, `** Thinly Traded…`, `# Unlisted Security`, `$ Less Than 0.01%…`), then `Notes:` (NAV per plan for this and last month, IDCW per unit, derivative tables, average maturity), then a benchmark line as the last row: `<scheme name> | <benchmark index>`. 63 sheets have a small `Scheme name / benchmark` table instead.
- **Trap, Sep BSLIF row 207**: a STRIPS holding (ISIN `IN000438C043`, value 1,003.00, inside the STRIPS block) whose name cell says `Notes:`. In the other 11 sheets that hold this ISIN the name is `0% GOI - (15/04/2038) STRIPS`. It's the only footnote-looking text before a grand total in all 417 sheets. **Rule: the block ends at `GRAND TOTAL (AUM)`, never at the first `Notes:`/footnote text.**

## 10. Totals check (FR-0.3, out §9)

| Check | Result |
|---|---|
| Sum of value rows vs `GRAND TOTAL (AUM)` value | equal in all 417 sheets (max diff < 0.01 lakh) |
| Each `Total` value vs its rows | equal everywhere |
| Sum of % cells (+ `$` rows computed) vs 100% | within 0.05 points in 395 sheets; the 22 others are all explained by §7 (19 July sheets, BSLNMF Aug, BTMIDX/BTMETF Oct) |
| Sheets missing a grand total | none |

## 11. Corrections to SPEC §3

| Spec says | Data shows |
|---|---|
| §3.2 "Merged cells: none in any of the 417 scheme sheets" | 1,436 merged ranges, all in the title/header rows or below the grand total; none inside a portfolio block |
| §3.2 "561 cells hold `$0.00%`" | 571 holding cells + 32 Total cells = 603 |
| §3.2 "No `SOV` label was found; checked in Phase 0" | The label is `Sovereign` (gilts, SDLs, T-bills, STRIPS, some Reverse Repo) |
| §3.3 "No `GRAND TOTAL (AUM)` row in Sep BSLIF" | It exists (row 229). The `Notes:` name at row 207 made the earlier check stop early |
| §3.3 "Extra ESG columns: 4 sheets per month" | 1 sheet per month (`ABSLESG`), 4 in total |
| §3.2 lists `Securitised Debt` and `Government Securities` as main sections | They are sub-headings under `Debt Instruments`; there are 5 main headings (§4) |
| — (new) | Net Receivable % is a balancing figure; July % cells are wrong for Net Receivable / Margin rows (§7) |

Applied to SPEC.md §3 in v0.4 (Phase 1).

## 12. Proposed parser rules for Phase 1

| # | Rule | Why |
|---|---|---|
| R1 | Find the header by the text `Name of the Instrument`; map columns by header text after collapsing whitespace. | Same row 4 everywhere today, ESG adds columns. |
| R2 | The block runs from header + 1 to the `GRAND TOTAL (AUM)` row. If there's no grand total, fall back to the first footnote / `Notes:` row and report it. | §9 trap. |
| R3 | Main heading = one of the 5 fixed texts (case-insensitive). Any other heading = sub-heading; it keeps the current main heading. A new main heading clears the sub-heading. Before any main heading, main = none. | §4. |
| R4 | asset_class from the (main, sub) table in §5, with fallback on the sub-heading. | Same holding, same class every month. |
| R5 | Holding = any block row with a numeric market value that isn't `Total` / `GRAND TOTAL`. Keep zero-value and negative rows. | §7, §8. |
| R6 | `pct` = the % cell, except: `$0.00%` → value ÷ grand total, flag `pct_computed`; **all rows under `Other Current Assets / (Liabilities)` → value ÷ grand total, flag `pct_computed`**. | §7: these cells are wrong or plugs. |
| R7 | Keep the name as written, and flag a holding whose name looks like a footnote marker (`name_suspect`). Don't fill names from other months. | Parser stays honest; report lists it. |
| R8 | Keep the ISIN column as given; add `isin_valid` (check digit passes and no `IDIA`/`GSECREPO` prefix). | §8. |
| R9 | FR-1.9 merged-cell assertion applies to the block rows only. | §3. |
| R10 | Validation tolerances: values 1 lakh; % 0.0005 (0.05 points) after R6; a `Total` % may be 5-decimal rounded. | §4, §10. |

## 13. Questions for you

- **Q1. % rule (R6).** Compute % from value ÷ grand total for the `Other Current Assets` rows (recommended), or keep ABSL's cell and only flag it? Keeping it would make July % sums reach 101.7%.
- **Q2. TREPS / Reverse Repo asset class.** `debt` (the D6 guess: it's short-term lending against government securities), or `other` (closer to "cash")? I recommend `debt`, as D6 said.
- **Q3. `Notes:` name (R7).** Keep the raw name and flag it (recommended), or fill the real name `0% GOI - (15/04/2038) STRIPS` from the other months? Note it's in **September**, the evaluation month, so it will show up in chunks.
- **Q4. Spec update.** OK to apply the §11 corrections to SPEC.md §3 in the Phase 1 branch?

**Answers (11 Nov 2026), all as recommended:** Q1 compute from value ÷ grand total (flag `recomputed`); Q2 TREPS / Reverse Repo → `debt`; Q3 keep the raw name and flag it (`name_suspect`); Q4 SPEC.md §3 corrected in the Phase 1 branch.

**Found while building Phase 1:** `ABSLESG` row 61 in Sep and Oct has a number only in the ESG score column, under the equity `Total` (a weighted ESG score). It is not a holding; the parser ignores rows whose only filled cells are unmapped columns and lists them in `results/parse_report.md` §7.
