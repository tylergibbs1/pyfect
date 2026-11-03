"""``TxHashSet[V]``: a transactional hash set (Effect's ``TxHashSet``).

The value is a ``HashSet`` (``pyfect.hash_set``) held in a ``TxRef``:
members compare as Effect's ``Equal`` (``True`` is not ``1``, NaN is one
member, lists are members by their items) and iterate in Effect's hash
order. Every operation joins the running transaction (``fx.tx``) or runs as
one of its own.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, TypeIs, overload

from pyfect import _tx_ops
from pyfect._core import Effect
from pyfect._unsubscripted import Unsubscripted
from pyfect.hash_set import HashSet
from pyfect.option import Some
from pyfect.tx_ref import TxRef


class TxHashSet[V = Unsubscripted]:
    """``TxHashSet(ref)`` wraps an existing ``TxRef``; ``empty``, ``make``,
    ``from_iterable`` and ``from_hash_set`` are the effects."""

    __slots__ = ("_ref",)

    def __init__(self, ref: TxRef[HashSet[V]]) -> None:
        self._ref = ref

    @classmethod
    def empty(cls) -> Effect[TxHashSet[V]]:
        """Spelled ``TxHashSet[str].empty()``."""
        return TxHashSet.from_hash_set(HashSet[V].empty())

    @overload
    @classmethod
    def make[T](cls: type[TxHashSet[Unsubscripted]], *values: T) -> Effect[TxHashSet[T]]: ...
    @overload
    @classmethod
    def make(cls, *values: V) -> Effect[TxHashSet[V]]: ...
    @classmethod
    def make[T](cls, *values: T) -> Effect[TxHashSet[T]]:
        return TxHashSet.from_iterable(values)

    @overload
    @classmethod
    def from_iterable[T](
        cls: type[TxHashSet[Unsubscripted]], values: Iterable[T]
    ) -> Effect[TxHashSet[T]]: ...
    @overload
    @classmethod
    def from_iterable(cls, values: Iterable[V]) -> Effect[TxHashSet[V]]: ...
    @classmethod
    def from_iterable[T](cls, values: Iterable[T]) -> Effect[TxHashSet[T]]:
        """A new set each time the effect runs. ``values`` is read once,
        here, so a one-shot iterator survives transaction retries."""
        return TxHashSet.from_hash_set(HashSet.from_iterable(values))

    @overload
    @classmethod
    def from_hash_set[T](
        cls: type[TxHashSet[Unsubscripted]], values: HashSet[T]
    ) -> Effect[TxHashSet[T]]: ...
    @overload
    @classmethod
    def from_hash_set(cls, values: HashSet[V]) -> Effect[TxHashSet[V]]: ...
    @classmethod
    def from_hash_set[T](cls, values: HashSet[T]) -> Effect[TxHashSet[T]]:
        return TxRef.make(values).map(TxHashSet)

    @property
    def ref(self) -> TxRef[HashSet[V]]:
        return self._ref

    # --- reads ---------------------------------------------------------------

    def has(self, value: V) -> Effect[bool]:
        return _tx_ops.read(self._ref, lambda s: s.has(value))

    def size(self) -> Effect[int]:
        return _tx_ops.read(self._ref, len)

    def is_empty(self) -> Effect[bool]:
        return _tx_ops.read(self._ref, HashSet[V].is_empty)

    def is_non_empty(self) -> Effect[bool]:
        return _tx_ops.read(self._ref, bool)

    def to_hash_set(self) -> Effect[HashSet[V]]:
        """The set as it is now; ``HashSet`` is immutable, so it never
        changes."""
        return self._ref.get()

    def is_subset(self, that: TxHashSet[Any]) -> Effect[bool]:
        """Whether every value of this set is in ``that``."""
        return _tx_ops.read2(self._ref, that._ref, HashSet[V].is_subset)

    def some(self, predicate: Callable[[V], bool]) -> Effect[bool]:
        return _tx_ops.read(self._ref, lambda s: s.some(predicate))

    def every(self, predicate: Callable[[V], bool]) -> Effect[bool]:
        return _tx_ops.read(self._ref, lambda s: s.every(predicate))

    def reduce[A](self, zero: A, f: Callable[[A, V], A]) -> Effect[A]:
        return _tx_ops.read(self._ref, lambda s: s.reduce(zero, f))

    # --- writes --------------------------------------------------------------

    def add(self, value: V) -> Effect[None]:
        """Add ``value``; a value already there leaves the same set, so the
        ref's version stays."""
        return self._ref.update(lambda s: s.add(value))

    def remove(self, value: V) -> Effect[bool]:
        """Remove ``value``; ``True`` when it was there."""
        return _tx_ops.modify_or_skip(
            self._ref, lambda s: (True, Some(s.remove(value))) if s.has(value) else (False, None)
        )

    def clear(self) -> Effect[None]:
        return self._ref.set(HashSet[V].empty())

    # --- new sets ------------------------------------------------------------

    def union[V1](self, that: TxHashSet[V1]) -> Effect[TxHashSet[V | V1]]:
        return _tx_ops.read2(self._ref, that._ref, lambda a, b: TxHashSet(TxRef(a.union(b))))

    def intersection(self, that: TxHashSet[Any]) -> Effect[TxHashSet[V]]:
        return _tx_ops.read2(self._ref, that._ref, lambda a, b: TxHashSet(TxRef(a.intersection(b))))

    def difference(self, that: TxHashSet[Any]) -> Effect[TxHashSet[V]]:
        return _tx_ops.read2(self._ref, that._ref, lambda a, b: TxHashSet(TxRef(a.difference(b))))

    def map[U](self, f: Callable[[V], U]) -> Effect[TxHashSet[U]]:
        return _tx_ops.read(self._ref, lambda s: TxHashSet(TxRef(s.map(f))))

    @overload
    def filter[U](self, predicate: Callable[[V], TypeIs[U]]) -> Effect[TxHashSet[U]]: ...
    @overload
    def filter(self, predicate: Callable[[V], bool]) -> Effect[TxHashSet[V]]: ...
    def filter(self, predicate: Callable[[V], bool]) -> Effect[TxHashSet[Any]]:
        return _tx_ops.read(self._ref, lambda s: TxHashSet(TxRef(s.filter(predicate))))

    def __repr__(self) -> str:
        return f"TxHashSet({self._ref!r})"


__all__ = ["TxHashSet"]
