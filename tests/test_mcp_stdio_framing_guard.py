"""MCP code reads a peer's stdio through ``pyfect.ai._mcp.ndjson.ndjson_lines``.

Effect frames MCP over stdio as NDJSON: a message ends at a newline, and text the
peer leaves without one when its output ends is dropped. ``split_lines`` gives that
text as a last line, so a client built on it read a reply Effect never sees.
"""

from __future__ import annotations

import ast
from pathlib import Path

MCP = Path(__file__).resolve().parent.parent / "src" / "pyfect" / "ai"
_BANNED = frozenset({"split_lines", "split_lines_within"})


def _names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Attribute):
        return {node.attr}
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.ImportFrom):
        return {alias.name for alias in node.names}
    return set()


def test_mcp_code_does_not_split_lines_itself():
    offenders = [
        f"{path.relative_to(MCP)}:{getattr(node, 'lineno', 0)}"
        for path in sorted(MCP.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(), str(path)))
        if _names(node) & _BANNED
    ]
    assert offenders == [], "read MCP stdio with pyfect.ai._mcp.ndjson.ndjson_lines"
