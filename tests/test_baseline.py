"""Phase 4 tests (spec §10): guard, sandbox process, result conversion, reply parsing, pipeline. No network."""

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.baseline import sandbox
from src.baseline.guard import BlockedCode, check_code
from src.baseline.pipeline import BaselinePipeline, to_answer
from src.baseline.sandbox import FRAME_COLUMNS, load_frame, run_code, run_in_sandbox, to_plain
from src.baseline.schema import describe_frame
from src.baseline.text_to_pandas import ReplyFormatError, build_messages, parse_reply
from src.config import load_settings
from src.llm import LLM, MockProvider, RateLimited

NO_ENV = Path("does-not-exist.env")
SEP, AUG = date(2026, 9, 30), date(2026, 8, 31)


def _row(n, code, scheme, d, section, instrument, industry, value, pct):
    return dict(amc="ABSL", scheme_code=code, scheme=scheme, as_of_date=d, section=section, subsection="",
                asset_class="equity" if section.startswith("Equity") else "debt", instrument=instrument,
                isin=f"INE{n:09d}", industry_or_rating=industry, quantity=float(n * 100), market_value_lakhs=value,
                pct_nav=pct, ytm=np.nan, ytc=np.nan, source_file="f.xls", source_sheet=code, source_row=10 + n)


@pytest.fixture(scope="module")
def parquet(tmp_path_factory) -> Path:
    eq, debt = "Equity & Equity Related", "Debt Instruments"
    rows = [
        _row(1, "FLEXI", "ABSL FLEXI CAP FUND", SEP, eq, "ICICI Bank Ltd.", "Banks", 500.0, 5.6),
        _row(2, "FLEXI", "ABSL FLEXI CAP FUND", SEP, eq, "HDFC Bank Ltd.", "Banks", 400.0, 4.4),
        _row(3, "FLEXI", "ABSL FLEXI CAP FUND", SEP, eq, "Infosys Ltd.", "IT - Software", 300.0, 3.0),
        _row(4, "INCOME", "ABSL INCOME FUND", SEP, debt, "7.1% GOI 2034", "SOVEREIGN", 900.0, 60.0),
        _row(5, "INCOME", "ABSL INCOME FUND", SEP, debt, "NABARD Bond", "ICRA AAA", 600.0, 40.0),
        _row(6, "FLEXI", "ABSL FLEXI CAP FUND", AUG, eq, "ICICI Bank Ltd.", "Banks", 450.0, 5.1),
    ]
    path = tmp_path_factory.mktemp("processed") / "holdings.parquet"
    pd.DataFrame(rows).to_parquet(path)
    return path


@pytest.fixture(scope="module")
def frame(parquet):
    return load_frame(parquet, ["2026-09-30"])


# --------------------------------------------------------------------------- guard

@pytest.mark.parametrize("code", [
    "import os\nresult = 1",
    "from os import path\nresult = 1",
    "result = open('x').read()",
    "f = eval\nresult = f('1')",
    "result = exec('x=1')",
    "result = getattr(df, 'shape')",
    "result = df.__class__",
    "result = ().__class__.__bases__[0].__subclasses__()",
    "result = df._data",
    "result = '{0.__class__}'.format(df)",
    "df.to_csv('out.csv')\nresult = 1",
    "df.to_string(buf='out.txt')\nresult = 1",
    "result = pd.read_excel('x.xls')",
    "result = pd.read_parquet('x')",
    "result = df.query('pct_nav > 1')",
    "result = pd.eval('1+1')",
    "result = pd.io.common",
    "pd.set_option('display.max_rows', 5)\nresult = 1",
    "class A:\n    pass\nresult = 1",
    "result = (x for x in []).gi_frame.f_globals",
    "def _hidden():\n    return 1\nresult = 1",
    "with pd.ExcelWriter('x.xlsx') as w:\n    pass\nresult = 1",
])
def test_guard_blocks(code):
    with pytest.raises(BlockedCode):
        check_code(code)


