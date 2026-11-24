"""``_json_depth``: the nesting depth ``_json_text.parse`` checks before a
parse, counted in C, gives what a character-by-character count gives, on JSON,
on random text and on text built to trip it. A backslash outside a string is
not JSON, and such text only has to get some number: the parse refuses it."""

from __future__ import annotations

import json
import random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pyfect._json_depth import nesting_depth, within_depth


def walked_depth(text: str) -> int | None:
    """The depth counted one character at a time, or ``None`` for text with a
    backslash outside a string."""
    depth = deepest = 0
    in_string = escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "\\":
            return None
        elif char in "[{":
            depth += 1
            deepest = max(depth, deepest)
        elif char in "]}":
            depth -= 1
    return deepest


def depth(text: str) -> int:
    return nesting_depth(text.encode("utf-8", "surrogatepass"))


def assert_counted(text: str) -> None:
    walked = walked_depth(text)
    counted = depth(text)
    assert counted == walked if walked is not None else isinstance(counted, int), text


_STRING_PARTS = st.text(alphabet='[]{}"\\ a\n€\U0001f600', max_size=12)
_JSON = st.recursive(
    st.none() | st.integers() | _STRING_PARTS,
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(_STRING_PARTS, inner, max_size=4),
    max_leaves=30,
)


@settings(max_examples=400, deadline=None)
@given(_JSON, st.booleans())
def test_json_gets_the_depth_the_walk_gave(value: object, ascii: bool) -> None:
    text = json.dumps(value, ensure_ascii=ascii)
    assert walked_depth(text) is not None
    assert depth(text) == walked_depth(text)


@settings(max_examples=400, deadline=None)
@given(st.text(alphabet='[]{}"\\ a,:\né€\U0001f600\ud800', max_size=80))
def test_random_text_gets_the_depth_the_walk_gave(text: str) -> None:
    assert_counted(text)


@settings(max_examples=200, deadline=None)
@given(st.text(max_size=40))
def test_any_text_gets_the_depth_the_walk_gave(text: str) -> None:
    assert_counted(text)


ADVERSARIAL = [
    "",
    "[" * 1000,
    "]" * 1000 + "[" * 7,
    "[" * 65 + "]" * 65,
    "[]" * 500,
    "]]][[[" * 300,
    '"' + "[" * 100,  # an unterminated string hides everything after it
    '"[\\',  # ... a last lone backslash too
    '"\\"[[[',
    '"\\\\"[[[',
    '"\\' + "[" * 9,
    '"\\"' * 5000,
    '{"a": "[[[{{{", "b": [1, {"c": "\\"]]"}]}',
    "[" * 64 + '"]' + "]" * 64 + '"' + "[",
    "[€" * 100 + "]" * 50,
    "{" * 7 + "[" * 9 + "}" * 3,
]


@pytest.mark.parametrize("text", ADVERSARIAL, ids=range(len(ADVERSARIAL)))
def test_text_built_to_trip_the_count_gets_the_depth_the_walk_gave(text: str) -> None:
    assert_counted(text)


def test_every_length_around_a_packed_byte_gets_the_depth_the_walk_gave() -> None:
    picks = random.Random(629)
    for length in range(1, 40):
        for _ in range(20):
            text = "".join(picks.choice("[]{}") for _ in range(length))
            assert_counted(text)


@settings(max_examples=300, deadline=None)
@given(st.text(alphabet='[]{}"\\ a', max_size=40), st.integers(min_value=0, max_value=12))
def test_within_depth_is_the_walked_depth_against_the_limit(text: str, limit: int) -> None:
    walked = walked_depth(text)
    if walked is not None:
        assert within_depth(text, limit) == (walked <= limit)


def test_within_depth_compares_with_the_limit() -> None:
    assert within_depth("[" * 64, 64)
    assert not within_depth("[" * 65, 64)
    assert within_depth('"\\"' * 200_000, 64)
    assert not within_depth("[" * 200_000, 64)
    assert not within_depth("[\ud800" * 65, 64)
