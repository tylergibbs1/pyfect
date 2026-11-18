"""No asyncio task is left for the garbage collector, and no loop thread
closes with work still on it.

asyncio holds tasks weakly, so a task whose result is dropped can be
collected mid-flight ("Task was destroyed but it is pending"): such work
goes through ``pyfect._background.start``. A loop on a thread of its own
goes through ``pyfect._loop_thread.LoopThread``, which settles every task
and async generator before the loop closes, waiting for the background
tasks to end. A set of one's own that keeps tasks until they end
(``add_done_callback(tasks.discard)``) is the same thing done by hand: the
loop thread cannot see it, so it cancels those tasks at stop, or closes
under one started meanwhile (a response's close lost that way in CI).
"""

from __future__ import annotations

import ast

import _source

_SOURCE = _source.SRC
_SPAWNERS = {"create_task", "ensure_future"}


def _sources() -> list[tuple[str, ast.Module]]:
    return [(str(path.relative_to(_SOURCE)), _source.tree(path)) for path in _source.files(_SOURCE)]


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


def _kept_by_hand(tree: ast.Module) -> list[int]:
    """Lines keeping tasks in a set of their own: ``add_done_callback(s.discard)``."""
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and _name(node) == "add_done_callback"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Attribute)
        and node.args[0].attr == "discard"
    ]


def test_no_task_is_kept_in_a_set_of_its_own() -> None:
    kept = [
        f"{name}:{line}"
        for name, tree in _sources()
        if name != "_background.py"
        for line in _kept_by_hand(tree)
    ]
    assert kept == [], "start the task with pyfect._background.start, which a LoopThread waits for"


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
    assert _dropped(_source.parse(source)) == [1, 2, 3]


def test_the_check_sees_a_task_kept_by_hand() -> None:
    source = (
        "task.add_done_callback(self._closing.discard)\n"
        "task.add_done_callback(_CLOSING.discard)\n"
        "task.add_done_callback(done)\n"
    )
    assert _kept_by_hand(_source.parse(source)) == [1, 2]
