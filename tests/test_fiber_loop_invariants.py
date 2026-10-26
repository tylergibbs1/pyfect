"""The fiber loop and interrupt delivery must not know about specific
primitives (CLAUDE.md): primitives implement ``_step``, frames implement
``_on_success``/``_on_failure``. A loop that special-cases one primitive is
how ordering bugs (an interrupt that skips a step, a resume that runs
twice) get in."""

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "pyfect"
LOOP_METHODS = {"_run", "_loop", "_continue", "_with_interrupt", "_deliver_interrupt"}


def _core_primitive_names() -> set[str]:
    tree = ast.parse((SRC / "_core.py").read_text())
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and any(isinstance(b, ast.Name | ast.Subscript) for b in node.bases)
    }


def test_the_fiber_loop_names_no_primitive():
    primitives = _core_primitive_names() - {"Effect", "Frame"}
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


def test_a_fiber_run_is_entered_only_from_the_scheduler_or_the_unwind_queue():
    """Running one fiber inside another nests their stacks; a cascade of
    interrupts then overflows Python's stack and wedges fibers half-finished.
    ``_run`` may be called from a scheduled task (a lambda), from ``_resume``
    (which the scheduler calls) or from ``_unwind`` (which runs a cascade
    one fiber at a time)."""
    allowed = {"_resume", "_unwind"}
    tree = ast.parse((SRC / "_fiber.py").read_text())
    offenders: list[str] = []

    def visit(node: ast.AST, owner: str) -> None:
        if isinstance(node, ast.FunctionDef):
            owner = node.name
        if isinstance(node, ast.Lambda):
            return
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_run"
            and owner not in allowed
        ):
            offenders.append(f"{owner}:{node.lineno}")
        for child in ast.iter_child_nodes(node):
            visit(child, owner)

    visit(tree, "<module>")
    assert offenders == []
