"""Ports of Effect's ``encoding/Json5.test.ts``. Each test's docstring is the
Effect test title; an ``it.each`` table is a parametrized test. JavaScript's
``Object.prototype`` has no Python counterpart: a dict's keys are only data,
so the inherited-member title checks that such names parse as plain keys."""

from __future__ import annotations

import math
import re
from typing import Any, cast

import pytest

from pyfect.encoding import json5
from pyfect.encoding.encoding_error import EncodingError
from pyfect.result import Err, Ok


def _parse(text: str) -> Any:
    result = json5.parse(text)
    assert isinstance(result, Ok)
    return result.value


def _failure_message(text: str) -> str:
    result = json5.parse(text)
    assert isinstance(result, Err)
    error = result.error
    assert isinstance(error, EncodingError)
    assert error.kind == "Decode"
    assert error.module == "Json5"
    assert error.input == text
    return error.message


def test_parses_json5_syntax():
    """parses JSON5 syntax"""
    text = """// comment
{ unquoted: 1, 'single': 'it\\'s', "double": "a\\/b", trailing: [1, 2,], hex: -0x1F,
  frac: .5, point: 5., plus: +1, exp: 1e3, esc: '\\x41\\u00e9\\0\\v', continued: 'a\\
b', \\u0061b: 1, a\\u0062c: 2, café: true, 𐐀: 2, $_: null, /* block */ }"""
    assert _parse(text) == {
        "unquoted": 1,
        "single": "it's",
        "double": "a/b",
        "trailing": [1, 2],
        "hex": -31,
        "frac": 0.5,
        "point": 5,
        "plus": 1,
        "exp": 1000,
        "esc": "Aé\0\v",
        "continued": "ab",
        "ab": 1,
        "abc": 2,
        "café": True,
        "𐐀": 2,
        "$_": None,
    }
    nan, infinity = _parse("\ufeff\v\f  [NaN, -Infinity] // end")
    assert math.isnan(nan) and infinity == -math.inf


def test_keeps_proto_as_data_and_lets_the_last_duplicate_key_win():
    """keeps __proto__ as data and lets the last duplicate key win"""
    value: dict[str, object] = _parse('{"__proto__": 1, a: 1, b: 0, a: 2}')
    assert list(value) == ["__proto__", "a", "b"]
    assert value["a"] == 2


def test_ignores_members_and_escapes_inherited_from_object_prototype():
    """ignores members and escapes inherited from Object.prototype"""
    assert _parse("{accessor: 1, readonly: [2], __class__: 3, get: 4}") == {
        "accessor": 1,
        "readonly": [2],
        "__class__": 3,
        "get": 4,
    }
    assert _parse(r'"\qa"') == "qa"


@pytest.mark.parametrize(
    "ending",
    ["\n", "\r", "\r\n", "\u2028", "\u2029"],
    ids=["LF", "CR", "CRLF", "line separator", "paragraph separator"],
)
def test_handles_line_endings(ending: str):
    """handles %s line endings"""
    assert _parse("'a\\" + ending + "b'") == "ab"
    assert _parse("// comment" + ending + "{}") == {}
    assert _failure_message("{" + ending + "  a: hidden}") == "Invalid JSON5 at line 2, column 6"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "/* comment */",
        "[,1]",
        "[1,,]",
        "{a:1 b:2}",
        "[1",
        "null true",
        "-01",
        "0x",
        "1e+",
        "1/* gap */2",
        "'line\nbreak'",
        r"'\1'",
        r"'\uZZZZ'",
        r"{0a: 1}",
        "{} /* unterminated",
    ],
)
def test_rejects_malformed_json5_without_quoting_it(text: str):
    """rejects malformed JSON5 %j without quoting it"""
    assert re.fullmatch(r"Invalid JSON5 at line \d+, column \d+", _failure_message(text))


def test_parses_and_locates_errors_beyond_the_javascript_call_stack_limit():
    """parses and locates errors beyond the JavaScript call-stack limit"""
    prefix = "[" * 10_000
    value: Any = _parse(prefix + "0" + "]" * 10_000)
    for _ in range(10_000):
        assert isinstance(value, list)
        value = cast("list[Any]", value)[0]
    assert value == 0
    assert _failure_message(prefix + "?") == "Invalid JSON5 at line 1, column 10001"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('{"emoji":"😀",a:?}', "Invalid JSON5 at line 1, column 17"),
        ("{a: tru}", "Invalid JSON5 at line 1, column 8"),
        ("'\\x4'", "Invalid JSON5 at line 1, column 5"),
        ("{\\u0030a: 1}", "Invalid JSON5 at line 1, column 2"),
        ("{a\\x: 1}", "Invalid JSON5 at line 1, column 4"),
        ("'\\08'", "Invalid JSON5 at line 1, column 4"),
        (".", "Invalid JSON5 at line 1, column 2"),
        ("1 /", "Invalid JSON5 at line 1, column 4"),
    ],
)
def test_error_positions(text: str, message: str):
    """(pyfect) printed by Effect 4.1.2 under Node"""
    assert _failure_message(text) == message


def test_values():
    """(pyfect) printed by Effect 4.1.2 under Node: escapes joining a
    surrogate pair, a lone surrogate, signs, numbers"""
    assert _parse(r'"😀"') == "😀"
    assert _parse(r'"\ud83d"') == "\ud83d"
    assert _parse("[+0x10, -.5e1, 5.e1, 0, 12345678901234567]") == [
        16,
        -5,
        50,
        0,
        12345678901234567,
    ]
