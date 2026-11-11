"""Section headings and the section -> asset_class mapping (task 1.7, D6).

Why a visible table: which bucket a TREPS line or an InvIT lands in changes the
answer to "how much debt does this fund hold?". Keeping the mapping as plain
data here means a reader can check it without reading parser code.

Source: DATA_NOTES §4 (headings seen in all 417 sheets) and §5 (draft mapping),
with Q2 answered as recommended: TREPS / Reverse Repo -> ``debt``.

All keys are lower-case with whitespace collapsed (see ``key``), so
``a) Listed/awaiting listing on Stock Exchanges`` and ``... the stock exchanges``
both match case-insensitively.
"""

from __future__ import annotations

from src.parsing.values import norm

AMC = "Aditya Birla Sun Life Mutual Fund"

EQUITY, DEBT, OTHER = "equity", "debt", "other"

# The five main headings, in the order they appear when present (DATA_NOTES §4).
# Any other heading text is a sub-heading.
MAIN_EQUITY = "equity & equity related"
MAIN_DEBT = "debt instruments"
MAIN_MONEY_MARKET = "money market instruments"
MAIN_OTHERS = "others"
MAIN_OTHER_CURRENT = "other current assets / (liabilities)"
MAIN_HEADINGS = (MAIN_EQUITY, MAIN_DEBT, MAIN_MONEY_MARKET, MAIN_OTHERS, MAIN_OTHER_CURRENT)

# Sub-headings
LISTED_EQ = "a) listed/awaiting listing on stock exchanges"
LISTED_DEBT = "a) listed/awaiting listing on the stock exchanges"
UNLISTED_EQ = "b) unlisted"
PRIVATE_DEBT = "b) privately placed/unlisted"
FOREIGN = "foreign securities and /or overseas etf"
GSEC = "government securities"
SECURITISED = "securitised debt"
CP = "commercial paper"
CD = "certificate of deposits"
TBILL = "treasury bills"
STRIPS = "strips"
TREPS = "treps / reverse repo investments"
MF_UNITS = "mutual fund units"
INTL_MF_UNITS = "international mutual fund units"
ETF = "exchange traded fund"
AIF = "alternative investment funds"
INVIT = "infrastructure investment trust"
GOLD = "gold"
SILVER = "silver"

# (main heading, sub-heading) -> asset_class. ``None`` sub = rows directly under the main heading.
ASSET_CLASS_BY_SECTION: dict[tuple[str, str | None], str] = {
    (MAIN_EQUITY, LISTED_EQ): EQUITY,
    (MAIN_EQUITY, UNLISTED_EQ): EQUITY,
    (MAIN_EQUITY, FOREIGN): EQUITY,              # direct foreign shares (e.g. Microsoft)
    (MAIN_DEBT, LISTED_DEBT): DEBT,
    (MAIN_DEBT, PRIVATE_DEBT): DEBT,
    (MAIN_DEBT, GSEC): DEBT,
    (MAIN_DEBT, SECURITISED): DEBT,
    (MAIN_MONEY_MARKET, CP): DEBT,
    (MAIN_MONEY_MARKET, CD): DEBT,
    (MAIN_MONEY_MARKET, TBILL): DEBT,
    (MAIN_MONEY_MARKET, STRIPS): DEBT,
    (MAIN_OTHERS, TREPS): DEBT,                  # Q2: short-term lending against G-secs
    (MAIN_OTHERS, MF_UNITS): OTHER,
    (MAIN_OTHERS, INTL_MF_UNITS): OTHER,
    (MAIN_OTHERS, ETF): OTHER,
    (MAIN_OTHERS, AIF): OTHER,
    (MAIN_OTHERS, INVIT): OTHER,
    (MAIN_OTHERS, GOLD): OTHER,
    (MAIN_OTHERS, SILVER): OTHER,
    (MAIN_OTHERS, FOREIGN): OTHER,               # overseas ETF units held by a fund of funds
    (MAIN_OTHER_CURRENT, None): OTHER,           # net receivable / payable, derivative margin
}

# Sub-heading with no main heading above it: Jul/Aug fund-of-fund sheets
# (NSDAQ100, BSLGRE) start directly with a sub-heading (DATA_NOTES §4).
ASSET_CLASS_BY_SUB_ONLY: dict[str, str] = {
    FOREIGN: OTHER,
    INTL_MF_UNITS: OTHER,
    MF_UNITS: OTHER,
    ETF: OTHER,
    AIF: OTHER,
    INVIT: OTHER,
    GOLD: OTHER,
    SILVER: OTHER,
    TREPS: DEBT,
}

# Last resort when a (main, sub) pair is new: the main heading's usual class.
# Used rows are reported as warnings, so a new layout is noticed, not hidden.
ASSET_CLASS_BY_MAIN: dict[str, str] = {
    MAIN_EQUITY: EQUITY,
    MAIN_DEBT: DEBT,
    MAIN_MONEY_MARKET: DEBT,
    MAIN_OTHERS: OTHER,
    MAIN_OTHER_CURRENT: OTHER,
}


def key(text: str | None) -> str | None:
    """Lower-case, whitespace-collapsed form used for every lookup here."""
    if text is None:
        return None
    k = norm(text).lower()
    return k or None


def is_main_heading(text: str) -> bool:
    return key(text) in MAIN_HEADINGS


def asset_class_for(main: str | None, sub: str | None) -> tuple[str | None, str]:
    """Return (asset_class, how). ``how`` is "section", "sub_only", "main_fallback" or "none"."""
    m, s = key(main), key(sub)
    if m is not None:
        if (m, s) in ASSET_CLASS_BY_SECTION:
            return ASSET_CLASS_BY_SECTION[(m, s)], "section"
        return ASSET_CLASS_BY_MAIN.get(m), "main_fallback"
    if s is not None and s in ASSET_CLASS_BY_SUB_ONLY:
        return ASSET_CLASS_BY_SUB_ONLY[s], "sub_only"
    return None, "none"
