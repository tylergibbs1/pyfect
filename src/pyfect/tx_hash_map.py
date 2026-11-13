"""``TxHashMap[K, V]``: a transactional hash map (Effect's ``TxHashMap``).

The value is a ``HashMap`` (``pyfect.hash_map``) held in a ``TxRef``: keys
compare as Effect's ``Equal`` (``True`` is not ``1``, NaN finds NaN, lists
are keys by their items) and iterate in Effect's hash order. A write makes a
new map and shares the rest, so a snapshot stays as it was. Every operation
joins the running transaction (``fx.tx``) or runs as one of its own.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Never, TypeIs, overload

from pyfect import _tx_ops
from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect._equal import equal_key
from pyfect._primitives import _Gen
from pyfect._unsubscripted import Unsubscripted
from pyfect.hash_map import HashMap
from pyfect.option import Option, Some
from pyfect.result import Result
from pyfect.transaction import tx
from pyfect.tx_ref import TxRef


class TxHashMap[K = Unsubscripted, V = Unsubscripted]:
    """``TxHashMap(ref)`` wraps an existing ``TxRef``; ``empty``, ``make``
    and ``from_iterable`` are the effects."""

    __slots__ = ("_ref",)

    def __init__(self, ref: TxRef[HashMap[K, V]]) -> None:
        self._ref = ref

    @classmethod
    def empty(cls) -> Effect[TxHashMap[K, V]]:
        """Spelled ``TxHashMap[str, int].empty()``."""
        return _new(HashMap[K, V].empty())

    @overload
    @classmethod
    def make[K2, V2](
        cls: type[TxHashMap[Unsubscripted, Unsubscripted]], *entries: tuple[K2, V2]
    ) -> Effect[TxHashMap[K2, V2]]: ...
    @overload
    @classmethod
    def make(cls, *entries: tuple[K, V]) -> Effect[TxHashMap[K, V]]: ...
    @classmethod
    def make(cls, *entries: tuple[Any, Any]) -> Effect[TxHashMap[Any, Any]]:
        """``TxHashMap[K, V].make(...)`` takes the subscript; ``TxHashMap.make``
        infers it from the entries."""
        return _new(HashMap.from_iterable(entries))

    # A list's own type is invariant, so pyright widens its literals: a list of
    # pairs gives `TxHashMap[str, int]`, not `TxHashMap[Literal["a"], Literal[1]]`.
    @overload
    @classmethod
    def from_iterable[K2, V2](
        cls: type[TxHashMap[Unsubscripted, Unsubscripted]], entries: list[tuple[K2, V2]]
    ) -> Effect[TxHashMap[K2, V2]]: ...
    @overload
    @classmethod
    def from_iterable[K2, V2](
        cls: type[TxHashMap[Unsubscripted, Unsubscripted]], entries: Iterable[tuple[K2, V2]]
    ) -> Effect[TxHashMap[K2, V2]]: ...
    @overload
    @classmethod
    def from_iterable(cls, entries: Iterable[tuple[K, V]]) -> Effect[TxHashMap[K, V]]: ...
    @classmethod
    def from_iterable(cls, entries: Iterable[tuple[Any, Any]]) -> Effect[TxHashMap[Any, Any]]:
        """A new map each time the effect runs. ``entries`` is read once,
        here, so a one-shot iterator survives transaction retries."""
        return _new(HashMap.from_iterable(entries))

    @property
    def ref(self) -> TxRef[HashMap[K, V]]:
        return self._ref

    # --- reads ---------------------------------------------------------------

    def get(self, key: K) -> Effect[Option[V]]:
        return _tx_ops.read(self._ref, lambda m: m.get(key))

    def has(self, key: K) -> Effect[bool]:
        return _tx_ops.read(self._ref, lambda m: m.has(key))

    def get_hash(self, key: K, hash: int) -> Effect[Option[V]]:
        """``get``, finding nothing unless ``hash`` is ``hash(equal_key(key))``."""
        return _tx_ops.read(self._ref, lambda m: m.get(key) if _hash(key) == hash else None)

    def has_hash(self, key: K, hash: int) -> Effect[bool]:
        """``has``, finding nothing unless ``hash`` is ``hash(equal_key(key))``."""
        return _tx_ops.read(self._ref, lambda m: _hash(key) == hash and m.has(key))

    def size(self) -> Effect[int]:
        return _tx_ops.read(self._ref, len)

    def is_empty(self) -> Effect[bool]:
        return _tx_ops.read(self._ref, HashMap[K, V].is_empty)

    def is_non_empty(self) -> Effect[bool]:
        return _tx_ops.read(self._ref, bool)

    def keys(self) -> Effect[list[K]]:
        return _tx_ops.read(self._ref, lambda m: list(m.keys()))

    def values(self) -> Effect[list[V]]:
        return _tx_ops.read(self._ref, HashMap[K, V].to_values)

    def entries(self) -> Effect[list[tuple[K, V]]]:
        return _tx_ops.read(self._ref, HashMap[K, V].to_entries)

    def to_entries(self) -> Effect[list[tuple[K, V]]]:
        return self.entries()

    def to_values(self) -> Effect[list[V]]:
        return self.values()

    def snapshot(self) -> Effect[HashMap[K, V]]:
        """The map as it is now; ``HashMap`` is immutable, so it never
        changes."""
        return self._ref.get()

    def reduce[A](self, zero: A, f: Callable[[A, V, K], A]) -> Effect[A]:
        return _tx_ops.read(self._ref, lambda m: m.reduce(zero, f))

    def has_by(self, predicate: Callable[[V, K], bool]) -> Effect[bool]:
        return self.some(predicate)

    def some(self, predicate: Callable[[V, K], bool]) -> Effect[bool]:
        return _tx_ops.read(self._ref, lambda m: m.some(predicate))

    def every(self, predicate: Callable[[V, K], bool]) -> Effect[bool]:
        return _tx_ops.read(self._ref, lambda m: m.every(predicate))

    def find_first(self, predicate: Callable[[V, K], bool]) -> Effect[tuple[K, V] | None]:
        """The first entry, in the map's hash order, satisfying
        ``predicate(value, key)``."""
        return _tx_ops.read(self._ref, lambda m: _value_or_none(m.find_first(predicate)))

    def for_each[E = Never, R = Never](
        self, f: Callable[[V, K], Effect[Any, E, R]]
    ) -> Effect[None, E, R]:
        """Run ``f`` on each entry of the map as it was read, in order."""
        return (
            self.entries()
            .flat_map(lambda items: for_each(items, lambda entry: f(entry[1], entry[0])))
            .as_void()
        )

    # --- writes --------------------------------------------------------------
    # As Effect's ``HashMap``, an update that changes no value (``Object.is``)
    # returns the same map, so the commit wakes waiters but leaves the ref's
    # version alone and reruns no concurrent reader.

    def set(self, key: K, value: V) -> Effect[None]:
        return self._ref.update(lambda m: m.set(key, value))

    def remove(self, key: K) -> Effect[bool]:
        """Remove ``key``; ``True`` when it was there."""
        return _tx_ops.modify_or_skip(
            self._ref, lambda m: (True, Some(m.remove(key))) if m.has(key) else (False, None)
        )

    def clear(self) -> Effect[None]:
        return self._ref.set(HashMap[K, V].empty())

    def modify(self, key: K, f: Callable[[V], V]) -> Effect[Option[V]]:
        """Replace the value at ``key`` with ``f`` of it; the old value, or
        ``None`` (and no write) when ``key`` is absent."""

        def run(m: HashMap[K, V]) -> tuple[Option[V], Option[HashMap[K, V]]]:
            match m.get(key):
                case Some(old):
                    return Some(old), Some(m.set(key, f(old)))
                case None:
                    return None, None

        return _tx_ops.modify_or_skip(self._ref, run)

    def modify_at(self, key: K, f: Callable[[Option[V]], Option[V]]) -> Effect[None]:
        """Set ``key`` to what ``f`` returns for its current value, or remove
        it when ``f`` returns ``None``."""

        def run(m: HashMap[K, V]) -> tuple[None, Option[HashMap[K, V]]]:
            current = m.get(key)
            match f(current):
                case Some(value):
                    return None, Some(m.set(key, value))
                case None:
                    return None, None if current is None else Some(m.remove(key))

        return _tx_ops.modify_or_skip(self._ref, run)

    def union(self, other: HashMap[K, V]) -> Effect[None]:
        """Add ``other``'s entries, replacing values at shared keys."""
        return self._ref.update(lambda m: m.set_many(other))

    def set_many(self, entries: Iterable[tuple[K, V]]) -> Effect[None]:
        """Set every entry; ``entries`` is read once, here."""
        added = list(entries)
        return self._ref.update(lambda m: m.set_many(added))

    def remove_many(self, keys: Iterable[K]) -> Effect[None]:
        """Remove every key; ``keys`` is read once, here."""
        removed = list(keys)
        return self._ref.update(lambda m: m.remove_many(removed))

    # --- new maps ------------------------------------------------------------

    def map[A](self, f: Callable[[V, K], A]) -> Effect[TxHashMap[K, A]]:
        return _derive(self, lambda m: m.map(f))

    @overload
    def filter[B](self, predicate: Callable[[V, K], TypeIs[B]]) -> Effect[TxHashMap[K, B]]: ...
    @overload
    def filter(self, predicate: Callable[[V, K], bool]) -> Effect[TxHashMap[K, V]]: ...
    def filter(self, predicate: Callable[[V, K], bool]) -> Effect[TxHashMap[K, Any]]:
        return _derive(self, lambda m: m.filter(predicate))

    def filter_map[A](self, f: Callable[[V, K], Result[A, object]]) -> Effect[TxHashMap[K, A]]:
        """A new map of the ``Ok`` values ``f`` gives; ``Err`` drops the
        entry."""
        return _derive(self, lambda m: m.filter_map(f))

    def compact[A](self: TxHashMap[K, Option[A]]) -> Effect[TxHashMap[K, A]]:
        """A new map of the ``Some`` values, unwrapped."""
        return _derive(self, HashMap[K, Option[A]].compact)

    def flat_map[A, E = Never, R = Never](
        self, f: Callable[[V, K], Effect[TxHashMap[K, A], E, R]]
    ) -> Effect[TxHashMap[K, A], E, R]:
        """A new map of the entries of every map ``f`` gives, in one
        transaction; later entries replace earlier ones."""

        def body():
            source = yield from self.entries()
            out = HashMap[K, A].empty()
            for key, value in source:
                produced = yield from f(value, key)
                out = out.set_many((yield from produced.entries()))
            return TxHashMap(TxRef(out))

        return tx(_Gen(body))

    def __repr__(self) -> str:
        return f"TxHashMap({self._ref!r})"


def _hash(key: object) -> int:
    # Effect's ``Hash.hash`` is ``hash(equal_key(key))`` (docs/PARITY.md section 4).
    return hash(equal_key(key))


def _value_or_none[A](found: Option[A]) -> A | None:
    return None if found is None else found.value


def _new[K, V](m: HashMap[K, V]) -> Effect[TxHashMap[K, V]]:
    return TxRef.make(m).map(TxHashMap)


def _derive[K, V, K2, V2](
    source: TxHashMap[K, V], f: Callable[[HashMap[K, V]], HashMap[K2, V2]]
) -> Effect[TxHashMap[K2, V2]]:
    return _tx_ops.read(source._ref, lambda m: TxHashMap(TxRef(f(m))))


__all__ = ["TxHashMap"]
