"""No ``race`` in the chat adapters. ``race`` waits for the first success, so
a side that fails (a socket Discord closed) is ignored until the other side
ends too; the adapters race loops that each run until they fail, and want the
first exit, ``race_first``."""

import ast
from collections.abc import Iterable

import _source

CHAT = _source.SRC / "chat"


def _races(nodes: Iterable[ast.AST]) -> list[int]:
    return [
        node.lineno
        for node in nodes
        if isinstance(node, ast.Attribute) and node.attr in {"race", "race_all"}
    ]


def test_the_chat_adapters_race_by_first_exit():
    hits = [
        f"{path.relative_to(_source.SRC)}:{line}"
        for path in _source.files(CHAT)
        for line in _races(_source.walk(path))
    ]
    assert hits == []


def test_the_guard_sees_a_race():
    module = _source.parse(
        "reading.race(writing)\nfx.race_all(a, b)\nreading.race_first(writing)\n"
    )
    assert _races(ast.walk(module)) == [1, 2]
