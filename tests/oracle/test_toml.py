"""Ports of Effect's ``encoding/Toml.test.ts``. Each test's docstring is the
Effect test title. ``parse`` returns a ``Result``; a failure is an
``EncodingError`` with Effect's message."""

from datetime import UTC, datetime
from typing import Any

import pytest

from pyfect.encoding import toml
from pyfect.encoding.encoding_error import EncodingError
from pyfect.result import Err, Ok


def _parse(text: str) -> dict[str, Any]:
    result = toml.parse(text)
    assert isinstance(result, Ok), result
    return result.value


def _failure(text: str) -> EncodingError:
    result = toml.parse(text)
    assert isinstance(result, Err), result
    return result.error


def _message(text: str) -> str:
    return _failure(text).message


def test_parses_tables_dotted_keys_arrays_and_inline_tables():
    """parses tables, dotted keys, arrays, and inline tables"""
    text = """
title = "Effect"
ports = [8000, 8001]

[database]
connection.timeout = 30
enabled = true
credentials = { user = "root", roles = ["admin", "writer"] }
"""
    assert _parse(text) == {
        "title": "Effect",
        "ports": [8000, 8001],
        "database": {
            "connection": {"timeout": 30},
            "enabled": True,
            "credentials": {"user": "root", "roles": ["admin", "writer"]},
        },
    }


def test_parses_arrays_of_tables_and_date_time_values():
    """parses arrays of tables and date-time values"""
    text = """
[[servers]]
name = "alpha"
started = 2026-08-05T01:02:03Z

[[servers]]
name = "beta"
started = 2026-08-05
"""
    assert _parse(text) == {
        "servers": [
            {"name": "alpha", "started": datetime(2026, 8, 5, 1, 2, 3, tzinfo=UTC)},
            {"name": "beta", "started": "2026-08-05"},
        ]
    }


def test_parses_child_tables_under_distinct_array_entries():
    """parses child tables under distinct array entries"""
    text = """
[[servers]]
[servers.tls]

[[servers]]
[servers.tls]
"""
    assert _parse(text) == {"servers": [{"tls": {}}, {"tls": {}}]}


def test_parses_empty_quoted_keys():
    """parses empty quoted keys"""
    assert _parse("\"\" = 1\nnested.'' = 2") == {"": 1, "nested": {"": 2}}


@pytest.mark.parametrize("text", [" = 1\n", "a. = 1\n", '" = 1', "' = 1", "\"\" = 1\n'' = 2"])
def test_rejects_empty_bare_keys_unterminated_keys_and_duplicate_empty_keys(text: str):
    """rejects empty bare keys, unterminated keys, and duplicate empty keys"""
    _failure(text)


def test_parses_multiline_strings_and_numeric_formats():
    """parses multiline strings and numeric formats"""
    text = '''
message = """
hello \\
  world"""
hex = 0xDEAD_BEEF
fraction = 1_000.5
limits = [-9_007_199_254_740_991, 9_007_199_254_740_991]
large_float = 1e20
local = 2026-08-05 01:02:03
'''
    assert _parse(text) == {
        "message": "hello world",
        "hex": 0xDEADBEEF,
        "fraction": 1000.5,
        "limits": [-(2**53 - 1), 2**53 - 1],
        "large_float": 1e20,
        "local": "2026-08-05T01:02:03",
    }
    for token in [
        "9007199254740992",
        "-9007199254740992",
        "0x20000000000000",
        "0o400000000000000000",
        "0b100000000000000000000000000000000000000000000000000000",
    ]:
        assert "Integer out of range" in _message(f"value = {token}")


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("\nvalue", "value"),
        ("\r\nvalue", "value"),
        ("\r\n\r\nfirst\r\nsecond", "\r\nfirst\r\nsecond"),
        (" \r\nvalue", " \r\nvalue"),
    ],
    ids=["LF", "CRLF", "additional newlines", "leading whitespace"],
)
def test_trims_only_an_immediate_opening_newline_in_multiline_strings(content: str, expected: str):
    """trims only an immediate opening newline in multiline strings (%s)"""
    text = f"basic = \"\"\"{content}\"\"\"\nliteral = '''{content}'''\n"
    assert _parse(text) == {"basic": expected, "literal": expected}


