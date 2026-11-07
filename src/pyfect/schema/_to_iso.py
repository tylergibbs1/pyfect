"""``to_iso``: an optic between a schema's values and their plain form, where each class is its
fields and each data type its ``to_codec`` form (Effect's ``Schema.toIso`` and ``toCodecIso``)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any, cast

from pyfect import optic
from pyfect.schema import ast
from pyfect.schema._codec_derivation import CodecDerivation
from pyfect.schema._codec_links import UNKNOWN_TO_JSON
from pyfect.schema._parse import decode_sync, encode_sync
from pyfect.schema._schema import Bottom, Codec
from pyfect.schema.transformation import Transformation


def to_codec_iso[T](schema: Codec[T, object, object, object], /) -> Bottom[T, Any]:
    return Bottom(_Derivation()(schema.__codec__().ast.to_type()))


def to_iso[T](schema: Codec[T, object, object, object], /) -> optic.Iso[T, Any]:
    serializer: Any = to_codec_iso(schema)
    return optic.make_iso(encode_sync(serializer), decode_sync(serializer))


def to_iso_source[T](_: Codec[T, object, object, object], /) -> optic.Iso[T, T]:
    return optic.Id()


def to_iso_focus(_: Codec[object, object, object, object], /) -> optic.Iso[Any, Any]:
    return optic.Id()


def override_to_codec_iso[T, I](
    to: Codec[I, object, object, object], transformation: Transformation[T, I], /
) -> Callable[[Codec[T, Any, Any, Any]], Bottom[T, Any, Any, Any]]:
    """``schema`` whose plain form is ``to``, read through ``transformation``."""
    link = ast.Link(to.__codec__().ast, transformation)

    def get_link(_: tuple[ast.AST, ...]) -> ast.Link:
        return link

    def override(schema: Codec[T, Any, Any, Any]) -> Bottom[T, Any, Any, Any]:
        return Bottom(ast.annotate(schema.__codec__().ast, {"to_codec_iso": get_link}))

    return override


class _Derivation(CodecDerivation):
    opaque = UNKNOWN_TO_JSON

    def _leaf(self, node: ast.AST) -> ast.AST:
        if not isinstance(node, ast.Declaration):
            return node
        annotations = node.annotations or {}
        get_link = annotations.get("to_codec_iso") or annotations.get("to_codec")
        if not callable(get_link):
            return node
        make = cast("Callable[[tuple[ast.AST, ...]], ast.Link | None]", get_link)
        link = make(node.type_parameters)
        if link is None:
            return node
        return replace(node, encoding=(ast.Link(self(link.to), link.transformation),))

    def _priority(self, encoded: ast.AST) -> int:
        return 0

    def _objects(self, node: ast.Objects) -> ast.Objects:
        properties = tuple(replace(p, type=self(p.type)) for p in node.properties)
        indexes = tuple(replace(i, type=self(i.type)) for i in node.index_signatures)
        return replace(node, properties=properties, index_signatures=indexes)
