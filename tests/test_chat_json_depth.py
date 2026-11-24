"""``chat._json_depth``: the nesting depth the chat adapters check before a
parse, counted in C, gives what the character-by-character count it replaced
gave, on random text and on text built to trip it."""

from __future__ import annotations

import random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pyfect.chat._json_depth import nesting_depth, within_depth


def walked_depth(text: str) -> int:
    """The count the Discord adapter made before, one character at a time."""
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
        elif char in "[{":
            depth += 1
            deepest = max(depth, deepest)
        elif char in "]}":
            depth -= 1
    return deepest


def depth(text: str) -> int:
    return nesting_depth(text.encode("utf-8", "surrogatepass"))


@settings(max_examples=400, deadline=None)
@given(st.text(alphabet='[]{}"\\ a,:\né€\U0001f600\ud800', max_size=80))
def test_random_text_gets_the_depth_the_walk_gave(text: str) -> None:
    assert depth(text) == walked_depth(text)


@settings(max_examples=200, deadline=None)
@given(st.text(max_size=40))
def test_any_text_gets_the_depth_the_walk_gave(text: str) -> None:
    assert depth(text) == walked_depth(text)


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
    assert depth(text) == walked_depth(text)


def test_every_length_around_a_packed_byte_gets_the_depth_the_walk_gave() -> None:
    picks = random.Random(629)
    for length in range(1, 40):
        for _ in range(20):
            text = "".join(picks.choice("[]{}") for _ in range(length))
            assert depth(text) == walked_depth(text), text


@settings(max_examples=300, deadline=None)
@given(st.text(alphabet='[]{}"\\ a', max_size=40), st.integers(min_value=0, max_value=12))
def test_within_depth_is_the_walked_depth_against_the_limit(text: str, limit: int) -> None:
    assert within_depth(text.encode(), limit) == (walked_depth(text) <= limit)


def test_within_depth_compares_with_the_limit() -> None:
    assert within_depth(b"[" * 64, 64)
    assert not within_depth(b"[" * 65, 64)
    assert within_depth(b'"\\"' * 200_000, 64)
    assert not within_depth(b"[" * 200_000, 64)
