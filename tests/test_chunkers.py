"""Chunker tests on a small synthetic DataFrame (spec §10, plan Phase 2).

A word-level fake tokenizer stands in for bge-small, so the tests need no
model download. It splits like BERT's basic tokenizer (words and single
punctuation marks) and adds 2 special tokens, so counts are additive over
lines exactly as with the real tokenizer.
"""

from __future__ import annotations

import re
from dataclasses import replace

import pandas as pd
import pytest

from src.chunking import REGISTRY, build_chunker
from src.chunking.base import (
    ALL_SECTIONS, TABLE_HEADER, ChunkingError, SheetInfo, count_tokens, fmt_pct, fmt_qty, format_row,
    format_row_labelled, format_table, prepare_sheet, row_key,
)
from src.chunking.fixed_size import FixedSizeChunker, rows_in_range, token_windows
from src.chunking.header_window import HeaderWindowChunker
from src.chunking.hierarchical import HierarchicalChunker
from src.chunking.report import ChunkerRun, build_samples_report, build_stats_report, compute_stats
from src.chunking.row_wise import RowWiseChunker
from src.chunking.scheme_level import SchemeLevelChunker
from src.chunking.section_aware import SectionAwareChunker
from src.config import load_settings

FILE, SHEET, CODE, DATE = "synthetic.xls", "SYNEQ", "SYNEQ", "2026-09-30"
EQ, DEBT, MM, OCA = ("Equity & Equity Related", "Debt Instruments", "Money Market Instruments",
                     "Other Current Assets / (Liabilities)")


class WordTokenizer:
    name = "fake-word"
    n_special = 2

    def offsets(self, text):
        return [m.span() for m in re.finditer(r"\w+|[^\w\s]", text)]


TOK = WordTokenizer()


def _row(r, section, sub, name, isin, ind, qty, value, pct, flag=None):
    return dict(amc="Test AMC", scheme_code=CODE, scheme="TEST FLEXI CAP FUND", as_of_date=pd.Timestamp(DATE).date(),
                section=section, subsection=sub, instrument=name, isin=isin, industry_or_rating=ind,
                quantity=qty, market_value_lakhs=value, pct_nav=pct, pct_nav_flag=flag,
                source_file=FILE, source_sheet=SHEET, source_row=r)


def make_sheet() -> pd.DataFrame:
    """18 holdings in 4 sections; Excel rows with gaps where headings and Totals sit."""
    listed = "a) Listed/awaiting listing on Stock Exchanges"
    rows = [_row(8 + i, EQ, listed, f"Stock {chr(65 + i)} Ltd.", f"INE00{i}A01021",
                 "Banks" if i < 4 else "IT - Software", 1000.0 * (i + 1), 500.0 - 20 * i, 5.5967 - 0.2 * i)
            for i in range(12)]
    rows[11] = _row(19, EQ, listed, "Tiny | Pipe Ltd.", "INE011A01021", "Retailing", 10.0, 0.4, 0.003, "lt_0.01")
    dl = "a) Listed/awaiting listing on the stock exchanges"
    rows += [_row(22 + i, DEBT, dl, f"7.{i}% Bond Ltd. (01/01/2030) **", f"INE10{i}B07010", "CRISIL AAA",
                  250.0, 100.0 + i, 1.5 + i / 10) for i in range(3)]
    rows += [_row(27, MM, "TREPS / Reverse Repo Investments", "Clearing Corporation of India Limited", None,
                  None, None, 300.0, 3.0)]
    rows += [_row(30, OCA, None, "Net Receivable / Payable", None, None, None, -12.5, -0.125, "recomputed"),
             _row(31, OCA, None, "Margin amount for Derivative positions", None, None, None, 2.25, 0.0225,
                  "recomputed")]
    df = pd.DataFrame(rows)
    return df.sample(frac=1, random_state=1)  # shuffled: chunkers must sort by source_row themselves


@pytest.fixture(scope="module")
def sheet():
    return make_sheet()


@pytest.fixture(scope="module")
def settings():
    return load_settings()


@pytest.fixture(scope="module")
def all_keys(sheet):
    return {row_key(r) for r in sheet.itertuples(index=False)}


