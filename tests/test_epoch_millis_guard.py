"""Epoch milliseconds go through ``pyfect.date_time._epoch``.

``moment.timestamp() * 1000`` and ``datetime.fromtimestamp(ms / 1000)``
go through a float, which is off by a millisecond for ordinary instants
(1972-02-22T12:02:41.945Z truncates to ...944) and by microseconds in far
years.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from oracle.test_http_static_server import file_info

from pyfect.http import etag

SRC = Path(__file__).resolve().parent.parent / "src" / "pyfect"


def _is_call_of(node: ast.AST, attr: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attr
    )


def _float_epoch_math(node: ast.AST) -> bool:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        return _is_call_of(node.left, "timestamp") or _is_call_of(node.right, "timestamp")
    if isinstance(node, ast.Call) and _is_call_of(node, "fromtimestamp") and node.args:
        first = node.args[0]
        return isinstance(first, ast.BinOp) and isinstance(first.op, ast.Div)
    return False


def test_no_float_epoch_millisecond_math():
    offenders = [
        f"{path.relative_to(SRC)}:{getattr(node, 'lineno', 0)}"
        for path in sorted(SRC.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(), str(path)))
        if _float_epoch_math(node)
    ]
    assert offenders == [], "use pyfect.date_time._epoch"


def test_file_etag_uses_exact_milliseconds():
    info = replace(file_info(16), mtime=datetime(1972, 2, 22, 12, 2, 41, 945_000, UTC))
    assert etag.value_from_file_info(info) == f"10-{67_608_161_945:x}"
