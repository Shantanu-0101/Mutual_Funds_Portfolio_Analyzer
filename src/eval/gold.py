"""Gold answers computed by code from holdings.parquet (task 5.1, FR-5.2, FR-5.3).

Every gold function takes the holdings DataFrame plus the question's
``params`` and returns ``GoldAnswer(value, rows)``: the correct answer and the
row keys ``(source_file, source_sheet, source_row)`` it was computed from.
No LLM is involved anywhere here.

Rules written down once (the question text states the same rule):

- **Percent** is ``pct_nav`` in percent units. Rows the file shows as
  ``$0.00%`` carry a value computed by the parser (value / grand total); that
  is what is summed.
- **Holding match**: by ISIN when the question has one, else by instrument
  name after ``norm_name`` (case and spaces). A holding that is not found is a
  ``GoldError`` (the question is wrong), except in ``which_holds_more``, where
  a scheme that does not hold the instrument counts as 0.
- **Ratings** (FR-5.3): ``normalise_rating`` turns ``[ICRA]AAA`` into
  ``ICRA AAA`` and upper-cases. A rating parameter with an agency
  (``CARE AAA``) must match exactly; one without (``AAA``) matches that grade
  from any agency. ``AAA(SO)`` (securitised) is its own grade, so it is
  **not** counted as ``AAA``. ``Sovereign`` is a grade with no agency.
  Only rows outside the equity section are rated (equity rows hold an
  industry in that column).
- **Industry** questions count only the ``Equity & Equity Related`` section
  (InvITs in ``Others`` also carry an industry label).
- **Overlap** of two schemes: equity-section holdings with the same ISIN
  (instrument name when the ISIN is empty).
- **Top n**: largest ``pct_nav`` first; ties keep file order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from src.chunking.base import RowKey, row_key

EQUITY_SECTION = "Equity & Equity Related"
AGENCIES = ("CRISIL", "ICRA", "CARE", "IND", "FITCH", "BWR", "ACUITE", "BRICKWORK", "INFOMERICS")


class GoldError(ValueError):
    """A question's parameters do not match the data (wrong name, scheme or month)."""


@dataclass(frozen=True)
class GoldAnswer:
    value: Any                      # float | int | str | list[str] | None
    rows: list[RowKey] = field(default_factory=list)


# --------------------------------------------------------------------------- helpers

