"""The decode / encode / make adapters at the ``pyfect.schema`` boundary:
the promise forms, the constructors as functions, a parse that omits its
value, and how the adapters use a decoder installed in the compiler
registry (``pyfect.schema.compiler``)."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypedDict

import pytest
from oracle._schema_compiler import fresh_registry

import pyfect as fx
from pyfect import schema as S
from pyfect.cause import Cause, Fail
from pyfect.exit import Failure, Success
from pyfect.option import Some
from pyfect.schema import compiler
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema.compiler import DEFAULT_PARSE_OPTIONS, MISSING, CompiledDecoder
from pyfect.schema.issue import Composite, InvalidValue, format_issue

__all__ = ["fresh_registry"]


def _settle[A](coroutine: Coroutine[Any, Any, A]) -> A:
    return asyncio.run(coroutine)


def _rejection(coroutine: Coroutine[Any, Any, object]) -> str:
    with pytest.raises(S.SchemaError) as raised:
        asyncio.run(coroutine)
    return raised.value.message


# ---------------------------------------------------------------- promises


def test_the_promise_adapters_settle_with_the_value():
    assert _settle(S.decode_promise(S.NumberFromString)("1")) == 1
    assert _settle(S.decode_unknown_promise(S.NumberFromString)("1")) == 1
    assert _settle(S.encode_promise(S.NumberFromString)(1)) == "1"
    assert _settle(S.encode_unknown_promise(S.NumberFromString)(1)) == "1"


def test_the_promise_adapters_take_options_when_made():
    assert _rejection(S.decode_promise(S.String, report_input=True)(1)) == "Expected string, got 1"  # pyright: ignore[reportArgumentType]
    assert _rejection(S.decode_unknown_promise(S.String, report_input=True)(1)) == (
        "Expected string, got 1"
    )
    assert _rejection(S.encode_promise(S.Number, report_input=True)("a")) == (  # pyright: ignore[reportArgumentType]
        'Expected number, got "a"'
    )
    assert _rejection(S.encode_unknown_promise(S.Number, report_input=True)("a")) == (
        'Expected number, got "a"'
    )


def test_the_promise_adapters_take_options_when_called():
    assert _rejection(S.decode_unknown_promise(S.String)(1, report_input=True)) == (
        "Expected string, got 1"
    )
    assert _rejection(
        S.decode_unknown_promise(S.String, report_input=True)(1, report_input=False)
    ) == ("Expected string")


# ----------------------------------------------------- an omitted value


def _omitting(getter: G.Getter[str, str]) -> S.Bottom[str, str]:
    return S.String.pipe(S.decode(T.Transformation(getter, G.passthrough())))


def test_a_value_omitted_at_the_top_is_invalid_also_when_the_omission_is_an_effect():
    omitted = _omitting(G.transform_optional_effect(lambda _, __: fx.sync(lambda: None)))
    invalid = Failure(Cause((Fail(S.SchemaError(InvalidValue())),)))
    assert S.decode_unknown_exit(omitted)("a") == invalid
    assert fx.run_sync_exit(S.decode_unknown_effect(omitted)("a")) == invalid
    with pytest.raises(S.SchemaError, match="Expected a valid value"):
        S.decode_unknown_sync(omitted)("a")


# ------------------------------------------------------------ constructors


class _Fields(TypedDict):
    a: str
    b: str


_DEFAULTED = S.Struct(
    _Fields,
    a=S.String.pipe(S.with_constructor_default(fx.succeed("default"))),
    b=S.String.check(S.is_min_length(2)),
)


def _raises(_: object) -> bool:
    raise RuntimeError("check raised")


_RAISING = S.String.check(S.make_filter(_raises))


def test_make_fills_defaults_and_raises_a_schema_error_with_the_call_options():
    make = S.make(_DEFAULTED)
    assert make({"b": "bb"}) == {"a": "default", "b": "bb"}  # pyright: ignore[reportArgumentType]
    with pytest.raises(S.SchemaError) as raised:
        make({"a": 1, "b": "b"}, errors="all")  # pyright: ignore[reportArgumentType]
    assert raised.value.message == (
        'Expected string\n  at ["a"]\nExpected a value with a length of at least 2\n  at ["b"]'
    )


def test_make_raises_a_defect_as_a_constructor_adapter_error():
    with pytest.raises(RuntimeError, match="Constructor adapter can only throw schema issues"):
        S.make(_RAISING)("a")


def test_make_option_gives_some_or_none():
    make = S.make_option(_DEFAULTED)
    assert make({"b": "bb"}) == Some({"a": "default", "b": "bb"})  # pyright: ignore[reportArgumentType]
    assert make({"b": "b"}) is None  # pyright: ignore[reportArgumentType]
    with pytest.raises(RuntimeError, match="Option adapter can only return none for schema issues"):
        S.make_option(_RAISING)("a")


def test_make_effect_fails_with_the_bare_issue():
    make = S.make_effect(_DEFAULTED)
    assert fx.run_sync(make({"b": "bb"})) == {"a": "default", "b": "bb"}  # pyright: ignore[reportArgumentType]
    exit = fx.run_sync_exit(make({"b": "b"}))  # pyright: ignore[reportArgumentType]
    assert isinstance(exit, Failure)
    match exit.cause.reasons:
        case (Fail(error=Composite() as issue),):
            assert format_issue(issue) == 'Expected a value with a length of at least 2\n  at ["b"]'
        case other:
            raise AssertionError(other)


# ------------------------------------------------- with an installed decoder


def _identity(input: object, options: object) -> Success[object]:
    return Success(input)


def _node(title: str) -> S.Bottom[str]:
    # A node of its own, so the decoder installed for it reaches nothing else.
    return S.String.annotate(title=title)


def test_a_guard_calls_the_installed_is_with_the_default_options():
    node = _node("guarded")
    calls: list[tuple[object, object]] = []

    def is_(input: object, options: object) -> bool:
        calls.append((input, options))
        return input == "yes"

    compiler.set(node.ast, CompiledDecoder(decode_effect=_identity, is_=is_))
    guard = S.is_(node)
    assert guard("yes")
    assert not guard("no")
    assert [input for input, _ in calls] == ["yes", "no"]
    assert all(options is DEFAULT_PARSE_OPTIONS for _, options in calls)


def test_an_installed_is_that_raises_is_a_guard_adapter_error():
    node = _node("raising guard")
    defect = ValueError("is raised")

    def is_(input: object, options: object) -> bool:
        raise defect

    compiler.set(node.ast, CompiledDecoder(decode_effect=_identity, is_=is_))
    with pytest.raises(RuntimeError, match="Type guard adapter") as raised:
        S.is_(node)("a")
    assert raised.value.__cause__ is defect


def test_a_parser_keeps_the_decoder_it_resolved_first():
    node = _node("kept")
    decode = S.decode_unknown_sync(node)
    compiler.set(node.ast, CompiledDecoder(decode_effect=lambda _, __: Success("first")))
    assert decode("a") == "first"
    compiler.set(node.ast, CompiledDecoder(decode_effect=lambda _, __: Success("second")))
    assert decode("a") == "first"
    assert S.decode_unknown_sync(node)("a") == "second"


def test_a_call_without_options_passes_the_default_options():
    node = _node("options")
    seen: list[object] = []

    def decode_effect(input: object, options: object) -> Success[object]:
        seen.append(options)
        return Success(input)

    compiler.set(node.ast, CompiledDecoder(decode_effect=decode_effect))
    S.decode_unknown_sync(node)("a")
    S.decode_unknown_sync(node, errors="all")("a")
    S.decode_unknown_sync(node)("a", errors="all")
    assert seen[0] is DEFAULT_PARSE_OPTIONS
    assert seen[1:] == [{"errors": "all"}, {"errors": "all"}]


def test_make_uses_the_installed_fast_constructor_and_make_effect_the_complete_one():
    node = _node("constructed")
    compiler.set(
        node.ast,
        CompiledDecoder(
            decode_effect=_identity,
            make=lambda _, __: "fast",
            make_effect=lambda _, __: Success("complete"),
        ),
    )
    assert S.make(node)("a") == "fast"
    assert S.make_option(node)("a") == Some("fast")
    assert fx.run_sync_exit(S.make_effect(node)("a")) == Success("complete")


class _Keys(TypedDict):
    a: str
    b: str


def test_a_missing_key_reaches_the_installed_decoder_of_its_value():
    field = _node("filled when missing")

    def decode_effect(input: object, options: object) -> Success[object]:
        return Success("filled" if input is MISSING else input)

    compiler.set(field.ast, CompiledDecoder(decode_effect=decode_effect))
    schema = S.Struct(_Keys, a=field, b=S.Literal("x"))
    assert S.decode_unknown_sync(schema)({"b": "x"}) == {"a": "filled", "b": "x"}
    assert S.decode_unknown_sync(schema)({"a": "given", "b": "x"}) == {"a": "given", "b": "x"}
