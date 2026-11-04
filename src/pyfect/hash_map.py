"""``HashMap[K, V]``: an immutable map whose keys compare as Effect's
``Equal.equals`` does (Effect's ``HashMap``).

A ``dict`` keys by ``==`` and ``hash``: it calls ``1`` and ``True`` one key,
a NaN never equal to itself and a list or dict unhashable. A ``HashMap``
keys by ``pyfect._equal.equal_key``: ``True`` stays apart from ``1``, NaN
finds NaN, and lists, tuples, dicts and sets are keys by their items::

    m = HashMap.make((["a", 1], "x"), (True, "y"))
    m.get(["a", 1])    # Some("x")
    m.get(1)           # None
    m2 = m.set(1, "z") # a new map; m is unchanged

Every update returns a new map and leaves the old one as it was. Like
Effect's, the map is a persistent hash array mapped trie (``pyfect._hamt``):
an update copies about ``log32(size)`` nodes and shares the rest.
Iteration yields ``(key, value)`` pairs in hash order, Effect's order: keys
are hashed with Effect's ``Hash.hash`` (``pyfect._effect_hash``).
The ``hash`` arguments of ``get_hash`` / ``has_hash`` / ``modify_hash`` are
accepted for Effect's API and not needed: keys are found by value.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Any, TypeIs, cast, overload

from pyfect import _hamt
from pyfect._equal import equal_key, equals
from pyfect._hamt import Entry, Node
from pyfect._unsubscripted import Unsubscripted
from pyfect.option import Option, Some
from pyfect.result import Ok, Result


class HashMap[K = Unsubscripted, V = Unsubscripted]:
    """Build one with ``HashMap.empty()``, ``HashMap.make(*entries)`` or
    ``HashMap.from_iterable(entries)``."""

    __slots__ = ("_mutable", "_root", "_size")

    _root: Node | None
    _size: int
    _mutable: bool

    def __init__(self, root: Node | None = None, size: int = 0) -> None:
        self._root = root
        self._size = size
        self._mutable = False

    # --- constructors -------------------------------------------------------------

    @classmethod
    def empty(cls) -> HashMap[K, V]:
        """Spelled ``HashMap[str, int].empty()``."""
        return HashMap()

    @overload
    @classmethod
    def make[K2, V2](
        cls: type[HashMap[Unsubscripted, Unsubscripted]], *entries: tuple[K2, V2]
    ) -> HashMap[K2, V2]: ...
    @overload
    @classmethod
    def make(cls, *entries: tuple[K, V]) -> HashMap[K, V]: ...
    @classmethod
    def make[K2, V2](cls, *entries: tuple[K2, V2]) -> HashMap[K2, V2]:
        return HashMap.from_iterable(entries)

    @overload
    @classmethod
    def from_iterable[K2, V2](
        cls: type[HashMap[Unsubscripted, Unsubscripted]], entries: Iterable[tuple[K2, V2]]
    ) -> HashMap[K2, V2]: ...
    @overload
    @classmethod
    def from_iterable(cls, entries: Iterable[tuple[K, V]]) -> HashMap[K, V]: ...
    @classmethod
    def from_iterable[K2, V2](cls, entries: Iterable[tuple[K2, V2]]) -> HashMap[K2, V2]:
        """The map of ``entries``; a later value for an equal key wins, and
        the first key is kept."""
        return HashMap[K2, V2]().set_many(entries)

    # --- reading ------------------------------------------------------------------

    def _entries(self) -> Iterator[Entry[K, V]]:
        return cast("Iterator[Entry[K, V]]", _hamt.entries(self._root))

    def _find(self, key: object) -> Entry[K, V] | None:
        ident = equal_key(key)
        found = _hamt.find(self._root, _hamt.hash_of(ident), ident)
        return cast("Entry[K, V] | None", found)

    def __len__(self) -> int:
        return self._size

    def __bool__(self) -> bool:
        return self._size > 0

    def __iter__(self) -> Iterator[tuple[K, V]]:
        return ((e.key, e.value) for e in self._entries())

    def __contains__(self, key: object) -> bool:
        return self.has(key)

    def __getitem__(self, key: K) -> V:
        found = self._find(key)
        if found is None:
            raise KeyError(key)
        return found.value

    def is_empty(self) -> bool:
        return self._size == 0

    def get(self, key: object) -> Option[V]:
        """``Some(value)`` for ``key``, or ``None``."""
        found = self._find(key)
        return None if found is None else Some(found.value)

    def get_hash(self, key: object, hash: int) -> Option[V]:
        return self.get(key)

    def get_unsafe(self, key: object) -> V:
        """The value for ``key``; raises ``KeyError`` without one."""
        found = self._find(key)
        if found is None:
            raise KeyError("HashMap.getUnsafe: key not found")
        return found.value

    def has(self, key: object) -> bool:
        return self._find(key) is not None

    def has_hash(self, key: object, hash: int) -> bool:
        return self.has(key)

    def has_by(self, predicate: Callable[[V, K], bool]) -> bool:
        """Whether an entry satisfies ``predicate(value, key)``."""
        return any(predicate(e.value, e.key) for e in self._entries())

    def keys(self) -> Iterator[K]:
        return (e.key for e in self._entries())

    def values(self) -> Iterator[V]:
        return (e.value for e in self._entries())

    def to_values(self) -> list[V]:
        return list(self.values())

    def entries(self) -> Iterator[tuple[K, V]]:
        return iter(self)

    def to_entries(self) -> list[tuple[K, V]]:
        return list(self)

    def find_first(self, predicate: Callable[[V, K], bool]) -> Option[tuple[K, V]]:
        """The first entry satisfying ``predicate(value, key)``."""
        for e in self._entries():
            if predicate(e.value, e.key):
                return Some((e.key, e.value))
        return None

    def some(self, predicate: Callable[[V, K], bool]) -> bool:
        return self.has_by(predicate)

    def every(self, predicate: Callable[[V, K], bool]) -> bool:
        return all(predicate(e.value, e.key) for e in self._entries())

    def reduce[Z](self, zero: Z, f: Callable[[Z, V, K], Z]) -> Z:
        out = zero
        for e in self._entries():
            out = f(out, e.value, e.key)
        return out

    def for_each(self, f: Callable[[V, K], object]) -> None:
        for e in self._entries():
            f(e.value, e.key)

    # --- updates --------------------------------------------------------------------

    def _with(self, root: Node | None, size: int) -> HashMap[K, V]:
        if root is self._root:
            return self
        if self._mutable:
            self._root, self._size = root, size
            return self
        return HashMap(root, size)

    def set(self, key: K, value: V) -> HashMap[K, V]:
        """The map with ``key`` set to ``value``; the same map when ``key``
        already holds this value (``Object.is``: ``pyfect._js.same_value``).
        An equal key already there is kept."""
        ident = equal_key(key)
        hash = _hamt.hash_of(ident)
        added = _hamt.find(self._root, hash, ident) is None
        root = _hamt.insert(self._root, Entry(hash, ident, key, value))
        return self._with(root, self._size + added)

    def set_many(self, entries: Iterable[tuple[K, V]]) -> HashMap[K, V]:
        root, size = self._root, self._size
        for key, value in entries:
            ident = equal_key(key)
            hash = _hamt.hash_of(ident)
            size += _hamt.find(root, hash, ident) is None
            root = _hamt.insert(root, Entry(hash, ident, key, value))
        return self._with(root, size)

    def remove(self, key: K) -> HashMap[K, V]:
        """The map without ``key``; the same map when it has no ``key``."""
        return self.remove_many((key,))

    def remove_many(self, keys: Iterable[K]) -> HashMap[K, V]:
        root, size = self._root, self._size
        for key in keys:
            ident = equal_key(key)
            smaller = _hamt.remove(root, _hamt.hash_of(ident), ident)
            size -= smaller is not root
            root = smaller
        return self._with(root, size)

    def modify_at(self, key: K, f: Callable[[Option[V]], Option[V]]) -> HashMap[K, V]:
        """Set, keep or remove ``key`` by what ``f`` makes of its current
        value: ``Some(new)`` sets it, ``None`` removes it."""
        match f(self.get(key)):
            case Some(value):
                return self.set(key, value)
            case None:
                return self.remove(key)

    def modify_hash(self, key: K, hash: int, f: Callable[[Option[V]], Option[V]]) -> HashMap[K, V]:
        return self.modify_at(key, f)

    def modify(self, key: K, f: Callable[[V], V]) -> HashMap[K, V]:
        """The map with ``key``'s value replaced by ``f(value)``; the same
        map without ``key``."""
        found = self._find(key)
        return self if found is None else self.set(found.key, f(found.value))

    def union[K1, V1](self, that: HashMap[K1, V1]) -> HashMap[K | K1, V | V1]:
        """Both maps' entries; ``that``'s value wins for an equal key."""
        return HashMap[K | K1, V | V1](self._root, self._size).set_many(that)

    def _rebuilt[A](self, pairs: Iterable[tuple[K, A]]) -> HashMap[K, A]:
        return HashMap[K, A]().set_many(pairs)

    def map[A](self, f: Callable[[V, K], A]) -> HashMap[K, A]:
        return self._rebuilt((e.key, f(e.value, e.key)) for e in list(self._entries()))

    def flat_map[A](self, f: Callable[[V, K], HashMap[K, A]]) -> HashMap[K, A]:
        """The union of ``f(value, key)`` for every entry."""
        return self._rebuilt(pair for e in list(self._entries()) for pair in f(e.value, e.key))

    @overload
    def filter[B](self, predicate: Callable[[V, K], TypeIs[B]]) -> HashMap[K, B]: ...
    @overload
    def filter(self, predicate: Callable[[V, K], bool]) -> HashMap[K, V]: ...
    def filter(self, predicate: Callable[[V, K], bool]) -> HashMap[K, Any]:
        return self._rebuilt((e.key, e.value) for e in self._entries() if predicate(e.value, e.key))

    def filter_map[A](self, f: Callable[[V, K], Result[A, object]]) -> HashMap[K, A]:
        """The entries ``f(value, key)`` keeps (``Ok``), with its values."""

        def kept() -> Iterator[tuple[K, A]]:
            for e in self._entries():
                result = f(e.value, e.key)
                if isinstance(result, Ok):
                    yield e.key, result.value

        return self._rebuilt(kept())

    def compact[A](self: HashMap[K, Option[A]]) -> HashMap[K, A]:
        """The ``Some`` values, unwrapped."""
        return self._rebuilt(
            (e.key, e.value.value) for e in self._entries() if isinstance(e.value, Some)
        )

    # --- batched updates --------------------------------------------------------------

    def begin_mutation(self) -> HashMap[K, V]:
        """A copy whose ``set`` / ``remove`` / ... update it in place (and
        return it) until ``end_mutation``."""
        out = HashMap[K, V](self._root, self._size)
        out._mutable = True
        return out

    def end_mutation(self) -> HashMap[K, V]:
        """Freeze a map from ``begin_mutation``; returns the same map."""
        self._mutable = False
        return self

    def mutate(self, f: Callable[[HashMap[K, V]], object]) -> HashMap[K, V]:
        """A new map: a mutable copy of this one after ``f`` has updated it."""
        draft = self.begin_mutation()
        f(draft)
        return draft.end_mutation()

    # --- equality -------------------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, HashMap):
            return NotImplemented
        theirs = cast("HashMap[object, object]", other)
        if self._size != theirs._size:
            return False
        for e in self._entries():
            found = _hamt.find(theirs._root, e.hash, e.ident)
            if found is None or not equals(e.value, found.value):
                return False
        return True

    def __hash__(self) -> int:
        return hash(frozenset((e.ident, equal_key(e.value)) for e in self._entries()))

    def __repr__(self) -> str:
        return f"HashMap({self.to_entries()!r})"


__all__ = ["HashMap"]
