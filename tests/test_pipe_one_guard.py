"""Every ``.pipe`` method takes ``*more: Never`` and returns ``pipe_one(...)``, so a second
function is a pyright error and, at run time, a message saying to chain ``.pipe(f).pipe(g)``
(``tests/test_effect_misuse_messages.py``) instead of Python's bare arity error."""

from __future__ import annotations

import ast

import _source
from _source import SRC


def test_every_pipe_method_routes_through_pipe_one():
    missing: list[str] = []
    for path in _source.files(SRC):
        for node in _source.walk(path):
            if not isinstance(node, ast.FunctionDef) or node.name != "pipe":
                continue
            vararg = node.args.vararg
            annotation = vararg.annotation if vararg is not None else None
            takes_more = annotation is not None and ast.unparse(annotation) == "Never"
            if not takes_more or not ast.unparse(node.body[-1]).startswith("return pipe_one("):
                missing.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert missing == []


def test_the_guard_sees_the_pipe_methods():
    found = [
        path.name
        for path in _source.files(SRC)
        for node in _source.walk(path)
        if isinstance(node, ast.FunctionDef) and node.name == "pipe"
    ]
    assert "_core.py" in found
    assert len(found) > 25
