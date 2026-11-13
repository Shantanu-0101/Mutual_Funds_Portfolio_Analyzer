"""Index + retrieval + RAG pipeline tests (spec §10). No network, no model download.

A bag-of-words fake embedder stands in for bge-small; Chroma runs on a tiny
collection in a temp folder; the LLM is the mock provider.
"""

import json
import re
import zlib
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from src.chunking import build_chunker
from src.chunking.base import _clean, row_key
from src.config import load_settings
from src.index.embedder import Embedder
from src.index.store import (
    IndexNotBuilt, chunk_from_record, chunk_metadata, get_collection, open_client, read_parents, write_month,
    write_parents,
)
from src.llm import JSON_INVALID, LLM, Completion, ContextOverflow, MockProvider
from src.rag.pipeline import RagPipeline, resolve_sources
from src.rag.prompt import SYSTEM_PROMPT, AnswerFormatError, build_messages, norm_name, parse_answer
from src.rag.retrieve import Retrieved, Retriever, swap_for_parents, where_filter
from tests.test_chunkers import CODE, DATE, TOK, make_sheet

NO_ENV = Path("does-not-exist.env")
DIM = 512


def bow_encode(texts):
    """Deterministic bag-of-words vectors: shared words -> similar vectors."""
    out = np.zeros((len(texts), DIM), dtype=np.float32)
    for i, t in enumerate(texts):
        for w in re.findall(r"\w+", t.lower()):
            out[i, zlib.crc32(w.encode()) % DIM] += 1.0
        out[i] /= np.linalg.norm(out[i]) or 1.0
    return out


class CountingEncode:
    def __init__(self):
        self.texts = 0

    def __call__(self, texts):
        self.texts += len(texts)
        return bow_encode(texts)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("rag")
    s = load_settings(env_file=NO_ENV, environ={"LLM_PROVIDER": "mock"})
    s = replace(s, paths=replace(s.paths, cache=tmp_path / "cache", chroma=tmp_path / "chroma",
                                 processed=tmp_path / "processed"))
    sheet = make_sheet()
    embedder = Embedder(s.embedding.model, s.paths.cache / "emb.sqlite", encode_fn=bow_encode, query_prefix="")
    client = open_client(s.paths.chroma)
    parents = []
    for name in ("row_wise", "hierarchical", "section_aware"):
        out = build_chunker(name, s, TOK).build(sheet)
        col = get_collection(client, name, s.embedding.model, create=True)
        write_month(col, DATE, out.chunks, embedder.embed_documents([c.text for c in out.chunks]))
        parents += out.parents
    write_parents(s.paths.processed / "parents_hierarchical.parquet", DATE, parents)
    names = {row_key(r): (norm_name(_clean(r.scheme)), norm_name(_clean(r.instrument)))
             for r in sheet.itertuples(index=False)}
    retriever = Retriever(s, embedder=embedder, client=client)
    return SimpleEnv(s, sheet, embedder, client, retriever, names)


class SimpleEnv:
    def __init__(self, s, sheet, embedder, client, retriever, names):
        self.s, self.sheet, self.embedder, self.client, self.retriever, self.names = (
            s, sheet, embedder, client, retriever, names)


# --------------------------------------------------------------------------- embedder + store

def test_embedder_cache(tmp_path):
    enc = CountingEncode()
    e = Embedder("BAAI/bge-small-en-v1.5", tmp_path / "e.sqlite", encode_fn=enc)
    v1 = e.embed_documents(["a b", "c d", "a b"])
    assert enc.texts == 2 and v1.shape == (3, DIM) and np.allclose(v1[0], v1[2])
    e2 = Embedder("BAAI/bge-small-en-v1.5", tmp_path / "e.sqlite", encode_fn=enc)   # new process, same file
    assert np.allclose(e2.embed_documents(["c d"])[0], v1[1]) and enc.texts == 2 and e2.hits == 1
    e2.embed_query("a b")                          # query prefix -> different text, embedded once
    assert enc.texts == 3 and e2.query_prefix.startswith("Represent this sentence")
    other = Embedder("other-model", tmp_path / "e.sqlite", encode_fn=enc)
    other.embed_documents(["a b"])                 # cache is keyed by model too
    assert enc.texts == 4
    Embedder("m", None, encode_fn=enc).load()   # injected encoder: load() is a no-op


