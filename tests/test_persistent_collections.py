"""``HashMap``, ``HashSet`` and ``Trie`` are persistent, as Effect's (a HAMT
and a ternary search tree): an update costs about the logarithm of the size
and shares the rest, where copying every entry made a map built one ``set``
at a time quadratic (collections review)."""

from __future__ import annotations

import random
import time
from collections.abc import Callable

from pyfect._js import js_sort_key
from pyfect.hash_map import HashMap
from pyfect.hash_set import HashSet
from pyfect.option import Some
from pyfect.trie import Trie


def _seconds(build: Callable[[int], object], n: int) -> float:
    runs: list[float] = []
    for _ in range(3):
        start = time.perf_counter()
        build(n)
        runs.append(time.perf_counter() - start)
    # Load only ever adds time, so the fastest run is the one to compare.
    return min(runs)


def _grows_linearly(build: Callable[[int], object]) -> None:
    # Four times the entries: about four times as long (copying took sixteen).
    assert _seconds(build, 16000) < 9 * _seconds(build, 4000)


def _hash_map(n: int) -> HashMap[int, int]:
    m = HashMap[int, int].empty()
    for i in range(n):
        m = m.set(i, i)
    return m


def _hash_set(n: int) -> HashSet[int]:
    s = HashSet[int].empty()
    for i in range(n):
        s = s.add(i)
    return s


def _trie(n: int) -> Trie[int]:
    t = Trie[int].empty()
    for i in range(n):
        t = t.insert(f"k{i * 7919 % n}", i)
    return t


def test_building_a_hash_map_one_set_at_a_time_is_linear() -> None:
    _grows_linearly(_hash_map)


def test_building_a_hash_set_one_add_at_a_time_is_linear() -> None:
    _grows_linearly(_hash_set)


def test_building_a_trie_one_insert_at_a_time_is_linear() -> None:
    _grows_linearly(_trie)


def test_updates_leave_every_earlier_version_as_it_was() -> None:
    versions = [HashMap[int, int].empty()]
    sets = [HashSet[int].empty()]
    tries = [Trie[int].empty()]
    for i in range(300):
        versions.append(versions[-1].set(i % 150, i))
        sets.append(sets[-1].add(i % 150).remove((i * 7) % 150))
        tries.append(tries[-1].insert(f"k{i % 150}", i).remove(f"k{(i * 7) % 150}"))
    expected: dict[int, int] = {}
    members: set[int] = set()
    entries: dict[str, int] = {}
    for i, (m, s, t) in enumerate(zip(versions, sets, tries, strict=True)):
        assert dict(m.entries()) == expected
        assert set(s) == members
        assert dict(t.entries()) == entries
        assert list(t.keys()) == sorted(entries)
        expected[i % 150] = i
        members.add(i % 150)
        members.discard((i * 7) % 150)
        entries[f"k{i % 150}"] = i
        entries.pop(f"k{(i * 7) % 150}", None)


class _Clash:
    """Equal by ``n``; every one hashes to one of two values, so the HAMT
    holds collision nodes at its deepest level and merges at the top."""

    __slots__ = ("n",)

    def __init__(self, n: int) -> None:
        self.n = n

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Clash) and other.n == self.n

    def __hash__(self) -> int:
        return self.n % 2

    def __repr__(self) -> str:
        return f"_Clash({self.n})"


def test_random_updates_match_a_dict() -> None:
    rng = random.Random(1)
    for keys in (
        [_Clash(i) for i in range(40)],
        list(range(300)),
        [i << 55 for i in range(40)],  # hashes alike in the low 55 bits: deep nodes
        [f"{a}{b}" for a in "ab\U00010000" for b in ("", "x", "", "ab")],
    ):
        m = HashMap[object, int].empty()
        s = HashSet[object].empty()
        model: dict[object, int] = {}
        for step in range(3000):
            key = rng.choice(keys)
            if rng.random() < 0.6:
                m, s = m.set(key, step), s.add(key)
                model[key] = step
            else:
                m, s = m.remove(key), s.remove(key)
                model.pop(key, None)
            assert len(m) == len(s) == len(model)
            assert m.get(key) == (Some(model[key]) if key in model else None)
        assert dict(m.entries()) == model
        assert set(s) == set(model)
        assert m == HashMap.from_iterable(model.items())
        assert s == HashSet.from_iterable(model)


def test_random_trie_updates_match_a_dict() -> None:
    rng = random.Random(2)
    alphabet = ["a", "b", "", "\U00010000"]
    t = Trie[int].empty()
    model: dict[str, int] = {}
    for step in range(4000):
        key = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 5)))
        if rng.random() < 0.6:
            t = t.insert(key, step)
            model[key] = step  # Effect 4.1.2 stores "" like any other key
        else:
            t = t.remove(key)
            model.pop(key, None)
        assert len(t) == len(model)
    order = sorted(model, key=js_sort_key)
    assert list(t.keys()) == order
    for prefix in ["", "a", "ab", "\U00010000", "a"]:
        assert list(t.keys_with_prefix(prefix)) == [k for k in order if k.startswith(prefix)]
    for key in ["", "abab\U00010000", "x"]:
        best = max((k for k in model if key.startswith(k)), key=len, default=None)
        assert t.longest_prefix_of(key) == (None if best is None else Some((best, model[best])))


def test_removing_a_sibling_keeps_a_deeper_node_at_its_depth() -> None:
    # 0 and 1024 differ first in hash bits 10-14, 32 in bits 5-9: removing 32
    # leaves the node splitting 0 from 1024 below a node of one child.
    m = HashMap.make((0, "a"), (1024, "b"), (32, "c")).remove(32)
    assert m.get(1024) == Some("b")
    assert m.get(0) == Some("a")
    s = HashSet.make(0, 1024, 32).remove(32)
    assert 1024 in s
    assert 0 in s
