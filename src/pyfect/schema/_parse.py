"""Decoding and encoding (Effect's ``Schema.decode*`` / ``encode*``).

Each function takes a schema (and parse options) and returns a ``Parser``:
call it with the input (and options overriding the first ones). The
result style is in the name: ``_effect`` (an ``Effect`` failing with
``SchemaError``, keeping the schema's services), ``_exit``, ``_option``
(``Some`` / ``None``), ``_result`` (``Ok`` / ``Err``) and ``_sync`` (the
value, or raises ``SchemaError``). The ``_unknown`` forms take any input;
the others take the schema's Encoded type (to decode) or Type (to encode).

Only schema failures become ``None`` / ``Err`` / ``SchemaError``: a defect
raised while parsing is raised as it is.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any, Never, Protocol, TypeIs, Unpack, cast

from pyfect._core import Effect
from pyfect.effect import fail, from_exit, succeed
from pyfect.exit import Exit, Failure, Success
from pyfect.exit import die as die_exit
from pyfect.exit import fail as fail_exit
from pyfect.option import Option, Some
from pyfect.result import Err, Ok, Result
from pyfect.run import run_async_exit, run_sync_exit
from pyfect.schema import ast as ast_module
from pyfect.schema._adapters import (
    ASSERTION,
    GUARD,
    OPTION,
    PROMISE,
    RESULT,
    SYNC,
    raise_schema_failure,
    schema_error_of,
)
from pyfect.schema._error import SchemaError
from pyfect.schema._options import ParseOptions
from pyfect.schema._schema import Codec, Top
from pyfect.schema.ast import AST
from pyfect.schema.issue import InvalidValue, Issue


class Parser[I, O](Protocol):
    """A decoder or encoder: ``parser(input, **options)``."""

    def __call__(self, input: I, /, **options: Unpack[ParseOptions]) -> O: ...


class Guard[A](Protocol):
    def __call__(self, input: object, /) -> TypeIs[A]: ...


type _Run[O] = Callable[[object, ParseOptions], Exit[O, SchemaError] | Effect[O, SchemaError, Any]]
"""A parse: an ``Exit``, or an ``Effect`` when a transformation needs one."""


def _present(value: object) -> Effect[object, Issue]:
    # A value made missing at the top (a getter omitting it) is invalid.
    return fail(InvalidValue()) if value is ast_module.MISSING else succeed(value)


def _runner[O](ast: AST, base: ParseOptions) -> _Run[O]:
    """Parse with ``ast``. The node is the schema's, so its output is the
    side's type: the casts of this module."""

    def run(
        input: object, options: ParseOptions
    ) -> Exit[O, SchemaError] | Effect[O, SchemaError, Any]:
        merged: ParseOptions = {**base, **options} if options else base
        try:
            result = ast.parse(input, merged)
        except RecursionError as overflow:
            # As in Effect: a walk that overflows the stack is a defect of
            # the parse (a schema whose aliases only reach each other).
            return die_exit(overflow)
        if isinstance(result, Success):
            if result.value is ast_module.MISSING:
                return fail_exit(SchemaError(InvalidValue()))
            return cast("Success[O]", result)
        if isinstance(result, Failure):
            return Failure(result.cause.map(SchemaError))
        return cast("Effect[O, SchemaError, Any]", result.flat_map(_present).map_error(SchemaError))

    return run


def _run_now[O](run: _Run[O], input: object, options: ParseOptions) -> Exit[O, SchemaError]:
    result = run(input, options)
    if isinstance(result, Success | Failure):
        return result
    return run_sync_exit(cast("Effect[O, SchemaError, Never]", result))


def _decoding[A](schema: Codec[A, object, object, object], options: ParseOptions) -> _Run[A]:
    return _runner(schema.__codec__().ast, options)


def _encoding[I](schema: Codec[object, I, object, object], options: ParseOptions) -> _Run[I]:
    return _runner(schema.__codec__().ast.flip(), options)


def _as_effect[O](run: _Run[O]) -> Parser[object, Effect[O, SchemaError, Any]]:
    """The parse as an effect; its services are the schema's (the caller's
    ``R``)."""

    def parse(input: object, /, **options: Unpack[ParseOptions]) -> Effect[O, SchemaError, Any]:
        result = run(input, options)
        if isinstance(result, Success | Failure):
            return from_exit(result)
        return result

    return parse


