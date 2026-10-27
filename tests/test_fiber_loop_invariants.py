"""The fiber loop and interrupt delivery must not know about specific
primitives (CLAUDE.md): primitives implement ``_step``, frames implement
``_on_success``/``_on_failure``. A loop that special-cases one primitive is
how ordering bugs (an interrupt that skips a step, a resume that runs
twice) get in."""

import ast
from pathlib import Path

from pyfect._effect_base import Frame

SRC = Path(__file__).parent.parent / "src" / "pyfect"
LOOP_METHODS = {"_run", "_loop", "_continue", "_with_interrupt", "_deliver_interrupt"}


def _frame_class_names() -> set[str]:
    """Every primitive and continuation frame, wherever it is defined."""
    found: set[str] = set()
    pending: list[type] = [Frame]
    while pending:
        cls = pending.pop()
        found.add(cls.__name__)
        pending.extend(cls.__subclasses__())
    return found


def test_the_frame_scan_sees_primitives_in_every_module():
    names = _frame_class_names()
    assert {"_Succeed", "_MatchCause", "_RestoreContext", "ServiceEffect"} <= names


def test_the_fiber_loop_names_no_primitive():
    primitives = _frame_class_names() - {"Effect", "Frame"}
    tree = ast.parse((SRC / "_fiber.py").read_text())
    fiber = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Fiber")
    methods = [n for n in fiber.body if isinstance(n, ast.FunctionDef) and n.name in LOOP_METHODS]
    assert {m.name for m in methods} == LOOP_METHODS
    used = {
        f"{m.name}: {node.id}"
        for m in methods
        for node in ast.walk(m)
        if isinstance(node, ast.Name) and node.id in primitives
    }
    assert used == set()


def test_a_fiber_run_is_entered_only_from_the_drain():
    """Running one fiber inside another nests their stacks; a cascade of
    interrupts, or a chain of children started immediately, then overflows
    Python's stack and wedges fibers half-finished. ``_run`` may only be
    called from ``_drain``, which runs fibers one after another; everything
    else (scheduled tasks included) goes through ``_drive`` or ``_unwind``."""
    tree = ast.parse((SRC / "_fiber.py").read_text())
    offenders: list[str] = []

    def visit(node: ast.AST, owner: str) -> None:
        if isinstance(node, ast.FunctionDef):
            owner = node.name
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_run"
            and owner != "_drain"
        ):
            offenders.append(f"{owner}:{node.lineno}")
        for child in ast.iter_child_nodes(node):
            visit(child, owner)

    visit(tree, "<module>")
    assert offenders == []


def test_every_effect_method_group_is_only_used_through_effect():
    """``as_effect`` treats ``self`` in a method group as an ``Effect``.
    That holds while ``Effect`` is the only class built on the groups."""
    from pyfect._core import Effect
    from pyfect._effect_base import EffectBase

    base: type = EffectBase
    groups = base.__subclasses__()
    assert all(cls.__bases__ == (EffectBase,) for cls in groups)
    users: set[type] = {sub for group in groups for sub in group.__subclasses__()}
    assert users == {Effect}
