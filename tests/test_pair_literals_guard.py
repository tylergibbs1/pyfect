"""The guard for pairs keeping their literal types (root cause of stockroom
finding 12, where ``TxHashMap.from_iterable([("a", 1)])`` was a
``TxHashMap[Literal["a"], Literal[1]]`` and a later ``set("b", 2)`` failed
pyright).

A parameter ``Iterable[tuple[K, V]]`` whose ``K`` or ``V`` the function
itself solves keeps the literals of a list of pairs, as ``Iterable`` is
covariant. An overload taking ``list[tuple[K, V]]`` before it widens them,
as a list is invariant. Every overloaded function with such a parameter has
one; ``tests/type_checks.py`` pins the result for each.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "pyfect"


def _is_overload(function: ast.FunctionDef) -> bool:
    return any(
        (isinstance(d, ast.Name) and d.id == "overload")
        or (isinstance(d, ast.Attribute) and d.attr == "overload")
        for d in function.decorator_list
    )


def _pair_of_own_type_params(annotation: ast.expr | None, container: str, own: set[str]) -> bool:
    """``container[tuple[X, Y]]`` with ``X`` or ``Y`` one of ``own``."""
    if not (
        isinstance(annotation, ast.Subscript)
        and isinstance(annotation.value, ast.Name)
        and annotation.value.id == container
    ):
        return False
    pair = annotation.slice
    if not (
        isinstance(pair, ast.Subscript)
        and isinstance(pair.value, ast.Name)
        and pair.value.id == "tuple"
        and isinstance(pair.slice, ast.Tuple)
    ):
        return False
    return any(isinstance(e, ast.Name) and e.id in own for e in pair.slice.elts)


def _missing_list_overloads(tree: ast.Module) -> list[str]:
    scopes: list[list[ast.stmt]] = [tree.body] + [
        node.body for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    ]
    missing: list[str] = []
    for body in scopes:
        overloads: dict[str, list[ast.FunctionDef]] = {}
        for stmt in body:
            if isinstance(stmt, ast.FunctionDef) and _is_overload(stmt):
                overloads.setdefault(stmt.name, []).append(stmt)
        for name, group in overloads.items():

            def takes(container: str, function: ast.FunctionDef) -> list[int]:
                own = {p.name for p in function.type_params if isinstance(p, ast.TypeVar)}
                args = function.args.posonlyargs + function.args.args
                return [
                    i
                    for i, arg in enumerate(args)
                    if _pair_of_own_type_params(arg.annotation, container, own)
                ]

            iterable_at = {i for function in group for i in takes("Iterable", function)}
            list_at = {i for function in group for i in takes("list", function)}
            missing.extend(f"{name}:{group[0].lineno}" for _ in iterable_at - list_at)
    return missing


def test_every_iterable_of_pairs_has_a_list_overload() -> None:
    found = {
        str(path.relative_to(SRC)): missing
        for path in sorted(SRC.rglob("*.py"))
        if (missing := _missing_list_overloads(ast.parse(path.read_text(), str(path))))
    }
    assert found == {}, f"add a list[tuple[K, V]] overload first: {found}"


def test_the_guard_finds_a_missing_list_overload() -> None:
    source = """
class Box[K, V]:
    @overload
    @classmethod
    def from_iterable[K2, V2](cls, entries: Iterable[tuple[K2, V2]]) -> Box[K2, V2]: ...
    @overload
    @classmethod
    def from_iterable(cls, entries: Iterable[tuple[K, V]]) -> Box[K, V]: ...
"""
    assert _missing_list_overloads(ast.parse(source)) == ["from_iterable:5"]
