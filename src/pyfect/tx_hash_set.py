"""``TxHashSet[V]``: a transactional hash set (Effect's ``TxHashSet``).

The value is a ``frozenset`` held in a ``TxRef``; every operation joins the
running transaction (``fx.tx``) or runs as one of its own.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Iterable, Set
from typing import Any, TypeIs, overload

from pyfect import _tx_ops
from pyfect._core import Effect
from pyfect.option import Some
from pyfect.tx_ref import TxRef


class TxHashSet[V]:
    """``TxHashSet(ref)`` wraps an existing ``TxRef``; ``empty``, ``make``,
    ``from_iterable`` and ``from_hash_set`` are the effects."""

    __slots__ = ("_ref",)

    def __init__(self, ref: TxRef[frozenset[V]]) -> None:
        self._ref = ref

    @classmethod
    def empty(cls) -> Effect[TxHashSet[V]]:
        """Spelled ``TxHashSet[str].empty()``."""
        return TxRef.make(frozenset[V]()).map(cls)

    @staticmethod
    def make[T](*values: T) -> Effect[TxHashSet[T]]:
        return TxHashSet.from_iterable(values)

    @staticmethod
    def from_iterable[T](values: Iterable[T]) -> Effect[TxHashSet[T]]:
        """A new set each time the effect runs. ``values`` is read once,
        here, so a one-shot iterator survives transaction retries."""
        return TxHashSet.from_hash_set(frozenset(values))

    @staticmethod
    def from_hash_set[T](values: Set[T]) -> Effect[TxHashSet[T]]:
        return TxRef.make(frozenset(values)).map(TxHashSet)

    @property
    def ref(self) -> TxRef[frozenset[V]]:
        return self._ref

    # --- reads ---------------------------------------------------------------

    def has(self, value: V) -> Effect[bool]:
        return _tx_ops.read(self._ref, lambda s: value in s)

    def size(self) -> Effect[int]:
        return _tx_ops.read(self._ref, len)

    def is_empty(self) -> Effect[bool]:
        return _tx_ops.read(self._ref, lambda s: not s)

    def is_non_empty(self) -> Effect[bool]:
        return _tx_ops.read(self._ref, bool)

    def to_hash_set(self) -> Effect[frozenset[V]]:
        return self._ref.get()

    def is_subset(self, that: TxHashSet[Any]) -> Effect[bool]:
        """Whether every value of this set is in ``that``."""
        return _tx_ops.read2(self._ref, that._ref, lambda a, b: a <= b)

    def some(self, predicate: Callable[[V], bool]) -> Effect[bool]:
        return _tx_ops.read(self._ref, lambda s: any(predicate(value) for value in s))

    def every(self, predicate: Callable[[V], bool]) -> Effect[bool]:
        return _tx_ops.read(self._ref, lambda s: all(predicate(value) for value in s))

    def reduce[A](self, zero: A, f: Callable[[A, V], A]) -> Effect[A]:
        def fold(s: frozenset[V]) -> A:
            acc = zero
            for value in s:
                acc = f(acc, value)
            return acc

        return _tx_ops.read(self._ref, fold)

    # --- writes --------------------------------------------------------------

    def add(self, value: V) -> Effect[None]:
        return self._ref.update(lambda s: s if value in s else s | {value})

    def remove(self, value: V) -> Effect[bool]:
        """Remove ``value``; ``True`` when it was there."""
        return _tx_ops.modify_or_skip(
            self._ref, lambda s: (True, Some(s - {value})) if value in s else (False, None)
        )

    def clear(self) -> Effect[None]:
        return self._ref.set(frozenset())

    # --- new sets ------------------------------------------------------------

    def union[V1](self, that: TxHashSet[V1]) -> Effect[TxHashSet[V | V1]]:
        return _tx_ops.read2(self._ref, that._ref, lambda a, b: TxHashSet(TxRef(a | b)))

    def intersection(self, that: TxHashSet[Any]) -> Effect[TxHashSet[V]]:
        return _tx_ops.read2(self._ref, that._ref, lambda a, b: TxHashSet(TxRef(a & b)))

    def difference(self, that: TxHashSet[Any]) -> Effect[TxHashSet[V]]:
        return _tx_ops.read2(self._ref, that._ref, lambda a, b: TxHashSet(TxRef(a - b)))

    def map[U](self, f: Callable[[V], U]) -> Effect[TxHashSet[U]]:
        return _tx_ops.read(
            self._ref, lambda s: TxHashSet(TxRef(frozenset(f(value) for value in s)))
        )

    @overload
    def filter[U](self, predicate: Callable[[V], TypeIs[U]]) -> Effect[TxHashSet[U]]: ...
    @overload
    def filter(self, predicate: Callable[[V], bool]) -> Effect[TxHashSet[V]]: ...
    def filter(self, predicate: Callable[[V], bool]) -> Effect[TxHashSet[Any]]:
        return _tx_ops.read(
            self._ref, lambda s: TxHashSet(TxRef(frozenset(v for v in s if predicate(v))))
        )

    def __repr__(self) -> str:
        return f"TxHashSet({self._ref!r})"


__all__ = ["TxHashSet"]
