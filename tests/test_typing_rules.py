"""A signature combining several effects or streams uses one shared error
and one shared service TypeVar (CLAUDE.md). Two ``Never``-defaulted error
TypeVars in one signature (``E2 = Never, E3 = Never`` read as ``E2 | E3``)
widen to ``Unknown`` when neither is constrained, as
``Stream.interleave_with`` did, and no pin catches it unless a test happens
to pass two error-free arguments."""

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "pyfect"

type Generic = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def _never_defaulted(node: Generic, prefix: str) -> list[str]:
    return [
        param.name
        for param in node.type_params
        if isinstance(param, ast.TypeVar)
        and param.name.startswith(prefix)
        and param.default_value is not None
        and ast.unparse(param.default_value) == "Never"
    ]


def _generics() -> list[tuple[str, Generic]]:
    return [
        (f"{path.relative_to(SRC)}:{node.lineno} {node.name}", node)
        for path in sorted(SRC.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    ]


def test_the_scan_sees_defaulted_type_parameters():
    defaulted = {where.split(" ")[1] for where, node in _generics() if _never_defaulted(node, "E")}
    assert {"interleave_with", "zip", "catch_all"} <= defaulted


def test_no_signature_has_two_never_defaulted_error_or_service_type_vars():
    offenders = [
        f"{where}: {names}"
        for where, node in _generics()
        for prefix in ("E", "R")
        if len(names := _never_defaulted(node, prefix)) > 1
    ]
    assert offenders == []
