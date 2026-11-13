# RAG sample (Phase 3)

| | |
|---|---|
| Generated | 13 Nov 2026 08:28 IST by `python -m src.rag` |
| Question | What % of AUM does the Flexi Cap Fund hold in ICICI Bank as on 30 Sep 2026? |
| LLM | groq / openai/gpt-oss-120b, temperature 0, reasoning low |
| Retrieval | top_k 5, filter: none |

## fixed_size

- status: **ok**
- answer: The Flexi Cap Fund holds 5.60% of its AUM in ICICI Bank as on 30 Sep 2026.
- value: 5.6 pct | insufficient_context: False
- cited rows: [8]
- tokens: prompt 1,740, completion 183 (reasoning 97) [cached]
- latency: retrieval 121 ms, generation 1,871 ms
- context: 5 chunks, 34 holding rows
- retrieved:
  1. `fixed_size:2026-09-30:BSLEQTY:0` score 0.787, 258 tokens
  2. `fixed_size:2026-09-30:ABSLMCF:0` score 0.749, 258 tokens
  3. `fixed_size:2026-09-30:ADVG:0` score 0.733, 258 tokens
  4. `fixed_size:2026-09-30:BSLFEF:0` score 0.732, 258 tokens
  5. `fixed_size:2026-09-30:BSLR96:0` score 0.729, 258 tokens

## row_wise

- status: **ok**
- answer: The Flexi Cap Fund holds 5.60% of its AUM in ICICI Bank as on 30 Sep 2026.
- value: 5.6 pct | insufficient_context: False
- cited rows: [8]
- tokens: prompt 900, completion 110 (reasoning 24) [cached]
- latency: retrieval 87 ms, generation 867 ms
- context: 5 chunks, 5 holding rows
- retrieved:
  1. `row_wise:2026-09-30:BSLEQTY:0` score 0.815, 101 tokens
  2. `row_wise:2026-09-30:BSLEQTY:85` score 0.775, 91 tokens
  3. `row_wise:2026-09-30:BSLEQTY:22` score 0.770, 100 tokens
  4. `row_wise:2026-09-30:BSLEQTY:4` score 0.769, 100 tokens
  5. `row_wise:2026-09-30:BSLEQTY:75` score 0.769, 101 tokens

## header_window

- status: **ok**
- answer: The Flexi Cap Fund holds 5.60% of its AUM in ICICI Bank as on 30 Sep 2026.
- value: 5.6 pct | insufficient_context: False
- cited rows: [8]
- tokens: prompt 2,419, completion 111 (reasoning 25) [cached]
- latency: retrieval 101 ms, generation 1,260 ms
- context: 5 chunks, 50 holding rows
- retrieved:
  1. `header_window:2026-09-30:BSLEQTY:0` score 0.775, 392 tokens
  2. `header_window:2026-09-30:BSLEQTY:2` score 0.774, 391 tokens
  3. `header_window:2026-09-30:BSLEQTY:3` score 0.760, 392 tokens
  4. `header_window:2026-09-30:BSLEQTY:1` score 0.754, 388 tokens
  5. `header_window:2026-09-30:BSLEQTY:7` score 0.746, 394 tokens

## scheme_level

- status: **context_overflow** (Error code: 413 - {'error': {'message': 'Request too large for model `openai/gpt-oss-120b` in organization `org_<redacted>` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Requested 13268, please reduce your message size and try again. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', 'type': 'tokens', 'code': 'rate_limit_exceeded'}})
- tokens: prompt 0, completion 0
- latency: retrieval 66 ms, generation 0 ms
- context: 5 chunks, 378 holding rows
- retrieved:
  1. `scheme_level:2026-09-30:BSLEQTY:0` score 0.774, 2,831 tokens
  2. `scheme_level:2026-09-30:ABSLMCF:0` score 0.734, 2,900 tokens
  3. `scheme_level:2026-09-30:BSLFEF:0` score 0.729, 2,473 tokens
  4. `scheme_level:2026-09-30:BSLBKFS:0` score 0.728, 1,444 tokens
  5. `scheme_level:2026-09-30:ADVG:0` score 0.728, 2,744 tokens

## section_aware

- status: **ok**
- answer: The Flexi Cap Fund holds 5.60% of its AUM in ICICI Bank as on 30 Sep 2026.
- value: 5.6 pct | insufficient_context: False
- cited rows: [8]
- tokens: prompt 1,818, completion 110 (reasoning 24) [cached]
- latency: retrieval 90 ms, generation 1,182 ms
- context: 5 chunks, 33 holding rows
- retrieved:
  1. `section_aware:2026-09-30:BSLEQTY:0` score 0.767, 485 tokens
  2. `section_aware:2026-09-30:BSLEQTY:8` score 0.765, 111 tokens
  3. `section_aware:2026-09-30:BSLEQTY:7` score 0.761, 78 tokens
  4. `section_aware:2026-09-30:BSLEQTY:1` score 0.758, 487 tokens
  5. `section_aware:2026-09-30:BSLEQTY:6` score 0.750, 203 tokens

## hierarchical

- status: **ok**
- answer: The Flexi Cap Fund holds 5.60% of its AUM in ICICI Bank as on 30 Sep 2026.
- value: 5.6 pct | insufficient_context: False
- cited rows: [8]
- tokens: prompt 3,325, completion 110 (reasoning 24) [cached]
- latency: retrieval 95 ms, generation 1,170 ms
- context: 2 chunks, 85 holding rows
- retrieved:
  1. `hierarchical:2026-09-30:BSLEQTY:p0` score 0.815, 2,750 tokens via 4 children
  2. `hierarchical:2026-09-30:BSLEQTY:p2` score 0.775, 111 tokens via 1 children

