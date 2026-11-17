"""MCP code doesn't split a peer's stdio into lines itself.

Effect frames MCP over stdio as NDJSON: a message ends at a newline, and text the
peer leaves without one when its output ends is dropped. ``split_lines`` gives that
text as a last line, so code built on it reads a message Effect never sees. MCP stdio is read
with ``pyfect.ai._mcp.ndjson.ndjson_lines``, which frames it as Effect does.
"""

from __future__ import annotations

import ast

import _source

MCP = _source.SRC / "ai"
_BANNED = frozenset({"split_lines", "split_lines_within"})


def _names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Attribute):
        return {node.attr}
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.ImportFrom):
        return {alias.name for alias in node.names}
    return set()


def _offending_files() -> set[str]:
    return {
        path.relative_to(MCP).as_posix()
        for path in _source.files(MCP)
        if _source.mentions(path, *_BANNED)
        for node in _source.walk(path)
        if _names(node) & _BANNED
    }


def test_mcp_code_does_not_split_lines_itself():
    offenders = sorted(_offending_files())
    assert offenders == [], "read MCP stdio with pyfect.ai._mcp.ndjson.ndjson_lines"
