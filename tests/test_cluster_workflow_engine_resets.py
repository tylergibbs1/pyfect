"""The cluster workflow engine resets a stored reply only through ``reset_reply``, which
passes the id of the reply it read as ``expected_reply_id``: a reset made without it would
erase a newer reply another runner stored (Effect 4.1.2's ``ClusterWorkflowEngine``; pinned
by ``keeps a newer activity reply when a stale Suspended reply resets the attempt``)."""

from __future__ import annotations

import ast
from pathlib import Path

import pyfect.cluster.cluster_workflow_engine as package


def _is_sharding_reset(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "reset"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "sharding"
    )


def _reset_calls() -> list[tuple[str, str]]:
    """(file, enclosing function) of every ``<...>.sharding.reset(...)`` call."""
    return [
        (path.name, function.name)
        for path in sorted(Path(package.__file__).parent.glob("*.py"))
        for function in ast.walk(ast.parse(path.read_text()))
        if isinstance(function, ast.FunctionDef)
        for node in ast.walk(function)
        if _is_sharding_reset(node)
    ]


def test_replies_are_reset_only_through_reset_reply() -> None:
    assert _reset_calls() == [("_engine.py", "reset_reply")]
