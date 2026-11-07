"""``to_codec_go_json``: JSON as Go's ``encoding/json`` writes it, where a nil slice or map is
``null`` and a nil pointer ``null`` (Effect's ``Schema.toCodecGoJson``).

``null`` decodes as an empty ``Array`` or ``Record``, or as a missing optional key; the canonical
member stays first, so a value the schema itself accepts is read as before. Tuples, non-empty
arrays and structs go on refusing ``null``, and nothing encodes to it."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from pyfect._json_value import JsonValue
from pyfect.schema import ast
from pyfect.schema import getter as G
from pyfect.schema._codec_derivation import CodecDerivation
from pyfect.schema._codec_links import UNKNOWN_TO_JSON
from pyfect.schema._parse import is_
from pyfect.schema._schema import Bottom, Codec
from pyfect.schema._to_codec_json import to_codec_json_asts
from pyfect.schema.transformation import Transformation


def to_codec_go_json[T, E, RD, RE](schema: Codec[T, E, RD, RE], /) -> Bottom[T, JsonValue, RD, RE]:
    """``schema`` reading JSON a Go program wrote. A declaration with no codec is read as JSON."""
    canonical = to_codec_json_asts([schema.__codec__().ast])[0]
    return Bottom(_on_last(_nil_as_empty)(_GoNil()(canonical)))


def _on_last(f: Callable[[ast.AST], ast.AST]) -> Callable[[ast.AST], ast.AST]:
    """``f`` on ``node``, or on what the last link of its encoding reads."""

    def apply(node: ast.AST) -> ast.AST:
        if node.encoding is None:
            return f(node)
        *init, last = node.encoding
        to = apply(last.to)
        return (
            node
            if to is last.to
            else replace(node, encoding=(*init, ast.Link(to, last.transformation)))
        )

    return apply


def _forbidden(_: object) -> str:
    return "Go nil values are never encoded"


def _null_to(decode: G.Getter[Any, Any]) -> Transformation[Any, Any]:
    return Transformation(decode, G.forbidden(_forbidden))


_NULL_AS_MISSING = _null_to(G.transform_optional(lambda _: None))
_NULL_AS_EMPTY_ARRAY = _null_to(G.transform(lambda _: []))
_NULL_AS_EMPTY_RECORD = _null_to(G.transform(lambda _: {}))
_EMPTY_ARRAY = ast.Arrays((), ())
_EMPTY_RECORD = ast.record(ast.string, ast.never)


def _is_go_nil(node: ast.AST) -> bool:
    """A union this codec built, so applying it again changes nothing."""
    if not isinstance(node, ast.Union):
        return False
    encoding = node.types[-1].encoding
    return encoding is not None and encoding[0].transformation in (
        _NULL_AS_MISSING,
        _NULL_AS_EMPTY_ARRAY,
        _NULL_AS_EMPTY_RECORD,
    )


def _last_encoding(node: ast.AST) -> ast.AST:
    return node if node.encoding is None else _last_encoding(node.encoding[-1].to)


def _accepts_null(node: ast.AST) -> bool:
    """Whether the schema certainly takes ``None`` (a ``Suspend`` stays unresolved, so a recursive
    definition stays lazy): skips the member added for it."""
    encoded = _last_encoding(node)
    match encoded:
        case ast.Union():
            return encoded.checks is None and any(map(_accepts_null, encoded.types))
        case ast.Null() | ast.Unknown() | ast.Any() | ast.Declaration():
            bare: Bottom[object] = Bottom(ast.replace_context(encoded, optional_key=False))
            return is_(bare)(None)
        case _:
            return False


def _or_null(node: ast.AST, member: ast.AST) -> ast.AST:
    bare = ast.replace_context(node, optional_key=False) if node.optional_key else node
    union = ast.Union((bare, member))
    if node.optional_key or node.key_annotations:
        return ast.replace_context(
            union, key_annotations=node.key_annotations, optional_key=node.optional_key
        )
    return union


def _nil_as_empty(node: ast.AST) -> ast.AST:
    match node:
        case ast.Suspend():
            return replace(node, thunk=lambda: _on_last(_nil_as_empty)(node.target))
        case ast.Arrays(elements=(), rest=(_,)):
            to = ast.decode_to(
                ast.null, replace(_EMPTY_ARRAY, checks=node.checks), _NULL_AS_EMPTY_ARRAY
            )
            return _or_null(node, to)
        case ast.Objects(properties=(), index_signatures=(_, *_)):
            to = ast.decode_to(
                ast.null, replace(_EMPTY_RECORD, checks=node.checks), _NULL_AS_EMPTY_RECORD
            )
            return _or_null(node, to)
        case _:
            return node


def _nil_as_missing(node: ast.AST) -> ast.AST:
    match node:
        case ast.Suspend():
            return replace(node, thunk=lambda: _on_last(_nil_as_missing)(node.target))
        case _ if _is_go_nil(node) or _accepts_null(node):
            return node
        case _:
            return _or_null(node, ast.decode_to(ast.null, ast.never, _NULL_AS_MISSING))


def _nil_for_key(node: ast.AST) -> ast.AST:
    return _nil_as_missing(node) if node.optional_key else _nil_as_empty(node)


class _GoNil(CodecDerivation):
    opaque = UNKNOWN_TO_JSON

    def _leaf(self, node: ast.AST) -> ast.AST:
        return node

    def _priority(self, encoded: ast.AST) -> int:
        return 0

    def _union(self, node: ast.Union) -> ast.Union:
        return node if _is_go_nil(node) else super()._union(node)

    def _step(self, node: ast.AST) -> ast.AST:
        if isinstance(node, ast.Arrays):
            elements = tuple(
                replace(e, type=_on_last(_nil_as_empty)(self(e.type))) for e in node.elements
            )
            rest = tuple(_on_last(_nil_as_empty)(self(t)) for t in node.rest)
            same = all(
                a.type is b.type for a, b in zip(elements, node.elements, strict=True)
            ) and all(a is b for a, b in zip(rest, node.rest, strict=True))
            return node if same else replace(node, elements=elements, rest=rest)
        return super()._step(node)

    def _objects(self, node: ast.Objects) -> ast.Objects:
        properties = tuple(
            replace(
                p,
                type=_on_last(_nil_as_missing if p.optional_when_encoded() else _nil_for_key)(
                    self(p.type)
                ),
            )
            for p in node.properties
        )
        for_key = _on_last(_nil_for_key)
        indexes = tuple(replace(i, type=for_key(self(i.type))) for i in node.index_signatures)
        same = all(
            a.type is b.type for a, b in zip(properties, node.properties, strict=True)
        ) and all(a.type is b.type for a, b in zip(indexes, node.index_signatures, strict=True))
        return node if same else replace(node, properties=properties, index_signatures=indexes)