def norm_name(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().casefold()


def normalise_rating(rating: Any) -> str:
    """``[ICRA]AAA`` → ``ICRA AAA``; ``crisil  aaa`` → ``CRISIL AAA``; empty → ``""``."""
    if rating is None or (isinstance(rating, float) and pd.isna(rating)):
        return ""
    text = re.sub(r"^\[\s*([A-Za-z]+)\s*\]\s*", r"\1 ", str(rating).strip())
    return re.sub(r"\s+", " ", text).strip().upper()


def split_rating(rating: Any) -> tuple[str | None, str]:
    """``CRISIL AAA(SO)`` → (``CRISIL``, ``AAA(SO)``); ``Sovereign`` → (None, ``SOVEREIGN``)."""
    norm = normalise_rating(rating)
    first, _, rest = norm.partition(" ")
    if first in AGENCIES and rest:
        return first, rest.replace(" ", "")
    return None, norm


def rating_matches(rating: Any, wanted: str) -> bool:
    agency, grade = split_rating(rating)
    w_agency, w_grade = split_rating(wanted)
    if not grade:
        return False
    return grade == w_grade and (w_agency is None or agency == w_agency)


def _keys(rows: pd.DataFrame) -> list[RowKey]:
    return [row_key(r) for r in rows.itertuples(index=False)]


def _pct(rows: pd.DataFrame) -> float:
    return float(rows["pct_nav"].fillna(0).sum())


def scheme_rows(df: pd.DataFrame, scheme_code: str, as_of_date: str) -> pd.DataFrame:
    rows = df[(df["scheme_code"] == scheme_code) & (df["as_of_date"].astype(str) == str(as_of_date))]
    if rows.empty:
        raise GoldError(f"no holdings for scheme {scheme_code} on {as_of_date}")
    return rows


def _holding(rows: pd.DataFrame, instrument: str | None, isin: str | None, required: bool = True) -> pd.DataFrame:
    if isin:
        hit = rows[rows["isin"] == isin]
    elif instrument:
        hit = rows[rows["instrument"].map(norm_name) == norm_name(instrument)]
    else:
        raise GoldError("a holding question needs 'isin' or 'instrument'")
    if hit.empty and required:
        raise GoldError(f"holding {isin or instrument!r} not found in {rows['scheme_code'].iloc[0]}")
    return hit


def _section(rows: pd.DataFrame, section: str | None, subsection: str | None = None) -> pd.DataFrame:
    if section:
        rows = rows[rows["section"] == section]
    if subsection:
        rows = rows[rows["subsection"] == subsection]
    return rows


def _match_key(row: Any) -> str:
    return row.isin if isinstance(row.isin, str) and row.isin else "name:" + norm_name(row.instrument)


# --------------------------------------------------------------------------- gold functions

def holding_pct(df, scheme_code, as_of_date, instrument=None, isin=None) -> GoldAnswer:
    hit = _holding(scheme_rows(df, scheme_code, as_of_date), instrument, isin)
    return GoldAnswer(_pct(hit), _keys(hit))


def holding_value(df, scheme_code, as_of_date, instrument=None, isin=None) -> GoldAnswer:
    hit = _holding(scheme_rows(df, scheme_code, as_of_date), instrument, isin)
    return GoldAnswer(float(hit["market_value_lakhs"].fillna(0).sum()), _keys(hit))


def industry_total(df, scheme_code, as_of_date, industry) -> GoldAnswer:
    rows = _section(scheme_rows(df, scheme_code, as_of_date), EQUITY_SECTION)
    hit = rows[rows["industry_or_rating"].map(norm_name) == norm_name(industry)]
    if hit.empty:
        raise GoldError(f"no {industry!r} holdings in {scheme_code}")
    return GoldAnswer(_pct(hit), _keys(hit))


def top_n_share(df, scheme_code, as_of_date, n, section=EQUITY_SECTION) -> GoldAnswer:
    rows = _section(scheme_rows(df, scheme_code, as_of_date), section)
    if len(rows) < n:
        raise GoldError(f"{scheme_code} has only {len(rows)} rows in {section!r}, fewer than {n}")
    top = rows.assign(_p=rows["pct_nav"].fillna(0)).sort_values("_p", ascending=False, kind="stable").head(n)
    return GoldAnswer(_pct(top), _keys(top))


def holding_count(df, scheme_code, as_of_date, section=EQUITY_SECTION, subsection=None) -> GoldAnswer:
    rows = _section(scheme_rows(df, scheme_code, as_of_date), section, subsection)
    return GoldAnswer(int(len(rows)), _keys(rows))


def section_total(df, scheme_code, as_of_date, section, subsection=None) -> GoldAnswer:
    rows = _section(scheme_rows(df, scheme_code, as_of_date), section, subsection)
    if rows.empty:
        raise GoldError(f"no rows in {section!r} / {subsection!r} for {scheme_code}")
    return GoldAnswer(_pct(rows), _keys(rows))


def _rated(df, scheme_code, as_of_date, rating) -> pd.DataFrame:
    rows = scheme_rows(df, scheme_code, as_of_date)
    rows = rows[rows["section"] != EQUITY_SECTION]
    return rows[rows["industry_or_rating"].map(lambda r: rating_matches(r, rating))]


def rating_share(df, scheme_code, as_of_date, rating) -> GoldAnswer:
    hit = _rated(df, scheme_code, as_of_date, rating)
    return GoldAnswer(_pct(hit), _keys(hit))


def instruments_by_rating(df, scheme_code, as_of_date, rating) -> GoldAnswer:
    hit = _rated(df, scheme_code, as_of_date, rating)
    if hit.empty:
        raise GoldError(f"no {rating!r} holdings in {scheme_code}")
    return GoldAnswer([str(x) for x in hit["instrument"]], _keys(hit))


def overlap_count(df, schemes, as_of_date, section=EQUITY_SECTION) -> GoldAnswer:
    if len(schemes) != 2:
        raise GoldError("overlap_count needs exactly two schemes")
    a, b = (_section(scheme_rows(df, s, as_of_date), section) for s in schemes)
    common = {_match_key(r) for r in a.itertuples()} & {_match_key(r) for r in b.itertuples()}
    rows = pd.concat([a, b])
    rows = rows[[_match_key(r) in common for r in rows.itertuples()]]
    return GoldAnswer(len(common), _keys(rows))


def which_holds_more(df, schemes, as_of_date, instrument=None, isin=None, measure="pct") -> GoldAnswer:
    """The scheme code that holds more of the instrument (by % of AUM or by value)."""
    if measure not in ("pct", "lakhs"):
        raise GoldError("measure must be 'pct' or 'lakhs'")
    col = "pct_nav" if measure == "pct" else "market_value_lakhs"
    amounts, keys = {}, []
    for s in schemes:
        hit = _holding(scheme_rows(df, s, as_of_date), instrument, isin, required=False)
        amounts[s] = float(hit[col].fillna(0).sum())
        keys += _keys(hit)
    if not any(amounts.values()):
        raise GoldError(f"none of {schemes} holds {isin or instrument!r}")
    ranked = sorted(amounts.items(), key=lambda kv: kv[1], reverse=True)
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        raise GoldError(f"tie between {ranked[0][0]} and {ranked[1][0]}")
    return GoldAnswer(ranked[0][0], keys)


def not_in_data(df=None, **_: Any) -> GoldAnswer:
    return GoldAnswer(None, [])


GOLD_FUNCTIONS: dict[str, Callable[..., GoldAnswer]] = {
    f.__name__: f for f in (holding_pct, holding_value, industry_total, top_n_share, holding_count,
                            rating_share, instruments_by_rating, section_total, overlap_count,
                            which_holds_more, not_in_data)
}


def compute(df: pd.DataFrame, gold_fn: str, params: dict) -> GoldAnswer:
    if gold_fn not in GOLD_FUNCTIONS:
        raise GoldError(f"unknown gold_fn {gold_fn!r}")
    try:
        return GOLD_FUNCTIONS[gold_fn](df, **params)
    except TypeError as e:  # wrong parameter names in questions.yaml
        raise GoldError(f"{gold_fn}: {e}") from None
