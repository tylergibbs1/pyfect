"""A future's ``set_result`` / ``set_exception`` is never passed as a callback.

A callback cannot check that the future is still pending: the task awaiting
it may have been cancelled first, and ``set_result`` then raises
``InvalidStateError`` into whoever calls the callback. As a fiber's exit
observer that stopped the fiber's other observers (a second cancel of
``run_async``). Pass ``pyfect._futures.settle`` instead, which skips a done
future, or call ``set_result`` after checking ``done()``.
"""

from __future__ import annotations

import ast

import _source

SRC = _source.SRC
_COMPLETERS = {"set_result", "set_exception"}


def _passed_completers(tree: ast.AST) -> list[int]:
    called = {
        id(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in _COMPLETERS and id(node) not in called
    ]


def test_no_future_completer_is_passed_as_a_callback() -> None:
    found = [
        f"{path.relative_to(SRC)}:{line}"
        for path in _source.files(SRC)
        for line in _passed_completers(_source.tree(path))
    ]
    assert found == [], "pass pyfect._futures.settle instead: " + ", ".join(found)


def test_the_check_finds_a_passed_completer() -> None:
    tree = _source.parse(
        "fiber.add_observer_unsafe(done.set_result)\nloop.call_soon(f.set_exception, e)"
    )
    assert _passed_completers(tree) == [1, 2]
    assert _passed_completers(_source.parse("done.set_result(1)")) == []
