"""Brand failure messages beyond Effect's tests, printed by Effect's
``Brand`` under Node: which text a failing filter reports."""

from typing import NewType

import pytest

from pyfect import schema as S
from pyfect.brand import Brand, BrandError
from pyfect.schema import Filter

Positive = NewType("Positive", int)


def message(f: Filter[int]) -> str:
    with pytest.raises(BrandError) as raised:
        Brand[int, Positive].check(f)(-1)
    return raised.value.message


FILTERS: list[tuple[Filter[int], str]] = [
    (S.make_filter(lambda n: n > 0), "Expected <filter>"),
    (S.make_filter(lambda n: n > 0 or "neg"), "neg"),
    (S.make_filter(lambda n: None if n > 0 else "neg"), "neg"),
    (S.make_filter(lambda n: n > 0, expected="a positive number"), "Expected a positive number"),
    (S.make_filter(lambda n: n > 0, message="custom"), "custom"),
    (S.make_filter(lambda n: n > 0 or "str", expected="a positive", message="custom"), "custom"),
    (S.make_filter(lambda n: n > 0 or "str", expected="a positive"), "str"),
    (S.make_filter(lambda n: n > 0, expected=""), "Expected "),
    (S.make_filter(lambda n: n > 0 or ""), ""),
]


@pytest.mark.parametrize(
    ("f", "expected"),
    FILTERS,
    ids=[
        "false",
        "string",
        "none-passes",
        "expected",
        "message",
        "message-wins",
        "string-wins",
        "empty-expected",
        "empty-string",
    ],
)
def test_the_failure_text_follows_effects_rules(f: Filter[int], expected: str):
    assert message(f) == expected


def test_a_brand_error_is_a_value_error():
    with pytest.raises(ValueError, match=r"^Expected <filter>$"):
        Brand[int, Positive].make(lambda n: n > 0)(0)


def test_all_of_nominal_constructors_checks_nothing():
    to_positive = Brand[int, Positive].all(Brand[int, Positive].nominal(), Brand[int, Positive]())
    assert to_positive(-1) == -1
    assert to_positive.checks == ()


def test_a_branded_value_is_the_value_itself():
    value = 2
    assert Brand[int, Positive].make(lambda n: n > 0)(value) is value
