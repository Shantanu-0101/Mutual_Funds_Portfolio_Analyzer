"""Small value rules shared by the parser (task 1.5).

Why a separate module: these rules decide what numbers end up in the gold
answers, so each one is written once, named, and unit-tested.

- ``% to AUM`` and YTM/YTC are fractions in the file (``0.0559`` = 5.59%); we
  store percent units (spec §6.2).
- ``$0.00%`` and the ``Other Current Assets`` rows get their % from
  value / grand total (FR-1.3, DATA_NOTES R6); that rule lives in
  ``sheet_parser.pct_rule`` because it needs the section.
"""

from __future__ import annotations

import re
from datetime import date, datetime

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
# Codes that sit in the ISIN column but are not real ISINs (DATA_NOTES §8):
# IDIA… = ABSL dummy codes for unlisted securities, GSECREPO… = reverse repo legs.
NOT_ISIN_PREFIXES = ("IDIA", "GSECREPO")
# Text that marks footnotes / the notes block below the portfolio (DATA_NOTES §9).
FOOTNOTE_RE = re.compile(r"^(\*|#|\$|\^|notes\s*:|fr[bn]\s*-|ytc represents)", re.IGNORECASE)
AS_ON_RE = re.compile(r"as on\s+([A-Za-z]+)\s+(\d{1,2}),?\s*(\d{4})", re.IGNORECASE)


def norm(text: object) -> str:
    """Collapse whitespace (incl. non-breaking spaces and line breaks) and strip."""
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text).replace("\xa0", " ")).strip()


def is_num(v: object) -> bool:
    return isinstance(v, float) and not isinstance(v, bool)


def num_or_none(v: object) -> float | None:
    return float(v) if is_num(v) else None


def fraction_to_pct(v: object) -> float | None:
    """0.0559 -> 5.59 (percent units). Non-numbers -> None."""
    return float(v) * 100.0 if is_num(v) else None


def parse_as_on(text: str) -> date | None:
    """'Portfolio Statement as on September 30, 2026' -> date(2026, 9, 30)."""
    m = AS_ON_RE.search(text)
    if not m:
        return None
    try:
        return datetime.strptime(" ".join(m.groups()), "%B %d %Y").date()
    except ValueError:
        return None


def isin_check_digit_ok(isin: str) -> bool:
    """ISO 6166 check digit: letters -> 10..35, then the Luhn algorithm."""
    if not ISIN_RE.match(isin):
        return False
    digits = "".join(str(int(ch, 36)) for ch in isin[:-1])
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            d = d - 9 if d > 9 else d
        total += d
    return (10 - total % 10) % 10 == int(isin[-1])


def isin_valid(isin: str | None) -> bool:
    """A real ISIN usable for cross-scheme matching (DATA_NOTES R8).

    The prefix test matters: 6 of the 44 IDIA dummy codes pass the check digit by chance.
    """
    if not isin:
        return False
    return isin_check_digit_ok(isin) and not isin.startswith(NOT_ISIN_PREFIXES)


def looks_like_footnote(text: str) -> bool:
    return bool(FOOTNOTE_RE.match(text))
