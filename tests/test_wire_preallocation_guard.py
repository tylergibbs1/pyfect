"""Code that reads a peer's messages never sizes a list by a number the
peer sent: ``[None] * total`` let one 1-byte chunk claiming a total of
2e7 reserve 160 MB before authentication (QA ai-workflow EL-1). A list
repeated by anything but ``len(...)`` of data already held is banned in
the wire packages; hold parts as they arrive (a ``dict``) instead."""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).parent.parent / "src" / "pyfect"
_WIRE_PACKAGES = ("eventlog", "ai", "graphql", "rpc", "workflow", "cluster", "socket", "devtools")


def _sized_by_length(node: ast.expr) -> bool:
    return isinstance(node, ast.Call) and getattr(node.func, "id", None) == "len"


def test_no_list_is_sized_by_a_received_number():
    offenders: list[str] = []
    for package in _WIRE_PACKAGES:
        for path in sorted((_SRC / package).rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult)):
                    continue
                for repeated, count in ((node.left, node.right), (node.right, node.left)):
                    if (
                        isinstance(repeated, ast.List)
                        and not isinstance(count, ast.Constant)
                        and not _sized_by_length(count)
                    ):
                        offenders.append(f"{path.relative_to(_SRC)}:{node.lineno}")
    assert offenders == []
