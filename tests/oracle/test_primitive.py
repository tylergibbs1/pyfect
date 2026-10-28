"""Effect's ``test/cli/Primitive.test.ts``."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC
from typing import Any, TypedDict

import pyfect as fx
from pyfect import platform_error, testing
from pyfect import schema as S
from pyfect.cli import primitive
from pyfect.cli.primitive import Primitive
from pyfect.file_system import NoopFileSystem
from pyfect.redacted import Redacted
from pyfect.testing import Services

from ._cli_env import base_layer, file_info, with_file_system

env = testing.layer_fixture(base_layer, scope="module")


def expect_valid_values(prim: Primitive[Any], cases: Sequence[tuple[str, object]]):
    for text, expected in cases:
        result = yield from prim.parse(text)
        assert result == expected
        assert not isinstance(expected, bool) or result is expected


def expect_invalid_values(prim: Primitive[Any], inputs: Sequence[str], messages: Sequence[str]):
    for text, message in zip(inputs, messages, strict=True):
        error = yield from prim.parse(text).flip()
        assert error == message


# --- Boolean -------------------------------------------------------------------------


@testing.effect
def test_boolean_should_parse_true_values_correctly(env: Services[Any]):
    """should parse true values correctly"""
    yield from expect_valid_values(
        primitive.boolean, [("true", True), ("1", True), ("y", True), ("yes", True), ("on", True)]
    )


@testing.effect
def test_boolean_should_parse_false_values_correctly(env: Services[Any]):
    """should parse false values correctly"""
    yield from expect_valid_values(
        primitive.boolean,
        [("false", False), ("0", False), ("n", False), ("no", False), ("off", False)],
    )


@testing.effect
def test_boolean_should_fail_for_invalid_values(env: Services[Any]):
    """should fail for invalid values"""
    yield from expect_invalid_values(
        primitive.boolean,
        ["invalid"],
        ['Expected "true" | "yes" | "on" | "1" | "y" | "false" | "no" | "off" | "0" | "n"'],
    )


def test_boolean_should_have_correct_tag():
    """should have correct _tag"""
    assert primitive.boolean.tag == "Boolean"


# --- Finite --------------------------------------------------------------------------


@testing.effect
def test_finite_should_parse_valid_finite_numbers(env: Services[Any]):
    """should parse valid finite numbers"""
    yield from expect_valid_values(
        primitive.finite,
        [("42", 42.0), ("3.14", 3.14), ("-42.5", -42.5), ("0", 0.0), ("1e3", 1000.0)],
    )


@testing.effect
def test_finite_should_fail_for_invalid_values(env: Services[Any]):
    """should fail for invalid values"""
    yield from expect_invalid_values(
        primitive.finite, ["not-a-number"], ["Expected a string representing a finite number"]
    )


@testing.effect
def test_finite_should_reject_non_finite_numbers_and_overflow(env: Services[Any]):
    """should reject non-finite numbers and overflow"""
    for text in ["NaN", "Infinity", "-Infinity", "1e309"]:
        error = yield from primitive.finite.parse(text).flip()
        assert "finite number" in error


def test_finite_should_have_correct_tag():
    """should have correct _tag"""
    assert primitive.finite.tag == "Finite"


# --- Date ----------------------------------------------------------------------------


@testing.effect
def test_date_should_parse_valid_date_values(env: Services[Any]):
    """should parse valid date values"""
    day = yield from primitive.date_.parse("2024-01-15")
    assert day.astimezone(UTC).date().isoformat() == "2024-01-15"
    full = yield from primitive.date_.parse("2024-01-15T12:30:45.123Z")
    assert (
        full.astimezone(UTC).isoformat(timespec="milliseconds") == "2024-01-15T12:30:45.123+00:00"
    )
    offset = yield from primitive.date_.parse("2024-01-15T12:30:45+02:00")
    utc = offset.astimezone(UTC)
    assert (utc.hour, utc.minute) == (10, 30)


@testing.effect
def test_date_should_fail_for_invalid_values(env: Services[Any]):
    """should fail for invalid values"""
    yield from expect_invalid_values(primitive.date_, ["not-a-date"], ["Expected a valid Date"])


def test_date_should_have_correct_tag():
    """should have correct _tag"""
    assert primitive.date_.tag == "Date"


# --- Int -----------------------------------------------------------------------------


@testing.effect
def test_int_should_parse_valid_integer_values(env: Services[Any]):
    """should parse valid integer values"""
    yield from expect_valid_values(
        primitive.integer,
        [
            ("42", 42),
            ("-123", -123),
            ("0", 0),
            ("9007199254740991", 9007199254740991),
            ("1e3", 1000),
        ],
    )


@testing.effect
def test_int_should_fail_for_invalid_values(env: Services[Any]):
    """should fail for invalid values"""
    yield from expect_invalid_values(
        primitive.integer,
        ["3.14", "not-a-number"],
        ["Expected an integer", "Expected a string representing a finite number"],
    )


def test_int_should_have_correct_tag():
    """should have correct _tag"""
    assert primitive.integer.tag == "Int"


# --- String --------------------------------------------------------------------------


@testing.effect
def test_string_should_parse_string_values(env: Services[Any]):
    """should parse string values"""
    yield from expect_valid_values(
        primitive.string,
        [
            ("hello", "hello"),
            ("", ""),
            (" spaces ", " spaces "),
            ("123", "123"),
            ("special!@#$%", "special!@#$%"),
        ],
    )


def test_string_should_have_correct_tag():
    """should have correct _tag"""
    assert primitive.string.tag == "String"


# --- Choice --------------------------------------------------------------------------

color_choice = primitive.choice([("red", "RED"), ("green", "GREEN"), ("blue", "BLUE")])


@testing.effect
def test_choice_should_parse_valid_choices(env: Services[Any]):
    """should parse valid choices"""
    yield from expect_valid_values(
        color_choice, [("red", "RED"), ("green", "GREEN"), ("blue", "BLUE")]
    )


@testing.effect
def test_choice_should_fail_for_invalid_choices(env: Services[Any]):
    """should fail for invalid choices"""
    valid = '"red" | "green" | "blue"'
    yield from expect_invalid_values(color_choice, ["yellow", "purple", ""], [valid] * 3)


def test_choice_should_have_correct_tag():
    """should have correct _tag"""
    assert color_choice.tag == "Choice"


@testing.effect
def test_choice_should_work_with_different_value_types(env: Services[Any]):
    """should work with different value types"""
    number_choice = primitive.choice([("one", 1), ("two", 2), ("three", 3)])
    yield from expect_valid_values(number_choice, [("one", 1), ("two", 2), ("three", 3)])


# --- Path ----------------------------------------------------------------------------


@testing.effect
def test_path_should_resolve_paths_without_requiring_existence(env: Services[Any]):
    """should resolve paths without requiring existence"""
    path_primitive = primitive.path("either")
    result1 = yield from path_primitive.parse("./test.txt")
    result2 = yield from path_primitive.parse("/absolute/path")
    result3 = yield from path_primitive.parse("relative/path")
    assert "test.txt" in result1
    assert result2 == "/absolute/path"
    assert "relative/path" in result3


def test_path_should_have_correct_tag():
    """should have correct _tag"""
    assert primitive.path("either").tag == "Path"


class _Missing(NoopFileSystem):
    def stat(self, path: str):
        return fx.fail(
            platform_error.bad_argument(
                module="", method="", description=f"The specified path {path} does not exist"
            )
        )


@testing.effect
def test_path_should_fail_when_a_required_file_path_does_not_exist(env: Services[Any]):
    """should fail when a required file path does not exist"""
    parse = primitive.path("file", True).parse("/non/existent/file.txt")
    error = yield from with_file_system(parse.flip(), _Missing())
    assert error == "Path does not exist: /non/existent/file.txt"


@testing.effect
def test_path_should_fail_when_a_required_directory_path_does_not_exist(env: Services[Any]):
    """should fail when a required directory path does not exist"""
    parse = primitive.path("directory", True).parse("/non/existent/directory")
    error = yield from with_file_system(parse.flip(), _Missing())
    assert error == "Path does not exist: /non/existent/directory"


# --- Redacted ------------------------------------------------------------------------


@testing.effect
def test_redacted_should_parse_and_redact_values(env: Services[Any]):
    """should parse and redact values"""
    result = yield from primitive.redacted.parse("secret123")
    assert isinstance(result, Redacted)
    assert str(result) == "<redacted>"


def test_redacted_should_have_correct_tag():
    """should have correct _tag"""
    assert primitive.redacted.tag == "Redacted"


@testing.effect
def test_redacted_should_handle_empty_strings(env: Services[Any]):
    """should handle empty strings"""
    result = yield from primitive.redacted.parse("")
    assert isinstance(result, Redacted)


# --- KeyValuePair --------------------------------------------------------------------


@testing.effect
def test_key_value_pair_should_preserve_equals_in_url_query_parameters(env: Services[Any]):
    """should preserve '=' in URL query parameters"""
    url = yield from primitive.key_value_pair.parse(
        "DATABASE_URL=postgres://user:pass@host:5432/db?sslmode=require"
    )
    assert url == {"DATABASE_URL": "postgres://user:pass@host:5432/db?sslmode=require"}


@testing.effect
def test_key_value_pair_should_preserve_trailing_equals_in_padded_values(env: Services[Any]):
    """should preserve trailing '=' in padded values"""
    padded = yield from primitive.key_value_pair.parse("TOKEN=YWJjZA==")
    assert padded == {"TOKEN": "YWJjZA=="}


@testing.effect
def test_key_value_pair_should_fail_when_the_input_is_malformed(env: Services[Any]):
    """should fail when the input is malformed"""
    yield from expect_invalid_values(
        primitive.key_value_pair,
        ["invalid", "=value", "key="],
        [
            "Invalid key=value format. Expected format: key=value, got: invalid",
            "Invalid key=value format. Both key and value must be non-empty. Got: =value",
            "Invalid key=value format. Both key and value must be non-empty. Got: key=",
        ],
    )


class _Enabled(TypedDict):
    enabled: bool


class _ConfigFile(NoopFileSystem):
    def exists(self, path: str):
        return fx.succeed(True)

    def stat(self, path: str):
        return fx.succeed(file_info("File"))

    def read_file_string(self, path: str, encoding: str = "utf-8"):
        return fx.succeed('{"enabled":true}')


@testing.effect
def test_file_constructors_preserve_text_parsed_content_and_schema_decoding(env: Services[Any]):
    """file constructors preserve text, parsed content, and schema decoding"""

    def body():
        assert (yield from primitive.file_text.parse("/config.json")) == '{"enabled":true}'
        assert (yield from primitive.file_parse().parse("/config.json")) == {"enabled": True}
        decoded = yield from primitive.file_schema(S.Struct(_Enabled)).parse("/config.json")
        assert decoded == {"enabled": True}
        error = yield from primitive.file_schema(S.String).parse("/config.json").flip()
        assert "string" in error

    yield from with_file_system(fx.gen(body), _ConfigFile())


def test_never_has_the_matching_primitive_tag():
    """Never has the matching primitive tag"""
    assert primitive.never.tag == "Never"


@testing.effect
def test_never_remains_an_always_failing_sentinel(env: Services[Any]):
    """Never remains an always-failing sentinel"""
    yield from expect_invalid_values(
        primitive.never, ["value"], ["This option does not accept values"]
    )
