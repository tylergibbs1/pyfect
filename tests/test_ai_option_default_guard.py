"""Effect's providers fall back to a default option with ``??``
(``options.apiUrl ?? "https://..."``), which keeps an empty string; Python's
``value or DEFAULT`` replaces it, as JavaScript's ``||`` would. So under
``pyfect.ai`` a fallback to a ``DEFAULT_*`` constant goes through
``or_default`` (found in the openrouter review: ``api_url=""`` was replaced
by the default URL in six clients)."""

from __future__ import annotations

import ast

import _source

_AI = _source.SRC / "ai"


def _is_default_constant(node: ast.expr) -> bool:
    name = (
        node.id
        if isinstance(node, ast.Name)
        else node.attr
        if isinstance(node, ast.Attribute)
        else ""
    )
    return name.startswith("DEFAULT_")


def test_no_or_fallback_to_a_default_constant():
    offenders = [
        f"{path.relative_to(_AI)}:{node.lineno} {ast.unparse(node)}"
        for path in _source.files(_AI)
        for node in _source.walk(path)
        if isinstance(node, ast.BoolOp)
        and isinstance(node.op, ast.Or)
        and _is_default_constant(node.values[-1])
    ]
    assert offenders == []
