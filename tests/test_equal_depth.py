"""``equals`` goes as deep as its values, as Effect's ``Equal.equals`` does
under JavaScript's stack: a deep value holding an unhashable object, and a
cycle longer than one thread's stack, compare without ``RecursionError``
and in time linear in their size."""

from __future__ import annotations

from collections.abc import Iterator
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


class _Counted(list[Any]):
    """A list that counts how often it is walked, in ``walks[0]``: a count
    of the work, which, unlike a time, no machine's speed changes."""

    __slots__ = ("walks",)

    def __init__(self, items: list[Any], walks: list[int]) -> None:
        super().__init__(items)
        self.walks = walks

    def __iter__(self) -> Iterator[Any]:
        self.walks[0] += 1
        return super().__iter__()


def _walks(depth: int) -> int:
    walks = [0]

    def counted(depth: int) -> _Counted:
        value = _Counted([bytearray(b"a")], walks)
        for _ in range(depth):
            value = _Counted([value, 0], walks)
        return value

    assert equals(counted(depth), counted(depth))
    return walks[0]


def test_deep_comparison_is_linear() -> None:
    # Four times as deep: about four times the walks (keying each level
    # again walked sixteen times as much).
    assert _walks(8000) <= 5 * _walks(2000)
