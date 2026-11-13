"""ChromaDB collections, one per chunker (task 3.5, FR-3.1).

Why one collection per chunker: retrieval must only ever compare chunks made
the same way, and every collection gets identical settings (cosine distance,
same HNSW parameters, vectors from the same embedding model, which is stored
on the collection and checked when it is opened again).

Chroma metadata must be flat strings / numbers / booleans and cannot be null,
so ``source_rows`` is stored as a JSON string and a missing ``parent_id`` as
``""``. ``chunk_from_record`` turns a stored record back into a ``Chunk``.

Indexing a month replaces that month's chunks in the collection (delete by
``as_of_date``, then add), so re-running is safe and other months are kept.

Hierarchical parents are never embedded. They are saved next to the parsed
tables in ``data/processed/parents_hierarchical.parquet`` and looked up by id
at query time.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.chunking.base import Chunk

PARENTS_FILE = "parents_hierarchical.parquet"
HNSW = {"space": "cosine", "ef_construction": 100, "ef_search": 100}
ADD_BATCH = 1000


class IndexNotBuilt(RuntimeError):
    """The index is missing or was built differently from what is asked now."""


def open_client(path: Path):
    import chromadb

    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path), settings=chromadb.Settings(anonymized_telemetry=False))


def collection_name(chunker: str) -> str:
    return f"mfpa_{chunker}"


def get_collection(client, chunker: str, embedding_model: str, create: bool = False):
    name = collection_name(chunker)
    if create:
        col = client.get_or_create_collection(name, configuration={"hnsw": HNSW},
                                              metadata={"chunker": chunker, "embedding_model": embedding_model},
                                              embedding_function=None)
    else:
        try:
            col = client.get_collection(name, embedding_function=None)
        except Exception as e:
            raise IndexNotBuilt(f"no collection for {chunker!r}: run `python -m src.index` first") from e
    built_with = (col.metadata or {}).get("embedding_model")
    if built_with != embedding_model:
        raise IndexNotBuilt(f"collection {name} was built with {built_with!r}, config says {embedding_model!r}; "
                          "re-index")
    return col


def chunk_metadata(c: Chunk) -> dict:
    return {"chunker": c.chunker, "amc": c.amc, "scheme_code": c.scheme_code, "scheme": c.scheme,
            "as_of_date": c.as_of_date, "section": c.section, "source_rows": json.dumps([list(k) for k in c.source_rows]),
            "parent_id": c.parent_id or "", "n_tokens": int(c.n_tokens), "truncated": bool(c.truncated)}


def chunk_from_record(chunk_id: str, text: str, meta: dict) -> Chunk:
    return Chunk(id=chunk_id, text=text, chunker=meta["chunker"], amc=meta["amc"], scheme_code=meta["scheme_code"],
                 scheme=meta["scheme"], as_of_date=meta["as_of_date"], section=meta["section"],
                 source_rows=tuple((f, s, int(r)) for f, s, r in json.loads(meta["source_rows"])),
                 n_tokens=int(meta["n_tokens"]), truncated=bool(meta["truncated"]),
                 parent_id=meta.get("parent_id") or None)


def write_month(col, month: str, chunks: list[Chunk], vectors: np.ndarray) -> int:
    """Replace ``month`` in the collection with ``chunks``. Returns how many were stored."""
    if len(chunks) != len(vectors):
        raise ValueError("one vector per chunk expected")
    col.delete(where={"as_of_date": month})
    for i in range(0, len(chunks), ADD_BATCH):
        part = chunks[i:i + ADD_BATCH]
        col.add(ids=[c.id for c in part], documents=[c.text for c in part],
                metadatas=[chunk_metadata(c) for c in part], embeddings=vectors[i:i + ADD_BATCH].tolist())
    return len(chunks)


# --------------------------------------------------------------------------- hierarchical parents

def parents_to_frame(parents: list[Chunk]) -> pd.DataFrame:
    return pd.DataFrame([{"id": p.id, "text": p.text, **chunk_metadata(p)} for p in parents])


def write_parents(path: Path, month: str, parents: list[Chunk]) -> None:
    new = parents_to_frame(parents)
    if path.is_file():
        old = pd.read_parquet(path)
        new = pd.concat([old[old["as_of_date"] != month], new], ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    new.to_parquet(path, index=False)


def read_parents(path: Path) -> dict[str, Chunk]:
    if not path.is_file():
        raise IndexNotBuilt(f"{path} not found: run `python -m src.index --chunkers hierarchical` first")
    df = pd.read_parquet(path)
    return {r["id"]: chunk_from_record(r["id"], r["text"], r) for r in df.to_dict("records")}
