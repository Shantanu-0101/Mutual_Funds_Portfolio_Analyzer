"""Runs one piece of LLM-written pandas code in a separate process (task 4.4, FR-4.2).

Parent side: ``run_in_sandbox(code, parquet, months, timeout_s)`` starts

    python -I <this file>

in an empty temp folder, with API keys and other secrets removed from its
environment. ``-I`` (isolated mode) ignores PYTHON* variables and the user
site folder and does not put the current folder on ``sys.path``. That is also
why this file imports only the standard library and pandas, never ``src``:
it runs as a plain script.

Child side, in order:

1. read one JSON line ``{"parquet": ..., "months": [...]}`` and load the
   DataFrame (``load_frame``) BEFORE any generated code exists;
2. print ``READY``; the parent starts the timeout clock only now, so loading
   pandas and the parquet does not eat into the code's time budget;
3. read one JSON line ``{"code": ...}`` and run it with only ``df`` (a copy),
   ``pd`` and ``SAFE_BUILTINS`` in scope; ``print`` output is captured;
4. print one JSON line: the result converted to plain JSON (``to_plain``) or
   the error.

If the code runs past ``timeout_s`` the parent kills the process (``timeout``).
The static check (``guard.py``) runs in the parent before any of this.
"""

from __future__ import annotations

import builtins
import contextlib
import datetime as _dt
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

# The columns the baseline sees, in this order. Parser-audit columns (source file/row,
# flags, raw % cell) are left out; the row index is kept so results can cite rows.
FRAME_COLUMNS = (
    "scheme_code", "scheme", "as_of_date", "section", "subsection", "asset_class", "instrument", "isin",
    "industry_or_rating", "quantity", "market_value_lakhs", "pct_nav", "ytm", "ytc",
)

SAFE_BUILTINS = {name: getattr(builtins, name) for name in (
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float", "frozenset", "int",
    "isinstance", "len", "list", "map", "max", "min", "pow", "print", "range", "reversed", "round", "set",
    "slice", "sorted", "str", "sum", "tuple", "zip", "ValueError", "KeyError", "IndexError", "Exception",
)}

MAX_ITEMS = 200            # rows / list items kept in the converted result
STARTUP_TIMEOUT_S = 120.0  # loading pandas + parquet; generous for a cold laptop
SECRET_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
READY = "READY"


# --------------------------------------------------------------------------- shared with the parent

def load_frame(parquet: str | Path, months: list[str] | tuple[str, ...]):
    """The DataFrame ``df`` exactly as the generated code sees it (also used to describe the schema)."""
    import pandas as pd

    df = pd.read_parquet(parquet, columns=list(FRAME_COLUMNS))
    df["as_of_date"] = df["as_of_date"].astype(str)
    return df[df["as_of_date"].isin([str(m) for m in months])]


# --------------------------------------------------------------------------- result → plain JSON

def _scalar(x: Any) -> Any:
    import numpy as np
    import pandas as pd

    if x is None:
        return None
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return None if math.isnan(x) or math.isinf(x) else float(x)
    if isinstance(x, str):
        return x
    if isinstance(x, (pd.Timestamp, _dt.date)):
        return str(x)[:10]
    try:
        if pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    return str(x)


def to_plain(value: Any) -> dict:
    """Convert ``result`` to {"kind": scalar|list|series|dataframe|dict, ...}, at most MAX_ITEMS entries."""
    import numpy as np
    import pandas as pd

    if isinstance(value, pd.DataFrame):
        head = value.head(MAX_ITEMS)
        return {"kind": "dataframe", "columns": [str(c) for c in value.columns],
                "index": [_scalar(i) for i in head.index],
                "rows": [[_scalar(v) for v in row] for row in head.itertuples(index=False, name=None)],
                "n": int(len(value))}
    if isinstance(value, pd.Series):
        head = value.head(MAX_ITEMS)
        return {"kind": "series", "name": _scalar(value.name), "index": [_scalar(i) for i in head.index],
                "values": [_scalar(v) for v in head.tolist()], "n": int(len(value))}
    if isinstance(value, (list, tuple, set, frozenset, np.ndarray, pd.Index)):
        items = list(value)
        if isinstance(value, (set, frozenset)):
            items = sorted(items, key=str)
        return {"kind": "list", "values": [_scalar(v) for v in items[:MAX_ITEMS]], "n": len(items)}
    if isinstance(value, dict):
        keys = list(value)[:MAX_ITEMS]
        return {"kind": "dict", "keys": [_scalar(k) for k in keys], "values": [_scalar(value[k]) for k in keys],
                "n": len(value)}
    return {"kind": "scalar", "value": _scalar(value)}