@pytest.fixture(scope="module", params=list(REGISTRY))
def built(request, sheet, settings):
    chunker = build_chunker(request.param, settings, TOK)
    return chunker, chunker.build(sheet)


# --------------------------------------------------------------------------- every chunker

def test_registry_order():
    assert list(REGISTRY) == ["fixed_size", "row_wise", "header_window", "scheme_level", "section_aware",
                              "hierarchical"]


def test_every_holding_covered(built, all_keys):
    _, out = built
    claimed = {k for c in out.chunks for k in c.source_rows}
    assert claimed == all_keys


def test_ids_unique_stable_and_named(built, sheet):
    chunker, out = built
    ids = [c.id for c in out.chunks + out.parents]
    assert len(ids) == len(set(ids))
    assert ids == [c.id for c in (lambda o: o.chunks + o.parents)(chunker.build(sheet.sample(frac=1, random_state=7)))]
    assert all(i.startswith(f"{chunker.name}:{DATE}:{CODE}:") for i in ids)


def test_metadata_and_token_count(built):
    chunker, out = built
    for c in out.chunks + out.parents:
        assert (c.chunker, c.scheme_code, c.as_of_date, c.amc) == (chunker.name, CODE, DATE, "Test AMC")
        assert c.n_tokens == count_tokens(TOK, c.text)
        assert c.truncated == (c.n_tokens > 512)
        assert c.metadata()["source_rows"] == [list(k) for k in c.source_rows]


def test_no_chunk_claims_a_row_it_does_not_contain(built, sheet):
    chunker, out = built
    rows = {row_key(r): r for r in sheet.itertuples(index=False)}
    if chunker.name == "fixed_size":
        info, ordered = prepare_sheet(sheet)
        flat = format_table(ordered, info, ALL_SECTIONS)
        pos = 0
        for c in out.chunks:
            start = flat.text.find(c.text, pos)
            assert start >= 0, "fixed_size chunk is not a substring of the flattened sheet"
            assert list(c.source_rows) == rows_in_range(flat.row_spans, start, start + len(c.text))
            pos = start
        return
    for c in out.chunks + out.parents:
        for k in c.source_rows:
            r = rows[k]
            assert format_row(r) in c.text or format_row_labelled(r, prepare_sheet(sheet)[0]) == c.text


# --------------------------------------------------------------------------- per chunker

def test_row_wise(sheet):
    out = RowWiseChunker(TOK).chunk(sheet)
    assert len(out) == 18 and all(len(c.source_rows) == 1 for c in out)
    first = out[0].text
    assert first.startswith(f"Scheme: TEST FLEXI CAP FUND | As on: {DATE} | Section: {EQ} | ")
    assert "Instrument: Stock A Ltd. | ISIN: INE000A01021 | Industry/Rating: Banks" in first
    assert first.endswith("Qty: 1000 | Value (Rs L): 500.00 | % to AUM: 5.60")
    by_row = {c.source_rows[0][2]: c.text for c in out}
    assert "Instrument: Tiny / Pipe Ltd." in by_row[19] and by_row[19].endswith("% to AUM: <0.01")
    assert "ISIN: - | Industry/Rating: - | Qty: -" in by_row[27]
    assert "Sub-section: - " in by_row[30] and by_row[30].endswith("Value (Rs L): -12.50 | % to AUM: -0.12")
    assert [c.section for c in out[:12]] == [EQ] * 12


def test_header_window(sheet):
    out = HeaderWindowChunker(TOK, rows_per_chunk=5).chunk(sheet)
    assert [len(c.source_rows) for c in out] == [5, 5, 5, 3]
    for c in out:
        lines = c.text.split("\n")
        assert lines[0] == "Scheme: TEST FLEXI CAP FUND" and lines[1] == f"As on: {DATE}"
        assert lines[2] == f"Section: {c.section}" and lines[3] == TABLE_HEADER
    # third window = rows 18, 19 (equity) + 22, 23, 24 (debt): both sections named, marker at the switch
    assert out[2].section == f"{EQ}; {DEBT}"
    assert f"[{DEBT} > a) Listed/awaiting listing on the stock exchanges]" in out[2].text
    assert out[3].section == f"{MM}; {OCA}" and f"[{OCA}]" in out[3].text


