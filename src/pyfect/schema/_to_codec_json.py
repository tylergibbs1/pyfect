"""``to_codec_json``: a schema's canonical JSON codec (Effect's
``Schema.toCodecJson``).

The derived schema decodes the same values from JSON: each node whose
values are not JSON gets an encoding from one that is, at the end of its
existing encoding chain. A number that may be non-finite is written as
``"NaN"`` / ``"Infinity"`` / ``"-Infinity"``, a bigint as its digits, an
``Unknown`` value as JSON, a declaration through its ``to_codec_json`` /
``to_codec`` annotation (``Option`` as ``{"_tag": "Some", "value": ...}``,
...) or as JSON when it has none, a mapping's ``int`` keys as text. The
other nodes are rebuilt from their derived parts; ``Any`` is kept as it is.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import cast

from pyfect._json_value import JsonValue
from pyfect.schema import ast
from pyfect.schema._codec_derivation import CodecDerivation
from pyfect.schema._codec_links import (
    BIG_INT_TO_STRING,
    NUMBER_TO_JSON,
    UNKNOWN_TO_JSON,
    is_finite_number,
)
from pyfect.schema._schema import Bottom, Codec


def to_codec_json[T, E, RD, RE](schema: Codec[T, E, RD, RE], /) -> Bottom[T, JsonValue, RD, RE]:
    """``schema`` decoding its values from JSON (Effect's ``toCodecJson``)."""
    return Bottom(_Derivation()(schema.__codec__().ast))


def to_codec_json_asts(nodes: Sequence[ast.AST]) -> list[ast.AST]:
    """The JSON forms of ``nodes`` from one derivation, so a node given
    twice (or shared between them) has one derived node, as Effect's
    memoized derivation gives."""
    derive = _Derivation()
    return [derive(node) for node in nodes]


class _Derivation(CodecDerivation):
    opaque = UNKNOWN_TO_JSON

    def _leaf(self, node: ast.AST) -> ast.AST:
        match node:
            case ast.Declaration():
                return self._declaration(node)
            case ast.Unknown():
                return replace(node, encoding=(UNKNOWN_TO_JSON,))
            case ast.Number():
                return node if is_finite_number(node) else replace(node, encoding=(NUMBER_TO_JSON,))
            case ast.BigInt():
                return replace(node, encoding=(BIG_INT_TO_STRING,))
            case _:
                return node

    def _priority(self, encoded: ast.AST) -> int:
        return 0 if isinstance(encoded, ast.BigInt) else 1

    def _declaration(self, node: ast.Declaration) -> ast.AST:
        annotations = node.annotations or {}
        get_link = annotations.get("to_codec_json") or annotations.get("to_codec")
        if not callable(get_link):
            return replace(node, encoding=(UNKNOWN_TO_JSON,))
        make = cast("Callable[[tuple[ast.AST, ...]], ast.Link | None]", get_link)
        link = make(tuple(ast.to_encoded(p) for p in node.type_parameters))
        if link is None:
            return node
        return replace(node, encoding=(ast.Link(self(link.to), link.transformation),))
