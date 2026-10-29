"""A parameter typed ``Effect[A, E, R | Tag]`` leaves ``R`` Unknown when the
argument needs only ``Tag`` (pyright solves nothing for ``R``), so such a
function needs a first overload for ``Effect[A, E, Tag]``. This check finds
the functions that lack one; ``tests/type_checks.py`` pins the result.

It covers the packages listed in ``CHECKED``."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "pyfect"
CHECKED = ["workflow"]


def _union_members(node: ast.expr) -> list[ast.expr]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _union_members(node.left) + _union_members(node.right)
    return [node]


def _unioned_requirements(annotation: ast.expr, type_params: set[str]) -> Iterator[str]:
    for node in ast.walk(annotation):
        if not (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "Effect"
            and isinstance(node.slice, ast.Tuple)
            and len(node.slice.elts) == 3
        ):
            continue
        members = _union_members(node.slice.elts[2])
        if len(members) > 1:
            yield from (m.id for m in members if isinstance(m, ast.Name) and m.id in type_params)


def _is_overload(f: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(isinstance(d, ast.Name) and d.id == "overload" for d in f.decorator_list)


def _missing_overloads(path: Path) -> Iterator[str]:
    tree = ast.parse(path.read_text())
    for parent in ast.walk(tree):
        if not isinstance(parent, ast.Module | ast.ClassDef):
            continue
        functions = [
            f for f in parent.body if isinstance(f, ast.FunctionDef | ast.AsyncFunctionDef)
        ]
        overloaded = {f.name for f in functions if _is_overload(f)}
        for f in functions:
            if f.name in overloaded:
                continue
            type_params = {t.name for t in f.type_params if isinstance(t, ast.TypeVar)}
            args = f.args.posonlyargs + f.args.args + f.args.kwonlyargs
            if any(
                next(_unioned_requirements(a.annotation, type_params), None)
                for a in args
                if a.annotation is not None
            ):
                yield f"{path.relative_to(SRC)}:{f.lineno} {f.name}"


def test_functions_taking_a_unioned_requirement_have_a_first_overload():
    missing = [
        found
        for package in CHECKED
        for path in sorted((SRC / package).rglob("*.py"))
        for found in _missing_overloads(path)
    ]
    assert missing == []
