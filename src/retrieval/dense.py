"""M1 ``dense``: today's search, unchanged (spec §5 M1).

Embed the question with bge-small (with the bge query prefix), take the nearest children by cosine from
the ``hierarchical`` Chroma collection. Same call as ``src/rag/retrieve.Retriever`` (no ``where`` filter
when the collection holds only the month), so its top 5 are the children the chunking run retrieved;
``python -m src.retrieval demo --check-dense`` checks that on the 28 original questions.
"""

from __future__ import annotations

from typing import Sequence

from src.retrieval.base import Ranked, RetrievalMethod


class Dense(RetrievalMethod):
    name = "dense"

    def rank(self, question: str, n: int, schemes: Sequence[str] | None = None) -> tuple[Ranked, dict]:
        return self.shared.dense.rank(question, n, schemes), {}