def test_scheme_level(sheet):
    (c,) = SchemeLevelChunker(TOK, on_overflow="truncate_and_warn").chunk(sheet)
    assert c.section == ALL_SECTIONS and len(c.source_rows) == 18 and c.id == f"scheme_level:{DATE}:{CODE}:0"
    assert "Section: ALL" in c.text
    for marker in (EQ, DEBT, MM, OCA):
        assert c.text.count(f"[{marker}") == 1
    assert [k[2] for k in c.source_rows] == sorted(k[2] for k in c.source_rows)


def test_section_aware_one_chunk_per_section(sheet):
    out = SectionAwareChunker(TOK, max_tokens=512).chunk(sheet)
    assert [c.section for c in out] == [EQ, DEBT, MM, OCA]
    assert [len(c.source_rows) for c in out] == [12, 3, 1, 2]


def test_section_aware_splits_long_sections_without_mixing(sheet):
    limit = 150
    out = SectionAwareChunker(TOK, max_tokens=limit).chunk(sheet)
    sections = {row_key(r): r.section for r in sheet.itertuples(index=False)}
    eq_parts = [c for c in out if c.section == EQ]
    assert len(eq_parts) > 1
    for c in out:
        assert {sections[k] for k in c.source_rows} == {c.section}
        assert c.n_tokens <= limit or len(c.source_rows) == 1
        assert c.text.split("\n")[3] == TABLE_HEADER
    # greedy: every part except the last of a section would overflow with the next row added
    info, rows = prepare_sheet(sheet)
    eq_rows = [r for r in rows if r.section == EQ]
    i = 0
    for part in eq_parts[:-1]:
        i += len(part.source_rows)
        assert count_tokens(TOK, format_table(eq_rows[i - len(part.source_rows):i + 1], info, EQ).text) > limit


def test_hierarchical(sheet):
    h = HierarchicalChunker(TOK, child="row", parent="section").build(sheet)
    rows_ = RowWiseChunker(TOK).chunk(sheet)
    assert [c.text for c in h.chunks] == [c.text for c in rows_]          # same text -> shared embedding cache
    # parents are whole sections, never split, even where section_aware would split
    assert [p.section for p in h.parents] == [EQ, DEBT, MM, OCA]
    assert [len(p.source_rows) for p in h.parents] == [12, 3, 1, 2]
    assert len([c for c in SectionAwareChunker(TOK, max_tokens=150).chunk(sheet) if c.section == EQ]) > 1
    assert h.parents[0].n_tokens > 150
    assert all(p.id.split(":")[-1].startswith("p") for p in h.parents)
    parents = {p.id: p for p in h.parents}
    assert len(parents) == len(h.parents)
    for child in h.chunks:
        assert child.parent_id in parents
        assert child.source_rows[0] in parents[child.parent_id].source_rows
    assert {k for p in h.parents for k in p.source_rows} == {k for c in h.chunks for k in c.source_rows}
    assert not {p.id for p in h.parents} & {c.id for c in h.chunks}


def test_token_windows():
    assert token_windows(10, 4, 1) == [(0, 4), (3, 7), (6, 10)]
    assert token_windows(3, 4, 1) == [(0, 3)]
    assert token_windows(0, 4, 1) == []
    assert token_windows(8, 4, 0) == [(0, 4), (4, 8)]


def test_fixed_size_overlap_and_cut_rows(sheet):
    size, overlap = 40, 8
    ch = FixedSizeChunker(TOK, chunk_tokens=size, overlap_tokens=overlap)
    out = ch.chunk(sheet)
    assert len(out) > 3
    pieces = [[c.text[a:b] for a, b in TOK.offsets(c.text)] for c in out]
    for prev, nxt in zip(pieces, pieces[1:]):
        assert prev[-overlap:] == nxt[:overlap]
    assert all(len(p) == size for p in pieces[:-1]) and len(pieces[-1]) <= size
    # the naive baseline's weakness, made visible: rows cut in two, header only in the first chunk
    claims = [k for c in out for k in c.source_rows]
    assert len(claims) > len(set(claims))
    assert TABLE_HEADER in out[0].text and all(TABLE_HEADER not in c.text for c in out[1:])


