"""What the LLM is told about ``df`` (task 4.1, FR-4.1).

Exactly what the spec lists, nothing more: column names, types, a short meaning
and a few example values per column, then the full lists of scheme names,
sections and months. The description is built from the same DataFrame the
sandbox loads (``sandbox.load_frame``), so it can never drift from the data.
"""

from __future__ import annotations

import pandas as pd

from src.baseline.sandbox import FRAME_COLUMNS

N_EXAMPLES = 4

COLUMN_NOTES = {
    "scheme_code": "short code of the scheme (fund); the full list is below",
    "scheme": "full scheme name as printed by the AMC, in capitals",
    "as_of_date": "portfolio date, 'YYYY-MM-DD' string",
    "section": "main heading the holding sits under in the disclosure",
    "subsection": "sub-heading under the section (may be empty)",
    "asset_class": "equity, debt or other (derived from section)",
    "instrument": "name of the company / security / instrument held",
    "isin": "ISIN code (may be empty for cash-like items)",
    "industry_or_rating": "industry for equity (e.g. Banks), credit rating for debt (e.g. 'ICRA AAA', "
                          "'[ICRA]AAA', 'SOVEREIGN'); written as in the file",
    "quantity": "number of shares / units held",
    "market_value_lakhs": "market value in Rs lakhs",
    "pct_nav": "% of the scheme's AUM held in this item, already in percent (5.6 means 5.6%); "
               "all rows of one scheme and date add up to about 100",
    "ytm": "yield to maturity in percent (debt only, else empty)",
    "ytc": "yield to call in percent (debt only, else empty)",
}


def _examples(series: pd.Series) -> str:
    values = series.dropna()
    values = values[values.astype(str).str.strip() != ""]
    if pd.api.types.is_float_dtype(values):
        picks = values.sample(min(N_EXAMPLES, len(values)), random_state=0).round(4).tolist()
    else:
        picks = values.drop_duplicates().head(N_EXAMPLES).tolist()
    return ", ".join(repr(v) for v in picks)


def describe_frame(df: pd.DataFrame) -> str:
    assert tuple(df.columns) == FRAME_COLUMNS, "schema and sandbox frame disagree"
    months = sorted(df["as_of_date"].unique())
    lines = [f"DataFrame `df`: {len(df):,} rows, one row per holding of one scheme on one date.",
             f"Dates (as_of_date): {', '.join(months)}.", "", "Columns (name, dtype: meaning; examples):"]
    for col in FRAME_COLUMNS:
        dtype = "str" if df[col].dtype == object or pd.api.types.is_string_dtype(df[col]) else str(df[col].dtype)
        lines.append(f"- {col} ({dtype}): {COLUMN_NOTES[col]}; e.g. {_examples(df[col])}")
    lines += ["", "Sections (section): " + "; ".join(sorted(df["section"].dropna().unique())),
              "Asset classes (asset_class): " + ", ".join(sorted(df["asset_class"].dropna().unique()))]
    schemes = df[["scheme_code", "scheme"]].drop_duplicates().sort_values("scheme_code")
    lines += ["", f"Schemes ({len(schemes)}), scheme_code: scheme:"]
    lines += [f"{r.scheme_code}: {r.scheme}" for r in schemes.itertuples(index=False)]
    return "\n".join(lines)
