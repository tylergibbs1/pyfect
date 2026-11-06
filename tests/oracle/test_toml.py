"""Ports of Effect's ``encoding/Toml.test.ts``. Each test's docstring is the
Effect test title. Effect's ``SyntaxError`` is a ``ValueError`` with its message."""

from datetime import UTC, datetime

import pytest

from pyfect.encoding import toml


def test_parses_tables_dotted_keys_arrays_and_inline_tables():
    """parses tables, dotted keys, arrays, and inline tables"""
    text = """
title = "Effect"
ports = [8000, 8001]
database.connection.timeout = 30

[database]
enabled = true
credentials = { user = "root", roles = ["admin", "writer"] }
"""
    assert toml.parse(text) == {
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
    assert toml.parse(text) == {
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
    assert toml.parse(text) == {"servers": [{"tls": {}}, {"tls": {}}]}


def test_parses_empty_quoted_keys():
    """parses empty quoted keys"""
    assert toml.parse("\"\" = 1\nnested.'' = 2") == {"": 1, "nested": {"": 2}}


@pytest.mark.parametrize("text", [" = 1\n", "a. = 1\n", '" = 1', "' = 1", "\"\" = 1\n'' = 2"])
def test_rejects_empty_bare_keys_unterminated_keys_and_duplicate_empty_keys(text: str):
    """rejects empty bare keys, unterminated keys, and duplicate empty keys"""
    with pytest.raises(ValueError):
        toml.parse(text)


def test_parses_multiline_strings_and_numeric_formats():
    """parses multiline strings and numeric formats"""
    text = '''
message = """
hello \\
  world"""
hex = 0xDEAD_BEEF
fraction = 1_000.5
local = 2026-08-05 01:02:03
'''
    assert toml.parse(text) == {
        "message": "hello world",
        "hex": 0xDEADBEEF,
        "fraction": 1000.5,
        "local": "2026-08-05T01:02:03",
    }


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
    assert toml.parse(text) == {"basic": expected, "literal": expected}


def test_parses_unicode_escapes_at_the_scalar_value_boundaries():
    """parses Unicode escapes at the scalar value boundaries"""
    text = r"""
before = "\uD7FF"
after = "\uE000"
max = "\U0010FFFF"
"""
    assert toml.parse(text) == {"before": "\ud7ff", "after": "\ue000", "max": "\U0010ffff"}


@pytest.mark.parametrize(
    "text",
    [r'value = "\uD800"', r'value = "\uDFFF"', r'value = "\uD83D\uDE00"', r'value = "\U00110000"'],
)
def test_rejects_unicode_escapes_that_are_not_scalar_values(text: str):
    """rejects Unicode escapes that are not scalar values: %s"""
    with pytest.raises(ValueError, match="Invalid unicode escape at line 1, column 12"):
        toml.parse(text)


def test_rejects_duplicate_keys():
    """rejects duplicate keys"""
    with pytest.raises(ValueError):
        toml.parse("key = 1\nkey = 2\n")
    with pytest.raises(ValueError):
        toml.parse("key = 1__000\n")


def test_reads_an_offset_date_time_as_javascript_s_date_does():
    """(pyfect) printed by Effect under Node: a day past the month's end rolls
    over, and an hour past 24 is invalid"""
    assert toml.parse("a = 2026-02-30T00:00:00Z") == {"a": datetime(2026, 3, 2, tzinfo=UTC)}
    with pytest.raises(ValueError, match="Invalid date-time '2026-01-01T25:00:00Z'"):
        toml.parse("a = 2026-01-01T25:00:00Z")


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
    with pytest.raises(ValueError) as raised:
        toml.parse(text)
    assert str(raised.value) == message


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[a]\n[a]\n", "Cannot redefine table 'a' at line 2, column 4"),
        ("[a]\nb.c = 1\n[a.b]\n[a.b]\n", "Cannot redefine table 'a.b' at line 4, column 6"),
    ],
)
def test_a_table_is_declared_once(text: str, message: str):
    """(pyfect) printed by Effect under Node"""
    with pytest.raises(ValueError) as raised:
        toml.parse(text)
    assert str(raised.value) == message


def test_an_invalid_escape_of_an_astral_character_counts_one_code_unit():
    """(pyfect) Effect stops after the first UTF-16 code unit of the character:
    column 8, where counting the whole character would give 9"""
    with pytest.raises(ValueError, match=r"at line 1, column 8$"):
        toml.parse('a = "\\\U0001f600"')


@pytest.mark.parametrize("text", ["a = 9999-12-31T23:00:00-02:00", "a = 0001-01-01T00:00:00+01:00"])
def test_a_date_time_python_cannot_hold_in_utc_is_invalid(text: str):
    """(pyfect) Effect's ``Date`` reaches further than ``datetime``: past year 9999
    or before year 1 in UTC is refused like the years ``_js_date`` already refuses"""
    with pytest.raises(ValueError, match="Invalid date-time"):
        toml.parse(text)