def test_truncation_flag_at_boundary():
    ch = RowWiseChunker(TOK, 512)
    info = SheetInfo("a", "S", "s", DATE)
    assert not ch.make_chunk("x", " ".join(["w"] * 510), info, "s", []).truncated   # 510 + 2 = 512
    assert ch.make_chunk("x", " ".join(["w"] * 511), info, "s", []).truncated       # 513


# --------------------------------------------------------------------------- input, options, formatting

def test_one_scheme_month_at_a_time(sheet):
    other = sheet.copy()
    other["scheme_code"] = "OTHER"
    with pytest.raises(ChunkingError, match="one scheme-month"):
        RowWiseChunker(TOK).chunk(pd.concat([sheet, other]))
    with pytest.raises(ChunkingError, match="missing columns"):
        RowWiseChunker(TOK).chunk(sheet.drop(columns=["pct_nav"]))
    with pytest.raises(ChunkingError, match="duplicate row keys"):
        RowWiseChunker(TOK).chunk(pd.concat([sheet, sheet.head(1)]))


@pytest.mark.parametrize("cls, opts, msg", [
    (FixedSizeChunker, {"chunk_tokens": 10, "overlap_tokens": 10}, "overlap_tokens"),
    (FixedSizeChunker, {"chunk_tokens": 10}, "missing keys"),
    (FixedSizeChunker, {"chunk_tokens": 10, "overlap_tokens": 1, "x": 1}, "unknown keys"),
    (HeaderWindowChunker, {"rows_per_chunk": 0}, "> 0"),
    (HeaderWindowChunker, {"rows_per_chunk": True}, "must be int"),
    (HeaderWindowChunker, {"rows_per_chunk": "10"}, "must be int"),
    (SchemeLevelChunker, {"on_overflow": "split"}, "on_overflow"),
    (HierarchicalChunker, {"child": "row", "parent": "scheme"}, "parent"),
])
def test_bad_options(cls, opts, msg):
    with pytest.raises(ChunkingError, match=msg):
        cls(TOK, 512, **opts)


def test_build_chunker_uses_config(settings):
    fs = build_chunker("fixed_size", settings, TOK)
    assert fs.options == {"chunk_tokens": 256, "overlap_tokens": 32} and fs.embed_max_tokens == 512
    assert build_chunker("hierarchical", settings, TOK).options == {"child": "row", "parent": "section"}
    with pytest.raises(ChunkingError, match="unknown chunker"):
        build_chunker("nope", settings, TOK)


def test_formatting_helpers():
    assert fmt_pct(5.5967, None) == "5.60" and fmt_pct(0.003, "lt_0.01") == "<0.01"
    assert fmt_pct(float("nan"), None) == "-"
    assert fmt_qty(1500.0) == "1500" and fmt_qty(2.5) == "2.5" and fmt_qty(None) == "-"


# --------------------------------------------------------------------------- report

def test_stats_and_reports(sheet, all_keys, settings):
    runs = []
    for name in REGISTRY:
        out = build_chunker(name, settings, TOK).build(sheet)
        runs.append(ChunkerRun(name, out.chunks, out.parents))
    st = compute_stats(runs[1].chunks, all_keys)
    assert (st.chunks, st.rows_covered, st.rows_missing, st.rows_in_several) == (18, 18, 0, 0)
    gap = compute_stats(runs[1].chunks[1:], all_keys)
    assert gap.rows_missing == 1
    text = build_stats_report(runs, DATE, 1, all_keys, TOK.name, 512, settings.chunking)
    assert "| row_wise | – | 18 |" in text and "`hierarchical` parents" in text
    samples = build_samples_report(runs, DATE, [CODE, "ABSENT"])
    assert "## fixed_size" in samples and "_No chunks for `ABSENT`._" in samples
    assert "(parent of the first child)" in samples


def test_chunk_is_frozen(sheet):
    c = RowWiseChunker(TOK).chunk(sheet)[0]
    with pytest.raises(Exception):
        c.text = "x"
    assert replace(c, text="y").text == "y"
