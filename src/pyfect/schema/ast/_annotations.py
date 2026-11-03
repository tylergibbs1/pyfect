"""Reading a node's annotations and key context (Effect's
``SchemaAST.resolve*`` and ``isOptional``)."""

from __future__ import annotations

from collections.abc import Callable

from pyfect.schema.ast._base import AST


def resolve_at(key: str) -> Callable[[AST], object]:
    """The annotation ``key`` of the annotations describing a node (its last
    check's when it has checks, else its own), or ``None`` (Effect's
    ``resolveAt``)."""

    def at(ast: AST) -> object:
        return (ast.resolve() or {}).get(key)

    return at


def _text_at(key: str) -> Callable[[AST], str | None]:
    at = resolve_at(key)

    def text(ast: AST) -> str | None:
        value = at(ast)
        return value if isinstance(value, str) else None

    return text


resolve_identifier = _text_at("identifier")
"""The node's ``identifier`` annotation (Effect's ``resolveIdentifier``)."""
resolve_title = _text_at("title")
"""The node's ``title`` annotation (Effect's ``resolveTitle``)."""
resolve_description = _text_at("description")
"""The node's ``description`` annotation (Effect's ``resolveDescription``)."""


def is_optional(ast: AST) -> bool:
    """A struct key holding ``ast`` may be missing (Effect's ``isOptional``:
    the node is ``optional_key``)."""
    return ast.optional_key
