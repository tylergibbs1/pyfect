"""Ports of Effect's ``encoding/Jsonc.test.ts``. Each test's docstring is the
Effect test title; an ``it.each`` table is a parametrized test. JavaScript's
``Object.prototype`` has no Python counterpart: a dict's keys are only data,
so the inherited-member title checks the error positions with such names."""

from __future__ import annotations

import re
from typing import Any, cast

import pytest

from pyfect._json_text import parse as json_parse
from pyfect.encoding import json5, jsonc
from pyfect.encoding.encoding_error import EncodingError
from pyfect.result import Err, Ok


def _parse(text: str) -> Any:
    result = jsonc.parse(text)
    assert isinstance(result, Ok)
    return result.value


def _failure_message(text: str) -> str:
    result = jsonc.parse(text)
    assert isinstance(result, Err)
    error = result.error
    assert isinstance(error, EncodingError)
    assert error.kind == "Decode"
    assert error.module == "Jsonc"
    assert error.input == text
    return error.message


def test_accepts_comments_wherever_json_accepts_whitespace():
    """accepts comments wherever JSON accepts whitespace"""
    text = """/* before */ {
      // property
      "a" /* key */ : /* value */ [1, /* item */ true, null],
      "nested": {"value": "ok"} /* end */
    } // after"""
    assert _parse(text) == {"a": [1, True, None], "nested": {"value": "ok"}}
    assert _parse("// comment\rtrue") is True
    assert _parse("// comment \u2028 still comment\r\ntrue") is True


def test_accepts_a_single_leading_byte_order_mark():
    """accepts a single leading byte order mark"""
    assert _parse("\ufeff{}") == {}
    assert _parse("\ufeff// comment\n[1, /* comment */ true]") == [1, True]
    assert _parse('\ufeff"\ufeff"') == "\ufeff"
    assert _failure_message("\ufeff\ufeff{}") == "Invalid JSONC at line 1, column 2"


def test_ends_strings_only_at_quotes_after_an_even_run_of_backslashes():
    """ends strings only at quotes after an even run of backslashes"""
    assert _parse(r'["\" /* in */" /* out */]') == ['" /* in */']
    assert _parse(r'["\\" /* out */]') == ["\\"]


@pytest.mark.parametrize(
    "text",
    [
        "1E-3",
        r'{"url":"https://example.com/a/*b*/", "quote":"\"//still a string", '
        r'"escapes":"\\\b\f\n\r\t\/A"}',
        '"\u2028\u2029"',
        '{"__proto__":{"polluted":true},"constructor":1,"a":1,"a":2}',
    ],
)
def test_matches_json_parse_for(text: str):
    """matches JSON.parse for %j"""
    assert _parse(text) == json_parse(text)


@pytest.mark.parametrize(
    "text",
    [
        "[1,]",
        '{"a":1,}',
        "{a: 1}",
        "['a']",
        "0x1f",
        "+1",
        ".5",
        "5.",
        "-Infinity",
        "NaN",
        r'"\x41"',
        r'"\v"',
        '"a\\\nb"',
        "\v{}",
        "\u00a0{}",
        "\u2028{}",
    ],
)
def test_rejects_json5_only_syntax(text: str):
    """rejects JSON5-only syntax %j"""
    assert isinstance(json5.parse(text), Ok)
    assert re.fullmatch(r"Invalid JSONC at line \d+, column \d+", _failure_message(text))


@pytest.mark.parametrize(
    ("text", "line", "column"),
    [
        ("", 1, 1),
        ("// only a comment", 1, 18),
        ('{\n  // note\n  "a": hidden\n}', 3, 8),
        ("/* first\nsecond */\n?", 3, 1),
        ("? /* unterminated", 1, 1),
        ("{\n/* secret", 2, 10),
        ("/* nested /* */ */ {}", 1, 17),
        ("tr/* gap */ue", 1, 3),
        ("1/* xx\n */2", 2, 4),
        ('"unfinished\\" // not a comment', 1, 31),
        ("[1, /* note */]", 1, 15),
        ('{"a": 1,}', 1, 9),
        ('{"a" 1}', 1, 6),
        ("01", 1, 2),
        (r'{"a":"\q"}', 1, 8),
        ('"raw\nnewline"', 1, 5),
        ('{"a":"secret', 1, 13),
        ("{}\n/* comment */ hidden", 2, 15),
        ('{\r\n  "a": hidden\r\n}', 2, 8),
        ('{\r  "a": hidden\r}', 2, 8),
        ('{"emoji":"😀","a":?}', 1, 19),
    ],
    ids=[
        "empty input",
        "only a comment",
        "value after a line comment",
        "value after a multiline comment",
        "invalid token before an unterminated comment",
        "unterminated block comment",
        "nested block comment",
        "comment splitting a literal",
        "comment splitting a number",
        "comment marker after an escaped quote",
        "trailing array comma",
        "trailing object comma",
        "missing colon",
        "leading zero",
        "invalid escape",
        "raw newline in a string",
        "unterminated string",
        "trailing content",
        "CRLF line endings",
        "CR line endings",
        "UTF-16 columns after an astral character",
    ],
)
def test_reports_the_original_position_for(text: str, line: int, column: int):
    """reports the original position for %s"""
    assert _failure_message(text) == f"Invalid JSONC at line {line}, column {column}"


def test_locates_errors_despite_members_and_escapes_inherited_from_object_prototype():
    """locates errors despite members and escapes inherited from Object.prototype"""
    assert _failure_message('{"accessor":1,"readonly":2,}') == "Invalid JSONC at line 1, column 28"
    assert _failure_message(r'"\q"') == "Invalid JSONC at line 1, column 3"


def test_locates_errors_beyond_the_javascript_call_stack_limit():
    """locates errors beyond the JavaScript call-stack limit"""
    assert _failure_message("[" * 10_000 + "?") == "Invalid JSONC at line 1, column 10001"


def test_parses_nesting_deeper_than_python_s_json_reads():
    """(pyfect) ``json`` raises past its recursion limit; the strict parser
    still reads the value, as ``JSON.parse`` does"""
    value: Any = _parse("[" * 100_000 + "]" * 100_000)
    depth = 0
    while value:
        assert isinstance(value, list)
        value = cast("list[Any]", value)[0]
        depth += 1
    assert depth == 99_999
