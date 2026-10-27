"""Ports of Effect's ``SchemaParser.test.ts`` that use primitive schemas
only. Each test's docstring is the Effect test title, prefixed by its
``describe`` block.

``SchemaParser``'s functions fail with the bare ``SchemaIssue`` (and throw
an ``Error`` whose cause is the issue); pyfect has one family of adapters,
``Schema``'s, failing with ``SchemaError``, which holds the issue. These
ports go through them, and ``Bottom.make`` raises ``SchemaError``.

Ported in part: "decodeUnknownExit / preserves values that use Effect data
protocols" (the ``Union([Unknown])`` half waits for unions).

Omitted: "makeEffect / defers deriving the type AST until the maker is
called and derives it once" (``make_effect`` is a method of an immutable
schema: there is no maker whose ``ast`` could be swapped), the
``decodeUnknownPromise`` titles (no async adapters while every
parser is synchronous), and the titles that exercise structs, unions,
tuples, records, declarations, transformations, middleware, suspended
schemas, constructor defaults and product concurrency: they come with
those schema kinds.
"""

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect.exit import Success, fail, succeed
from pyfect.option import Some


def test_make_should_throw_an_error_when_the_input_is_invalid():
    """make / should throw an error when the input is invalid"""
    with pytest.raises(S.SchemaError, match=r"^Expected string$"):
        S.String.make(None)  # pyright: ignore[reportArgumentType]


def test_sync_should_throw_an_error_when_the_input_is_invalid():
    """decodeUnknownSync / encodeUnknownSync / should throw an error when the input is invalid"""
    with pytest.raises(S.SchemaError, match=r"^Expected string$"):
        S.decode_unknown_sync(S.String)(None)
    with pytest.raises(S.SchemaError, match=r"^Expected string$"):
        S.encode_unknown_sync(S.String)(None)


def test_option_should_return_none_when_the_input_is_invalid():
    """decodeUnknownOption / encodeUnknownOption / should return none when the input is invalid"""
    assert S.decode_unknown_option(S.String)("a") == Some("a")
    assert S.decode_unknown_option(S.String)(None) is None
    assert S.encode_unknown_option(S.String)("a") == Some("a")
    assert S.encode_unknown_option(S.String)(None) is None


def test_is_should_return_false_when_the_input_is_invalid():
    """is / should return false when the input is invalid"""
    is_string = S.is_(S.String)
    assert is_string("a") is True
    assert is_string(None) is False


def test_decode_unknown_exit_preserves_values_that_use_effect_data_protocols():
    """decodeUnknownExit / preserves values that use Effect data protocols"""
    executions = 0

    def run() -> str:
        nonlocal executions
        executions += 1
        return "a"

    decode = S.decode_unknown_exit(S.Unknown)
    values: list[object] = [None, Some("a"), succeed("a"), fail("a"), fx.sync(run)]

    for value in values:
        result = decode(value)
        assert isinstance(result, Success)
        assert result.value is value
    assert executions == 0
