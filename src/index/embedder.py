"""Text → vector with ``BAAI/bge-small-en-v1.5``, cached on disk (task 3.4, FR-3.2).

Why a cache: the six collections share a lot of identical text (row_wise and
the hierarchical children are the same 5,646 lines), and re-indexing after a
small change should only embed what changed. Vectors are stored in one SQLite
file (``<paths.cache>/embeddings.sqlite``) keyed by (model, sha256(text)):
one file, not thousands, which matters inside a OneDrive folder.

Vectors are L2-normalised, so cosine similarity = dot product.

Queries get the instruction prefix the bge model card recommends for short
question → passage retrieval; documents are embedded as they are. The model
truncates anything over 512 tokens (that is what ``Chunk.truncated`` records).
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

EncodeFn = Callable[[list[str]], np.ndarray]


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class VectorCache:
    """(model, text hash) → float32 vector, in SQLite."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(str(path))
        self.db.execute("CREATE TABLE IF NOT EXISTS vectors (model TEXT, hash TEXT, dim INTEGER, vec BLOB, "
                        "PRIMARY KEY (model, hash))")
        self.db.commit()

    def get_many(self, model: str, hashes: Sequence[str]) -> dict[str, np.ndarray]:
        out: dict[str, np.ndarray] = {}
        unique = list(dict.fromkeys(hashes))
        for i in range(0, len(unique), 500):
            part = unique[i:i + 500]
            rows = self.db.execute(
                f"SELECT hash, vec FROM vectors WHERE model = ? AND hash IN ({','.join('?' * len(part))})",
                [model, *part]).fetchall()
            out.update({h: np.frombuffer(v, dtype=np.float32) for h, v in rows})
        return out

    def put_many(self, model: str, items: dict[str, np.ndarray]) -> None:
        self.db.executemany("INSERT OR REPLACE INTO vectors VALUES (?, ?, ?, ?)",
                            [(model, h, int(v.shape[0]), v.astype(np.float32).tobytes()) for h, v in items.items()])
        self.db.commit()

    def close(self) -> None:
        self.db.close()


class Embedder:
    def __init__(self, model: str, cache_path: Path | None, batch_size: int = 32,
                 encode_fn: EncodeFn | None = None, query_prefix: str | None = None):
        self.model = model
        self.batch_size = batch_size
        self.cache = VectorCache(cache_path) if cache_path else None
        self._encode_fn = encode_fn
        self.query_prefix = BGE_QUERY_PREFIX if query_prefix is None and "bge" in model.lower() else (query_prefix or "")
        self.hits = 0
        self.misses = 0

    @classmethod
    def from_settings(cls, settings, encode_fn: EncodeFn | None = None) -> "Embedder":
        return cls(settings.embedding.model, settings.paths.cache / "embeddings.sqlite",
                   settings.embedding.batch_size, encode_fn)

    def load(self) -> None:
        """Load the model now (a few seconds), so the first timed query does not pay for it."""
        if self._encode_fn is None:
            from sentence_transformers import SentenceTransformer  # heavy: load only when needed

            st = SentenceTransformer(self.model, device="cpu")

            def encode(batch: list[str]) -> np.ndarray:
                return st.encode(batch, batch_size=self.batch_size, normalize_embeddings=True,
                                 convert_to_numpy=True, show_progress_bar=len(batch) > 500)

            self._encode_fn = encode

    def _encode(self, texts: list[str]) -> np.ndarray:
        self.load()
        return np.asarray(self._encode_fn(texts), dtype=np.float32)

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        hashes = [text_hash(t) for t in texts]
        found = self.cache.get_many(self.model, hashes) if self.cache else {}
        todo = {h: t for h, t in zip(hashes, texts) if h not in found}
        self.hits += len(texts) - sum(1 for h in hashes if h in todo)
        self.misses += sum(1 for h in hashes if h in todo)
        if todo:
            vectors = self._encode(list(todo.values()))
            new = dict(zip(todo.keys(), vectors))
            if self.cache:
                self.cache.put_many(self.model, new)
            found = {**found, **new}
        return np.stack([found[h] for h in hashes])

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([self.query_prefix + text])[0]
