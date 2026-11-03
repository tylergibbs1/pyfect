"""``MutableHashMap[K, V]``: a mutable map whose keys compare as Effect's
``Equal.equals`` does (Effect's ``MutableHashMap``).

Like a ``dict`` updated in place, but keyed by ``pyfect._equal.equal_key``:
``True`` stays apart from ``1``, NaN finds NaN, and lists, tuples, dicts and
sets are keys by their items. Setting an equal key keeps the key first
stored, as ``dict`` does. Iteration yields ``(key, value)`` pairs in
insertion order. Being mutable, it is unhashable.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Iterator
from typing import cast

from pyfect._equal import equal_key, equals
from pyfect.option import Option, Some


class MutableHashMap[K, V]:
    """Build one with ``MutableHashMap.empty()``, ``make(*entries)`` or
    ``from_iterable(entries)``. Updates return the map itself."""

    __slots__ = ("_entries",)

    _entries: dict[Hashable, tuple[K, V]]

    def __init__(self) -> None:
        self._entries = {}

    @classmethod
    def empty(cls) -> MutableHashMap[K, V]:
        """Spelled ``MutableHashMap[str, int].empty()``."""
        return MutableHashMap()

    @staticmethod
    def make[K2, V2](*entries: tuple[K2, V2]) -> MutableHashMap[K2, V2]:
        return MutableHashMap.from_iterable(entries)

    @staticmethod
    def from_iterable[K2, V2](entries: Iterable[tuple[K2, V2]]) -> MutableHashMap[K2, V2]:
        out = MutableHashMap[K2, V2]()
        for key, value in entries:
            out.set(key, value)
        return out

    def __len__(self) -> int:
        return len(self._entries)

    def __bool__(self) -> bool:
        return bool(self._entries)

    def __iter__(self) -> Iterator[tuple[K, V]]:
        return iter(list(self._entries.values()))

    def __contains__(self, key: object) -> bool:
        return self.has(key)

    def is_empty(self) -> bool:
        return not self._entries

    def get(self, key: object) -> Option[V]:
        found = self._entries.get(equal_key(key))
        return None if found is None else Some(found[1])

    def has(self, key: object) -> bool:
        return equal_key(key) in self._entries

    def keys(self) -> Iterator[K]:
        return iter([k for k, _ in self._entries.values()])

    def values(self) -> Iterator[V]:
        return iter([v for _, v in self._entries.values()])

    def set(self, key: K, value: V) -> MutableHashMap[K, V]:
        k = equal_key(key)
        found = self._entries.get(k)
        self._entries[k] = (key if found is None else found[0], value)
        return self

    def modify(self, key: K, f: Callable[[V], V]) -> MutableHashMap[K, V]:
        """Replace ``key``'s value with ``f(value)``; nothing without ``key``."""
        k = equal_key(key)
        found = self._entries.get(k)
        if found is not None:
            self._entries[k] = (found[0], f(found[1]))
        return self

    def modify_at(self, key: K, f: Callable[[Option[V]], Option[V]]) -> MutableHashMap[K, V]:
        """Set or remove ``key`` by what ``f`` makes of its current value."""
        match f(self.get(key)):
            case Some(value):
                return self.set(key, value)
            case None:
                return self.remove(key)

    def remove(self, key: K) -> MutableHashMap[K, V]:
        self._entries.pop(equal_key(key), None)
        return self

    def clear(self) -> MutableHashMap[K, V]:
        self._entries.clear()
        return self

    def for_each(self, f: Callable[[V, K], object]) -> None:
        for k, v in list(self._entries.values()):
            f(v, k)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MutableHashMap):
            return NotImplemented
        theirs = cast("MutableHashMap[object, object]", other)._entries
        return len(self._entries) == len(theirs) and all(
            h in theirs and equals(v, theirs[h][1]) for h, (_, v) in self._entries.items()
        )

    __hash__ = None  # pyright: ignore[reportAssignmentType]

    def __repr__(self) -> str:
        return f"MutableHashMap({list(self._entries.values())!r})"


__all__ = ["MutableHashMap"]
