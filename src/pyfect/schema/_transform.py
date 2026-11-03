"""Schemas transforming between two others (Effect's ``decodeTo``,
``encodeTo``, ``decode``, ``encode``, ``flip``, ``toType``, ``toEncoded``).

``source.pipe(S.decode_to(target, transformation))`` decodes a value of
``source``'s Encoded through ``source``, then ``transformation.decode``,
then ``target``; encoding runs the other way. Without a transformation the
value passes unchanged. The source may be ``S.optional_key(schema)``: the
struct key is then optional on the encoded side.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Generic, Never, TypeVar, overload

from pyfect.schema import ast
from pyfect.schema._arrays import OptionalKey
from pyfect.schema._schema import Bottom, Codec
from pyfect.schema.transformation import Transformation, passthrough

T_co = TypeVar("T_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)
RD_co = TypeVar("RD_co", covariant=True, default=Never)
RE_co = TypeVar("RE_co", covariant=True, default=Never)

type Source[T, E, RD, RE] = Codec[T, E, RD, RE] | OptionalKey[T, E, RD, RE]
"""What ``decode_to`` takes as its source: a schema, or one in
``optional_key``."""


@dataclass(frozen=True, slots=True, eq=False)
class DecodeToSchema(Bottom[T_co, E_co, RD_co, RE_co], Generic[T_co, E_co, RD_co, RE_co]):
    """A schema decoding ``from_``'s Encoded into ``to``'s Type."""

    from_: Source[object, E_co, RD_co, RE_co]
    to: Codec[T_co, object, RD_co, RE_co]


def _source_ast(source: Source[Any, Any, Any, Any]) -> ast.AST:
    if isinstance(source, OptionalKey):
        return ast.optional_key(source.schema.__codec__().ast)
    return source.__codec__().ast


def _make[T, E, RD, RE](
    from_: Source[Any, E, RD, RE],
    to: Codec[T, Any, RD, RE],
    transformation: Transformation[Any, Any, Any, Any],
) -> DecodeToSchema[T, E, RD, RE]:
    node = ast.decode_to(_source_ast(from_), to.__codec__().ast, transformation)
    return DecodeToSchema(node, from_, to)


class DecodeTo(Generic[T_co, E_co, RD_co, RE_co]):
    """``decode_to(to, transformation)``: apply with ``.pipe`` to a source
    whose Type is ``E``."""

    __slots__ = ("_to", "_transformation")

    def __init__(
        self, to: Codec[T_co, Any, RD_co, RE_co], transformation: Transformation[Any, Any, Any, Any]
    ) -> None:
        self._to = to
        self._transformation = transformation

    def __call__[I, RD2 = Never, RE2 = Never](
        self, source: Source[E_co, I, RD2, RE2], /
    ) -> DecodeToSchema[T_co, I, RD_co | RD2, RE_co | RE2]:
        return _make(source, self._to, self._transformation)


@overload
def decode_to[T, M, RD, RE](to: Codec[T, M, RD, RE], /) -> DecodeTo[T, M, RD, RE]: ...
@overload
def decode_to[T, M, F, RD, RE](
    to: Codec[T, M, RD, RE], transformation: Transformation[M, F, RD, RE], /
) -> DecodeTo[T, F, RD, RE]: ...
def decode_to(
    to: Codec[Any, Any, Any, Any],
    transformation: Transformation[Any, Any, Any, Any] | None = None,
    /,
) -> DecodeTo[Any, Any, Any, Any]:
    """The source's values decoded through ``transformation`` (none: kept
    as they are) into ``to``'s (Effect's ``decodeTo``)."""
    return DecodeTo(to, passthrough() if transformation is None else transformation)


class EncodeTo(Generic[T_co, E_co, RD_co, RE_co]):
    """``encode_to(to, transformation)``: apply with ``.pipe`` to a schema
    whose Encoded is ``T``."""

    __slots__ = ("_to", "_transformation")

    def __init__(
        self,
        to: Source[Any, E_co, RD_co, RE_co],
        transformation: Transformation[Any, Any, Any, Any],
    ) -> None:
        self._to = to
        self._transformation = transformation

    def __call__[A, RD2 = Never, RE2 = Never](
        self, schema: Codec[A, T_co, RD2, RE2], /
    ) -> DecodeToSchema[A, E_co, RD_co | RD2, RE_co | RE2]:
        return _make(self._to, schema, self._transformation)


@overload
def encode_to[M, E, RD, RE](to: Source[M, E, RD, RE], /) -> EncodeTo[M, E, RD, RE]: ...
@overload
def encode_to[M, F, E, RD, RE](
    to: Source[M, E, RD, RE], transformation: Transformation[F, M, RD, RE], /
) -> EncodeTo[F, E, RD, RE]: ...
def encode_to(
    to: Source[Any, Any, Any, Any],
    transformation: Transformation[Any, Any, Any, Any] | None = None,
    /,
) -> EncodeTo[Any, Any, Any, Any]:
    """The schema's Encoded encoded further into ``to``'s: ``s.pipe(
    S.encode_to(to, t))`` is ``to.pipe(S.decode_to(s, t))`` (Effect's
    ``encodeTo``)."""
    return EncodeTo(to, passthrough() if transformation is None else transformation)


class Decode(Generic[T_co, RD_co, RE_co]):
    """``decode(transformation)``: apply with ``.pipe``."""

    __slots__ = ("_transformation",)

    def __init__(self, transformation: Transformation[Any, Any, Any, Any]) -> None:
        self._transformation = transformation

    def __call__[E, RD2 = Never, RE2 = Never](
        self, schema: Codec[T_co, E, RD2, RE2], /
    ) -> DecodeToSchema[T_co, E, RD_co | RD2, RE_co | RE2]:
        return _make(schema, to_type(schema), self._transformation)


def decode[T, RD = Never, RE = Never](
    transformation: Transformation[T, T, RD, RE], /
) -> Decode[T, RD, RE]:
    """The schema, then ``transformation`` on its decoded values (Effect's
    ``decode``)."""
    return Decode(transformation)


class Encode(Generic[E_co, RD_co, RE_co]):
    """``encode(transformation)``: apply with ``.pipe``."""

    __slots__ = ("_transformation",)

    def __init__(self, transformation: Transformation[Any, Any, Any, Any]) -> None:
        self._transformation = transformation

    def __call__[T, RD2 = Never, RE2 = Never](
        self, schema: Codec[T, E_co, RD2, RE2], /
    ) -> DecodeToSchema[T, E_co, RD_co | RD2, RE_co | RE2]:
        return _make(to_encoded(schema), schema, self._transformation)


def encode[E, RD = Never, RE = Never](
    transformation: Transformation[E, E, RD, RE], /
) -> Encode[E, RD, RE]:
    """``transformation`` on the encoded values, before the schema (Effect's
    ``encode``)."""
    return Encode(transformation)


@dataclass(frozen=True, slots=True, eq=False)
class FlipSchema(Bottom[T_co, E_co, RD_co, RE_co], Generic[T_co, E_co, RD_co, RE_co]):
    """``schema`` the other way: it decodes what ``schema`` encodes."""

    schema: Codec[E_co, T_co, RE_co, RD_co]


@overload
def flip[T, E, RD, RE](  # pyright: ignore[reportOverlappingOverload]
    schema: FlipSchema[T, E, RD, RE], /
) -> Codec[E, T, RE, RD]: ...
@overload
def flip[T, E, RD, RE](schema: Codec[T, E, RD, RE], /) -> FlipSchema[E, T, RE, RD]: ...
def flip(schema: Codec[Any, Any, Any, Any], /) -> Codec[Any, Any, Any, Any]:
    """The schema decoding its Type into its Encoded (Effect's ``flip``);
    the flip of a flip is the original schema, rebuilt on the flipped node
    (so checks added in between stay)."""
    if isinstance(schema, FlipSchema):
        node = schema.ast.flip()
        original = schema.schema.__codec__()
        return original if original.ast is node else replace(original, ast=node)
    return FlipSchema(schema.__codec__().ast.flip(), schema)


def to_type[T](schema: Codec[T, object, object, object], /) -> Bottom[T]:
    """The schema's decoded side: it checks a Type value and keeps it
    (Effect's ``toType``)."""
    return Bottom(schema.__codec__().ast.to_type())


def to_encoded[E](schema: Codec[object, E, object, object], /) -> Bottom[E]:
    """The schema's encoded side (Effect's ``toEncoded``)."""
    return Bottom(ast.to_encoded(schema.__codec__().ast))


def link[T, M](
    encode_to: Codec[M, object, object, object], transformation: Transformation[T, M], /
) -> ast.Link:
    """A declaration's codec step (Effect's ``link<T>()(encodeTo, t)``): its
    ``T`` values encoded through ``transformation`` to ``encode_to``, for a
    ``to_codec`` / ``to_codec_json`` annotation."""
    return ast.Link(encode_to.__codec__().ast, transformation)
