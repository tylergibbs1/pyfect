"""The guard for JavaScript's ``Object.is`` (root cause of stockroom finding
7, where ``json_patch`` compared numbers by hand and lost NaN is NaN).

Comparing two numbers' signs with ``math.copysign`` is how a hand-written
``Object.is`` tells ``-0.0`` from ``0.0``, and the place it forgets NaN.
That comparison lives only in ``pyfect._js`` (``same_value``,
``same_json_value``); every other module calls those.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "pyfect"


def _is_copysign(node: ast.expr) -> bool:
    return isinstance(node, ast.Call) and (
        (isinstance(node.func, ast.Attribute) and node.func.attr == "copysign")
        or (isinstance(node.func, ast.Name) and node.func.id == "copysign")
    )


def _sign_comparisons(tree: ast.Module) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and _is_copysign(node.left)
        and any(_is_copysign(right) for right in node.comparators)
    ]


def test_only_js_compares_number_signs() -> None:
    found = {
        str(path.relative_to(SRC)): lines
        for path in sorted(SRC.rglob("*.py"))
        if path.name != "_js.py" or path.parent != SRC
        if (lines := _sign_comparisons(ast.parse(path.read_text(), str(path))))
    }
    assert found == {}, f"use pyfect._js.same_value / same_json_value: {found}"


def test_the_guard_finds_a_hand_written_object_is() -> None:
    tree = ast.parse("ok = a == b and math.copysign(1, a) == math.copysign(1, b)")
    assert _sign_comparisons(tree) == [1]
