"""MCP code doesn't split a peer's stdio into lines itself.

Effect frames MCP over stdio as NDJSON: a message ends at a newline, and text the
peer leaves without one when its output ends is dropped. ``split_lines`` gives that
text as a last line, so code built on it reads a message Effect never sees. The two
readers that do so today change in 0.7.0; no new one may.
"""

from __future__ import annotations

import ast

import _source

MCP = _source.SRC / "ai"
_BANNED = frozenset({"split_lines", "split_lines_within"})

ALLOWED = {
    "_mcp/client_transport.py": "0.7.0: mcp-stdio-server-070 (the client dropping a reply "
    "its server ends without a newline breaks a client of such a server)",
    "_mcp/stdio.py": "0.7.0: mcp-stdio-server-070 (the server dropping an unterminated last "
    "request and a lone \\r no longer ending a line is a change a program can see)",
}


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
    offenders = sorted(_offending_files() - set(ALLOWED))
    assert offenders == [], "split MCP stdio as Effect does: newline-terminated lines only"


def test_every_allowed_file_still_splits_lines():
    assert sorted(set(ALLOWED) - _offending_files()) == []
