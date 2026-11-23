"""M6 ``scheme_filter``: find scheme names in the question, search only inside them (spec §5 M6, §5.1).

**Extraction** reads the question text and the month's scheme list only, never a question's gold
``params`` (that would leak the answer into retrieval). Per scheme the name variants are:

- the full name as in the file, the current full name without "(FORMERLY KNOWN AS …)";
- the short name, without the leading "ADITYA BIRLA SUN LIFE";
- the former name ("FORMERLY KNOWN AS …"), full and short, where the file gives one;
- the scheme code (e.g. ``BSLEQTY``), matched only as an exact, case-sensitive word, and skipped when the
  code is also an ordinary word of some scheme name ("NIFTY", "MIDCAP", "PLUS", "MNC").

Names are compared after normalising: lower case, ``&`` → ``and``, every other non letter/digit → a space.
A variant that would point to two schemes is dropped.

**Rule.** Exact matches on whole words first, longest first; a match that overlaps an already accepted
one does not count (so "Short Term Fund" inside "Ultra Short Term Fund" is not a second scheme). Only if
no exact match is found: fuzzy matching (stdlib ``difflib``) of each name variant against the question's
word n-grams of about the same length, best ratio first, same overlap rule, ratio ≥ ``fuzzy_threshold``
(tuned on dev in R3). Schemes are returned in the order they appear in the question.

**Search.** One scheme: the inner ranker (dense for M6) inside it. Two or more: round robin by rank:
each scheme's own ranked list in turn (1st of A, 1st of B, 2nd of A, …); a scheme with too few rows
gives its share to the others. None found: the inner ranker on everything (plain M1 for M6). If the
named schemes have fewer rows in all than asked for (small FoF / debt schemes; every method ranks 20),
the rest comes from the inner ranker on everything, **after** the filtered rows (``debug.padded``), so
every method still returns exactly k.
``debug`` records ``schemes_found``, ``match`` (exact / fuzzy / none) and the matched words, so a wrong
filter shows up in the results as ``filter_miss`` / ``filter_wrong`` (R4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Sequence

import pandas as pd

from src.retrieval.base import Ranked, RetrievalMethod

AMC_PREFIX = "ADITYA BIRLA SUN LIFE "
FORMERLY = re.compile(r"\(\s*FORMERLY KNOWN AS ([^)]*)\)", re.IGNORECASE)
WORD = re.compile(r"[A-Za-z0-9]+")


def raw_words(text: str) -> list[str]:
    """Words of ``text`` with their case kept, after ``&`` → ``and`` and dropping punctuation."""
    return WORD.findall(text.replace("&", " and ").replace("'", ""))


def normalise(text: str) -> list[str]:
    """Words of ``text`` lower-cased, after ``&`` → ``and`` and dropping punctuation."""
    return [w.lower() for w in raw_words(text)]


def name_variants(scheme: str) -> list[str]:
    """Full, current, short, former (full + short) names of one scheme, unique, longest first."""
    raw = scheme.strip()
    out = [raw]
    m = FORMERLY.search(raw)
    current = FORMERLY.sub("", raw).strip()
    names = [current] + ([m.group(1).strip()] if m else [])
    for name in names:
        out.append(name)
        if name.upper().startswith(AMC_PREFIX):
            out.append(name[len(AMC_PREFIX):].strip())
    seen: dict[tuple[str, ...], None] = {}
    for v in out:
        words = tuple(normalise(v))
        if words:
            seen.setdefault(words, None)
    return [" ".join(w) for w in sorted(seen, key=lambda w: (-len(w), w))]


@dataclass(frozen=True)
class Match:
    code: str
    start: int            # word positions in the question, end exclusive
    end: int
    text: str
    kind: str             # exact | code | fuzzy
    score: float = 1.0


@dataclass(frozen=True)
class Extraction:
    schemes: tuple[str, ...]
    match: str            # exact | fuzzy | none
    matches: tuple[Match, ...]

    def debug(self) -> dict:
        return {"schemes_found": list(self.schemes), "match": self.match,
                "matched": [f"{m.text} -> {m.code} ({m.kind}{'' if m.kind != 'fuzzy' else f' {m.score:.2f}'})"
                            for m in self.matches]}


def _overlaps(m: Match, taken: list[Match]) -> bool:
    return any(m.start < t.end and t.start < m.end for t in taken)


def _accept(cands: list[Match]) -> list[Match]:
    """Greedy: candidates are already sorted best first; keep those that overlap nothing kept."""
    kept: list[Match] = []
    for m in cands:
        if not _overlaps(m, kept):
            kept.append(m)
    return kept


class SchemeExtractor:
    def __init__(self, schemes: pd.DataFrame):
        """``schemes``: the month's scheme list, columns ``scheme_code`` and ``scheme``."""
        owner: dict[tuple[str, ...], set[str]] = {}
        for code, name in zip(schemes["scheme_code"], schemes["scheme"]):
            for v in name_variants(str(name)):
                owner.setdefault(tuple(v.split()), set()).add(str(code))
        self.ambiguous = sorted(" ".join(v) for v, codes in owner.items() if len(codes) > 1)
        self.variants: dict[tuple[str, ...], str] = {v: next(iter(c)) for v, c in owner.items() if len(c) == 1}
        name_words = {w for v in owner for w in v}
        codes = [str(c) for c in schemes["scheme_code"]]
        self.codes = {c for c in codes if c.lower() not in name_words}
        self.by_first: dict[str, list[tuple[str, ...]]] = {}
        for v in self.variants:
            self.by_first.setdefault(v[0], []).append(v)

    # -- exact ---------------------------------------------------------------------------------------
    def _exact(self, words: list[str], raw_words: list[str]) -> list[Match]:
        cands = []
        for i, w in enumerate(words):
            for v in self.by_first.get(w, ()):
                if tuple(words[i:i + len(v)]) == v:
                    cands.append(Match(self.variants[v], i, i + len(v), " ".join(v), "exact"))
        cands += [Match(w, i, i + 1, w, "code") for i, w in enumerate(raw_words) if w in self.codes]
        cands.sort(key=lambda m: (-(m.end - m.start), -len(m.text), m.start))
        return _accept(cands)

    # -- fuzzy ---------------------------------------------------------------------------------------
    def _fuzzy(self, words: list[str], threshold: float) -> list[Match]:
        cands = []
        for v, code in self.variants.items():
            target = " ".join(v)
            for size in {max(1, len(v) - 1), len(v), len(v) + 1}:
                for i in range(0, len(words) - size + 1):
                    gram = " ".join(words[i:i + size])
                    sm = SequenceMatcher(None, target, gram, autojunk=False)
                    if sm.real_quick_ratio() < threshold or sm.quick_ratio() < threshold:
                        continue
                    r = sm.ratio()
                    if r >= threshold:
                        cands.append(Match(code, i, i + size, gram, "fuzzy", r))
        cands.sort(key=lambda m: (-m.score, -(m.end - m.start), m.start, m.code))
        return _accept(cands)

    def extract(self, question: str, fuzzy_threshold: float = 0.85) -> Extraction:
        raw = raw_words(question)                 # same words as ``words``, case kept (for codes)
        words = [w.lower() for w in raw]
        found = self._exact(words, raw)
        kind = "exact" if found else "none"
        if not found:
            found = self._fuzzy(words, fuzzy_threshold)
            kind = "fuzzy" if found else "none"
        order = sorted(found, key=lambda m: m.start)
        schemes = tuple(dict.fromkeys(m.code for m in order))
        return Extraction(schemes, kind, tuple(order))


