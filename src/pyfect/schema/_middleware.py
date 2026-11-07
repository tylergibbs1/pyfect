"""Middleware and decoding defaults (Effect's ``middlewareDecoding``,
``middlewareEncoding``, ``catchDecoding``, ``catchEncoding``,
``withDecodingDefaultKey``, ``withDecodingDefaultTypeKey``, ``withDecodingDefault``,
``withDecodingDefaultType``).

A middleware gets the schema's whole parse as an effect (``Some(value)``,
``None`` for a missing key, or the failure) and gives the parse to use.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Generic, Literal, Never, TypeVar

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._primitives import known_exit
from pyfect.exit import Failure, Success
from pyfect.option import Option, Some
from pyfect.schema import ast
from pyfect.schema._arrays import optional_key
from pyfect.schema._error import SchemaError
from pyfect.schema._literals import Union
from pyfect.schema._options import ParseOptions
from pyfect.schema._primitives import Null
from pyfect.schema._schema import Bottom, Codec
from pyfect.schema._transform import DecodeToSchema, decode_to, encode_to, to_encoded, to_type
from pyfect.schema.getter import (
    Getter,
    Outcome,
    TransformOptionalEffect,
    omit,
    passthrough,
    with_default,
)
from pyfect.schema.issue import Issue
from pyfect.schema.transformation import Middleware, Transformation
from pyfect.schema.transformation._transformation import unchanged

A = TypeVar("A")
R_co = TypeVar("R_co", covariant=True)
RI_contra = TypeVar("RI_contra", contravariant=True)

type Parse[A, R] = Effect[Option[A], Issue, R]
"""A parse as a middleware sees it: ``Some(value)``, ``None`` for a
missing value, or the failure."""


class MiddlewareDecoding(Generic[A, RI_contra, R_co]):
    """``middleware_decoding(f)``: apply with ``.pipe``. The schema decodes
    with the services ``f`` needs (``R``): ``f`` gets the parse needing the
    schema's own (``RI``) and may provide them."""

    __slots__ = ("_f",)

    def __init__(self, f: Callable[[Parse[A, RI_contra], ParseOptions], Parse[A, R_co]]) -> None:
        self._f = f

    def __call__[E, RE = Never](
        self, schema: Codec[A, E, RI_contra, RE], /
    ) -> Bottom[A, E, R_co, RE]:
        node = schema.__codec__().ast
        return Bottom(ast.decode_to(node, node.to_type(), Middleware(self._f, unchanged)))


def middleware_decoding[T, RI = Never, R = Never](
    f: Callable[[Parse[T, RI], ParseOptions], Parse[T, R]], /
) -> MiddlewareDecoding[T, RI, R]:
    """The schema's decoding passed through ``f(parse, options)``: the
    schema then decodes with the services ``f`` needs (Effect's
    ``middlewareDecoding``)."""
    return MiddlewareDecoding(f)


class MiddlewareEncoding(Generic[A, RI_contra, R_co]):
    """``middleware_encoding(f)``: apply with ``.pipe`` (see
    ``MiddlewareDecoding``)."""

    __slots__ = ("_f",)

    def __init__(self, f: Callable[[Parse[A, RI_contra], ParseOptions], Parse[A, R_co]]) -> None:
        self._f = f

    def __call__[T, RD = Never](
        self, schema: Codec[T, A, RD, RI_contra], /
    ) -> Bottom[T, A, RD, R_co]:
        node = schema.__codec__().ast
        return Bottom(ast.decode_to(ast.to_encoded(node), node, Middleware(unchanged, self._f)))


def middleware_encoding[E, RI = Never, R = Never](
    f: Callable[[Parse[E, RI], ParseOptions], Parse[E, R]], /
) -> MiddlewareEncoding[E, RI, R]:
    """The schema's encoding passed through ``f(parse, options)``: the
    schema then encodes with the services ``f`` needs (Effect's
    ``middlewareEncoding``)."""
    return MiddlewareEncoding(f)


