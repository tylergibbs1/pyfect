"""Ports of Effect's ``JsonPointer.test.ts``. Each test's docstring is the
Effect test title, prefixed by its ``describe`` blocks.

Python mappings: Effect's ``URIError`` is a ``ValueError``; the
"immutability" titles hold trivially (Python strings are immutable) and are
kept for the equalities they check.
"""

import pytest

from pyfect.json_pointer import (
    escape_token,
    format_uri_fragment,
    parse_uri_fragment,
    unescape_token,
)


def test_escape_tilde():
    """escapeToken / basic escaping / escapes tilde (~) to ~0"""
    assert escape_token("a~b") == "a~0b"
    assert escape_token("~") == "~0"
    assert escape_token("~~") == "~0~0"


def test_escape_slash():
    """escapeToken / basic escaping / escapes forward slash (/) to ~1"""
    assert escape_token("a/b") == "a~1b"
    assert escape_token("/") == "~1"
    assert escape_token("//") == "~1~1"


def test_escape_both():
    """escapeToken / basic escaping / escapes both tilde and slash in same string"""
    assert escape_token("a~b/c") == "a~0b~1c"
    assert escape_token("path/to~key") == "path~1to~0key"
    assert escape_token("~a/b~c/d~") == "~0a~1b~0c~1d~0"


def test_escape_order():
    """escapeToken / order of operations / replaces ~ before / to prevent double-escaping"""
    result = escape_token("a~b/c")
    assert result == "a~0b~1c"
    assert "~0~1" not in result
    assert "~1~0" not in result


def test_escape_tilde_then_slash():
    """escapeToken / order of operations / handles ~ followed by / correctly"""
    assert escape_token("a~/b") == "a~0~1b"


def test_escape_slash_then_tilde():
    """escapeToken / order of operations / handles / followed by ~ correctly"""
    assert escape_token("a/~b") == "a~1~0b"


def test_escape_consecutive():
    """escapeToken / order of operations / handles consecutive special characters"""
    assert escape_token("~~") == "~0~0"
    assert escape_token("//") == "~1~1"
    assert escape_token("~/") == "~0~1"
    assert escape_token("/~") == "~1~0"


def test_escape_empty():
    """escapeToken / edge cases / returns empty string unchanged"""
    assert escape_token("") == ""


def test_escape_unchanged():
    """escapeToken / edge cases / returns input unchanged when no special characters"""
    assert escape_token("abc") == "abc"
    assert escape_token("hello world") == "hello world"
    assert escape_token("123") == "123"


def test_escape_only_tildes():
    """escapeToken / edge cases / handles strings with only tildes"""
    assert escape_token("~~~") == "~0~0~0"
    assert escape_token("a~b~c") == "a~0b~0c"


def test_escape_only_slashes():
    """escapeToken / edge cases / handles strings with only slashes"""
    assert escape_token("///") == "~1~1~1"
    assert escape_token("a/b/c") == "a~1b~1c"


def test_escape_multiple_occurrences():
    """escapeToken / edge cases / handles multiple occurrences of same character"""
    assert escape_token("a~b~c~d") == "a~0b~0c~0d"
    assert escape_token("a/b/c/d") == "a~1b~1c~1d"


def test_escape_confusable_sequences():
    """escapeToken / edge cases / handles special sequences that could be confused"""
    assert escape_token("~01") == "~001"
    assert escape_token("~10") == "~010"
    assert escape_token("~00") == "~000"
    assert escape_token("~11") == "~011"


def test_escape_unicode():
    """escapeToken / unicode and other characters / passes through unicode characters unchanged"""
    for token in ("héllo", "世界", "🚀"):
        assert escape_token(token) == token


def test_escape_other_specials():
    """escapeToken / unicode and other characters / passes through other special characters unchanged"""  # noqa: E501
    for token in ("a.b", "a-b", "a_b", "a@b", "a#b", "a$b", "a%b", "a&b", "a*b", "a+b", "a=b"):
        assert escape_token(token) == token
    assert escape_token("a?b") == "a?b"
    assert escape_token("a!b") == "a!b"


def test_escape_mixed_unicode():
    """escapeToken / unicode and other characters / handles mixed unicode and special characters"""
    assert escape_token("héllo~world/test") == "héllo~0world~1test"
    assert escape_token("世界/🌍~key") == "世界~1🌍~0key"


def test_escape_does_not_mutate():
    """escapeToken / immutability / does not mutate input string"""
    original = "a~b/c"
    escape_token(original)
    assert original == "a~b/c"


