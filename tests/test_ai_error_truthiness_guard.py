"""Effect tests an optional ``Duration`` or ``DateTime`` field with
``if (this.field)``, and an object is always truthy; in Python a zero
``timedelta`` is falsy. So a ``timedelta`` / ``datetime`` field is tested
with ``is not None``, never by truthiness (QA ai-workflow AI-2)."""

from __future__ import annotations

import ast
from pathlib import Path

_AI = Path(__file__).parent.parent / "src" / "pyfect" / "ai"
_OBJECT_TYPES = ("timedelta", "datetime")


def _object_fields(tree: ast.Module) -> set[str]:
    return {
        node.target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and any(name in ast.unparse(node.annotation) for name in _OBJECT_TYPES)
    }


def _truthiness_tests(tree: ast.Module) -> list[ast.expr]:
    tests: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp, ast.While)):
            tests.append(node.test)
        elif isinstance(node, ast.BoolOp):
            tests.extend(node.values)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            tests.append(node.operand)
    return tests


def test_duration_and_date_time_fields_are_not_tested_by_truthiness():
    offenders: list[str] = []
    for path in sorted(_AI.rglob("*.py")):
        tree = ast.parse(path.read_text())
        fields = _object_fields(tree)
        offenders.extend(
            f"{path.name}:{test.lineno} {ast.unparse(test)}"
            for test in _truthiness_tests(tree)
            if isinstance(test, ast.Attribute)
            and isinstance(test.value, ast.Name)
            and test.value.id == "self"
            and test.attr in fields
        )
    assert offenders == []