@pytest.mark.parametrize("code", [
    "result = df.groupby('scheme_code')['pct_nav'].sum()",
    "m = df['industry_or_rating'].str.contains('bank', case=False, regex=False)\nresult = df[m].pct_nav.sum()",
    "result = df.loc[df.scheme_code == 'FLEXI', 'instrument'].to_list()",
    "result = sorted({x for x in df.instrument if 'Bank' in x})",
    "result = df.nlargest(3, 'pct_nav').pct_nav.sum()",
    "def top(n):\n    return df.nlargest(n, 'pct_nav')\nresult = top(2)",
    "result = len(df.apply(lambda r: r['pct_nav'] * 2, axis=1))",
    "result = pd.to_numeric(df['quantity']).max()",
])
def test_guard_allows_plain_pandas(code):
    check_code(code)


def test_guard_lists_every_problem_and_passes_syntax_errors():
    with pytest.raises(BlockedCode) as e:
        check_code("import os\nresult = open('x')")
    assert "import" in str(e.value) and "'open'" in str(e.value)
    with pytest.raises(SyntaxError):
        check_code("result = (")


# --------------------------------------------------------------------------- sandbox (real child processes)

def test_sandbox_runs_code_on_the_frame(parquet):
    res = run_in_sandbox("result = df[df.industry_or_rating == 'Banks'].pct_nav.sum()", parquet, ["2026-09-30"], 10)
    assert res["ok"] and res["result"] == {"kind": "scalar", "value": pytest.approx(10.0)}


def test_sandbox_kills_endless_code(parquet):
    res = run_in_sandbox("while True:\n    pass", parquet, ["2026-09-30"], 1.5)
    assert not res["ok"] and res["error_type"] == "timeout"
    assert res["wall_ms"] < 10_000


def test_sandbox_reports_errors_and_missing_result(parquet):
    res = run_in_sandbox("x = df['no_such_column']", parquet, ["2026-09-30"], 10)
    assert res["error_type"] == "runtime_error" and "KeyError" in res["error"]
    # even if the guard were skipped, the builtins are not there
    res = run_in_sandbox("result = open('x')", parquet, ["2026-09-30"], 10)
    assert res["error_type"] == "runtime_error" and "open" in res["error"]
    res = run_in_sandbox("print('hi')\nx = 1", parquet, ["2026-09-30"], 10)
    assert res["error_type"] == "no_result" and res["stdout"] == "hi\n"


def test_sandbox_start_failure_reported(tmp_path):
    res = run_in_sandbox("result = 1", tmp_path / "missing.parquet", ["2026-09-30"], 10)
    assert res["error_type"] == "sandbox_error" and "missing.parquet" in res["error"]