def _as_exit[O](run: _Run[O]) -> Parser[object, Exit[O, SchemaError]]:
    def parse(input: object, /, **options: Unpack[ParseOptions]) -> Exit[O, SchemaError]:
        return _run_now(run, input, options)

    return parse


def _as_option[O](run: _Run[O]) -> Parser[object, Option[O]]:
    def parse(input: object, /, **options: Unpack[ParseOptions]) -> Option[O]:
        match _run_now(run, input, options):
            case Success(value):
                return Some(value)
            case failure:
                schema_error_of(failure.cause, OPTION)
                return None

    return parse


def _as_result[O](run: _Run[O]) -> Parser[object, Result[O, SchemaError]]:
    def parse(input: object, /, **options: Unpack[ParseOptions]) -> Result[O, SchemaError]:
        match _run_now(run, input, options):
            case Success(value):
                return Ok(value)
            case failure:
                return Err(schema_error_of(failure.cause, RESULT))

    return parse


def _as_sync[O](run: _Run[O]) -> Parser[object, O]:
    def parse(input: object, /, **options: Unpack[ParseOptions]) -> O:
        match _run_now(run, input, options):
            case Success(value):
                return value
            case failure:
                raise_schema_failure(failure.cause, SYNC)

    return parse


# ---------------------------------------------------------------- decoding


def _as_promise[I, A](
    parser: Parser[I, Effect[A, SchemaError]],
) -> Parser[I, Coroutine[Any, Any, A]]:
    async def run(effect: Effect[A, SchemaError]) -> A:
        match await run_async_exit(effect):
            case Success(value):
                return value
            case failure:
                raise_schema_failure(failure.cause, PROMISE)

    def promise(input: I, /, **options: Unpack[ParseOptions]) -> Coroutine[Any, Any, A]:
        return run(parser(input, **options))

    return promise


def decode_unknown_effect[A, R](
    schema: Codec[A, object, R, object], /, **options: Unpack[ParseOptions]
) -> Parser[object, Effect[A, SchemaError, R]]:
    return _as_effect(_decoding(schema, options))


def decode_effect[A, I, R](
    schema: Codec[A, I, R, object], /, **options: Unpack[ParseOptions]
) -> Parser[I, Effect[A, SchemaError, R]]:
    return _as_effect(_decoding(schema, options))


def decode_unknown_promise[A](
    schema: Codec[A, object, Never, object], /, **options: Unpack[ParseOptions]
) -> Parser[object, Coroutine[Any, Any, A]]:
    """A coroutine that decodes, raising ``SchemaError`` (Effect's
    ``decodeUnknownPromise``)."""
    return _as_promise(decode_unknown_effect(schema, **options))


def decode_promise[A, I](
    schema: Codec[A, I, Never, object], /, **options: Unpack[ParseOptions]
) -> Parser[I, Coroutine[Any, Any, A]]:
    """A coroutine that decodes, raising ``SchemaError`` (Effect's
    ``decodePromise``)."""
    return _as_promise(decode_effect(schema, **options))


def decode_unknown_exit[A](
    schema: Codec[A, object, Never, object], /, **options: Unpack[ParseOptions]
) -> Parser[object, Exit[A, SchemaError]]:
    return _as_exit(_decoding(schema, options))


def decode_exit[A, I](
    schema: Codec[A, I, Never, object], /, **options: Unpack[ParseOptions]
) -> Parser[I, Exit[A, SchemaError]]:
    return _as_exit(_decoding(schema, options))


def decode_unknown_option[A](
    schema: Codec[A, object, Never, object], /, **options: Unpack[ParseOptions]
) -> Parser[object, Option[A]]:
    return _as_option(_decoding(schema, options))


def decode_option[A, I](
    schema: Codec[A, I, Never, object], /, **options: Unpack[ParseOptions]
) -> Parser[I, Option[A]]:
    return _as_option(_decoding(schema, options))


def decode_unknown_result[A](
    schema: Codec[A, object, Never, object], /, **options: Unpack[ParseOptions]
) -> Parser[object, Result[A, SchemaError]]:
    return _as_result(_decoding(schema, options))


def decode_result[A, I](
    schema: Codec[A, I, Never, object], /, **options: Unpack[ParseOptions]
) -> Parser[I, Result[A, SchemaError]]:
    return _as_result(_decoding(schema, options))


