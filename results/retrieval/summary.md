# Retrieval benchmark, Stage B (end to end, real LLM answers)

Written by `python -m src.retrieval report` from `results/retrieval/results.csv` (264 rows: 3 shortlisted methods × 88 test questions). Stage A, the free offline comparison of all eight methods, is in [`offline_summary.md`](offline_summary.md).

|  |  |
| --- | --- |
| LLM | `x-ai/grok-4.20` (temperature 0) |
| Embedding | `BAAI/bge-small-en-v1.5`, candidate_k 20, top_k 5 |
| Reranker | `BAAI/bge-reranker-base` @ `2cfc18c9415c` |
| Question set | `test`, sha256 `a74a671f8bfc2e49…` |
| Run | started 2026-11-24T10:14:17+05:30, 2 session(s), last finished 2026-11-24T10:25:50+05:30 |
| Rows | 264 of 264, 0 pending |
| Cached answers | 131 of 264 (byte-identical prompt, same model — RD7) |
| Model check (§12) | same answers — M1 re-asked with the cache off on 3 questions, `x-ai/grok-4.20` |

## 1. Verdict

**Best retrieval method for this data: M8 best_combo (final for this run).**

Rule, fixed before the paid run (§6.5): most correct answers on the test set; a tie goes to higher context gold-row recall, then to fewer prompt tokens per question, then to lower retrieval latency. The verdict is computed by code (`src/retrieval/verdict.py`), not written by hand. Full detail: [`retrieval_report.xlsx`](retrieval_report.xlsx).

- Most correct answers: 76% (67/88), 2 more than the runner-up M6 scheme_filter (74%, 65/88).
- Against the reference M1 dense (M1, the method the chunking run used): +10 correct answers, context gold-row recall 100% vs 92%, 3,121 vs 5,445 prompt tokens per question.
- Highest accuracy (alone or tied) on: lookup (100%), aggregation (59%), debt (38%), cross_scheme (88%), unanswerable (100%).
- Weakest on debt: 38% (6/16). 8 of its 10 wrong answers are labelled generation error: the rows were there but the LLM still answered wrong.
- Weakest on aggregation: 59% (13/22). 8 of its 9 wrong answers are labelled generation error: the rows were there but the LLM still answered wrong.
- Cost: 3,121 prompt tokens per question (2,526 of them the retrieved sections); the cheapest is M6 scheme_filter (2,965).
- Retrieval latency: 19 ms median per question, measured after the models are loaded; the LLM call dominates the rest (3,295 ms per question in all).
- Refusals: says the data does not contain the answer on 12 of 12 unanswerable questions, and wrongly refuses 5 of 76 answerable ones.

> The lead over M6 scheme_filter is small (2 correct answer(s) out of 88); with this few questions it could be noise.  

| # | method | settings | correct | accuracy | context gold rows | prompt tok | median retrieval ms | note |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | M8 best_combo | filter=True, ranker=mmr | 67/88 | 76% | 100% | 3,121 | 19 | best |
| 2 | M6 scheme_filter | fuzzy_threshold=0.85, ranker=dense | 65/88 | 74% | 99% | 2,965 | 7 | 2 fewer correct than M8 best_combo; biggest gap on debt (25% vs 38%); most wrong answers are generation error (18 of 23) |
| 3 | M1 dense | – | 57/88 | 65% | 92% | 5,445 | 6 | 10 fewer correct than M8 best_combo; biggest gap on cross_scheme (44% vs 88%); most wrong answers are generation error (19 of 31) |

**Best method per question type** (same rule; input for a router later, not used by the pipeline):

| question type | questions | best | accuracy | runner-up | its accuracy | decided by |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| lookup | 22 | **M6 scheme_filter** | 100% | M8 best_combo | 100% | fewer prompt tokens (tied on accuracy and recall) |
| aggregation | 22 | **M6 scheme_filter** | 59% | M8 best_combo | 59% | fewer prompt tokens (tied on accuracy and recall) |
| debt | 16 | **M8 best_combo** | 38% | M1 dense | 31% | accuracy |
| cross_scheme | 16 | **M6 scheme_filter** | 88% | M8 best_combo | 88% | fewer prompt tokens (tied on accuracy and recall) |
| unanswerable | 12 | **M6 scheme_filter** | 100% | M1 dense | 100% | fewer prompt tokens (tied on accuracy and recall) |

**Is the lead real?** Paired bootstrap, 10,000 resamples, seed 42 (§6.5, RD8):

