"""No asyncio task is left for the garbage collector, and no loop thread
closes with work still on it.

asyncio holds tasks weakly, so a task whose result is dropped can be
collected mid-flight ("Task was destroyed but it is pending"): such work
goes through ``pyfect._background.start``. A loop on a thread of its own
goes through ``pyfect._loop_thread.LoopThread``, which settles every task
and async generator before the loop closes.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pyfect

_SOURCE = Path(pyfect.__file__).parent
_SPAWNERS = {"create_task", "ensure_future"}


def _sources() -> list[tuple[str, ast.Module]]:
    return [
        (str(path.relative_to(_SOURCE)), ast.parse(path.read_text(), str(path)))
        for path in sorted(_SOURCE.rglob("*.py"))
    ]


def _name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else None


def _dropped(tree: ast.Module) -> list[int]:
    """Lines spawning a task nobody keeps: the call is a statement of its
    own, a lambda's result, or only the receiver of a call that is."""
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    lines: list[int] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _name(node) in _SPAWNERS):
            continue
        holder = parents[node]
        if isinstance(holder, ast.Attribute) and isinstance(parents[holder], ast.Call):
            holder = parents[parents[holder]]
        if isinstance(holder, ast.Expr | ast.Lambda):
            lines.append(node.lineno)
    return lines


def test_no_task_is_dropped() -> None:
    dropped = [
        f"{name}:{line}"
        for name, tree in _sources()
        if name != "_background.py"
        for line in _dropped(tree)
    ]
    assert dropped == [], "keep the task, or start it with pyfect._background.start"


def test_loop_threads_go_through_loop_thread() -> None:
    running = [
        f"{name}:{node.lineno}"
        for name, tree in _sources()
        if name != "_loop_thread.py"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "run_forever"
    ]
    assert running == [], "run a loop on a thread of its own with pyfect._loop_thread.LoopThread"


def test_the_checks_see_a_dropped_task() -> None:
    source = (
        "asyncio.ensure_future(f())\n"
        "loop.create_task(f()).add_done_callback(g)\n"
        "loop.call_soon(lambda: loop.create_task(f()))\n"
        "task = loop.create_task(f())\n"
        "tasks.add(asyncio.ensure_future(f()))\n"
    )
    assert _dropped(ast.parse(source)) == [1, 2, 3]
