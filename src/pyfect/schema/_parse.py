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
from pyfect.cause import die as die_cause
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
    CONSTRUCTOR,
    GUARD,
    OPTION,
    PROMISE,
    RESULT,
    SYNC,
    raise_schema_failure,
    schema_error_of,
)
from pyfect.schema._error import SchemaError
from pyfect.schema._make import Maker
from pyfect.schema._options import ParseOptions
from pyfect.schema._schema import Codec, Top
from pyfect.schema.ast import AST, ParseResult, run_now, to_effect
from pyfect.schema.compiler import _registry
from pyfect.schema.compiler._registry import DEFAULT_PARSE_OPTIONS
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
    """Parse with ``ast``'s registry entry, resolved on the first call and
    kept (Effect's ``runWithCompiler``). The node is the schema's, so its
    output is the side's type: the casts of this module."""
    entries: list[_registry.Entry] = []

    def run(
        input: object, options: ParseOptions
    ) -> Exit[O, SchemaError] | Effect[O, SchemaError, Any]:
        merged: ParseOptions = {**base, **options} if options else base or DEFAULT_PARSE_OPTIONS
        if not entries:
            entries.append(_registry.resolve(ast))
        try:
            result = (
                entries[0].parser(input, merged) if _registry.active() else ast.parse(input, merged)
            )
        except RecursionError as overflow:
            # As in Effect: a walk that overflows the stack is a defect of
            # the parse (a schema whose aliases only reach each other).
            return die_exit(overflow)
        return _settled(result)

    return run


def _settled[O](result: ParseResult) -> Exit[O, SchemaError] | Effect[O, SchemaError, Any]:
    if isinstance(result, Success):
        if result.value is ast_module.MISSING:
            return fail_exit(SchemaError(InvalidValue()))
        return cast("Success[O]", result)
    if isinstance(result, Failure):
        return Failure(result.cause.map(SchemaError))
    return cast("Effect[O, SchemaError, Any]", result.flat_map(_present).map_error(SchemaError))


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
    """A type guard for the schema's decoded side (Effect's ``is``): an
    installed ``is_`` operation when there is one, called with
    ``DEFAULT_PARSE_OPTIONS``."""
    ast = schema.__codec__().ast.to_type()
    resolved: list[Callable[[object], bool]] = []

    def guard(input: object, /) -> TypeIs[A]:
        if not resolved:
            # As in Effect, a guard first called before anything is
            # installed stays with the interpreter.
            active = _registry.active()
            run = _runner(ast, {})
            entry = _registry.resolve(ast)
            resolved.append(_guard_of(entry) if active else lambda input: _check(run, input))
        return resolved[0](input)

    return guard


def _guard_of(entry: _registry.Entry) -> Callable[[object], bool]:
    fast = entry.is_
    if fast is not None:

        def by_is(input: object) -> bool:
            try:
                return fast(input, DEFAULT_PARSE_OPTIONS)
            except Exception as defect:
                schema_error_of(die_cause(defect), GUARD)
                return False

        return by_is
    parser = entry.parser

    return lambda input: _check(lambda i, o: _settled(parser(i, o)), input)


def _check(run: _Run[object], input: object) -> bool:
    match _run_now(run, input, DEFAULT_PARSE_OPTIONS):
        case Success():
            return True
        case failure:
            schema_error_of(failure.cause, GUARD)
            return False


def asserts(schema: Top, input: object, /) -> None:
    """Raise ``SchemaError`` unless ``input`` is a value of the schema's
    decoded side."""
    run: _Run[object] = _runner(schema.__codec__().ast.to_type(), {})
    match _run_now(run, input, {}):
        case Success():
            return
        case failure:
            raise_schema_failure(failure.cause, ASSERTION)


# ------------------------------------------------------------ construction


def make[A](schema: Codec[A, object, object, object], /) -> Parser[A, A]:
    """The schema's constructor (Effect's ``SchemaParser.make``): raises
    ``SchemaError``. Its registry entry is resolved on the first call and
    kept."""
    maker = Maker(schema.__codec__().ast.to_type())

    def construct(input: A, /, **options: Unpack[ParseOptions]) -> A:
        match run_now(maker.parse(input, options, True)):
            case Success(value):
                return cast("A", value)
            case failure:
                raise_schema_failure(failure.cause.map(SchemaError), CONSTRUCTOR)

    return construct


def make_option[A](schema: Codec[A, object, object, object], /) -> Parser[A, Option[A]]:
    """The schema's constructor giving ``Some`` or ``None`` (Effect's
    ``SchemaParser.makeOption``)."""
    maker = Maker(schema.__codec__().ast.to_type())

    def construct(input: A, /, **options: Unpack[ParseOptions]) -> Option[A]:
        match run_now(maker.parse(input, options, True)):
            case Success(value):
                return Some(cast("A", value))
            case failure:
                schema_error_of(failure.cause.map(SchemaError), OPTION)
                return None

    return construct


def make_effect[A](schema: Codec[A, object, object, object], /) -> Parser[A, Effect[A, Issue, Any]]:
    """The schema's constructor as an effect failing with the bare ``Issue``
    (Effect's ``SchemaParser.makeEffect``)."""
    maker = Maker(schema.__codec__().ast.to_type())

    def construct(input: A, /, **options: Unpack[ParseOptions]) -> Effect[A, Issue, Any]:
        return cast("Effect[A, Issue, Any]", to_effect(maker.parse(input, options, False)))

    return construct
