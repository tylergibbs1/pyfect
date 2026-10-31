"""GraphQL writes its wire JSON with ``_json_text.js_stringify``, which
writes ``NaN`` as ``null`` as Effect's ``JSON.stringify`` does; plain
``stringify`` raises on it, so a non-finite variable killed a POST (QA
ai-workflow GQL-1). Only the cache keys of ``_slices`` (never sent) use
``stringify``."""

from __future__ import annotations

import ast
from pathlib import Path

_GRAPHQL = Path(__file__).parent.parent / "src" / "pyfect" / "graphql"
_NOT_SENT = {"_slices.py"}


def test_graphql_wire_json_is_written_as_json_stringify_writes_it():
    offenders = [
        f"{path.name}:{node.lineno}"
        for path in sorted(_GRAPHQL.rglob("*.py"))
        if path.name not in _NOT_SENT
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Attribute | ast.Name)
        and (node.attr if isinstance(node, ast.Attribute) else node.id) == "stringify"
    ]
    assert offenders == []
