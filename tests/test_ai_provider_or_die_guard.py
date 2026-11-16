"""A provider's failures are ``AiError`` s, never defects made with ``or_die``.

OpenAI's WebSocket mode died when a client transform failed to prepare the connection
request (``.or_die()``), where Effect 4.1.4 reports an ``AiError`` (#10512). A provider maps
what fails to its ``AiError`` (``ErrorMapper.catch`` / ``http_error``); what cannot fail
needs no ``or_die``.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable

import _source

_AI = _source.SRC / "ai"
_PROVIDERS = ("anthropic", "cloudflare", "openai", "openai_compat", "openrouter", "typesafe")


def _or_die_calls(nodes: Iterable[ast.AST]) -> list[int]:
    return [
        node.lineno
        for node in nodes
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "or_die"
    ]


def test_no_provider_turns_a_failure_into_a_defect() -> None:
    found = [
        f"{path.relative_to(_AI)}:{line}"
        for provider in _PROVIDERS
        for path in _source.files(_AI / provider)
        for line in _or_die_calls(_source.walk(path))
    ]
    assert not found, found


def test_the_guard_sees_or_die() -> None:
    assert _or_die_calls(ast.walk(_source.parse("client.preprocess(request).or_die()"))) == [1]
