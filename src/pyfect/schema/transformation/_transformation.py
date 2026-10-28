"""``Transformation`` (a getter each way) and ``Middleware`` (a function of
the whole parse each way), Effect's ``SchemaTransformation``. A schema made
with ``decode_to`` holds one in its encoding."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Never, Self, TypeIs, TypeVar, cast

from pyfect._core import Effect
from pyfect.option import Option, Some
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast import MISSING, ParseResult, call, map_value, to_effect
from pyfect.schema.getter import (
    Getter,
    Outcome,
)
from pyfect.schema.getter import (
    passthrough as passthrough_getter,
)
from pyfect.schema.getter import (
    transform as transform_getter,
)
from pyfect.schema.getter import (
    transform_effect as transform_effect_getter,
)
from pyfect.schema.getter import (
    transform_optional as transform_optional_getter,
)
from pyfect.schema.getter._getter import apply_result
from pyfect.schema.issue import Issue

T = TypeVar("T")
E = TypeVar("E")
RD_co = TypeVar("RD_co", covariant=True, default=Never)
RE_co = TypeVar("RE_co", covariant=True, default=Never)


@dataclass(frozen=True, slots=True, eq=False)
class Transformation(Generic[T, E, RD_co, RE_co]):
    """``decode`` turns an ``E`` into a ``T``, ``encode`` back, needing the
    services ``RD`` / ``RE`` (Effect's ``Transformation``)."""

    decode: Getter[T, E, RD_co]
    encode: Getter[E, T, RE_co]

    @property
    def sees_failures(self) -> bool:
        return False

    def flip(self) -> Transformation[E, T, RE_co, RD_co]:
        """The transformation the other way."""
        return Transformation(self.encode, self.decode)

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        return f(self)

    def compose[T2, RD2 = Never, RE2 = Never](
        self, other: Transformation[T2, T, RD2, RE2], /
    ) -> Transformation[T2, E, RD_co | RD2, RE_co | RE2]:
        """This transformation, then ``other`` (Effect's
        ``composeTransformation``)."""
        return Transformation(self.decode.compose(other.decode), other.encode.compose(self.encode))

    def decode_result(self, result: ParseResult, options: ParseOptions) -> ParseResult:
        return apply_result(self.decode, result, options)


type _Parse[A, R] = Effect[Option[A], Issue, R]


def unchanged[A, R](parse: _Parse[A, R], options: ParseOptions, /) -> _Parse[A, R]:
    """The side of a ``Middleware`` that leaves the parse as it is (Effect's
    ``identity`` in ``middlewareDecoding`` / ``middlewareEncoding``)."""
    return parse


@dataclass(frozen=True, slots=True, eq=False)
class Middleware(Generic[T, E, RD_co, RE_co]):
    """A function of the whole parse each way: ``decode(effect, options)``
    gets the source's parse (an effect giving ``Some(value)``, or ``None``
    for a missing value, or failing with its issue) and gives the target's
    (Effect's ``Middleware``). It sees failures, so it can recover from
    them (``catch_decoding``)."""

    decode: Callable[[_Parse[E, Any], ParseOptions], _Parse[T, RD_co]]
    encode: Callable[[_Parse[T, Any], ParseOptions], _Parse[E, RE_co]]

    @property
    def sees_failures(self) -> bool:
        return self.decode is not unchanged

    def flip(self) -> Middleware[E, T, RE_co, RD_co]:
        return Middleware(self.encode, self.decode)

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        return f(self)

    def decode_result(self, result: ParseResult, options: ParseOptions) -> ParseResult:
        source = cast("_Parse[E, Any]", to_effect(map_value(result, _option)))
        return map_value(call(self.decode, source, options), _value)


def _option(value: object) -> Option[object]:
    return None if value is MISSING else Some(value)


def _value(option: object) -> object:
    return MISSING if option is None else cast("Some[object]", option).value


def is_transformation(value: object) -> TypeIs[Transformation[Any, Any, Any, Any]]:
    """``value`` is a ``Transformation`` (Effect's ``isTransformation``)."""
    return isinstance(value, Transformation)


def transform[T2, E2](
    *, decode: Callable[[E2], T2], encode: Callable[[T2], E2]
) -> Transformation[T2, E2]:
    """A function each way (Effect's ``transform``)."""
    return Transformation(transform_getter(decode), transform_getter(encode))


def transform_effect[T2, E2, RD = Never, RE = Never](
    *,
    decode: Callable[[E2, ParseOptions], Outcome[T2, RD]],
    encode: Callable[[T2, ParseOptions], Outcome[E2, RE]],
) -> Transformation[T2, E2, RD, RE]:
    """An effectful function each way, failing with an ``Issue`` (Effect's
    ``transformEffect``)."""
    return Transformation(transform_effect_getter(decode), transform_effect_getter(encode))


def transform_optional[T2, E2](
    *,
    decode: Callable[[Option[E2]], Option[T2]],
    encode: Callable[[Option[T2]], Option[E2]],
) -> Transformation[T2, E2]:
    """A function of an ``Option`` each way (Effect's ``transformOptional``)."""
    return Transformation(transform_optional_getter(decode), transform_optional_getter(encode))


_PASSTHROUGH: Transformation[Any, Any] = Transformation(passthrough_getter(), passthrough_getter())


def passthrough[T2]() -> Transformation[T2, T2]:
    """The value unchanged each way (Effect's ``passthrough``)."""
    return _PASSTHROUGH


def passthrough_supertype() -> Transformation[Any, Any]:
    """The value unchanged each way, from a supertype ``E`` to its subtype
    ``T`` (Effect's ``passthroughSupertype``). Python cannot say that ``T``
    is a subtype of ``E``, so it is typed ``Any``."""
    return _PASSTHROUGH


def passthrough_subtype() -> Transformation[Any, Any]:
    """The value unchanged each way, from a subtype ``E`` to its supertype
    ``T`` (Effect's ``passthroughSubtype``)."""
    return _PASSTHROUGH
