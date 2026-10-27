"""A signature combining several effects or streams uses one shared error
and one shared service TypeVar (CLAUDE.md). Two ``Never``-defaulted error
TypeVars in one signature (``E2 = Never, E3 = Never`` read as ``E2 | E3``)
widen to ``Unknown`` when neither is constrained, as
``Stream.interleave_with`` did, and no pin catches it unless a test happens
to pass two error-free arguments. Defaulted TypeVars in separate slots
(a schema's decoding services ``RD`` and encoding services ``RE``) never
meet in a union: a function is flagged when two of them do."""

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


def _union_members(node: ast.expr) -> set[str]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _union_members(node.left) | _union_members(node.right)
    return {node.id} if isinstance(node, ast.Name) else set()


def _unioned(node: Generic, names: list[str]) -> list[str]:
    """The ``names`` that appear together in one union of the signature
    (every name, for a class: its methods may union them anywhere)."""
    if isinstance(node, ast.ClassDef):
        return names
    arguments = node.args
    annotations = [
        a.annotation
        for a in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
        if a.annotation is not None
    ]
    for root in (*annotations, node.returns):
        for part in ast.walk(root) if root is not None else ():
            members = (
                _union_members(part) & set(names) if isinstance(part, ast.BinOp) else set[str]()
            )
            if len(members) > 1:
                return sorted(members)
    return []


def test_the_scan_flags_a_union_of_two_defaulted_type_vars():
    source = "def f[E2 = Never, E3 = Never](a: X[E2], b: X[E3]) -> X[E2 | E3]: ..."
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.FunctionDef)
    assert _unioned(node, _never_defaulted(node, "E")) == ["E2", "E3"]
    separate = ast.parse("def g[RD = Never, RE = Never](s: S[RD, RE]) -> S[RD, RE]: ...").body[0]
    assert isinstance(separate, ast.FunctionDef)
    assert _unioned(separate, _never_defaulted(separate, "R")) == []


def test_no_signature_has_two_never_defaulted_error_or_service_type_vars():
    offenders = [
        f"{where}: {names}"
        for where, node in _generics()
        for prefix in ("E", "R")
        if len(names := _unioned(node, _never_defaulted(node, prefix))) > 1
    ]
    assert offenders == []
