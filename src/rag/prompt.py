"""The generation prompt and the answer format (task 3.8, FR-3.5, FR-3.6).

One prompt for every chunker, so only the context differs between methods.

The model must reply with one JSON object::

    {"answer": "plain-English answer",
     "value": 5.6, "unit": "pct" | "lakhs" | "count" | null,
     "items": ["for list answers"],
     "sources": [{"scheme": "...", "instrument": "..."}],
     "insufficient_context": false}

Change from the spec's example: ``sources`` has no ``row``. The chunk text the
model sees has no Excel row numbers, so it could only guess them. The pipeline
instead matches each cited (scheme, instrument) to the context rows, which
gives exact row keys (``RagResult.cited_rows``).

``parse_answer`` is strict: invalid JSON, a missing key or a wrong type is a
format failure (FR-3.6). Nothing is repaired; extra keys are ignored.
"""

from __future__ import annotations

import json
import re
from typing import Any

from src.chunking.base import Chunk

UNITS = ("pct", "lakhs", "count")

SYSTEM_PROMPT = """You answer questions about mutual fund portfolio holdings (Indian mutual fund monthly disclosures).

Rules:
1. Use ONLY the context chunks given below. Never use outside knowledge, and never fill in numbers from memory.
2. If the context does not contain what is needed to answer fully, set "insufficient_context" to true and say what is missing. Do not guess.
3. Numbers: "% to AUM" values are already in percent (5.60 means 5.60%). "Value (Rs L)" is in Rs lakhs. When you add or compare values, use only rows present in the context.
4. Cite every holding you used in "sources" with its scheme name and instrument name exactly as written in the context.
5. Reply with ONE JSON object and nothing else, with exactly these keys:
{"answer": string, plain-English answer,
 "value": number or null, the single numeric answer if there is one,
 "unit": "pct" or "lakhs" or "count" or null, the unit of "value",
 "items": list of strings, for answers that are a list (else []),
 "sources": list of {"scheme": string, "instrument": string},
 "insufficient_context": true or false}"""


def format_context(chunks: list[Chunk]) -> str:
    return "\n\n".join(f"[Chunk {n}]\n{c.text}" for n, c in enumerate(chunks, 1))


def build_messages(question: str, chunks: list[Chunk]) -> list[dict[str, str]]:
    user = (f"Context:\n\n{format_context(chunks)}\n\n" if chunks else "Context: (no chunks retrieved)\n\n")
    user += f"Question: {question}\n\nReply with the JSON object only."
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


class AnswerFormatError(ValueError):
    pass


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def parse_answer(text: str) -> dict:
    """Parse and check the model's JSON answer; raise AnswerFormatError on anything off-format."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as e:
        raise AnswerFormatError(f"not valid JSON: {e}") from None
    if not isinstance(data, dict):
        raise AnswerFormatError("answer is not a JSON object")
    missing = [k for k in ("answer", "value", "unit", "items", "sources", "insufficient_context") if k not in data]
    if missing:
        raise AnswerFormatError(f"missing keys: {missing}")
    if not isinstance(data["answer"], str):
        raise AnswerFormatError("'answer' must be a string")
    if data["value"] is not None and not _is_number(data["value"]):
        raise AnswerFormatError("'value' must be a number or null")
    if data["unit"] is not None and data["unit"] not in UNITS:
        raise AnswerFormatError(f"'unit' must be one of {UNITS} or null")
    if not isinstance(data["items"], list) or not all(isinstance(i, str) for i in data["items"]):
        raise AnswerFormatError("'items' must be a list of strings")
    if not isinstance(data["sources"], list) or not all(
            isinstance(s, dict) and isinstance(s.get("scheme"), str) and isinstance(s.get("instrument"), str)
            for s in data["sources"]):
        raise AnswerFormatError("'sources' must be a list of {scheme, instrument} objects")
    if not isinstance(data["insufficient_context"], bool):
        raise AnswerFormatError("'insufficient_context' must be true or false")
    return data


def norm_name(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().casefold()
