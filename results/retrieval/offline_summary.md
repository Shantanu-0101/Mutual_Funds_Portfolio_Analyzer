# Retrieval benchmark, Stage A (offline, no LLM call)

Question set `test`: 88 questions, 76 of them answerable (retrieval metrics use those). Every method ranks 20 children per question; the pipeline sends the top 5 after the parent swap.

**Best offline (§6.5): M8 best_combo** — mean `section_recall@5` 100%, `hit@5` 89%, `mrr@10` 0.773, median 7 ms.

**Shortlist for Stage B (RD6): M8 best_combo, M6 scheme_filter, M1 dense** — the top 2 plus M1 `dense` as the reference.

## 1. Leaderboard (set `test`)

| # | method | settings | section recall@5 | hit@5 | mrr@10 | row recall@5 | scheme recall@5 | context gold rows | context tokens | median ms | p90 ms | Stage B |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | M8 best_combo | filter=True, ranker=mmr | 100% | 89% | 0.773 | 55% | 100% | 100% | 2,526 | 7 | 18 | yes |
| 2 | M6 scheme_filter | fuzzy_threshold=0.85, ranker=dense | 99% | 88% | 0.762 | 54% | 100% | 99% | 2,378 | 8 | 17 | yes |
| 3 | M7 mmr | depth=50, lambda=0.7 | 94% | 80% | 0.704 | 46% | 96% | 94% | 6,521 | 6 | 9 |  |
| 4 | M3 hybrid_rrf | depth=20, rrf_k=60 | 93% | 84% | 0.795 | 55% | 93% | 93% | 4,504 | 5 | 6 |  |
| 5 | M1 dense | – | 92% | 86% | 0.718 | 49% | 95% | 92% | 4,778 | 5 | 6 | yes |
| 6 | M5 hybrid_rerank | depth=50, hybrid_depth=50 | 90% | 88% | 0.682 | 59% | 91% | 90% | 4,364 | 8,427 | 9,612 |  |
| 7 | M2 bm25 | b=0.9, k1=2.0 | 88% | 79% | 0.719 | 54% | 89% | 88% | 4,965 | 1 | 1 |  |
| 8 | M4 dense_rerank | depth=20 | 87% | 84% | 0.747 | 52% | 89% | 87% | 3,829 | 4,171 | 6,658 |  |

Ranked by mean `section_recall@5`; ties by `hit@5`, then `mrr@10`, then lower median latency (§6.5). Latency is measured after the models are loaded, so the reranker's cost is the uncached one. `context gold rows` and `context tokens` describe the top 5 **after** the parent swap: the context the LLM would see.

## 2. `section_recall@5` by question type

| method | lookup | aggregation | debt | cross_scheme | overall |
| --- | ---: | ---: | ---: | ---: | ---: |
| M8 best_combo | 100% | 100% | 100% | 100% | 100% |
| M6 scheme_filter | 100% | 100% | 94% | 100% | 99% |
| M7 mmr | 100% | 100% | 94% | 78% | 94% |
| M3 hybrid_rrf | 100% | 95% | 100% | 75% | 93% |
| M1 dense | 100% | 100% | 88% | 75% | 92% |
| M5 hybrid_rerank | 100% | 91% | 88% | 78% | 90% |
| M2 bm25 | 91% | 86% | 94% | 81% | 88% |
| M4 dense_rerank | 100% | 95% | 81% | 62% | 87% |

**Best method per type** (same rule; input for a router later, not used now):

| type | questions | best | its recall@5 | runner-up | its recall@5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| lookup | 22 | M4 dense_rerank | 100% | M5 hybrid_rerank | 100% |
| aggregation | 22 | M6 scheme_filter | 100% | M1 dense | 100% |
| debt | 16 | M8 best_combo | 100% | M3 hybrid_rrf | 100% |
| cross_scheme | 16 | M8 best_combo | 100% | M6 scheme_filter | 100% |

## 3. `section_recall@k`

| method | k=1 | k=3 | k=5 | k=10 | k=20 |
| --- | ---: | ---: | ---: | ---: | ---: |
| M8 best_combo | 84% | 100% | 100% | 100% | 100% |
| M6 scheme_filter | 84% | 97% | 99% | 99% | 99% |
| M7 mmr | 78% | 91% | 94% | 95% | 97% |
| M3 hybrid_rrf | 84% | 93% | 93% | 98% | 98% |
| M1 dense | 78% | 90% | 92% | 94% | 95% |
| M5 hybrid_rerank | 66% | 84% | 90% | 96% | 97% |
| M2 bm25 | 71% | 87% | 88% | 93% | 96% |
| M4 dense_rerank | 76% | 87% | 87% | 93% | 95% |

The pipeline uses k = 5. A big jump from k=5 to k=10 or 20 means the right section is found but ranked too low.