def round_robin(lists: Sequence[Ranked], n: int) -> Ranked:
    """1st of each list in turn, then 2nd, … until ``n``; an exhausted list gives its turn to the rest.
    A child already taken (cannot happen across schemes, but kept safe) is skipped."""
    out: Ranked = []
    seen: set[int] = set()
    pos = [0] * len(lists)
    while len(out) < n and any(p < len(lst) for p, lst in zip(pos, lists)):
        for j, lst in enumerate(lists):
            if len(out) >= n:
                break
            while pos[j] < len(lst) and lst[pos[j]][0] in seen:
                pos[j] += 1
            if pos[j] < len(lst):
                out.append(lst[pos[j]])
                seen.add(lst[pos[j]][0])
                pos[j] += 1
    return out


class SchemeFilter(RetrievalMethod):
    def __init__(self, shared, inner: RetrievalMethod, fuzzy_threshold: float = 0.85, name: str = "scheme_filter"):
        super().__init__(shared)
        self.inner, self.fuzzy_threshold, self.name = inner, float(fuzzy_threshold), name

    def load(self) -> None:
        self.inner.load()
        self.shared.extractor

    def rank(self, question: str, n: int, schemes: Sequence[str] | None = None) -> tuple[Ranked, dict]:
        ex = self.shared.extractor.extract(question, self.fuzzy_threshold)
        debug = ex.debug()
        found = [s for s in ex.schemes if schemes is None or s in schemes]
        if not found:
            ranked, inner_debug = self.inner.rank(question, n, schemes)
            return ranked, {**debug, "split_top5": None, "padded": 0,
                            **{f"inner_{k}": v for k, v in inner_debug.items()}}
        lists = [self.inner.rank(question, n, (s,))[0] for s in found]
        ranked = round_robin(lists, n)
        split = {s: int(sum(self.corpus.schemes[i] == s for i, _ in ranked[:5])) for s in found}
        padded = 0
        if len(ranked) < n:
            # The named schemes have fewer than n rows in all (small debt / FoF schemes). Every method
            # returns exactly n, so the rest comes from the inner ranker on everything, after them.
            taken = {i for i, _ in ranked}
            rest, _ = self.inner.rank(question, n + len(taken), None)
            extra = [(i, s) for i, s in rest if i not in taken][:n - len(ranked)]
            padded = len(extra)
            ranked += extra
        return ranked, {**debug, "split_top5": split, "padded": padded}
