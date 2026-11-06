"""``S.is_ecma_pattern`` and ``S.compile_ecma``: JSON Schema's ``pattern`` is an ECMAScript
regular expression in Unicode mode. ``TABLE`` is what ``new RegExp(pattern, "u").test(input)``
gives under Node (``None`` for a ``SyntaxError``)."""

from typing import Any

import pytest

from pyfect import schema as S
from pyfect.schema import representation as R

TABLE: list[tuple[str, str, bool | None]] = [
    ("^a$", "a", True),
    ("^a$", "a\n", False),
    ("a.b", "a\nb", False),
    ("a.b", "a\u2028b", False),
    ("a.b", "axb", True),
    ("\\d+", "\u0663", False),
    ("\\d+", "3", True),
    ("\\w", "\xe9", False),
    ("\\s", "\xa0", True),
    ("\\s", "\ufeff", True),
    ("\\S", "\xa0", False),
    ("\\u{1F600}", "\U0001f600", True),
    ("\\u0041", "A", True),
    ("\\x41", "A", True),
    ("(?<y>a)\\k<y>", "aa", True),
    ("(a)\\1", "aa", True),
    ("(?=a)a", "a", True),
    ("(?<=a)b", "ab", True),
    ("[^]", "\n", True),
    ("[]", "a", False),
    ("^[\\d-x]", "-", None),
    ("a{2", "a{2", None),
    ("a{,2}", "a", None),
    ("]", "]", None),
    ("{", "{", None),
    ("\\-", "-", None),
    ("\\/", "/", True),
    ("\\e", "e", None),
    ("(?i)a", "A", None),
    ("\\cA", "\x01", True),
    ("\\0", "\x00", True),
    ("[\\b]", "\x08", True),
    ("\\bfoo\\b", "a foo b", True),
    ("^.$", "\U0001f600", True),
    ("(?:a|b)+?", "ab", True),
    ("a{2,1}", "aa", None),
    ("*", "a", None),
    ("\\v", "\x0b", True),
    ("\\f", "\x0c", True),
    ("$^", "", True),
    ("x$", "x\n", False),
    ("^x", "\nx", False),
    ("\\Z", "Z", None),
    ("\\A", "A", None),
    ("(?P<n>a)", "a", None),
    ("[a-\\d]", "a", None),
    ("\\u{110000}", "a", None),
    ("(a)?\\1b", "b", True),
    ("(a)|\\1b", "b", True),
    ("(?<n>a)?\\k<n>b", "b", True),
    ("^(a)?\\1b$", "ab", False),
    ("(?=a)*", "a", None),
    ("(?!a){2}", "a", None),
    ("(?<=a)+", "a", None),
    ("(?<!a)?", "a", None),
    ("[\\0-\\s]", "a", None),
    ("[\\s-a]", "a", None),
    ("[a-\\S]", "a", None),
    ("[\\w-]", "-", True),
    ("[!--]", "#", True),
    ("(?<$m>a)\\k<$m>", "aa", True),
    ("\\100", "@", None),
    ("(a)\\10", "a", None),
]


@pytest.mark.parametrize(("pattern", "value", "expected"), TABLE)
def test_matches_as_node_does(pattern: str, value: str, expected: bool | None) -> None:
    if expected is None:
        with pytest.raises(S.EcmaPatternError):
            S.compile_ecma(pattern)
    else:
        assert (S.compile_ecma(pattern).search(value) is not None) is expected


@pytest.mark.parametrize(
    "pattern",
    [
        "\\2(a)(b)",
        "\\k<n>(?<n>a)",
        "(a\\1)",
        "(?<a>x)|(?<a>y)",
        "(?:(a)|b)+\\1",
        "(?:(?<n>a)|b){2}\\k<n>",
    ],
)
def test_what_python_cannot_match_alike_is_refused(pattern: str) -> None:
    """Node accepts these. ``re`` cannot refer to a group opened later or still open and
    takes a group name once. In the last two, each
    turn of a loop clears a group in JavaScript, and keeps its last value in ``re``."""
    with pytest.raises(S.EcmaPatternError):
        S.compile_ecma(pattern)


def test_the_check_is_the_payload_a_document_revives() -> None:
    schema: Any = S.String.check(S.is_ecma_pattern("^a$"))
    document = R.to_representation(schema)
    revived: Any = R.from_representation(document, revivers=R.BUILTIN_REVIVERS)
    assert S.is_(revived)("a")
    assert not S.is_(revived)("a\n")


def test_the_check_exports_its_source_as_json_schema_pattern() -> None:
    schema: Any = S.String.check(S.is_ecma_pattern("^a$"))
    assert S.to_json_schema_document(schema).schema["pattern"] == "^a$"


def test_arbitrary_values_match_the_check() -> None:
    pytest.importorskip("hypothesis")
    from hypothesis import find, given

    schema: Any = S.String.check(S.is_ecma_pattern("^[a-c]{2}$"))
    strategy = S.to_strategy(schema)
    assert find(strategy, lambda value: value != "") != ""

    @given(strategy)
    def check(value: str) -> None:
        assert S.is_(schema)(value)

    check()


def test_a_group_name_may_be_any_identifier_and_nothing_else() -> None:
    assert S.compile_ecma("(?<é>a)\\k<é>").search("aa") is not None
    for pattern in ("(?<1a>a)", "(?<>a)", "(?<a", "(?<a>a)\\k<b", "(?<a>a)\\k"):
        with pytest.raises(S.EcmaPatternError):
            S.compile_ecma(pattern)


@pytest.mark.parametrize(
    ("pattern", "value", "expected"),
    [
        ("^\\p{L}$", "é", True),
        ("^\\p{L}$", "1", False),
        ("^\\P{L}$", "1", True),
        ("^\\p{Lu}+$", "àB", False),
        ("^\\p{Script=Greek}+$", "αβ", True),
        ("^\\p{gc=Nd}$", "٣", True),
        ("^[\\p{L}\\d]+$", "é1", True),
        ("^\\p{Emoji}$", "😀", True),
        ("\\p{L}\\bé", "aé", True),
        ("^[\\W]+$", "é", True),
        ("(?<=a+)b", "aab", True),
        ("(?<=a+)b", "cb", False),
        ("(?<=x|yy)z", "yyz", True),
        ("(?<!a+)b", "ab", False),
    ],
)
def test_properties_and_variable_lookbehind_run_on_the_regex_extra(
    pattern: str, value: str, expected: bool
) -> None:
    """Node 24: ``new RegExp(pattern, "u").test(value)``."""
    assert (S.compile_ecma(pattern).search(value) is not None) is expected


@pytest.mark.parametrize(
    "pattern", ["\\p{l}", "\\p{Foo}", "\\p{Script=Nope}", "\\p", "\\p{}", "\\p{Script=latin}"]
)
def test_property_names_node_rejects_are_rejected(pattern: str) -> None:
    with pytest.raises(S.EcmaPatternError):
        S.compile_ecma(pattern)
