"""Every place the runtime interrupts because an owner (a ``Scope``,
``FiberMap``, ``FiberSet``, ``FiberHandle``) is closed says so with
``closed(...)`` / ``interrupt_closed(...)`` (DOGFOOD beacon 11).

Walks ``src/pyfect``: an ``if`` that tests whether an owner is closed
(``x._closed is not None``, or a collection's ``_state`` / ``_fibers`` being
``None``) and interrupts in its body must name the owner, so a new closed
path can't interrupt without a reason.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "pyfect"

_CLOSED_STATE = {"_closed"}
_COLLECTION_STATE = {"_state", "_fibers", "state", "fibers"}
_COLLECTIONS = {"fiber_map.py", "fiber_set.py", "fiber_handle.py"}
_INTERRUPTS = {"interrupt_as_unsafe", "interrupt", "interrupted", "interrupted_fiber"}
_REASONS = {"closed", "interrupt_closed"}


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _tests_closed(test: ast.expr, collection: bool) -> bool:
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1):
        return False
    subject, op, other = test.left, test.ops[0], test.comparators[0]
    if not (isinstance(other, ast.Constant) and other.value is None):
        return False
    name = _name(subject)
    if isinstance(op, ast.IsNot) and name in _CLOSED_STATE:
        return True
    return collection and isinstance(op, ast.Is) and name in _COLLECTION_STATE


def _calls(body: list[ast.stmt]) -> set[str]:
    return {
        name
        for stmt in body
        for node in ast.walk(stmt)
        if isinstance(node, ast.Call) and (name := _name(node.func)) is not None
    }


def test_closed_owner_interrupts_name_the_owner() -> None:
    unnamed: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(), str(path))
        collection = path.name in _COLLECTIONS
        for node in ast.walk(tree):
            if not (isinstance(node, ast.If) and _tests_closed(node.test, collection)):
                continue
            calls = _calls(node.body)
            if calls & _INTERRUPTS and not calls & _REASONS:
                unnamed.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert unnamed == [], f"closed-owner interrupts without closed(...): {unnamed}"
