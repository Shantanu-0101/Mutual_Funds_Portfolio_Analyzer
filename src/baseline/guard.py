"""Static check of LLM-written pandas code before it runs (task 4.3, FR-4.2).

``check_code(code)`` parses the code and raises ``BlockedCode`` (with the
reason) if it contains anything outside "pandas on the DataFrame we gave you":

- any ``import``, and class definitions;
- the names ``open, exec, eval, compile, __import__, getattr, setattr, delattr,
  globals, locals, vars, type, object, super, input, breakpoint, help, exit,
  quit`` and similar, used anywhere (not only when called, so ``f = eval``
  is caught too);
- any attribute or name that starts with ``_`` (dunders like ``__class__``
  and private pandas internals);
- frame and code-object attributes (``f_globals``, ``gi_frame``, ...);
- pandas I/O: every ``read_*``, every ``to_*`` except a short safe list
  (``to_list``, ``to_dict``, ``to_numpy``, ...), ``ExcelWriter``, ``HDFStore``;
- the pandas sub-modules that lead to the OS (``pd.io``, ``pd.api``,
  ``pd.core``, ``pd.util``, ...), plotting and options;
- ``.eval()`` and ``.query()``: they evaluate a string with pandas' own
  expression engine, which this check cannot see into;
- ``format_map`` and any string constant containing ``__`` (string-based
  attribute access through ``str.format``).

A ``SyntaxError`` is left to the caller (reported as ``syntax_error``).

What this does NOT protect against (DESIGN.md says so too, spec §9.3): Python
cannot be fully sandboxed inside Python. A determined attacker who controls the
model's output may find a path this list misses; memory use is not limited.
That is acceptable here because the code comes from our own prompt, runs on
our own public data on this laptop, in a separate process with reduced
builtins, no API keys in its environment, a temp working folder and a timeout
(``sandbox.py``).
"""

from __future__ import annotations

import ast

BLOCKED_NAMES = frozenset({
    "open", "exec", "eval", "compile", "__import__", "getattr", "setattr", "delattr", "hasattr",
    "globals", "locals", "vars", "dir", "type", "object", "super", "classmethod", "staticmethod",
    "property", "input", "breakpoint", "help", "exit", "quit", "memoryview", "bytearray",
    "os", "sys", "subprocess", "builtins", "importlib", "shutil", "pathlib", "socket",
})

BLOCKED_ATTRS = frozenset({
    # string evaluation inside pandas
    "eval", "query",
    # pandas sub-modules and config that lead outside the DataFrame
    "io", "api", "core", "util", "compat", "testing", "plotting", "errors", "arrays", "tseries",
    "options", "set_option", "get_option", "reset_option", "describe_option", "option_context",
    "show_versions", "plot", "style", "ExcelWriter", "HDFStore",
    # frames, generators, tracebacks, code objects
    "f_globals", "f_locals", "f_builtins", "f_back", "f_code", "gi_frame", "gi_code", "cr_frame",
    "ag_frame", "tb_frame", "tb_next", "co_code", "func_globals", "mro", "format_map",
})

SAFE_TO = frozenset({
    "to_list", "to_dict", "to_numpy", "to_frame", "to_records", "to_period", "to_timestamp",
    "to_datetime", "to_numeric", "to_timedelta", "to_flat_index", "to_series", "to_pydatetime",
})


class BlockedCode(ValueError):
    """The code uses something the runner does not allow."""


def _attr_problem(name: str) -> str | None:
    if name.startswith("_"):
        return f"access to '{name}' (names starting with '_' are not allowed)"
    if name in BLOCKED_ATTRS:
        return f"'.{name}' is not allowed"
    if name.startswith("read_"):
        return f"pandas I/O '.{name}' is not allowed"
    if name.startswith("to_") and name not in SAFE_TO:
        return f"pandas I/O '.{name}' is not allowed"
    return None


def problems(tree: ast.AST) -> list[str]:
    """Every rule the parsed code breaks, in source order."""
    found: list[str] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found.append(f"line {line}: import is not allowed")
        elif isinstance(node, ast.ClassDef):
            found.append(f"line {line}: class definitions are not allowed")
        elif isinstance(node, ast.Name):
            if node.id in BLOCKED_NAMES:
                found.append(f"line {line}: '{node.id}' is not allowed")
            elif node.id.startswith("_"):
                found.append(f"line {line}: names starting with '_' are not allowed ('{node.id}')")
        elif isinstance(node, ast.Attribute):
            why = _attr_problem(node.attr)
            if why:
                found.append(f"line {line}: {why}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "__" in node.value:
            found.append(f"line {line}: strings containing '__' are not allowed")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("_"):
            found.append(f"line {line}: names starting with '_' are not allowed ('{node.name}')")
        elif isinstance(node, ast.arg) and node.arg.startswith("_"):
            found.append(f"line {line}: names starting with '_' are not allowed ('{node.arg}')")
    return found


def check_code(code: str) -> None:
    """Raise ``BlockedCode`` listing every problem; a ``SyntaxError`` passes through."""
    tree = ast.parse(code, mode="exec")
    found = problems(tree)
    if found:
        raise BlockedCode("; ".join(sorted(set(found), key=found.index)))