def test_metadata_round_trip(env):
    h = build_chunker("hierarchical", env.s, TOK).build(env.sheet)
    for c in (h.chunks[0], h.parents[0]):
        assert chunk_from_record(c.id, c.text, chunk_metadata(c)) == c
    assert chunk_metadata(h.parents[0])["parent_id"] == ""


def test_reindex_replaces_month_only(env):
    col = get_collection(env.client, "section_aware", env.s.embedding.model)   # not queried by other tests
    n = col.count()
    chunks = build_chunker("section_aware", env.s, TOK).chunk(env.sheet)
    vectors = env.embedder.embed_documents([c.text for c in chunks])
    write_month(col, DATE, chunks, vectors)
    assert col.count() == n == len(chunks) == 4
    other = [replace(c, id=c.id.replace(DATE, "2026-08-31"), as_of_date="2026-08-31") for c in chunks[:3]]
    write_month(col, "2026-08-31", other, vectors[:3])
    write_month(col, DATE, chunks[:2], vectors[:2])
    assert col.count() == 5


def test_collection_checks(env):
    with pytest.raises(IndexNotBuilt, match="built with"):
        get_collection(env.client, "row_wise", "another-model")
    with pytest.raises(IndexNotBuilt, match="no collection"):
        get_collection(env.client, "scheme_level", env.s.embedding.model)
    with pytest.raises(IndexNotBuilt):
        read_parents(Path("missing.parquet"))


# --------------------------------------------------------------------------- retrieval

def test_where_filter():
    assert where_filter() is None
    assert where_filter("X") == {"scheme_code": "X"}
    assert where_filter("X", DATE) == {"$and": [{"scheme_code": "X"}, {"as_of_date": DATE}]}


def test_retrieve_top_k_and_context_rows(env):
    r = env.retriever.retrieve("Stock C Ltd. Banks", "row_wise", top_k=3)
    assert len(r.chunks) == 3 and [x.rank for x in r.chunks] == [1, 2, 3]
    assert "Instrument: Stock C Ltd." in r.chunks[0].chunk.text
    assert r.chunks[0].score >= r.chunks[1].score >= r.chunks[2].score
    assert r.context_rows == [x.chunk.source_rows[0] for x in r.chunks]
    assert len(env.retriever.retrieve("x", "row_wise").chunks) == env.s.retrieval.top_k
    filtered = env.retriever.retrieve("Stock C", "row_wise", top_k=3, scheme_code="NOPE")
    assert filtered.chunks == []


def test_hierarchical_swaps_children_for_unique_parents(env):
    r = env.retriever.retrieve("Stock A Ltd. Stock B Ltd. Stock C Ltd. Banks", "hierarchical", top_k=5)
    assert len(r.children) == 5 and all(c.chunk.parent_id for c in r.children)
    ids = [x.chunk.id for x in r.chunks]
    assert len(ids) == len(set(ids)) and all(":p" in i for i in ids)
    assert sorted(cid for x in r.chunks for cid in x.children) == sorted(c.chunk.id for c in r.children)
    assert set(r.context_rows) == {k for x in r.chunks for k in x.chunk.source_rows}
    for x in r.chunks:
        assert x.score == max(c.score for c in r.children if c.chunk.id in x.children)


def test_swap_for_parents_order_and_dedupe(env):
    h = build_chunker("hierarchical", env.s, TOK).build(env.sheet)
    parents = {p.id: p for p in h.parents}
    kids = [h.chunks[15], h.chunks[0], h.chunks[1], h.chunks[16]]    # TREPS, equity, equity, net receivable
    got = swap_for_parents([Retrieved(c, 1.0 - i / 10, i + 1) for i, c in enumerate(kids)], parents)
    assert [g.chunk.section for g in got] == ["Money Market Instruments", "Equity & Equity Related",
                                              "Other Current Assets / (Liabilities)"]
    assert [g.rank for g in got] == [1, 2, 3]
    assert [g.chunk.id for g in got] == [kids[0].parent_id, kids[1].parent_id, kids[3].parent_id]
    assert got[1].children == (kids[1].id, kids[2].id) and got[1].score == pytest.approx(0.9)


# --------------------------------------------------------------------------- prompt + answer format

GOOD = {"answer": "5.60%", "value": 5.6, "unit": "pct", "items": [], "insufficient_context": False,
        "sources": [{"scheme": "TEST FLEXI CAP FUND", "instrument": "Stock A Ltd."}]}