def test_rejects_bare_carriage_returns():
    """rejects bare carriage returns"""
    assert _parse("a = 1 # comment\r\nb = 2") == {"a": 1, "b": 2}
    assert "Invalid control character" in _message("a = 1 # comment\rb = 2")


def test_parses_unicode_escapes_at_the_scalar_value_boundaries():
    """parses Unicode escapes at the scalar value boundaries"""
    text = r"""
before = "\uD7FF"
after = "\uE000"
max = "\U0010FFFF"
nul = "\u0000"
"""
    assert _parse(text) == {
        "before": "\ud7ff",
        "after": "\ue000",
        "max": "\U0010ffff",
        "nul": "\x00",
    }


def test_rejects_raw_control_characters():
    """rejects raw control characters"""
    for text in ['"\x00" = 1', "key = '\x7f'", 'key = """\x1f"""', "# comment\r"]:
        assert "Invalid control character" in _message(text)
    assert _message('key = "a\x00"') == "Invalid control character at line 1, column 9"
    assert _parse("key = '''\t\r\n'''\r\n# \t\r\n") == {"key": "\t\r\n"}


@pytest.mark.parametrize(
    "text",
    [r'value = "\uD800"', r'value = "\uDFFF"', r'value = "\uD83D\uDE00"', r'value = "\U00110000"'],
)
def test_rejects_unicode_escapes_that_are_not_scalar_values(text: str):
    """rejects Unicode escapes that are not scalar values: %s"""
    assert _message(text) == "Invalid unicode escape at line 1, column 12"


@pytest.mark.parametrize("quote", ['"', "'"])
def test_preserves_up_to_two_closing_content_quotes_in_multiline_strings(quote: str):
    """preserves up to two closing content quotes in multiline strings (%s)"""
    delimiter = quote * 3
    text = (
        f"empty = {delimiter}{delimiter}\n"
        f"one = {delimiter}value{quote}{delimiter}\n"
        f"two = {delimiter}value{quote}{quote}{delimiter}"
    )
    assert _parse(text) == {"empty": "", "one": f"value{quote}", "two": f"value{quote}{quote}"}


def test_preserves_escaped_quotes_before_multiline_closing_content_quotes():
    """preserves escaped quotes before multiline closing content quotes"""
    assert _parse(r'value = """value\""""""') == {"value": 'value"""'}


@pytest.mark.parametrize("quote", ['"', "'"])
def test_rejects_six_or_more_closing_quotes_in_multiline_strings(quote: str):
    """rejects six or more closing quotes in multiline strings (%s)"""
    for count in (6, 7):
        _failure(f"value = {quote * 3}value{quote * count}")


def test_rejects_duplicate_keys():
    """rejects duplicate keys"""
    duplicate = _failure("key = 1\nkey = 2\n")
    assert duplicate.kind == "Decode"
    assert duplicate.module == "Toml"
    assert duplicate.input == "key = 1\nkey = 2\n"
    assert duplicate.message == "Cannot redefine existing key 'key' at line 2, column 8"
    _failure("key = 1__000\n")


def test_rejects_extending_inline_tables_and_arrays():
    """rejects extending inline tables and arrays"""
    _failure("point = { x = 1 }\npoint.y = 2\n")
    _failure("point = { x = 1 }\n[point]\ny = 2\n")
    _failure("fruits = []\n[[fruits]]\n")
    assert _parse("t = { a.x = 1, a.y = 2 }\n") == {"t": {"a": {"x": 1, "y": 2}}}


def test_rejects_tables_defined_twice():
    """rejects tables defined twice"""
    for text in [
        '[fruit]\napple.color = "red"\n[fruit.apple]\n',
        "[a.b]\n[a]\nb.c = 1\n",
        "[[a]]\n[a]\n",
    ]:
        _failure(text)
    text = (
        '[fruit]\napple.color = "red"\napple.taste.sweet = true\n'
        "[fruit.apple.texture]\nsmooth = true\n"
    )
    assert _parse(text) == {
        "fruit": {"apple": {"color": "red", "taste": {"sweet": True}, "texture": {"smooth": True}}}
    }


