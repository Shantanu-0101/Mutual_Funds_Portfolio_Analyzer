# Chunk stats (Phase 2)

| | |
|---|---|
| Generated | 11 Nov 2026 15:49 IST by `python -m src.chunking --month 2026-09-30` |
| Month | 2026-09-30 |
| Schemes | 104 |
| Holdings | 5,646 |
| Tokenizer | `BAAI/bge-small-en-v1.5` (tokens = word pieces + 2 special tokens, what the embedding model sees) |
| Truncated means | more than 512 tokens: the embedding only sees the start of the chunk |

## 1. Per chunker

| Chunker | Options | Chunks | Avg tokens | Median | Max | Truncated | Total tokens | Avg rows / chunk | Holdings covered | Holdings in >1 chunk |
|---|---|---|---|---|---|---|---|---|---|---|
| fixed_size | chunk_tokens=256, overlap_tokens=32 | 942 | 245.1 | 258 | 259 | 0 (0.0%) | 230,929 | 7.7 | 5,646 | 1,569 |
| row_wise | – | 5,646 | 105.6 | 103 | 141 | 0 (0.0%) | 596,048 | 1.0 | 5,646 | 0 |
| header_window | rows_per_chunk=10 | 622 | 384.2 | 385 | 556 | 75 (12.1%) | 238,971 | 9.1 | 5,646 | 0 |
| scheme_level | on_overflow=truncate_and_warn | 104 | 1,946.9 | 1,561 | 8,823 | 78 (75.0%) | 202,482 | 54.3 | 5,646 | 0 |
| section_aware | max_tokens=512 | 707 | 341.7 | 476 | 512 | 0 (0.0%) | 241,548 | 8.0 | 5,646 | 0 |
| hierarchical | child=row, parent=section | 5,646 | 105.6 | 103 | 141 | 0 (0.0%) | 596,048 | 1.0 | 5,646 | 0 |

`hierarchical` parents (sent to the LLM, never embedded): 707 parents, avg 341.7 tokens, max 512, 8.0 rows each, 5,646 holdings covered.

Truncation only affects the embedding (retrieval). The full chunk text is stored and sent to the LLM.

## 2. Largest chunks per chunker

| Chunker | Chunk id | Scheme | Tokens | Rows |
|---|---|---|---|---|
| fixed_size | `fixed_size:2026-09-30:BBP:1` | ADITYA BIRLA SUN LIFE ULTRA SHORT TERM FUND (FORMERLY KNOWN AS ADITYA BIRLA SUN LIFE SAVINGS FUND) | 259 | 6 |
| fixed_size | `fixed_size:2026-09-30:BSL95F:10` | ADITYA BIRLA SUN LIFE AGGRESSIVE HYBRID FUND (FORMERLY KNOWN AS ADITYA BIRLA SUN LIFE EQUITY HYBRID '95 FUND) | 259 | 9 |
| fixed_size | `fixed_size:2026-09-30:BSLMTP:9` | ADITYA BIRLA SUN LIFE MEDIUM TERM FUND (FORMERLY KNOWN AS ADITYA BIRLA SUN LIFE MEDIUM TERM PLAN) | 259 | 7 |
| row_wise | `row_wise:2026-09-30:BSL95F:90` | ADITYA BIRLA SUN LIFE AGGRESSIVE HYBRID FUND (FORMERLY KNOWN AS ADITYA BIRLA SUN LIFE EQUITY HYBRID '95 FUND) | 141 | 1 |
| row_wise | `row_wise:2026-09-30:BBP:40` | ADITYA BIRLA SUN LIFE ULTRA SHORT TERM FUND (FORMERLY KNOWN AS ADITYA BIRLA SUN LIFE SAVINGS FUND) | 139 | 1 |
| row_wise | `row_wise:2026-09-30:BSLCM:7` | ADITYA BIRLA SUN LIFE ULTRA SHORT TO SHORT TERM FUND (FORMERLY KNOWN AS ADITYA BIRLA SUN LIFE LOW DURATION FUND) | 139 | 1 |
| header_window | `header_window:2026-09-30:BBP:0` | ADITYA BIRLA SUN LIFE ULTRA SHORT TERM FUND (FORMERLY KNOWN AS ADITYA BIRLA SUN LIFE SAVINGS FUND) | 556 | 10 |
| header_window | `header_window:2026-09-30:BSLCM:0` | ADITYA BIRLA SUN LIFE ULTRA SHORT TO SHORT TERM FUND (FORMERLY KNOWN AS ADITYA BIRLA SUN LIFE LOW DURATION FUND) | 555 | 10 |
| header_window | `header_window:2026-09-30:BSLCM:1` | ADITYA BIRLA SUN LIFE ULTRA SHORT TO SHORT TERM FUND (FORMERLY KNOWN AS ADITYA BIRLA SUN LIFE LOW DURATION FUND) | 555 | 10 |
| scheme_level | `scheme_level:2026-09-30:BFL:0` | ADITYA BIRLA SUN LIFE FLOATING INTEREST RATES FUND (FORMERLY KNOWN AS ADITYA BIRLA SUN LIFE FLOATING RATE FUND) | 8,823 | 211 |
| scheme_level | `scheme_level:2026-09-30:BSLIF:0` | ADITYA BIRLA SUN LIFE CORPORATE BOND FUND | 8,276 | 190 |
| scheme_level | `scheme_level:2026-09-30:CASH:0` | ADITYA BIRLA SUN LIFE LIQUID FUND | 8,124 | 193 |
| section_aware | `section_aware:2026-09-30:ABSLCONF:1` | ADITYA BIRLA SUN LIFE CONGLOMERATE FUND | 512 | 14 |
| section_aware | `section_aware:2026-09-30:BBIF:4` | ADITYA BIRLA SUN LIFE SHORT TERM FUND | 512 | 10 |
| section_aware | `section_aware:2026-09-30:BBP:0` | ADITYA BIRLA SUN LIFE ULTRA SHORT TERM FUND (FORMERLY KNOWN AS ADITYA BIRLA SUN LIFE SAVINGS FUND) | 512 | 9 |
| hierarchical | `hierarchical:2026-09-30:BSL95F:90` | ADITYA BIRLA SUN LIFE AGGRESSIVE HYBRID FUND (FORMERLY KNOWN AS ADITYA BIRLA SUN LIFE EQUITY HYBRID '95 FUND) | 141 | 1 |
| hierarchical | `hierarchical:2026-09-30:BBP:40` | ADITYA BIRLA SUN LIFE ULTRA SHORT TERM FUND (FORMERLY KNOWN AS ADITYA BIRLA SUN LIFE SAVINGS FUND) | 139 | 1 |
| hierarchical | `hierarchical:2026-09-30:BSLCM:7` | ADITYA BIRLA SUN LIFE ULTRA SHORT TO SHORT TERM FUND (FORMERLY KNOWN AS ADITYA BIRLA SUN LIFE LOW DURATION FUND) | 139 | 1 |

