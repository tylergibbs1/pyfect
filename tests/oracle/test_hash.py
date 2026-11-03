"""Ports of Effect's ``Hash.test.ts``.

Effect's ``Hash`` is Python's ``hash`` (docs/PARITY.md section 4). Where
pyfect keys values the way Effect's ``Equal`` does, the hash is that of
``pyfect._equal.equal_key`` (lists and dicts hash by their items, every NaN
alike, ``True`` apart from ``1``), which these ports exercise as ``h``. A
record is a ``dict``, an array a ``list``, a native ``Set`` a ``frozenset``.

Omitted, with the reason:

- the HashMap, HashSet, Trie, Chunk and Graph collision titles, "does not
  give distinct HashSets one constant hash", "hashes a HashMap like a fresh
  build after persistent and in-place edits", "invalidates CollisionNode
  hashes after in-place edits" and "does not cache a HashMap subtree hash
  computed from a circular sentinel": those collections are Python's
  ``dict``, ``frozenset`` and ``tuple`` (section 4), whose hashes CPython
  computes from scratch.
- "does not collide for ArrayBuffers with different bytes": ``bytes`` hash
  by Python's own ``hash``.
- "does not cache a hash computed from a circular sentinel": a value holding
  itself has no key (``equal_key`` raises ``TypeError``; ``equals`` compares
  it part by part, ``test_equal.py``).
"""

import itertools
import math
import struct

import pytest

from pyfect._equal import equal_key


def h(value: object) -> int:
    return hash(equal_key(value))


def assert_no_hash_collisions(values: list[object]) -> None:
    assert len({h(v) for v in values}) == len(values)


def grid(size: int) -> list[tuple[int, int]]:
    return list(itertools.product(range(size), range(size)))


def test_does_not_collide_for_a_100_by_100_grid_of_arrays() -> None:
    """does not collide for a 100 by 100 grid of arrays"""
    assert_no_hash_collisions([[i, j] for i, j in grid(100)])


def test_does_not_collide_for_a_100_by_100_grid_of_records() -> None:
    """does not collide for a 100 by 100 grid of records"""
    assert_no_hash_collisions([{"i": i, "j": j} for i, j in grid(100)])


def test_does_not_collide_for_a_100_by_100_grid_of_combined_hashes() -> None:
    """does not collide for a 100 by 100 grid of combined hashes"""
    assert_no_hash_collisions([hash((h(i), h(j))) for i, j in grid(100)])


def test_does_not_collide_for_native_sets_of_pairs_below_150() -> None:
    """does not collide for native Sets of pairs below 150"""
    assert_no_hash_collisions([frozenset([i, j]) for i, j in itertools.combinations(range(150), 2)])


def test_does_not_collide_for_every_permutation_of_seven_integers() -> None:
    """does not collide for every permutation of seven integers"""
    assert_no_hash_collisions([list(p) for p in itertools.permutations(range(7))])


def test_does_not_collide_for_nested_arrays_and_records() -> None:
    """does not collide for nested arrays and records"""
    values: list[object] = [
        {"a": [i, j], "b": {"c": k}} for i, j, k in itertools.product(range(10), repeat=3)
    ]
    assert_no_hash_collisions(values)


def test_keeps_array_order_and_length_in_the_hash() -> None:
    """keeps array order and length in the hash"""
    assert h([1, 2]) != h([2, 1])
    assert h([1, 2, 3]) != h([])


@pytest.mark.parametrize("value", [None, True, False])
def test_does_not_hash_null_undefined_booleans_and_symbols_like_their_names(
    value: object,
) -> None:
    """does not hash null, undefined, booleans and symbols like their names"""
    assert h(value) != h(str(value))


@pytest.mark.parametrize("step", [0.1, 0.001])
def test_does_not_collide_for_10k_multiples(step: float) -> None:
    """does not collide for 10k multiples of 0.1; does not collide for 10k multiples of 0.001"""
    assert_no_hash_collisions([i * step for i in range(10_000)])


def test_hashes_0_and_minus_0_the_same() -> None:
    """hashes 0 and -0 the same"""
    assert h(0) == h(-0.0)
    assert h(0.0) == h(-0.0)


def test_hashes_every_nan_the_same() -> None:
    """hashes every NaN the same"""
    quiet_payload = struct.unpack("<d", struct.pack("<II", 1, 0x7FF80000))[0]
    signaling_negative = struct.unpack("<d", struct.pack("<II", 0, 0xFFF00001))[0]
    assert math.isnan(quiet_payload)
    assert math.isnan(signaling_negative)
    assert h(math.nan) == h(float("nan"))
    assert h(math.nan) == h(quiet_payload)
    assert h(math.nan) == h(signaling_negative)
    assert h(math.inf) != h(-math.inf)


def test_hashes_hash_maps_and_hash_sets_independently_of_insertion_order() -> None:
    """hashes HashMaps and HashSets independently of insertion order"""
    seed = 1

    def random(n: int) -> int:
        nonlocal seed
        seed = (seed * 1103515245 + 12345) & 0xFFFFFFFF
        return (seed >> 16) % n

    def shuffle[A](values: list[A]) -> list[A]:
        out = list(values)
        for i in range(len(out) - 1, 0, -1):
            j = random(i + 1)
            out[i], out[j] = out[j], out[i]
        return out

    for _ in range(200):
        keys = list(dict.fromkeys(random(1000) for _ in range(1 + random(80))))
        entries = [(key, random(3)) for key in keys]
        assert h(dict(entries)) == h(dict(shuffle(entries)))
        assert h(frozenset(keys)) == h(frozenset(shuffle(keys)))


def test_clears_visited_state_when_a_custom_hasher_throws() -> None:
    """clears visited state when a custom hasher throws"""

    class Boom:
        def __hash__(self) -> int:
            raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        h([Boom()])
    with pytest.raises(ValueError, match="boom"):
        h([Boom()])