def test_rejects_out_of_range_dates_and_times():
    """rejects out of range dates and times"""
    for value in [
        "1979-02-30T07:32:00Z",
        "1900-02-29",
        "1979-13-01",
        "24:00:00",
        "07:60:00",
        "07:32:61",
        "1990-12-31T23:59:60Z",
        "1979-05-27T07:32:00+24:00",
        "1979-05-27T07:32:00+00:60",
    ]:
        _failure(f"a = {value}")
    text = (
        "a = 2000-02-29T23:59:59\nb = 1979-05-27T07:32:00+23:59\n"
        "c = 1990-12-31T23:59:60\nd = 23:59:60"
    )
    assert _parse(text) == {
        "a": "2000-02-29T23:59:59",
        "b": datetime(1979, 5, 26, 7, 33, tzinfo=UTC),
        "c": "1990-12-31T23:59:60",
        "d": "23:59:60",
    }


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            "a = 2026-02-30T00:00:00Z",
            "Invalid date-time '2026-02-30T00:00:00Z' at line 1, column 25",
        ),
        (
            "a = 2026-01-01T25:00:00Z",
            "Invalid date-time '2026-01-01T25:00:00Z' at line 1, column 25",
        ),
        ("a = 1979-13-01", "Invalid date-time '1979-13-01' at line 1, column 15"),
        ("a = 2026-01-01 25:00:00", "Invalid date-time '2026-01-01T25:00:00' at line 1, column 24"),
        ("a = 0x20000000000000", "Integer out of range '0x20000000000000' at line 1, column 21"),
        ('a = """x"""""""', "Expected the end of the line at line 1, column 14"),
        ("a = 1\rb = 2", "Invalid control character at line 1, column 6"),
        ("a = { x = 1 }\n[a.b]\n", "Cannot redefine existing key 'a' at line 2, column 6"),
        ("[a]\nb.c = 1\n[a.b]\n", "Cannot redefine table 'a.b' at line 3, column 6"),
        ("[a]\n[b]\na.c = 1\n", ""),
    ],
)
def test_invalid_dates_numbers_and_tables_report_effect_s_message(text: str, message: str):
    """(pyfect) printed by Effect 4.1.2 under Node"""
    if message:
        assert _message(text) == message
    else:
        assert _parse(text) == {"a": {}, "b": {"a": {"c": 1}}}


def test_reads_a_lowercase_separator_and_offset():
    """(pyfect) printed by Effect 4.1.2 under Node: ``t`` and ``z`` are read as
    ``T`` and ``Z``, and a local date-time is written with ``T``"""
    assert _parse("a = 2026-01-01t01:00:00z\nb = 2026-01-01t01:00:00") == {
        "a": datetime(2026, 1, 1, 1, tzinfo=UTC),
        "b": "2026-01-01T01:00:00",
    }


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("a = []\n[a.b]\n", "Cannot redefine existing key 'a' at line 2, column 6"),
        ("a = []\n[a]\n", "Cannot redefine existing key 'a' at line 2, column 4"),
        ('a = "\\', "Invalid escape '\\' at line 1, column 8"),
        ('a = "\\\n"', "Invalid escape '\\\n' at line 2, column 1"),
    ],
    ids=["below an empty array", "an empty array as a table", "at the end", "before a newline"],
)
def test_invalid_text_reports_effect_s_message(text: str, message: str):
    """(pyfect) printed by Effect under Node"""
    assert _message(text) == message


def test_a_table_is_declared_once():
    """(pyfect) printed by Effect under Node"""
    assert _message("[a]\n[a]\n") == "Cannot redefine table 'a' at line 2, column 4"


def test_an_invalid_escape_of_an_astral_character_counts_one_code_unit():
    """(pyfect) Effect stops after the first UTF-16 code unit of the character:
    column 8, where counting the whole character would give 9"""
    assert _message('a = "\\\U0001f600"').endswith("at line 1, column 8")


@pytest.mark.parametrize("text", ["a = 9999-12-31T23:00:00-02:00", "a = 0001-01-01T00:00:00+01:00"])
def test_a_date_time_python_cannot_hold_in_utc_is_invalid(text: str):
    """(pyfect) Effect's ``Date`` reaches further than ``datetime``: past year 9999
    or before year 1 in UTC is refused like the years ``_js_date`` already refuses"""
    assert _message(text).startswith("Invalid date-time")
