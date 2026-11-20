"""Fibers run coroutines on pyfect's loops only through ``pyfect._loop_bridge``.

Five drivers once each waited on their loop in their own way, and the same
leak (a value made for a fiber that had given up, never released) and hang
were fixed driver by driver (c5f8b49c, 75943852, 02404d99, f7bf366a,
8b1373ad, and a socket adoption in 0.6.16). This walks ``src``: outside the
bridge, nothing submits a coroutine to another thread's loop
(``run_coroutine_threadsafe``), owns a ``LoopThread``, or starts a task on a
loop from a function an ``os_wait`` registers."""

from __future__ import annotations

import ast
from pathlib import Path

import _source

SRC = _source.SRC
_BRIDGE = {"_loop_bridge.py", "_loop_thread.py"}
_POSTS = {"run_coroutine_threadsafe", "create_task", "ensure_future", "wrap_future"}


def _name(call: ast.Call) -> str | None:
    match call.func:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None


def _offenders(tree: ast.Module, where: str) -> list[str]:
    found: list[str] = []
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "pyfect._loop_thread":
            found.append(f"{where}:{node.lineno} imports pyfect._loop_thread")
        if not isinstance(node, ast.Call):
            continue
        name = _name(node)
        if name == "run_coroutine_threadsafe":
            found.append(f"{where}:{node.lineno} calls run_coroutine_threadsafe")
        if name == "os_wait" and node.args:
            match node.args[0]:
                case ast.Name(id=registered) if registered in functions:
                    register: ast.AST = functions[registered]
                case ast.Lambda() as register:
                    pass
                case _:
                    continue
            posts = {
                called
                for inner in ast.walk(register)
                if isinstance(inner, ast.Call) and (called := _name(inner)) in _POSTS
            }
            if posts:
                found.append(f"{where}:{node.lineno} waits on a loop by hand ({sorted(posts)})")
    return found


def _source_offenders(root: Path = SRC) -> list[str]:
    return [
        line
        for path in _source.files(root)
        if path.relative_to(root).as_posix() not in _BRIDGE
        and _source.mentions(path, "run_coroutine_threadsafe", "_loop_thread", "os_wait")
        for line in _offenders(_source.tree(path), path.relative_to(root).as_posix())
    ]


def test_only_the_bridge_waits_on_a_loop_for_a_fiber() -> None:
    assert _source_offenders() == [], (
        "run the coroutine with pyfect._loop_bridge.LoopBridge.run (or spawn and wait), "
        "which releases what a fiber gave up on"
    )


def test_the_check_sees_each_hand_rolled_wait() -> None:
    sample = _source.parse(
        "from pyfect._loop_thread import LoopThread\n"
        "def run(make, loop):\n"
        "    future = asyncio.run_coroutine_threadsafe(make(), loop)\n"
        "    def register(resume):\n"
        "        loop.call_soon_threadsafe(lambda: loop.create_task(make()))\n"
        "    return os_wait(register, waits_for='work')\n"
    )
    assert _offenders(sample, "sample.py") == [
        "sample.py:1 imports pyfect._loop_thread",
        "sample.py:3 calls run_coroutine_threadsafe",
        "sample.py:6 waits on a loop by hand (['create_task'])",
    ]
