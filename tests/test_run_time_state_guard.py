"""The guard for state an effect keeps between runs (M10g review, root cause
of ``entity_resource.make`` sharing its shutdown flag across activations):
an effect is a description that can run many times, so the mutable state a
run uses is made by that run.

A function that builds an effect from a nested ``@gen`` / ``@fn`` body must
not make a mutable cell (``x = [...]``, ``{...}``, ``list()``, ...) outside
that body for the body to use: every run of the effect would share it. Make
the cell inside the body instead (Effect's ``fnUntraced`` locals).
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "pyfect"

# Called at run time (inside a ``_WithFiber`` body), so each run makes its own.
_ALLOWED = {"rpc/client/_core.py:_clear"}

_BODY_DECORATORS = {"gen", "fn"}
_CELL_CALLS = {"list", "dict", "set"}


def _is_body(node: ast.stmt) -> bool:
    if not isinstance(node, ast.FunctionDef):
        return False
    for decorator in node.decorator_list:
        name = getattr(decorator, "id", None) or getattr(decorator, "attr", None)
        if name in _BODY_DECORATORS:
            return True
    return False


def _is_cell(value: ast.expr) -> bool:
    if isinstance(value, ast.List | ast.Dict | ast.Set):
        return True
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id in _CELL_CALLS
    )


def _offenders(name: str, tree: ast.Module) -> list[str]:
    found: list[str] = []
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef) or _is_body(function):
            continue
        if f"{name}:{function.name}" in _ALLOWED:
            continue
        cells = {
            statement.targets[0].id: statement.lineno
            for statement in function.body
            if isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and _is_cell(statement.value)
        }
        for statement in function.body:
            if not _is_body(statement):
                continue
            used = {node.id for node in ast.walk(statement) if isinstance(node, ast.Name)}
            found.extend(
                f"{name}:{line} ({function.name}: {cell})"
                for cell, line in cells.items()
                if cell in used
            )
    return found


def test_effect_bodies_make_their_own_mutable_state():
    offenders = [
        offender
        for path in sorted(SRC.rglob("*.py"))
        for offender in _offenders(str(path.relative_to(SRC)), ast.parse(path.read_text()))
    ]
    assert offenders == [], "make the cell inside the @gen body, so each run has its own"


def test_the_guard_finds_a_cell_shared_by_runs():
    source = (
        "def make():\n"
        "    flag = [False]\n"
        "    @gen\n"
        "    def run():\n"
        "        flag[0] = True\n"
        "        yield from x\n"
        "    return run\n"
    )
    assert _offenders("m.py", ast.parse(source)) == ["m.py:2 (make: flag)"]
