"""``to_codec_string_tree``: a schema's canonical string-tree codec (Effect's
``Schema.toCodecStringTree``).

The derived schema decodes the same values from a tree of strings: mappings
and sequences stay, and every leaf is text. ``None`` is ``"null"``, a
boolean ``"true"`` / ``"false"``, a number or bigint its digits, a
non-string literal or enum value its text, and a declaration goes through
its ``to_codec_string_tree`` annotation, else its ``to_codec_json`` /
``to_codec`` one (an error when it has none). ``Unknown`` values are kept
as any string tree; ``Any`` is kept as it is.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import cast

from pyfect.schema import ast
from pyfect.schema._codec_derivation import CodecDerivation
from pyfect.schema._codec_links import (
    BIG_INT_TO_STRING,
    BOOLEAN_TO_STRING,
    FINITE_TO_STRING,
    NULL_TO_STRING,
    NUMBER_TO_STRING,
    UNKNOWN_TO_STRING_TREE,
    enum_to_string,
    is_finite_number,
    literal_to_string,
)
from pyfect.schema._schema import Bottom, Codec
from pyfect.schema._to_codec_array_from_single import FROM_SINGLE

type StringTree = str | Sequence[StringTree] | Mapping[str, StringTree] | None
"""Text leaves (``None`` for Effect's ``undefined``) in lists and string-keyed
mappings (Effect's ``StringTree``)."""


def to_codec_string_tree[T, E, RD, RE](
    schema: Codec[T, E, RD, RE], /
) -> Bottom[T, StringTree, RD, RE]:
    """``schema`` decoding its values from a string tree (Effect's
    ``toCodecStringTree``). A declaration with no codec annotation is a
    ``ValueError``."""
    return Bottom(to_codec_string_tree_ast(schema.__codec__().ast))


def to_codec_string_tree_ast(node: ast.AST) -> ast.AST:
    return _Derivation()(node)


class _Derivation(CodecDerivation):
    opaque = UNKNOWN_TO_STRING_TREE

    def _stops_at(self, link: ast.Link) -> bool:
        return link.transformation is FROM_SINGLE

    def _leaf(self, node: ast.AST) -> ast.AST:  # noqa: PLR0911
        match node:
            case ast.Declaration():
                return self._declaration(node)
            case ast.Null():
                return replace(node, encoding=(NULL_TO_STRING,))
            case ast.Boolean():
                return replace(node, encoding=(BOOLEAN_TO_STRING,))
            case ast.Unknown():
                return replace(node, encoding=(UNKNOWN_TO_STRING_TREE,))
            case ast.Number():
                link = FINITE_TO_STRING if is_finite_number(node) else NUMBER_TO_STRING
                return replace(node, encoding=(link,))
            case ast.BigInt():
                return replace(node, encoding=(BIG_INT_TO_STRING,))
            case ast.Literal() if not isinstance(node.literal, str):
                return literal_to_string(node)
            case ast.Enum():
                return self._enum(node)
            case _:
                return node

    def _enum(self, node: ast.Enum) -> ast.AST:
        match node.side:
            case "encode":
                return replace(node, encoding=(UNKNOWN_TO_STRING_TREE,))
            case "type":
                return self._enum(replace(node, side="decode"))
            case "decode" | "encoded":
                if all(isinstance(member.value, str) for member in node.enum):
                    return node
                return enum_to_string(node)

    def _priority(self, encoded: ast.AST) -> int:
        return 0 if isinstance(encoded, (ast.Null, ast.Boolean, ast.Number, ast.BigInt)) else 1

    def _declaration(self, node: ast.Declaration) -> ast.AST:
        annotations = node.annotations or {}
        parameters = tuple(ast.to_encoded(p) for p in node.type_parameters)
        own = annotations.get("to_codec_string_tree")
        if callable(own):
            link = _link_of(own, parameters)
            return node if link is None else self._linked(node, link)
        for key in ("to_codec_json", "to_codec"):
            get_link = annotations.get(key)
            if callable(get_link):
                link = _link_of(get_link, parameters)
                if link is not None:
                    return self._linked(node, link)
        raise ValueError(f"Missing structural codec for StringTree: {node.expected()}")

    def _linked(self, node: ast.Declaration, link: ast.Link) -> ast.AST:
        return replace(node, encoding=(ast.Link(self(link.to), link.transformation),))


def _link_of(get_link: object, parameters: tuple[ast.AST, ...]) -> ast.Link | None:
    return cast("Callable[[tuple[ast.AST, ...]], ast.Link | None]", get_link)(parameters)