- M8 best_combo vs M1 dense on correct: +0.114 (95% +0.045 to +0.193), so M8 best_combo is better than M1 dense here. (88 paired questions)
- M8 best_combo vs M1 dense on section_recall@5: +0.079 (95% +0.033 to +0.138), so M8 best_combo is better than M1 dense here. (76 paired questions)

## 2. Accuracy by method and question type

Correct answers / questions. An unanswerable question counts as correct when the method says the data does not contain the answer.

| Method | lookup (22) | aggregation (22) | debt (16) | cross_scheme (16) | unanswerable (12) | overall (88) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **M1 dense** | 100% (22/22) | 50% (11/22) | 31% (5/16) | 44% (7/16) | 100% (12/12) | **65% (57/88)** |
| **M6 scheme_filter** | 100% (22/22) | 59% (13/22) | 25% (4/16) | 88% (14/16) | 100% (12/12) | **74% (65/88)** |
| **M8 best_combo** | 100% (22/22) | 59% (13/22) | 38% (6/16) | 88% (14/16) | 100% (12/12) | **76% (67/88)** |

## 3. Retrieval and the context the LLM saw

Answerable questions only. *Hit*: at least one gold row reached the LLM. *Context gold-row recall*: share of the gold rows in the context after the parent swap — the verdict's first tie-break. Context tokens use the embedding tokenizer; prompt tokens are the LLM's count of the whole prompt, so the gap between them is the instructions and the question.

| Method | Hit | Context gold-row recall | Sections | Holding rows | Context tokens | Prompt tokens | Accuracy (answerable) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **M1 dense** | 96% (73/76) | 92% | 2.6 | 141 | 4,778 | 5,445 | 59% (45/76) |
| **M6 scheme_filter** | 99% (75/76) | 99% | 1.7 | 67 | 2,378 | 2,965 | 70% (53/76) |
| **M8 best_combo** | 100% (76/76) | 100% | 1.9 | 71 | 2,526 | 3,121 | 72% (55/76) |

## 4. Tokens and latency

Means per question, except the median retrieval latency. A cached answer carries the latency of its original call, so generation times mix old and new calls; retrieval latency is this run's own measurement.

| Method | Prompt tok | Completion tok | Total tok (all questions) | Retrieval ms (median) | Retrieval ms (mean) | Generation ms | Total ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **M1 dense** | 5,445 | 354 | 510,283 | 6 | 7 | 3,426 | 3,433 |
| **M6 scheme_filter** | 2,965 | 365 | 293,029 | 7 | 8 | 3,341 | 3,349 |
| **M8 best_combo** | 3,121 | 342 | 304,766 | 19 | 20 | 3,276 | 3,295 |

## 5. Refusals, status and failure kinds

| Method | Unanswerable: correctly refused | Answerable: refused anyway |
| --- | ---: | ---: |
| **M1 dense** | 100% (12/12) | 13% (10/76) |
| **M6 scheme_filter** | 100% (12/12) | 7% (5/76) |
| **M8 best_combo** | 100% (12/12) | 7% (5/76) |

| Method | Non-ok status | Wrong answers by kind |
| --- | --- | --- |
| **M1 dense** | format_error 5 | generation error 19, retrieval miss 7, format error 5 |
| **M6 scheme_filter** | format_error 4 | generation error 18, format error 4, retrieval miss 1 |
| **M8 best_combo** | format_error 3 | generation error 18, format error 3 |

