"""M2 ``bm25``: Okapi BM25 over the child texts, own code (spec §5 M2, RD3).

Tokenizer: lowercase, split on anything that is not a letter or digit. Every token is kept, however
short, so "aaa", "psu", "it" and numbers ("8", "56", "2028") stay searchable. No stop-word list: IDF
already makes words in every row ("scheme", "section", "isin") nearly worthless.

Score of a document d for query tokens q1..qn (a token repeated in the question counts each time):

    sum_i  idf(qi) * tf(qi, d) * (k1 + 1) / (tf(qi, d) + k1 * (1 - b + b * |d| / avgdl))
    idf(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))         (always > 0)

The index is built once (seconds for ~5,600 rows); k1 and b are applied at query time, so the dev grid
can try several values on one index. Ties keep corpus order, so results are deterministic.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Sequence

import numpy as np

from src.retrieval.base import Ranked, RetrievalMethod, order_scores

TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


class BM25Index:
    def __init__(self, texts: Sequence[str]):
        self.n_docs = len(texts)
        docs = [tokenize(t) for t in texts]
        self.doc_len = np.array([len(d) for d in docs], dtype=np.float64)
        self.avgdl = float(self.doc_len.mean()) if self.n_docs else 0.0
        postings: dict[str, tuple[list[int], list[int]]] = {}
        for i, d in enumerate(docs):
            for term, tf in Counter(d).items():
                p = postings.setdefault(term, ([], []))
                p[0].append(i)
                p[1].append(tf)
        self.postings = {t: (np.array(ix), np.array(tf, dtype=np.float64)) for t, (ix, tf) in postings.items()}
        self.idf = {t: math.log(1 + (self.n_docs - len(ix) + 0.5) / (len(ix) + 0.5))
                    for t, (ix, _) in self.postings.items()}

    def scores(self, query: str, k1: float, b: float) -> np.ndarray:
        out = np.zeros(self.n_docs)
        norm = k1 * (1 - b + b * self.doc_len / self.avgdl) if self.avgdl else np.zeros(self.n_docs)
        for term in tokenize(query):
            if term not in self.postings:
                continue
            ix, tf = self.postings[term]
            out[ix] += self.idf[term] * tf * (k1 + 1) / (tf + norm[ix])
        return out


class BM25(RetrievalMethod):
    name = "bm25"

    def __init__(self, shared, k1: float = 1.5, b: float = 0.75):
        super().__init__(shared)
        self.k1, self.b = float(k1), float(b)

    def load(self) -> None:
        self.shared.bm25                       # build the index before timing

    def rank(self, question: str, n: int, schemes: Sequence[str] | None = None) -> tuple[Ranked, dict]:
        pos = self.corpus.positions(schemes)
        scores = self.shared.bm25.scores(question, self.k1, self.b)[pos]
        return order_scores(pos, scores, n), {}