class CatchDecoding(Generic[A, R_co]):
    """``catch_decoding(f)``: apply with ``.pipe``."""

    __slots__ = ("_f",)

    def __init__(self, f: Callable[[Issue], Parse[A, R_co]]) -> None:
        self._f = f

    def __call__[E, RD = Never, RE = Never](
        self, schema: Codec[A, E, RD, RE], /
    ) -> Bottom[A, E, RD | R_co, RE]:
        middleware: MiddlewareDecoding[A, RD, RD | R_co] = MiddlewareDecoding(_catching(self._f))
        return middleware(schema)


class CatchEncoding(Generic[A, R_co]):
    """``catch_encoding(f)``: apply with ``.pipe``."""

    __slots__ = ("_f",)

    def __init__(self, f: Callable[[Issue], Parse[A, R_co]]) -> None:
        self._f = f

    def __call__[T, RD = Never, RE = Never](
        self, schema: Codec[T, A, RD, RE], /
    ) -> Bottom[T, A, RD, RE | R_co]:
        middleware: MiddlewareEncoding[A, RE, RE | R_co] = MiddlewareEncoding(_catching(self._f))
        return middleware(schema)


def _catching[V, RI, R](
    f: Callable[[Issue], Parse[V, R]],
) -> Callable[[Parse[V, RI], ParseOptions], Parse[V, RI | R]]:
    return lambda effect, _: effect.catch_all(f)


def catch_decoding[T, R = Never](f: Callable[[Issue], Parse[T, R]], /) -> CatchDecoding[T, R]:
    """A failed decoding replaced by ``f(issue)``: ``Some(value)``, ``None``
    (no value: a missing key), or another failure (Effect's
    ``catchDecoding`` / ``catchDecodingWithContext``; ``f`` may need
    services)."""
    return CatchDecoding(f)


def catch_encoding[E, R = Never](f: Callable[[Issue], Parse[E, R]], /) -> CatchEncoding[E, R]:
    """A failed encoding replaced by ``f(issue)`` (Effect's ``catchEncoding``
    / ``catchEncodingWithContext``)."""
    return CatchEncoding(f)


type EncodingStrategy = Literal["passthrough", "omit"]
"""What a defaulted key encodes to: its value, or nothing."""


def _issue_of(error: SchemaError) -> Issue:
    return error.issue


def _issue_outcome[A, R](default: Effect[A, SchemaError, R]) -> Outcome[A, R]:
    """``default`` failing with its error's issue; an effect that is only
    its outcome stays an ``Exit``, so the decoding stays synchronous."""
    known = known_exit(default)
    if known is None:
        return default.map_error(_issue_of)
    return known if isinstance(known, Success) else Failure(known.cause.map(_issue_of))


class WithDecodingDefaultKey(Generic[A, R_co]):
    """``with_decoding_default_key(default)``: apply with ``.pipe``."""

    __slots__ = ("_default", "_strategy")

    def __init__(self, default: Effect[A, SchemaError, R_co], strategy: EncodingStrategy) -> None:
        self._default = default
        self._strategy: EncodingStrategy = strategy

    def __call__[T, RD = Never, RE = Never](
        self, schema: Codec[T, A, RD, RE], /
    ) -> DecodeToSchema[T, A, RD | R_co, RE]:
        default = with_default(_issue_outcome(self._default))
        encode: Getter[Any, Any] = omit()
        if self._strategy == "passthrough":
            encode = passthrough()
        transformation: Transformation[Any, Any, Any, Any] = Transformation(default, encode)
        return optional_key(to_encoded(schema)).pipe(decode_to(schema, transformation))


def with_decoding_default_key[E, R = Never](
    default: Effect[E, SchemaError, R], /, *, encoding_strategy: EncodingStrategy = "passthrough"
) -> WithDecodingDefaultKey[E, R]:
    """A missing struct key decoded as ``default``'s Encoded value (Effect's
    ``withDecodingDefaultKey``): the key is optional on the encoded side;
    ``encoding_strategy="omit"`` leaves it out when encoding."""
    require_effect(default, "default")
    return WithDecodingDefaultKey(default, encoding_strategy)


