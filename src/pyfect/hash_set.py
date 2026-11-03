"""``HashSet[A]``: an immutable set whose members compare as Effect's
``Equal.equals`` does (Effect's ``HashSet``).

A ``frozenset`` calls ``1`` and ``True`` one member and cannot hold a list;
a ``HashSet`` keys members by ``pyfect._equal.equal_key``: ``True`` stays
apart from ``1``, NaN is one member, and lists, tuples, dicts and sets are
members by their items. Updates return a new set, or the same set when
nothing changes; like Effect's, it is a persistent hash array mapped trie
(``pyfect._hamt``), so an update costs about ``log32(size)``. Iteration
follows Effect's hashes (``pyfect._effect_hash``), in Effect's order.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Iterator
from typing import Any, TypeIs, cast, overload

from pyfect import _hamt
from pyfect._equal import equal_key
from pyfect._hamt import Entry, Node


class HashSet[A]:
    """Build one with ``HashSet.empty()``, ``HashSet.make(*values)`` or
    ``HashSet.from_iterable(values)``."""

    __slots__ = ("_root", "_size")

    _root: Node | None
    _size: int

    def __init__(self, root: Node | None = None, size: int = 0) -> None:
        self._root = root
        self._size = size

    @classmethod
    def empty(cls) -> HashSet[A]:
        """Spelled ``HashSet[str].empty()``."""
        return HashSet()

    @staticmethod
    def make[B](*values: B) -> HashSet[B]:
        return HashSet.from_iterable(values)

    @staticmethod
    def from_iterable[B](values: Iterable[B]) -> HashSet[B]:
        """The set of ``values``; the first of equal values is kept."""
        return HashSet[B]()._added(values)

    def _entries(self) -> Iterator[Entry[A, None]]:
        return cast("Iterator[Entry[A, None]]", _hamt.entries(self._root))

    def _has_ident(self, ident: Hashable) -> bool:
        return _hamt.find(self._root, _hamt.hash_of(ident), ident) is not None

    def _added[B](self, values: Iterable[B]) -> HashSet[A | B]:
        root, size = self._root, self._size
        for value in values:
            ident = equal_key(value)
            hash = _hamt.hash_of(ident)
            if _hamt.find(root, hash, ident) is None:
                root = _hamt.insert(root, Entry(hash, ident, value, None))
                size += 1
        return cast("HashSet[A | B]", self) if root is self._root else HashSet(root, size)

    def __len__(self) -> int:
        return self._size

    def __bool__(self) -> bool:
        return self._size > 0

    def __iter__(self) -> Iterator[A]:
        return (e.key for e in self._entries())

    def __contains__(self, value: object) -> bool:
        return self.has(value)

    def is_empty(self) -> bool:
        return self._size == 0

    def has(self, value: object) -> bool:
        return self._has_ident(equal_key(value))

    def add(self, value: A) -> HashSet[A]:
        """The set with ``value``; the same set when it has it already."""
        return self._added((value,))

    def remove(self, value: A) -> HashSet[A]:
        """The set without ``value``; the same set when it lacks it."""
        ident = equal_key(value)
        root = _hamt.remove(self._root, _hamt.hash_of(ident), ident)
        return self if root is self._root else HashSet(root, self._size - 1)

    def union[B](self, that: HashSet[B]) -> HashSet[A | B]:
        return self._added(that)

    def _kept(self, keep: Callable[[Entry[A, None]], bool]) -> HashSet[A]:
        return HashSet[A]()._added(e.key for e in self._entries() if keep(e))

    def intersection(self, that: HashSet[Any]) -> HashSet[A]:
        """The members of this set that ``that`` has too."""
        return self._kept(lambda e: that._has_ident(e.ident))

    def difference(self, that: HashSet[Any]) -> HashSet[A]:
        """The members of this set that ``that`` lacks."""
        return self._kept(lambda e: not that._has_ident(e.ident))

    def is_subset(self, that: HashSet[Any]) -> bool:
        """Whether ``that`` has every member of this set."""
        return all(that._has_ident(e.ident) for e in self._entries())

    def map[B](self, f: Callable[[A], B]) -> HashSet[B]:
        """``f`` of every member; equal results are kept once."""
        return HashSet.from_iterable(f(v) for v in list(self))

    @overload
    def filter[B](self, predicate: Callable[[A], TypeIs[B]]) -> HashSet[B]: ...
    @overload
    def filter(self, predicate: Callable[[A], bool]) -> HashSet[A]: ...
    def filter(self, predicate: Callable[[A], bool]) -> HashSet[Any]:
        return self._kept(lambda e: predicate(e.key))

    def some(self, predicate: Callable[[A], bool]) -> bool:
        return any(predicate(v) for v in self)

    def every(self, predicate: Callable[[A], bool]) -> bool:
        return all(predicate(v) for v in self)

    def reduce[Z](self, zero: Z, f: Callable[[Z, A], Z]) -> Z:
        out = zero
        for v in self:
            out = f(out, v)
        return out

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, HashSet):
            return NotImplemented
        theirs = cast("HashSet[object]", other)
        return self._size == theirs._size and all(
            theirs._has_ident(e.ident) for e in self._entries()
        )

    def __hash__(self) -> int:
        return hash(frozenset(e.ident for e in self._entries()))

    def __repr__(self) -> str:
        return f"HashSet({list(self)!r})"


__all__ = ["HashSet"]