def test_messages_have_rules_context_and_question(env):
    chunks = build_chunker("row_wise", env.s, TOK).chunk(env.sheet)[:2]
    sys_msg, user = build_messages("What is X?", chunks)
    assert sys_msg["content"] == SYSTEM_PROMPT and "ONLY the context" in SYSTEM_PROMPT
    assert "[Chunk 1]\n" + chunks[0].text in user["content"] and "[Chunk 2]" in user["content"]
    assert user["content"].rstrip().endswith("Reply with the JSON object only.") and "Question: What is X?" in user["content"]
    assert "no chunks retrieved" in build_messages("q", [])[1]["content"]


@pytest.mark.parametrize("text, msg", [
    ("not json", "not valid JSON"),
    ("[1, 2]", "not a JSON object"),
    (json.dumps({k: v for k, v in GOOD.items() if k != "items"}), "missing keys"),
    (json.dumps({**GOOD, "value": "5.6"}), "'value'"),
    (json.dumps({**GOOD, "value": True}), "'value'"),
    (json.dumps({**GOOD, "unit": "percent"}), "'unit'"),
    (json.dumps({**GOOD, "sources": [{"scheme": "x"}]}), "'sources'"),
    (json.dumps({**GOOD, "insufficient_context": "no"}), "insufficient_context"),
])
def test_parse_answer_rejects(text, msg):
    with pytest.raises(AnswerFormatError, match=msg):
        parse_answer(text)


def test_parse_answer_accepts_and_ignores_extra():
    assert parse_answer(json.dumps({**GOOD, "note": "x"}))["value"] == 5.6
    assert parse_answer(json.dumps({**GOOD, "value": None, "unit": None}))["value"] is None


# --------------------------------------------------------------------------- pipeline

def _pipe(env, responder=None, provider=None):
    llm = LLM(env.s, provider or MockProvider(env.s, responder), cache=False)
    return RagPipeline(env.s, retriever=env.retriever, llm=llm, row_names=env.names)


def test_pipeline_ok_resolves_cited_rows(env):
    r = _pipe(env, lambda m: json.dumps(GOOD)).answer("Stock A Ltd. % to AUM", "row_wise")
    assert r.status == "ok" and r.answer["value"] == 5.6 and r.error is None
    assert r.cited_rows == [("synthetic.xls", "SYNEQ", 8)] and not r.unmatched_sources
    assert r.prompt_tokens > 0 and r.completion_tokens > 0 and r.retrieval_ms > 0 and r.model == "mock"
    assert len(r.retrieval.chunks) == env.s.retrieval.top_k


def test_pipeline_unmatched_source(env):
    bad = {**GOOD, "sources": [{"scheme": "TEST FLEXI CAP FUND", "instrument": "Not In Context Ltd."}]}
    r = _pipe(env, lambda m: json.dumps(bad)).answer("Stock A Ltd.", "row_wise")
    assert r.status == "ok" and r.cited_rows == [] and r.unmatched_sources == bad["sources"]


def test_pipeline_format_error_not_repaired(env):
    r = _pipe(env, lambda m: "Sure! " + json.dumps(GOOD)).answer("Stock A", "row_wise")
    assert r.status == "format_error" and r.answer is None and r.raw_text.startswith("Sure!")


def test_pipeline_json_rejected_by_provider(env):
    class Rejecting(MockProvider):
        def complete(self, messages, json_mode):
            return Completion(text="{oops", prompt_tokens=0, completion_tokens=0, finish_reason=JSON_INVALID)
    r = _pipe(env, provider=Rejecting(env.s)).answer("Stock A", "row_wise")
    assert r.status == "format_error" and "invalid JSON" in r.error


def test_pipeline_context_overflow(env):
    class Overflow(MockProvider):
        def complete(self, messages, json_mode):
            raise ContextOverflow("413 Request too large")
    r = _pipe(env, provider=Overflow(env.s)).answer("Stock A", "hierarchical")
    assert r.status == "context_overflow" and r.answer is None and r.retrieval.chunks


def test_resolve_sources_scheme_must_match(env):
    rows = list(env.names)
    got, missing = resolve_sources([{"scheme": "OTHER FUND", "instrument": "Stock A Ltd."},
                                    {"scheme": "", "instrument": "stock  b ltd."}], rows, env.names)
    assert got == [("synthetic.xls", "SYNEQ", 9)] and missing == [{"scheme": "OTHER FUND", "instrument": "Stock A Ltd."}]
