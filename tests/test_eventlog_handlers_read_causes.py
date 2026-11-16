"""Event log server handlers map a storage failure through
``_store_unavailable.protocol_error``, which reads the cause, so a store
refused until the operator acts reaches the client as such instead of a
generic "Persistence failure" (0.6.6 dropped ``LegacyStoreNeedsMigration``
this way). A ``catch_cause`` that ignores its cause must be listed here
with the reason it may."""

from __future__ import annotations

import ast
from pathlib import Path

import _source

import pyfect.eventlog

IGNORES_CAUSE_ON_PURPOSE = {
    # A failed binding lookup is a Forbidden Authenticate, as in Effect;
    # no store is involved yet.
    ("event_log_server.py", "bound_signing_key"),
}


class _Finder(ast.NodeVisitor):
    """The innermost function around each ``catch_cause(lambda _: ...)``."""

    def __init__(self, file: str) -> None:
        self.file = file
        self.functions: list[str] = []
        self.found: set[tuple[str, str]] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "catch_cause"
            and node.args
            and isinstance(handler := node.args[0], ast.Lambda)
            and [a.arg for a in handler.args.args] == ["_"]
        ):
            self.found.add((self.file, self.functions[-1] if self.functions else "<module>"))
        self.generic_visit(node)


def test_handlers_never_drop_a_storage_failures_cause() -> None:
    root = Path(pyfect.eventlog.__file__).parent
    found: set[tuple[str, str]] = set()
    for path in _source.files(root):
        finder = _Finder(path.name)
        finder.visit(_source.tree(path))
        found |= finder.found
    assert found == IGNORES_CAUSE_ON_PURPOSE
