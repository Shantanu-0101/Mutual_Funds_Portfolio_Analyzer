"""Mutual Fund Portfolio Analyzer: the app (Phase 6, spec §6.7).

    streamlit run app/streamlit_app.py

Three pages, in ``app/pages/``:

- Ask      one question, one chunking method (or the pandas baseline), with the rows and chunks behind it
- Compare  one question through every method, side by side
- Results  the recorded evaluation: the recommended chunker, the tables, the chart, the Excel report

The app only reads what ``python -m src.parsing`` and ``python -m src.index`` built (FR-6.4).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="MF Portfolio Analyzer", page_icon=":material/pie_chart:", layout="wide")

pages = [
    st.Page("pages/ask.py", title="Ask", icon=":material/chat:", default=True),
    st.Page("pages/compare.py", title="Compare", icon=":material/view_column:"),
    st.Page("pages/results.py", title="Results", icon=":material/leaderboard:"),
]
st.navigation(pages).run()
