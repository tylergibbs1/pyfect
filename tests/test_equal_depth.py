"""``equals`` goes as deep as its values, as Effect's ``Equal.equals`` does
under JavaScript's stack: a deep value holding an unhashable object, and a
cycle longer than one thread's stack, compare without ``RecursionError``
and in time linear in their size."""

from __future__ import annotations

import time
from typing import Any

from pyfect._equal import equals

DEPTH = 5000


def nested(depth: int, leaf: object) -> list[Any]:
    value: list[Any] = [leaf]
    for _ in range(depth):
        value = [value, 0]
    return value


def ring(size: int, last: int = 0) -> list[Any]:
    nodes: list[list[Any]] = [[0, None] for _ in range(size)]
    nodes[-1][0] = last
    for i, n in enumerate(nodes):
        n[1] = nodes[(i + 1) % size]
    return nodes[0]


def test_deep_values_holding_an_unhashable_object_compare() -> None:
    assert equals(nested(DEPTH, bytearray(b"a")), nested(DEPTH, bytearray(b"a")))
    assert not equals(nested(DEPTH, bytearray(b"a")), nested(DEPTH, bytearray(b"b")))


def test_long_cycles_compare_by_bisimilarity() -> None:
    assert equals(ring(DEPTH), ring(DEPTH))
    assert not equals(ring(DEPTH), ring(DEPTH, last=1))


def test_deep_comparison_is_linear() -> None:
    def seconds(depth: int) -> float:
        a, b = nested(depth, bytearray(b"a")), nested(depth, bytearray(b"a"))
        runs: list[float] = []
        for _ in range(3):
            start = time.perf_counter()
            assert equals(a, b)
            runs.append(time.perf_counter() - start)
        return sorted(runs)[1]

    # Four times as deep: about four times as long (keying each level again
    # took sixteen times as long).
    assert seconds(8000) < 10 * seconds(2000)
