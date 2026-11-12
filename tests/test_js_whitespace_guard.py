"""Parsers ported from Effect read whitespace as JavaScript does.

Python's ``str.split()``, ``strip()``, ``isspace()`` and ``re``'s ``\\s`` count
U+001C-U+001F and U+0085 as space and miss U+FEFF, so a parser using them
accepts text Effect rejects (fuzzing found cron, semver ranges and cookies
doing so). These modules use ``_js.split_space`` / ``trim`` / ``SPACE``.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).parents[1] / "src" / "pyfect"
PORTED_PARSERS = [
    "big_decimal.py",
    "byte_size.py",
    "cron",
    "date_time",
    "duration.py",
    "encoding",
    "glob",
    "http/cookies.py",
    "json_pointer.py",
    "semver.py",
    "semver_range.py",
    "_js_date.py",
]
_PYTHON_SPACE_METHODS = {"split", "strip", "lstrip", "rstrip", "isspace", "splitlines"}


def _files() -> list[Path]:
    paths = [SRC / name for name in PORTED_PARSERS]
    assert all(path.exists() for path in paths), [p for p in paths if not p.exists()]
    return sorted(f for p in paths for f in ([p] if p.is_file() else p.rglob("*.py")))


def _docstrings(tree: ast.AST) -> set[int]:
    return {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
    }


def _python_whitespace(tree: ast.AST) -> list[int]:
    """Lines calling a whitespace method without arguments, or with ``\\s`` in
    a string (a regex) other than a docstring."""
    docstrings = _docstrings(tree)
    lines: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _PYTHON_SPACE_METHODS
            and not node.args
            and not node.keywords
        ):
            lines.append(node.lineno)
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "\\s" in node.value
            and id(node) not in docstrings
        ):
            lines.append(node.lineno)
    return lines


@pytest.mark.parametrize("path", _files(), ids=lambda p: str(p.relative_to(SRC)))
def test_no_python_whitespace(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert _python_whitespace(tree) == [], f"{path}: Python whitespace at these lines"
