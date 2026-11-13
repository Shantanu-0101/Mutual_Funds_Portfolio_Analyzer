"""The baseline prompt and reading the code out of the reply (task 4.2, FR-4.1).

The model replies with one JSON object (JSON mode, same as the RAG prompt)::

    {"code": "result = df[...]...", "unit": "pct" | "lakhs" | "count" | null}

``unit`` is the unit of ``result`` when it is a number; the code alone cannot
say whether 5.6 is a percent or lakhs, and the metrics need the same answer
object as RAG (FR-4.4). A reply that is not this object is a format failure;
nothing is repaired except stripping a ```python fence around the code, which
is formatting, not content.
"""

from __future__ import annotations

import json
import re

from src.rag.prompt import UNITS

SYSTEM_PROMPT = """You answer questions about Indian mutual fund portfolio holdings by writing pandas code.

A pandas DataFrame `df` is already loaded; its schema is below. `pd` is pandas. Nothing else is available.

Rules:
1. Write Python code that computes the answer from `df` and stores it in a variable named `result`.
2. Not allowed (the code is rejected): import, open/exec/eval/getattr, any name starting with "_", reading or writing files, .query() and .eval() (use boolean masks instead).
3. `result` must be a number, a string, a list of strings, or the matching rows of `df` (a DataFrame or Series that keeps df's index) when the question asks for a list of holdings.
4. Pick schemes by scheme_code from the list below. Text columns are written as in the files, so prefer case-insensitive matching (str.contains(..., case=False, regex=False)) over exact equality for names and industries.
5. "% of AUM", "% to NAV" and "weight" mean the pct_nav column, already in percent. Values are market_value_lakhs, in Rs lakhs.
6. If df cannot answer the question (a month, scheme or field that is not in df), set result = None.
7. Reply with ONE JSON object and nothing else:
{"code": string, the Python code,
 "unit": "pct" or "lakhs" or "count" or null, the unit of `result` when it is a number}"""


def build_messages(question: str, schema: str) -> list[dict[str, str]]:
    user = f"Schema:\n\n{schema}\n\nQuestion: {question}\n\nReply with the JSON object only."
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


class ReplyFormatError(ValueError):
    pass


_FENCE = re.compile(r"^\s*```(?:python|py)?\s*\n(.*?)\n?\s*```\s*$", re.DOTALL)


def parse_reply(text: str) -> tuple[str, str | None]:
    """(code, unit) from the model's JSON reply; ReplyFormatError if it is off-format."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as e:
        raise ReplyFormatError(f"not valid JSON: {e}") from None
    if not isinstance(data, dict) or "code" not in data or "unit" not in data:
        raise ReplyFormatError("reply must be a JSON object with keys 'code' and 'unit'")
    code, unit = data["code"], data["unit"]
    if not isinstance(code, str) or not code.strip():
        raise ReplyFormatError("'code' must be a non-empty string")
    if unit is not None and unit not in UNITS:
        raise ReplyFormatError(f"'unit' must be one of {UNITS} or null")
    m = _FENCE.match(code)
    return (m.group(1) if m else code).strip(), unit
