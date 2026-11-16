"""An upgraded connection's shutdown hook (``Exchange.go_away``) is set only by
``Exchange.write_switch``, which sets it as the ``101`` is handed to the transport. Set after the
write returns, a shutdown that begins once the client sees the ``101`` would find no hook and
wait out the graceful timeout."""

from __future__ import annotations

import ast
from pathlib import Path

import _source

LIVE_SERVER = _source.SRC / "http" / "live_server"
ALLOWED = {"__init__", "write_switch"}


def _outside_allowed(path: Path) -> list[str]:
    allowed = [
        range(node.lineno, (node.end_lineno or node.lineno) + 1)
        for exchange in _source.walk(path)
        if isinstance(exchange, ast.ClassDef) and exchange.name == "Exchange"
        for node in exchange.body
        if isinstance(node, ast.FunctionDef) and node.name in ALLOWED
    ]
    return [
        f"{path.name}:{node.lineno}"
        for node in _source.walk(path)
        if isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign)
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Attribute) and target.attr == "go_away"
        if not any(node.lineno in lines for lines in allowed)
    ]


def test_only_write_switch_sets_the_shutdown_hook() -> None:
    assert [
        hit
        for path in _source.files(LIVE_SERVER, recursive=False)
        for hit in _outside_allowed(path)
    ] == []
