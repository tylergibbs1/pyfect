"""``TxChunk[A]``: a transactional sequence (Effect's ``TxChunk``).

The value is an immutable ``tuple`` held in a ``TxRef``; every operation
joins the running transaction (``fx.tx``) or runs as one of its own.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import overload

from pyfect import _tx_ops
from pyfect._core import Effect
from pyfect._unsubscripted import Unsubscripted
from pyfect.tx_ref import TxRef


class TxChunk[A = Unsubscripted]:
    """``TxChunk(ref)`` is Effect's ``makeUnsafe``; ``make``, ``empty`` and
    ``from_iterable`` are the effects."""

    __slots__ = ("_ref",)

    def __init__(self, ref: TxRef[tuple[A, ...]]) -> None:
        self._ref = ref

    @overload
    @classmethod
    def make[T](cls: type[TxChunk[Unsubscripted]], items: Iterable[T]) -> Effect[TxChunk[T]]: ...
    @overload
    @classmethod
    def make(cls, items: Iterable[A]) -> Effect[TxChunk[A]]: ...
    @classmethod
    def make[T](cls, items: Iterable[T]) -> Effect[TxChunk[T]]:
        """A new ``TxChunk`` each time the effect runs. ``items`` is read
        once, here, so a one-shot iterator survives transaction retries."""
        initial = tuple(items)
        return TxRef.make(initial).map(TxChunk)

    @classmethod
    def empty(cls) -> Effect[TxChunk[A]]:
        """Spelled ``TxChunk[int].empty()``."""
        empty: tuple[A, ...] = ()
        return TxRef.make(empty).map(cls)

    @overload
    @classmethod
    def from_iterable[T](
        cls: type[TxChunk[Unsubscripted]], items: Iterable[T]
    ) -> Effect[TxChunk[T]]: ...
    @overload
    @classmethod
    def from_iterable(cls, items: Iterable[A]) -> Effect[TxChunk[A]]: ...
    @classmethod
    def from_iterable[T](cls, items: Iterable[T]) -> Effect[TxChunk[T]]:
        return TxChunk.make(items)

    @property
    def ref(self) -> TxRef[tuple[A, ...]]:
        return self._ref

    def get(self) -> Effect[tuple[A, ...]]:
        return self._ref.get()

    def set(self, items: tuple[A, ...]) -> Effect[None]:
        return self._ref.set(items)

    def modify[B](self, f: Callable[[tuple[A, ...]], tuple[B, tuple[A, ...]]]) -> Effect[B]:
        """Replace the items with the second item of ``f(items)``; succeed
        with the first."""
        return self._ref.modify(f)

    def update(self, f: Callable[[tuple[A, ...]], tuple[A, ...]]) -> Effect[None]:
        return self._ref.update(f)

    def append(self, item: A) -> Effect[None]:
        return self.update(lambda items: (*items, item))

    def prepend(self, item: A) -> Effect[None]:
        return self.update(lambda items: (item, *items))

    def append_all(self, items: Iterable[A]) -> Effect[None]:
        added = tuple(items)
        return self.update(lambda current: current + added)

    def prepend_all(self, items: Iterable[A]) -> Effect[None]:
        added = tuple(items)
        return self.update(lambda current: added + current)

    def concat(self, other: TxChunk[A]) -> Effect[None]:
        """Append ``other``'s items, read in the same transaction."""
        return _tx_ops.update_reading(self._ref, other._ref, lambda items, added: items + added)

    def size(self) -> Effect[int]:
        return _tx_ops.read(self._ref, len)

    def is_empty(self) -> Effect[bool]:
        return _tx_ops.read(self._ref, lambda items: not items)

    def is_non_empty(self) -> Effect[bool]:
        return _tx_ops.read(self._ref, bool)

    def take(self, n: int) -> Effect[None]:
        """Keep the first ``n`` items; none when ``n`` is 0 or less."""
        return self.update(lambda items: items[: max(n, 0)])

    def drop(self, n: int) -> Effect[None]:
        """Remove the first ``n`` items; none when ``n`` is 0 or less."""
        return self.update(lambda items: items[max(n, 0) :])

    def slice(self, start: int, end: int) -> Effect[None]:
        """Keep the items from ``start`` up to ``end``: ``drop(start)`` then
        ``take(end - start)``, so negative bounds do not count from the
        end."""
        return self.update(lambda items: items[max(start, 0) :][: max(end - start, 0)])

    def map(self, f: Callable[[A], A]) -> Effect[None]:
        return self.update(lambda items: tuple(f(item) for item in items))

    def filter(self, predicate: Callable[[A], bool]) -> Effect[None]:
        return self.update(lambda items: tuple(item for item in items if predicate(item)))

    def __repr__(self) -> str:
        return f"TxChunk({self._ref!r})"


__all__ = ["TxChunk"]