class WithDecodingDefaultTypeKey(Generic[A, R_co]):
    """``with_decoding_default_type_key(default)``: apply with ``.pipe``."""

    __slots__ = ("_default", "_strategy")

    def __init__(self, default: Effect[A, SchemaError, R_co], strategy: EncodingStrategy) -> None:
        self._default = default
        self._strategy: EncodingStrategy = strategy

    def __call__[E, RD = Never, RE = Never](
        self, schema: Codec[A, E, RD, RE], /
    ) -> DecodeToSchema[A, E, RD | R_co, RE]:
        defaulted = WithDecodingDefaultKey(self._default, self._strategy)(to_type(schema))
        return defaulted.pipe(encode_to(optional_key(schema)))


def with_decoding_default_type_key[T, R = Never](
    default: Effect[T, SchemaError, R], /, *, encoding_strategy: EncodingStrategy = "passthrough"
) -> WithDecodingDefaultTypeKey[T, R]:
    """A missing struct key decoded as ``default``'s Type value (Effect's
    ``withDecodingDefaultTypeKey``)."""
    require_effect(default, "default")
    return WithDecodingDefaultTypeKey(default, encoding_strategy)


def _with_default_nullish[T, R](default: Outcome[T, R]) -> Getter[T, T | None, R]:
    """A missing value or ``None`` is the outcome of ``default`` (Effect's
    ``withDefault``, where ``None`` is JavaScript's ``undefined``)."""

    def run(input: Option[T | None], options: ParseOptions) -> Outcome[Option[T], R]:
        if input is not None and input.value is not None:
            return Success(Some(input.value))
        if isinstance(default, Success):
            return Success(Some(default.value))
        if isinstance(default, Failure):
            return default
        return default.map(Some)

    return TransformOptionalEffect(run)


class WithDecodingDefault(Generic[A, R_co]):
    """``with_decoding_default(default)``: apply with ``.pipe``."""

    __slots__ = ("_default", "_strategy")

    def __init__(self, default: Effect[A, SchemaError, R_co], strategy: EncodingStrategy) -> None:
        self._default = default
        self._strategy: EncodingStrategy = strategy

    def __call__[T, RD = Never, RE = Never](
        self, schema: Codec[T, A, RD, RE], /
    ) -> DecodeToSchema[T, A | None, RD | R_co, RE]:
        default = _with_default_nullish(_issue_outcome(self._default))
        encode: Getter[Any, Any] = omit()
        if self._strategy == "passthrough":
            encode = passthrough()
        transformation: Transformation[Any, Any, Any, Any] = Transformation(default, encode)
        source = optional_key(Union(to_encoded(schema), Null))
        return source.pipe(decode_to(schema, transformation))


def with_decoding_default[E, R = Never](
    default: Effect[E, SchemaError, R], /, *, encoding_strategy: EncodingStrategy = "passthrough"
) -> WithDecodingDefault[E, R]:
    """A missing struct key or ``None`` decoded as ``default``'s Encoded
    value (Effect's ``withDecodingDefault``, ``None`` standing for
    ``undefined``): the key is optional and nullable on the encoded side;
    ``encoding_strategy="omit"`` leaves it out when encoding."""
    require_effect(default, "default")
    return WithDecodingDefault(default, encoding_strategy)


class WithDecodingDefaultType(Generic[A, R_co]):
    """``with_decoding_default_type(default)``: apply with ``.pipe``."""

    __slots__ = ("_default", "_strategy")

    def __init__(self, default: Effect[A, SchemaError, R_co], strategy: EncodingStrategy) -> None:
        self._default = default
        self._strategy: EncodingStrategy = strategy

    def __call__[E, RD = Never, RE = Never](
        self, schema: Codec[A, E, RD, RE], /
    ) -> DecodeToSchema[A, E | None, RD | R_co, RE]:
        defaulted = WithDecodingDefault(self._default, self._strategy)(to_type(schema))
        return defaulted.pipe(encode_to(optional_key(Union(schema, Null))))


def with_decoding_default_type[T, R = Never](
    default: Effect[T, SchemaError, R], /, *, encoding_strategy: EncodingStrategy = "passthrough"
) -> WithDecodingDefaultType[T, R]:
    """A missing struct key or ``None`` decoded as ``default``'s Type value
    (Effect's ``withDecodingDefaultType``)."""
    require_effect(default, "default")
    return WithDecodingDefaultType(default, encoding_strategy)