def test_escape_returns_different_value():
    """escapeToken / immutability / returns a different token value when escaping changes the input"""  # noqa: E501
    assert escape_token("a~b") != "a~b"
    assert escape_token("a~b") == "a~0b"


def test_escape_rfc_examples():
    """escapeToken / RFC 6901 examples / handles examples from documentation"""
    assert escape_token("name/alias") == "name~1alias"
    assert escape_token("path/to~key") == "path~1to~0key"


def test_unescape_tilde():
    """unescapeToken / basic unescaping / unescapes ~0 to ~"""
    assert unescape_token("a~0b") == "a~b"
    assert unescape_token("~0") == "~"
    assert unescape_token("~0~0") == "~~"


def test_unescape_slash():
    """unescapeToken / basic unescaping / unescapes ~1 to /"""
    assert unescape_token("a~1b") == "a/b"
    assert unescape_token("~1") == "/"
    assert unescape_token("~1~1") == "//"


def test_unescape_both():
    """unescapeToken / basic unescaping / unescapes both ~0 and ~1 in same string"""
    assert unescape_token("a~0b~1c") == "a~b/c"
    assert unescape_token("path~1to~0key") == "path/to~key"
    assert unescape_token("~0a~1b~0c~1d~0") == "~a/b~c/d~"


def test_unescape_order():
    """unescapeToken / order of operations / replaces ~1 before ~0 to prevent incorrect decoding"""
    assert unescape_token("a~1b~0c") == "a/b~c"


def test_unescape_01():
    """unescapeToken / order of operations / handles ~01 sequence correctly (unescapes to ~1)"""
    assert unescape_token("~01") == "~1"


def test_unescape_10():
    """unescapeToken / order of operations / handles ~10 sequence correctly (unescapes to /0)"""
    assert unescape_token("~10") == "/0"


def test_unescape_00():
    """unescapeToken / order of operations / handles ~00 sequence correctly (unescapes to ~0)"""
    assert unescape_token("~00") == "~0"


def test_unescape_11():
    """unescapeToken / order of operations / handles ~11 sequence correctly (unescapes to /1)"""
    assert unescape_token("~11") == "/1"


def test_unescape_empty():
    """unescapeToken / edge cases / returns empty string unchanged"""
    assert unescape_token("") == ""


def test_unescape_unchanged():
    """unescapeToken / edge cases / returns input unchanged when no escaped sequences"""
    for token in ("abc", "hello world", "123"):
        assert unescape_token(token) == token


def test_unescape_only_0():
    """unescapeToken / edge cases / handles strings with only ~0 sequences"""
    assert unescape_token("~0~0~0") == "~~~"
    assert unescape_token("a~0b~0c") == "a~b~c"


def test_unescape_only_1():
    """unescapeToken / edge cases / handles strings with only ~1 sequences"""
    assert unescape_token("~1~1~1") == "///"
    assert unescape_token("a~1b~1c") == "a/b/c"


def test_unescape_multiple_occurrences():
    """unescapeToken / edge cases / handles multiple occurrences of same sequence"""
    assert unescape_token("a~0b~0c~0d") == "a~b~c~d"
    assert unescape_token("a~1b~1c~1d") == "a/b/c/d"


def test_unescape_boundaries():
    """unescapeToken / edge cases / decodes escaped sequences at token boundaries and suffixes"""
    assert unescape_token("~0") == "~"
    assert unescape_token("~1") == "/"
    assert unescape_token("a~0") == "a~"
    assert unescape_token("a~1") == "a/"


def test_unescape_unicode():
    """unescapeToken / unicode and other characters / passes through unicode characters unchanged"""
    for token in ("héllo", "世界", "🚀"):
        assert unescape_token(token) == token


def test_unescape_other_specials():
    """unescapeToken / unicode and other characters / passes through other special characters unchanged"""  # noqa: E501
    for token in ("a.b", "a-b", "a_b", "a@b"):
        assert unescape_token(token) == token


def test_unescape_mixed_unicode():
    """unescapeToken / unicode and other characters / handles mixed unicode and escaped sequences"""
    assert unescape_token("héllo~0world~1test") == "héllo~world/test"
    assert unescape_token("世界~1🌍~0key") == "世界/🌍~key"


def test_unescape_does_not_mutate():
    """unescapeToken / immutability / does not mutate input string"""
    original = "a~0b~1c"
    unescape_token(original)
    assert original == "a~0b~1c"


