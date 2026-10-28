"""Ports of Effect's ``encoding/Ini.test.ts``. Each test's docstring is the
Effect test title."""

from pyfect.encoding import ini


def test_parses_sections_arrays_and_scalar_values():
    """parses sections, arrays, and scalar values"""
    text = (
        "\nenabled=true\nmissing=null\nname=effect\ntag[]=one\ntag[]=two\n"
        "\n[database.pool]\nsize=10\n"
    )
    assert ini.parse(text) == {
        "enabled": True,
        "missing": None,
        "name": "effect",
        "tag": ["one", "two"],
        "database": {"pool": {"size": "10"}},
    }


def test_supports_quoted_values_comments_and_escaped_section_dots():
    """supports quoted values, comments, and escaped section dots"""
    text = '\nplain=value ; comment\nquoted="value # retained"\n[a\\.b]\nkey=yes\n'
    assert ini.parse(text) == {
        "plain": "value",
        "quoted": "value # retained",
        "a.b": {"key": "yes"},
    }


def test_preserves_a_trailing_backslash_in_unquoted_values_and_section_names():
    """preserves a trailing backslash in unquoted values and section names"""
    assert ini.parse("only = \\\n[C:\\]\nkey = yes") == {"only": "\\", "C:\\": {"key": "yes"}}
