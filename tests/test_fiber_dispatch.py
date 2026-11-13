"""A fiber's tasks wait in a dispatcher, and the code queueing one names
whose: ``fiber.dispatcher()``, Effect's ``fiber.currentDispatcher``. Calling
the run's scheduler directly (``fiber._scheduler.schedule``) put every task in
one queue, so a fork, a yield or a wake ran in a different order than in
Effect (tests/oracle/test_fiber_dispatchers.py). Only work arriving from
another thread, which Effect has no counterpart of, goes to the run directly.
"""

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "pyfect"

# (module, function): a resume, an interrupt or a deferred wake of a waiter from
# another thread, and the runs a raising drain left over, which no fiber queued.
_FROM_OTHER_THREADS = {
    ("_fiber.py", "resume"),
    ("_fiber.py", "interrupt_as_unsafe"),
    ("_fiber.py", "_drain"),
    ("_waiters.py", "wake_soon_from_here"),
}


class _Scan(ast.NodeVisitor):
    """Each ``<x>._scheduler.schedule(...)`` call, by its innermost function."""

    def __init__(self, module: str) -> None:
        self.module = module
        self.function = "<module>"
        self.found: set[tuple[str, str]] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        outer, self.function = self.function, node.name
        self.generic_visit(node)
        self.function = outer

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        match node.func:
            case ast.Attribute(attr="schedule", value=ast.Attribute(attr="_scheduler")):
                self.found.add((self.module, self.function))
            case _:
                pass
        self.generic_visit(node)


def _direct_schedules() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in SRC.rglob("*.py"):
        scan = _Scan(str(path.relative_to(SRC)))
        scan.visit(ast.parse(path.read_text(encoding="utf-8")))
        found |= scan.found
    return found


def test_fibers_queue_tasks_on_a_named_dispatcher():
    assert _direct_schedules() <= _FROM_OTHER_THREADS


def test_the_scan_sees_the_cross_thread_sites():
    assert _direct_schedules() == _FROM_OTHER_THREADS