# --------------------------------------------------------------------------- child

def run_code(code: str, df: Any) -> dict:
    import pandas as pd

    env: dict[str, Any] = {"__builtins__": dict(SAFE_BUILTINS), "df": df.copy(), "pd": pd}
    exec(compile(code, "<generated>", "exec"), env)  # noqa: S102 (checked by guard.py, isolated process)
    if "result" not in env:
        return {"ok": False, "error_type": "no_result", "error": "the code did not set `result`"}
    return {"ok": True, "result": to_plain(env["result"])}


def child_main() -> int:
    out = sys.stdout
    setup = json.loads(sys.stdin.readline())
    df = load_frame(setup["parquet"], setup["months"])
    out.write(READY + "\n")
    out.flush()
    code = json.loads(sys.stdin.readline())["code"]
    captured = io.StringIO()
    t0 = time.perf_counter()
    try:
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            res = run_code(code, df)
    except Exception as e:  # noqa: BLE001 (any failure of generated code is a result, not a crash)
        res = {"ok": False, "error_type": "runtime_error", "error": f"{type(e).__name__}: {e}"[:1000]}
    res["exec_ms"] = (time.perf_counter() - t0) * 1000
    res["stdout"] = captured.getvalue()[:2000]
    out.write(json.dumps(res) + "\n")
    out.flush()
    return 0


# --------------------------------------------------------------------------- parent

def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not any(h in k.upper() for h in SECRET_HINTS)}


def _readline(stream: Any, timeout_s: float) -> str | None:
    box: list[str] = []
    t = threading.Thread(target=lambda: box.append(stream.readline()), daemon=True)
    t.start()
    t.join(timeout_s)
    return box[0] if box else None


def run_in_sandbox(code: str, parquet: str | Path, months: list[str] | tuple[str, ...], timeout_s: float,
                   startup_timeout_s: float = STARTUP_TIMEOUT_S) -> dict:
    """Run ``code`` in a fresh isolated process. Returns the child's JSON dict, always with ``ok``.

    ``error_type`` on failure: ``timeout``, ``no_result``, ``runtime_error`` or ``sandbox_error``
    (the child itself failed to start or answer). ``wall_ms`` is the time after READY.
    """
    with tempfile.TemporaryDirectory(prefix="mfpa_sandbox_", ignore_cleanup_errors=True) as tmp:
        proc = subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve())], cwd=tmp, env=_clean_env(),
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8")
        try:
            # absolute: the child runs in the empty temp folder
            proc.stdin.write(json.dumps({"parquet": str(Path(parquet).resolve()), "months": list(months)}) + "\n")
            proc.stdin.flush()
            line = _readline(proc.stdout, startup_timeout_s)
            if (line or "").strip() != READY:
                proc.kill()
                _, err = proc.communicate()
                return {"ok": False, "error_type": "sandbox_error",
                        "error": f"sandbox did not start: {(line or '').strip()[:200]} {err[-800:]}".strip()}
            t0 = time.perf_counter()
            try:
                out, err = proc.communicate(json.dumps({"code": code}) + "\n", timeout=timeout_s)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                return {"ok": False, "error_type": "timeout", "error": f"killed after {timeout_s:g} s",
                        "wall_ms": (time.perf_counter() - t0) * 1000}
            wall_ms = (time.perf_counter() - t0) * 1000
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
    lines = [x for x in out.splitlines() if x.strip()]
    try:
        res = json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError):
        return {"ok": False, "error_type": "sandbox_error", "error": f"no result from sandbox: {err[-800:]}",
                "wall_ms": wall_ms}
    res["wall_ms"] = wall_ms
    return res


if __name__ == "__main__":
    sys.exit(child_main())