def test_child_env_has_no_secrets(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xk")
    monkeypatch.setenv("MY_TOKEN", "t")
    monkeypatch.setenv("HARMLESS", "1")
    env = sandbox._clean_env()
    assert "XAI_API_KEY" not in env and "MY_TOKEN" not in env and env["HARMLESS"] == "1"


def test_run_code_in_process_scope(frame):
    assert run_code("result = len(df)", frame)["result"] == {"kind": "scalar", "value": 5}
    with pytest.raises(NameError):
        run_code("result = __import__('os')", frame)
    run_code("df['pct_nav'] = 0.0\nresult = 0", frame)
    assert frame["pct_nav"].max() == 60.0      # the code gets a copy


# --------------------------------------------------------------------------- to_plain / to_answer

def test_to_plain_types(frame):
    assert to_plain(np.int64(3)) == {"kind": "scalar", "value": 3}
    assert to_plain(float("nan")) == {"kind": "scalar", "value": None}
    assert to_plain(pd.Timestamp("2026-09-30")) == {"kind": "scalar", "value": "2026-09-30"}
    assert to_plain({"b", "a"}) == {"kind": "list", "values": ["a", "b"], "n": 2}
    s = to_plain(frame.groupby("scheme_code").pct_nav.sum())
    assert s["kind"] == "series" and s["index"] == ["FLEXI", "INCOME"] and s["values"] == [13.0, 100.0]
    d = to_plain(frame.head(2))
    assert d["kind"] == "dataframe" and d["n"] == 2 and d["columns"] == list(FRAME_COLUMNS)


def answer_of(value, frame, unit=None):
    return to_answer(to_plain(value), unit, frame.index, frame["instrument"])


def test_to_answer_numbers_text_and_empty(frame):
    a, rows = answer_of(5.6, frame, "pct")
    assert (a["value"], a["unit"], a["items"], a["insufficient_context"], rows) == (5.6, "pct", [], False, [])
    assert answer_of(None, frame, "pct")[0]["insufficient_context"] is True
    assert answer_of(None, frame, "pct")[0]["unit"] is None
    assert answer_of(float("nan"), frame)[0]["insufficient_context"] is True
    assert answer_of(frame.iloc[0:0], frame)[0]["insufficient_context"] is True
    assert answer_of("ABSL INCOME FUND", frame)[0]["items"] == ["ABSL INCOME FUND"]
    a = answer_of(True, frame)[0]
    assert a["answer"] == "Result: Yes" and not a["insufficient_context"]
    assert answer_of([3], frame, "count")[0]["value"] == 3
    assert answer_of(pd.Series([7.5]), frame, "pct")[0]["value"] == 7.5
    assert answer_of(pd.DataFrame({"x": [2.0]}), frame, "lakhs")[0]["value"] == 2.0


def test_to_answer_lists_and_rows(frame):
    banks = frame[frame.industry_or_rating == "Banks"]
    a, rows = answer_of(banks, frame)
    assert a["items"] == ["ICICI Bank Ltd.", "HDFC Bank Ltd."] and rows == list(banks.index)
    a, rows = answer_of(banks.pct_nav, frame)              # Series of df rows: instruments, cited
    assert a["items"] == ["ICICI Bank Ltd.", "HDFC Bank Ltd."] and rows == list(banks.index)
    a, rows = answer_of(frame.industry_or_rating.value_counts(), frame)   # labels, not rows
    assert "Banks" in a["items"] and rows == []
    a, _ = answer_of(["A", "B"], frame)
    assert a["items"] == ["A", "B"] and a["value"] is None
    a, _ = answer_of({"FLEXI": 13.0}, frame)
    assert a["items"] == ["FLEXI: 13"]


# --------------------------------------------------------------------------- reply parsing and schema

def test_parse_reply():
    assert parse_reply(json.dumps({"code": "result = 1", "unit": "count"})) == ("result = 1", "count")
    fenced = json.dumps({"code": "```python\nresult = 2\n```", "unit": None})
    assert parse_reply(fenced) == ("result = 2", None)
    for bad in ("not json", "[]", json.dumps({"code": "x"}), json.dumps({"code": "", "unit": None}),
                json.dumps({"code": "result = 1", "unit": "percent"})):
        with pytest.raises(ReplyFormatError):
            parse_reply(bad)


def test_schema_describes_frame(frame):
    text = describe_frame(frame)
    assert "5 rows" in text and "2026-09-30" in text and "2026-08-31" not in text
    assert "FLEXI: ABSL FLEXI CAP FUND" in text and "INCOME: ABSL INCOME FUND" in text
    assert all(f"- {c} (" in text for c in FRAME_COLUMNS)
    assert "Debt Instruments" in text
    msgs = build_messages("q?", text)
    assert msgs[0]["role"] == "system" and "Question: q?" in msgs[1]["content"]


# --------------------------------------------------------------------------- pipeline (mock LLM, in-process runner)

def settings_for(tmp_path, parquet):
    s = load_settings(env_file=NO_ENV, environ={"LLM_PROVIDER": "mock"})
    return replace(s, paths=replace(s.paths, processed=parquet.parent, cache=tmp_path / "cache"),
                   data=replace(s.data, eval_months=("2026-09-30",)))


def pipeline_with(tmp_path, parquet, frame, reply, runner=None):
    s = settings_for(tmp_path, parquet)
    llm = LLM(s, MockProvider(s, responder=lambda m: reply), cache=False)
    in_process = lambda code: {**run_code(code, frame), "wall_ms": 1.0}   # noqa: E731
    return BaselinePipeline(s, llm=llm, runner=runner or in_process)


def reply(code, unit=None):
    return json.dumps({"code": code, "unit": unit})


def test_pipeline_ok_with_cited_rows(tmp_path, parquet, frame):
    p = pipeline_with(tmp_path, parquet, frame, reply("result = df[df.industry_or_rating == 'Banks']"))
    r = p.answer("Which banks does the Flexi Cap Fund hold?")
    assert r.status == "ok" and r.answer["items"] == ["ICICI Bank Ltd.", "HDFC Bank Ltd."]
    assert r.cited_rows == [("f.xls", "FLEXI", 11), ("f.xls", "FLEXI", 12)]
    assert r.answer["sources"][0] == {"scheme": "ABSL FLEXI CAP FUND", "instrument": "ICICI Bank Ltd."}
    assert r.provider == "mock" and r.code.startswith("result =")


def test_pipeline_number(tmp_path, parquet, frame):
    code = "result = df[(df.scheme_code == 'FLEXI') & (df.industry_or_rating == 'Banks')].pct_nav.sum()"
    r = pipeline_with(tmp_path, parquet, frame, reply(code, "pct")).answer("Banks % in Flexi?")
    assert r.status == "ok" and r.answer["value"] == pytest.approx(10.0) and r.answer["unit"] == "pct"


@pytest.mark.parametrize("text, status", [
    ("this is not json", "format_error"),
    (reply("import os\nresult = 1"), "blocked"),
    (reply("result = ("), "syntax_error"),
    (reply("result = df['nope']"), "runtime_error"),
    (reply("x = 1"), "no_result"),
])
def test_pipeline_failures_reported_not_retried(tmp_path, parquet, frame, text, status):
    calls = []

    def runner(code):
        calls.append(code)
        try:
            return {**run_code(code, frame), "wall_ms": 1.0}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error_type": "runtime_error", "error": repr(e)}

    p = pipeline_with(tmp_path, parquet, frame, text, runner)
    r = p.answer("q?")
    assert r.status == status and r.answer is None and r.error
    assert p.llm.provider.calls == 1                    # never re-asked with hints
    if status in ("format_error", "blocked", "syntax_error"):
        assert calls == []                              # nothing ran


def test_pipeline_timeout_and_llm_errors(tmp_path, parquet, frame):
    p = pipeline_with(tmp_path, parquet, frame, reply("result = 1"),
                      runner=lambda code: {"ok": False, "error_type": "timeout", "error": "killed", "wall_ms": 10.0})
    r = p.answer("q?")
    assert r.status == "timeout" and r.execution_ms == 10.0

    class Down:
        name, model = "down", "m"

        def complete(self, messages, json_mode):
            raise RateLimited("daily")

    s = settings_for(tmp_path, parquet)
    p = BaselinePipeline(s, llm=LLM(s, Down(), cache=False, sleep=lambda _: None), frame=frame)
    assert p.answer("q?").status == "rate_limited"


def test_pipeline_real_sandbox_end_to_end(tmp_path, parquet):
    s = settings_for(tmp_path, parquet)
    code = "result = df.loc[df.scheme_code == 'INCOME', 'pct_nav'].max()"
    llm = LLM(s, MockProvider(s, responder=lambda m: reply(code, "pct")), cache=False)
    r = BaselinePipeline(s, llm=llm).answer("Largest holding % in the Income Fund?")
    assert r.status == "ok" and r.answer["value"] == 60.0 and r.execution_ms > 0