def test_unescape_returns_different_value():
    """unescapeToken / immutability / returns a different token value when unescaping changes the input"""  # noqa: E501
    assert unescape_token("a~0b") != "a~0b"
    assert unescape_token("a~0b") == "a~b"


def test_unescape_rfc_examples():
    """unescapeToken / RFC 6901 examples / handles examples from documentation"""
    assert unescape_token("name~1alias") == "name/alias"
    assert unescape_token("path~1to~0key") == "path/to~key"


def test_parse_root():
    """parseUriFragment / parses the document root"""
    assert parse_uri_fragment("") == []
    assert parse_uri_fragment("#") == []


def test_parse_percent_encoding():
    """parseUriFragment / decodes percent-encoding before splitting tokens"""
    assert parse_uri_fragment("#/definitions/a%20b") == ["definitions", "a b"]
    assert parse_uri_fragment("#%2Fdefinitions%2FValue") == ["definitions", "Value"]
    assert parse_uri_fragment("#/definitions/a%25b") == ["definitions", "a%b"]
    assert parse_uri_fragment("#/definitions/caf%C3%A9") == ["definitions", "café"]


def test_parse_encoded_separators():
    """parseUriFragment / distinguishes encoded separators from escaped slashes"""
    assert parse_uri_fragment("#/$defs/Box%2Fproperties%2Fvalue") == [
        "$defs",
        "Box",
        "properties",
        "value",
    ]
    assert parse_uri_fragment("#/$defs/Box~1properties~1value") == ["$defs", "Box/properties/value"]
    assert parse_uri_fragment("#/$defs/Box%7E1properties%7E1value") == [
        "$defs",
        "Box/properties/value",
    ]


@pytest.mark.parametrize(
    "fragment",
    ["/a", "#/%", "#/%FF", "#/a b", "#/a#b", "#/a\\b", "#/café", "#/\ud800", "#/a~2b", "#/a~"],
)
def test_parse_rejects_invalid(fragment: str):
    """parseUriFragment / rejects invalid fragments"""
    assert parse_uri_fragment(fragment) is None


def test_format_root():
    """formatUriFragment / formats the document root"""
    assert format_uri_fragment([]) == "#"


def test_format_escapes_then_encodes():
    """formatUriFragment / applies JSON Pointer escaping before URI percent-encoding"""
    assert (
        format_uri_fragment(["$defs", "a b", "a%b", "a/b", "café", "a#b"])
        == "#/$defs/a%20b/a%25b/a~1b/caf%C3%A9/a%23b"
    )


def test_format_round_trips():
    """formatUriFragment / round trips path tokens"""
    paths = [
        [],
        [""],
        ["$defs", "Rate%"],
        ["a/b", "c~d"],
        ["!$&'()*+,;=:@?"],
        ["café", "世界", "🚀"],
    ]
    for path in paths:
        assert parse_uri_fragment(format_uri_fragment(path)) == path


def test_format_unpaired_surrogate():
    """formatUriFragment / throws for unpaired surrogates"""
    with pytest.raises(ValueError, match="URI malformed"):
        format_uri_fragment(["\ud800"])


def _round_trips(tokens: list[str]) -> None:
    for token in tokens:
        assert unescape_token(escape_token(token)) == token, token


def test_round_trip_basic():
    """round-trip / unescapeToken(escapeToken(token)) === token for basic cases"""
    _round_trips(["abc", "a~b", "a/b", "a~b/c", "path/to~key", "name/alias"])
    _round_trips(["~", "/", "~~", "//", "~/", "/~"])


def test_round_trip_edge_cases():
    """round-trip / unescapeToken(escapeToken(token)) === token for edge cases"""
    _round_trips(["", "~01", "~10", "~00", "~11", "a~01b", "a~10b", "a~00b", "a~11b"])


def test_round_trip_unicode():
    """round-trip / unescapeToken(escapeToken(token)) === token for unicode"""
    _round_trips(["héllo", "世界", "🚀", "héllo~world/test", "世界/🌍~key"])


def test_round_trip_complex():
    """round-trip / unescapeToken(escapeToken(token)) === token for complex sequences"""
    _round_trips(["a~b/c~d/e", "path/to~key/value", "~a/b~c/d~", "a~/b/c~d", "a/~b/c~d"])


def test_round_trip_multiple():
    """round-trip / handles multiple round-trips"""
    current = "a~b/c~d"
    for _ in range(5):
        current = unescape_token(escape_token(current))
        assert current == "a~b/c~d"
