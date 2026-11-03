"""``pyfect._effect_hash`` gives Effect's ``Hash.hash`` (``>>> 0``), values
printed by Effect under Node."""

from __future__ import annotations

import math

import pytest

from pyfect._effect_hash import effect_hash
from pyfect._equal import equal_key
from pyfect.hash_map import HashMap
from pyfect.option import Some

_CASES: list[tuple[object, int]] = [
    (2**60, 3765300770),
    (1.5, 4112544204),
    ("héllo😀", 997057334),
    ([1, "a", True, None], 3225020710),
    ({"a": 1, "b": [2]}, 473189249),
    ({1: 2, "x": 3}, 464445210),
    ({1, 2}, 3735868283),
    (-0.0, 0),
    (math.nan, 389652371),
    (math.inf, 3930186649),
    (2**70 + 1, 43723170),  # a BigInt
    (2**1024 - 1, 369180345),  # a BigInt no float holds
]


@pytest.mark.parametrize(("value", "expected"), _CASES)
def test_hash_is_effects(value: object, expected: int) -> None:
    assert effect_hash(equal_key(value)) == expected


def test_an_int_past_the_float_range_is_a_key() -> None:
    m = HashMap[int, str].empty().set(2**1024 - 1, "a").set(2**1100, "b")
    assert m.get(2**1024 - 1) == Some("a")
    assert m.get(2**1100) == Some("b")