*retrieval miss*: not every gold row reached the LLM; *generation error*: the rows were there and the answer is still wrong; *format error*: the reply broke the JSON format; *context overflow*: the provider refused the prompt as too large. For a method that filters by scheme, a retrieval miss is refined to *filter_miss* (the question's own scheme was not found) or *filter_wrong* (a scheme the gold rows do not use was searched) — R4.4.

| Method | Rows | filter_miss | filter_wrong | context gold-row recall | accuracy |
| --- | --- | ---: | ---: | ---: | ---: |
| **M6 scheme_filter** | 76 | 0 | 0 | 99% | 70% |
| **M8 best_combo** | 76 | 0 | 0 | 100% | 72% |

## 6. Failure examples

Up to three wrong answers per method, different kinds first.

### M1 dense

- **Q08** (aggregation) · *generation error*, context gold-row recall 100%  
  Q: What is the total % of AUM in equity holdings of the Banks industry for Aditya Birla Sun Life Flexi Cap Fund as on 30 Sep 2026?  
  Gold: 19.239918634537645 pct  
  Given: value 18.23 pct ("The total % of AUM in equity holdings of the Banks industry is 18.23%.")
- **Q14** (aggregation) · *format error*, context gold-row recall 100%  
  Q: What is the total % of AUM in the Equity & Equity Related section of Aditya Birla Sun Life Aggressive Hybrid Fund as on 30 Sep 2026?  
  Gold: 76.18333853980906 pct  
  Given: status `format_error`: not valid JSON: Unterminated string starting at: line 1 column 6263 (char 6262) (reply cut at max_output_tokens)
- **Q21** (cross_scheme) · *retrieval miss*, context gold-row recall 50%  
  Q: Which holds more HDFC Bank Ltd. as a % of AUM as on 30 Sep 2026: Aditya Birla Sun Life Flexi Cap Fund or Aditya Birla Sun Life Value Fund?  
  Gold: "PURE"  
  Given: value 3.91 pct ("Aditya Birla Sun Life Flexi Cap Fund holds 3.91% of AUM in HDFC Bank Ltd.")

### M6 scheme_filter

- **Q08** (aggregation) · *generation error*, context gold-row recall 100%  
  Q: What is the total % of AUM in equity holdings of the Banks industry for Aditya Birla Sun Life Flexi Cap Fund as on 30 Sep 2026?  
  Gold: 19.239918634537645 pct  
  Given: value 18.23 pct ("The total % of AUM in equity holdings of the Banks industry is 18.23%.")
- **Q14** (aggregation) · *format error*, context gold-row recall 100%  
  Q: What is the total % of AUM in the Equity & Equity Related section of Aditya Birla Sun Life Aggressive Hybrid Fund as on 30 Sep 2026?  
  Gold: 76.18333853980906 pct  
  Given: status `format_error`: not valid JSON: Unterminated string starting at: line 1 column 6263 (char 6262) (reply cut at max_output_tokens)
- **T033** (debt) · *retrieval miss*, context gold-row recall 0%  
  Q: As on 30 September 2026, what % of the AUM of Aditya Birla Sun Life Medium to Long Term Fund is held in Certificate of Deposits, as listed under Money Market Instruments?  
  Gold: 1.34743127370151 pct  
  Given: "The provided context does not list any holdings under Money Market Instruments or Certificate of Deposits for this scheme."

### M8 best_combo

- **Q08** (aggregation) · *generation error*, context gold-row recall 100%  
  Q: What is the total % of AUM in equity holdings of the Banks industry for Aditya Birla Sun Life Flexi Cap Fund as on 30 Sep 2026?  
  Gold: 19.239918634537645 pct  
  Given: value 15.21 pct ("The total % of AUM in equity holdings of the Banks industry is 15.21%.")
- **Q14** (aggregation) · *format error*, context gold-row recall 100%  
  Q: What is the total % of AUM in the Equity & Equity Related section of Aditya Birla Sun Life Aggressive Hybrid Fund as on 30 Sep 2026?  
  Gold: 76.18333853980906 pct  
  Given: status `format_error`: not valid JSON: Unterminated string starting at: line 1 column 6263 (char 6262) (reply cut at max_output_tokens)
- **Q09** (aggregation) · *generation error*, context gold-row recall 100%  
  Q: What is the total % of AUM in equity holdings of the IT - Software industry for Aditya Birla Sun Life Digital India Fund as on 30 Sep 2026?  
  Gold: 57.005349052224894 pct  
  Given: value 55.01 pct ("The total % of AUM in equity holdings of the IT - Software industry is 55.01%.")

## 7. What the run cost

Tokens only: prices are not kept in this repo (RD11). One row per paid run, from [`spend_log.csv`](spend_log.csv).

| At (IST) | Phase | Questions | Calls | Cached | Paid calls | Prompt tok | Completion tok | Total tok | Estimated tok | Cap | Stopped |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-11-24 10:14 | smoke | 3 | 12 | 5 | 7 | 40,256 | 926 | 41,182 | 24,388 | 55,000 | – |
| 2026-11-24 10:25 | full | 88 | 255 | 126 | 129 | 483,924 | 35,144 | 519,068 | 840,562 | 900,000 | – |

The last run used 519,068 tokens against an estimate of 840,562 (62% of it): the estimate assumes every uncached call is paid at the predicted prompt size, and answers that came from the cache during the run made it cheaper.
