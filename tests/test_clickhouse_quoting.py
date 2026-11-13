"""(pyfect) ClickHouse string literals are written in one place.

A map setting's keys and values were written as ``'k':'v'`` without escaping, so a quote or a
backslash in one broke out of its literal. Every ClickHouse literal the driver writes now goes
through ``params._quote``; the guard below keeps hand-written quoting of a value out of the
driver. The real server's reading of them is checked by
``tests/oracle/test_sql_hostile_round_trip.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from pyfect.sql.clickhouse import params

_CLICKHOUSE = Path(params.__file__).parent


def test_map_setting_keys_and_values_are_escaped():
    """(pyfect) a map setting's quotes and backslashes are escaped"""
    setting = params.format_setting({"t'1": "v = 'a\\'", "k\\": "x"})
    assert setting == "{'t\\'1':'v = \\'a\\\\\\'','k\\\\':'x'}"


def _quoted_interpolations(tree: ast.AST) -> list[int]:
    """Lines of f-strings that put a single quote right next to an interpolated value."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        parts = node.values
        for i, part in enumerate(parts):
            if not isinstance(part, ast.Constant) or not isinstance(part.value, str):
                continue
            text = part.value
            if (text.endswith("'") and i + 1 < len(parts)) or (text.startswith("'") and i > 0):
                lines.append(node.lineno)
                break
    return lines


def _quote_literals_outside_quote(tree: ast.AST) -> list[int]:
    """Lines outside ``_quote`` with a bare ``"'"`` string (a literal built by hand); the
    escape table's key is not one."""
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_quote":
            allowed |= {id(n) for n in ast.walk(node)}
        if isinstance(node, ast.Dict):
            allowed |= {id(key) for key in node.keys if key is not None}
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == "'" and id(node) not in allowed
    ]


def test_clickhouse_literals_are_quoted_only_by_quote():
    """(pyfect) the ClickHouse driver quotes values only through ``params._quote``"""
    found: dict[str, list[int]] = {}
    for path in sorted(_CLICKHOUSE.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        lines = _quoted_interpolations(tree) + _quote_literals_outside_quote(tree)
        if lines:
            found[path.name] = lines
    assert found == {}
