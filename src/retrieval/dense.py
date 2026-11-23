"""M1 ``dense``: today's search, unchanged (spec §5 M1).

Embed the question with bge-small (with the bge query prefix), take the nearest children of the month by
cosine. Same embedding, same score and same intent as ``src/rag/retrieve.Retriever``, but the ranking is
computed from the stored child embeddings rather than asked of Chroma's approximate index, which is not
reproducible across processes (``DenseSearch.rank``). ``python -m src.retrieval demo --check-dense``
checks M1 against the sections the chunking run actually retrieved, on the 28 original questions.
"""

from __future__ import annotations

from typing import Sequence

from src.retrieval.base import Ranked, RetrievalMethod


class Dense(RetrievalMethod):
    name = "dense"

    def rank(self, question: str, n: int, schemes: Sequence[str] | None = None) -> tuple[Ranked, dict]:
        return self.shared.dense.rank(question, n, schemes), {}