def decode_unknown_sync[A](
    schema: Codec[A, object, Never, object], /, **options: Unpack[ParseOptions]
) -> Parser[object, A]:
    return _as_sync(_decoding(schema, options))


def decode_sync[A, I](
    schema: Codec[A, I, Never, object], /, **options: Unpack[ParseOptions]
) -> Parser[I, A]:
    return _as_sync(_decoding(schema, options))


# ---------------------------------------------------------------- encoding


def encode_unknown_effect[I, R](
    schema: Codec[object, I, object, R], /, **options: Unpack[ParseOptions]
) -> Parser[object, Effect[I, SchemaError, R]]:
    return _as_effect(_encoding(schema, options))


def encode_effect[A, I, R](
    schema: Codec[A, I, object, R], /, **options: Unpack[ParseOptions]
) -> Parser[A, Effect[I, SchemaError, R]]:
    return _as_effect(_encoding(schema, options))


def encode_unknown_promise[I](
    schema: Codec[object, I, object, Never], /, **options: Unpack[ParseOptions]
) -> Parser[object, Coroutine[Any, Any, I]]:
    """A coroutine that encodes, raising ``SchemaError`` (Effect's
    ``encodeUnknownPromise``)."""
    return _as_promise(encode_unknown_effect(schema, **options))


def encode_promise[A, I](
    schema: Codec[A, I, object, Never], /, **options: Unpack[ParseOptions]
) -> Parser[A, Coroutine[Any, Any, I]]:
    """A coroutine that encodes, raising ``SchemaError`` (Effect's
    ``encodePromise``)."""
    return _as_promise(encode_effect(schema, **options))


def encode_unknown_exit[I](
    schema: Codec[object, I, object, Never], /, **options: Unpack[ParseOptions]
) -> Parser[object, Exit[I, SchemaError]]:
    return _as_exit(_encoding(schema, options))


def encode_exit[A, I](
    schema: Codec[A, I, object, Never], /, **options: Unpack[ParseOptions]
) -> Parser[A, Exit[I, SchemaError]]:
    return _as_exit(_encoding(schema, options))


def encode_unknown_option[I](
    schema: Codec[object, I, object, Never], /, **options: Unpack[ParseOptions]
) -> Parser[object, Option[I]]:
    return _as_option(_encoding(schema, options))


def encode_option[A, I](
    schema: Codec[A, I, object, Never], /, **options: Unpack[ParseOptions]
) -> Parser[A, Option[I]]:
    return _as_option(_encoding(schema, options))


def encode_unknown_result[I](
    schema: Codec[object, I, object, Never], /, **options: Unpack[ParseOptions]
) -> Parser[object, Result[I, SchemaError]]:
    return _as_result(_encoding(schema, options))


def encode_result[A, I](
    schema: Codec[A, I, object, Never], /, **options: Unpack[ParseOptions]
) -> Parser[A, Result[I, SchemaError]]:
    return _as_result(_encoding(schema, options))


def encode_unknown_sync[I](
    schema: Codec[object, I, object, Never], /, **options: Unpack[ParseOptions]
) -> Parser[object, I]:
    return _as_sync(_encoding(schema, options))


def encode_sync[A, I](
    schema: Codec[A, I, object, Never], /, **options: Unpack[ParseOptions]
) -> Parser[A, I]:
    return _as_sync(_encoding(schema, options))


# ------------------------------------------------------------------ guards


def is_[A](schema: Codec[A, object, object, object], /) -> Guard[A]:
    """A type guard for the schema's decoded side (Effect's ``is``)."""
    run: _Run[A] = _runner(schema.__codec__().ast.to_type(), {})

    def guard(input: object, /) -> TypeIs[A]:
        match _run_now(run, input, {}):
            case Success():
                return True
            case failure:
                schema_error_of(failure.cause, GUARD)
                return False

    return guard


def asserts(schema: Top, input: object, /) -> None:
    """Raise ``SchemaError`` unless ``input`` is a value of the schema's
    decoded side."""
    run: _Run[object] = _runner(schema.__codec__().ast.to_type(), {})
    match _run_now(run, input, {}):
        case Success():
            return
        case failure:
            raise_schema_failure(failure.cause, ASSERTION)
