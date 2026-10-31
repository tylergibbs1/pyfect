"""Durations become milliseconds through ``duration.to_millis``.

A ``Seconds`` value times 1000 goes through a float product: 2.007 s is
2006.9999999999998 ms or 2007.0000000000002 ms, so a ``ceil`` or ``int``
of it lands a millisecond off (a durable clock woke at 2008 ms for a
2007 ms sleep). ``to_millis`` reads the seconds as the decimal that prints
them, as Effect's millisecond durations are exact."""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "pyfect"

_DURATION_NAME = re.compile(r"duration|ttl|timeout|idle|interval|delay", re.IGNORECASE)


def _name_of(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_thousand(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value == 1000


def _seconds_times_thousand(node: ast.AST) -> bool:
    if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult)):
        return False
    for value, factor in ((node.left, node.right), (node.right, node.left)):
        name = _name_of(value)
        if _is_thousand(factor) and name is not None and _DURATION_NAME.search(name):
            return True
    return False


def test_no_duration_times_a_thousand():
    offenders = [
        f"{path.relative_to(SRC)}:{getattr(node, 'lineno', 0)}"
        for path in sorted(SRC.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(), str(path)))
        if _seconds_times_thousand(node)
    ]
    assert offenders == [], "use pyfect.duration.to_millis"


def test_the_guard_sees_a_duration_times_a_thousand():
    tree = ast.parse("clock.duration * 1000 + 1000 * ttl")
    assert sum(_seconds_times_thousand(node) for node in ast.walk(tree)) == 2