## 4. The 28 hand-written questions on their own

| method | 28 hand-written: recall@5 | hit@5 | 60 generated: recall@5 | hit@5 |
| --- | ---: | ---: | ---: | ---: |
| M8 best_combo | 100% | 96% | 100% | 87% |
| M6 scheme_filter | 100% | 96% | 98% | 85% |
| M1 dense | 96% | 96% | 90% | 81% |
| M3 hybrid_rrf | 96% | 88% | 92% | 83% |
| M7 mmr | 96% | 88% | 93% | 77% |
| M4 dense_rerank | 90% | 92% | 86% | 81% |
| M5 hybrid_rerank | 90% | 92% | 90% | 87% |
| M2 bm25 | 81% | 79% | 91% | 79% |

The generated questions copy scheme and instrument names from the data, which flatters keyword search and the scheme filter (§12); the hand-written ones are the honest check. The reported verdict uses the whole set, as the spec fixes it.

## 5. Settings chosen on dev, and M8

| method | variants tried | chosen | dev recall@5 | dev hit@5 | dev mrr@10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| M1 dense | 1 | – | 96% | 85% | 0.685 |
| M2 bm25 | 9 | b=0.9, k1=2.0 | 84% | 82% | 0.773 |
| M3 hybrid_rrf | 3 | depth=20, rrf_k=60 | 91% | 88% | 0.846 |
| M4 dense_rerank | 2 | depth=20 | 94% | 88% | 0.832 |
| M5 hybrid_rerank | 2 | depth=50, hybrid_depth=50 | 90% | 85% | 0.715 |
| M6 scheme_filter | 3 | fuzzy_threshold=0.85, ranker=dense | 100% | 88% | 0.716 |
| M7 mmr | 3 | depth=50, lambda=0.7 | 97% | 85% | 0.695 |

Chosen on dev only, by mean `section_recall@5` with the §6.5 tie-breaks, and written into `config.yaml` with the date (FR-R2.3). Test scores were computed after that.

**M8 `best_combo` = filter=True, ranker=mmr** (declared from dev, before any test score, R3.4). The candidates:

| # | candidate | dev recall@5 | dev hit@5 | dev mrr@10 | median ms |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | filter=True, ranker=mmr | 100% | 94% | 0.739 | 8 |
| 2 | filter=True, ranker=hybrid_rerank | 100% | 91% | 0.771 | 8 |
| 3 | filter=True, ranker=dense | 100% | 88% | 0.716 | 5 |
| 4 | filter=True, ranker=dense_rerank | 97% | 91% | 0.832 | 7 |
| 5 | filter=False, ranker=mmr | 97% | 85% | 0.695 | 6 |
| 6 | filter=False, ranker=dense | 96% | 85% | 0.685 | 5 |
| 7 | filter=True, ranker=hybrid_rrf | 94% | 88% | 0.846 | 7 |
| 8 | filter=False, ranker=dense_rerank | 94% | 88% | 0.832 | 5 |
| 9 | filter=False, ranker=hybrid_rrf | 91% | 88% | 0.846 | 7 |
| 10 | filter=True, ranker=bm25 | 91% | 88% | 0.813 | 1 |
| 11 | filter=False, ranker=hybrid_rerank | 90% | 85% | 0.715 | 11 |
| 12 | filter=False, ranker=bm25 | 84% | 82% | 0.773 | 1 |

The candidates ran after the grid above, so a candidate with a cross-encoder read its scores from the disk cache and its `median ms` here is **not** the uncached cost. The leaderboard's latency (table 1) is the first, uncached run of each method on this set.

## 6. Is the lead real? (paired bootstrap, 10,000 resamples, seed 42)

- M8 best_combo vs M1 dense on section_recall@5: +0.079 (95% +0.033 to +0.138), so M8 best_combo is better than M1 dense here.
- M6 scheme_filter vs M1 dense on section_recall@5: +0.066 (95% +0.026 to +0.112), so M6 scheme_filter is better than M1 dense here.
- M7 mmr vs M1 dense on section_recall@5: +0.020 (95% +0.000 to +0.053). The interval includes 0, so M7 mmr is not distinguishable from M1 dense on this question set.

The same interval for end-to-end `correct` follows in Stage B (§6.5).

## 7. The scheme filter on real questions

| method | questions | filter_miss | filter_wrong | recall@5 |
| --- | ---: | ---: | ---: | ---: |
| M6 scheme_filter | 76 | 0 | 0 | 99% |
| M8 best_combo | 76 | 0 | 0 | 100% |

`filter_miss`: the question's own scheme was not found (the method then searches everything, as M1 does). `filter_wrong`: a scheme the gold rows do not use was found — a fund-of-funds question naming another AMC's fund does this (R2 notes, D031).
