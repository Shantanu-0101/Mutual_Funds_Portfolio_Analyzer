"""Optional smoke test: all chunkers on the real September Flexi Cap sheet with the real tokenizer.

Skipped when data/processed/holdings.parquet is missing (run ``python -m src.parsing``)
or the bge-small tokenizer cannot be loaded.
"""

import pandas as pd
import pytest

from src.chunking import REGISTRY, build_chunker
from src.chunking.base import row_key
from src.config import get_settings

S = get_settings()
HOLDINGS = S.paths.processed / "holdings.parquet"

pytestmark = pytest.mark.skipif(not HOLDINGS.is_file(), reason="holdings.parquet not built")


@pytest.fixture(scope="module")
def tokenizer():
    try:
        from src.chunking.base import get_tokenizer
        return get_tokenizer(S.embedding.model)
    except Exception as e:  # no network and no cached tokenizer
        pytest.skip(f"tokenizer {S.embedding.model} not available: {e}")


@pytest.fixture(scope="module")
def flexi_cap():
    h = pd.read_parquet(HOLDINGS)
    return h[(h["as_of_date"].astype(str) == "2026-09-30") & (h["scheme_code"] == "BSLEQTY")]


def test_real_flexi_cap(tokenizer, flexi_cap):
    keys = {row_key(r) for r in flexi_cap.itertuples(index=False)}
    assert len(keys) == 86
    out = {name: build_chunker(name, S, tokenizer).build(flexi_cap) for name in REGISTRY}
    for name, cs in out.items():
        assert {k for c in cs.chunks for k in c.source_rows} == keys, name
    (scheme,) = out["scheme_level"].chunks
    assert scheme.truncated and 2_000 < scheme.n_tokens < 4_000   # spec §6.3: "~2,500 tokens"
    assert len(out["row_wise"].chunks) == 86 and not any(c.truncated for c in out["row_wise"].chunks)
    assert all(c.n_tokens <= 512 for c in out["section_aware"].chunks)
    parents = out["hierarchical"].parents
    assert [len(p.source_rows) for p in parents][0] == 83   # whole equity section, not split
    first = out["row_wise"].chunks[0].text
    assert "Instrument: ICICI Bank Ltd." in first and first.endswith("% to AUM: 5.60")
