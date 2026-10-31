"""Ports of Effect's ``encoding/Ini.test.ts``. Each test's docstring is the
Effect test title."""

import pytest

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


# QA schema-data F11: what Effect's parser does where the ``ini`` port
# differed (node, Effect 4.0.6).


def test_a_section_over_an_array_keeps_the_array():
    """``k[]=1`` then ``[k]``: Effect gives ``{"k": ["1"]}``."""
    assert ini.parse("k[]=1\n[k]\nx=1") == {"k": ["1"]}


def test_a_section_over_a_value_raises():
    """``a=1`` then ``[a]``: Effect throws ``Cannot create property 'b' on string '1'``."""
    with pytest.raises(ValueError, match="Cannot create property 'b' on string '1'"):
        ini.parse("a=1\n[a]\nb=2")


def test_a_section_over_a_value_with_no_properties_keeps_the_value():
    """``a=1`` then ``[a]`` and nothing set in it: Effect gives ``{"a": "1"}``
    (``??=`` keeps the value, and only setting a property on it throws)."""
    assert ini.parse("a=1\n[a]") == {"a": "1"}
    assert ini.parse("a=true\n[a]\n;c") == {"a": True}
    assert ini.parse("a=1\n[a]\n__proto__=2") == {"a": "1"}


def test_a_byte_order_mark_alone_is_a_blank_line():
    """JavaScript's ``\\s`` includes U+FEFF: Effect gives ``{}``."""
    assert ini.parse("﻿") == {}


def test_an_information_separator_is_a_key():
    """JavaScript's ``\\s`` excludes U+001C: Effect gives ``{"\\u001c": true}``."""
    assert ini.parse("\x1c") == {"\x1c": True}


def test_proto_sections_and_keys_are_dropped():
    """Effect skips a ``__proto__`` section, key and section part."""
    text = "[__proto__]\nx=1\n__proto__=2\n[a.__proto__.b]\nc=3"
    assert ini.parse(text) == {"a": {"b": {"c": "3"}}}


def test_a_quoted_nan_stays_text():
    """``JSON.parse("NaN")`` throws, so Effect keeps the text."""
    assert ini.parse("q='NaN'") == {"q": "NaN"}
