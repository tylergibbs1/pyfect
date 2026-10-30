"""``TxPriorityQueue[A]``: a transactional priority queue (Effect's
``TxPriorityQueue``).

Items are kept sorted by a ``key`` function, smallest first, as ``sorted``
orders them (Effect's ``Order``); items with equal keys come out in the
order they went in. ``take`` and ``peek`` wait (``tx_retry``) while the
queue is empty.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, Never, overload

from pyfect import _tx_ops
from pyfect._core import Effect
from pyfect.effect import succeed
from pyfect.option import Option, Some
from pyfect.transaction import Transaction, TransactionMeta, tx_retry
from pyfect.tx_ref import TxRef

if TYPE_CHECKING:
    from _typeshed import SupportsRichComparison

type Key[A] = Callable[[A], SupportsRichComparison]


def _identity(item: Any) -> Any:
    return item


def _merge_sorted[A](
    items: tuple[A, ...], added: list[A], key: Callable[[A], Any]
) -> tuple[A, ...]:
    """Merge sorted ``added`` into sorted ``items``, each new item after the
    equal ones already there. Each insertion point is found by galloping
    from the previous one and then bisecting, so a few new items cost a few
    key calls each rather than one per queued item."""
    out: list[A] = []
    i = 0
    n = len(items)
    for item in added:
        k = key(item)
        lo = hi = i
        step = 1
        while hi < n and not k < key(items[hi]):
            lo = hi + 1
            hi += step
            step *= 2
        hi = min(hi, n)
        while lo < hi:
            mid = (lo + hi) // 2
            if not k < key(items[mid]):
                lo = mid + 1
            else:
                hi = mid
        out.extend(items[i:lo])
        out.append(item)
        i = lo
    out.extend(items[i:])
    return tuple(out)


class TxPriorityQueue[A]:
    """``TxPriorityQueue(ref, key)`` wraps an existing ``TxRef`` of sorted
    items (Effect's ``makeUnsafe``); ``empty``, ``from_iterable`` and
    ``make`` are the effects. Without ``key``, items compare as they are."""

    __slots__ = ("_key", "_ref")

    def __init__(self, ref: TxRef[tuple[A, ...]], key: Key[A]) -> None:
        self._ref = ref
        self._key = key

    @overload
    @classmethod
    def empty[T: SupportsRichComparison](
        cls: type[TxPriorityQueue[T]],
    ) -> Effect[TxPriorityQueue[T]]: ...
    @overload
    @classmethod
    def empty(cls, *, key: Key[A]) -> Effect[TxPriorityQueue[A]]: ...
    @classmethod
    def empty(cls, *, key: Key[Any] = _identity) -> Effect[TxPriorityQueue[Any]]:
        """Spelled ``TxPriorityQueue[int].empty()`` or
        ``TxPriorityQueue[Task].empty(key=priority)``."""
        empty: tuple[Any, ...] = ()
        return TxRef.make(empty).map(lambda ref: TxPriorityQueue(ref, key))

    @overload
    @staticmethod
    def from_iterable[T: SupportsRichComparison](
        items: Iterable[T],
    ) -> Effect[TxPriorityQueue[T]]: ...
    @overload
    @staticmethod
    def from_iterable[T](items: Iterable[T], *, key: Key[T]) -> Effect[TxPriorityQueue[T]]: ...
    @staticmethod
    def from_iterable(
        items: Iterable[Any], *, key: Key[Any] = _identity
    ) -> Effect[TxPriorityQueue[Any]]:
        """A new queue each time the effect runs. ``items`` is read once,
        here, so a one-shot iterator survives transaction retries."""
        initial = tuple(sorted(items, key=key))
        return TxRef.make(initial).map(lambda ref: TxPriorityQueue(ref, key))

    @overload
    @staticmethod
    def make[T: SupportsRichComparison](*items: T) -> Effect[TxPriorityQueue[T]]: ...
    @overload
    @staticmethod
    def make[T](*items: T, key: Key[T]) -> Effect[TxPriorityQueue[T]]: ...
    @staticmethod
    def make(*items: Any, key: Key[Any] = _identity) -> Effect[TxPriorityQueue[Any]]:
        return TxPriorityQueue.from_iterable(items, key=key)

    @property
    def ref(self) -> TxRef[tuple[A, ...]]:
        """The items, sorted."""
        return self._ref

    @property
    def key(self) -> Key[A]:
        return self._key

    def size(self) -> Effect[int]:
        return _tx_ops.read(self._ref, len)

    def is_empty(self) -> Effect[bool]:
        return _tx_ops.read(self._ref, lambda items: not items)

    def is_non_empty(self) -> Effect[bool]:
        return _tx_ops.read(self._ref, bool)

    def peek(self) -> Effect[A]:
        """The smallest item, left in the queue; waits while it is empty."""

        def decide(state: TransactionMeta) -> Effect[A, Never, Transaction]:
            items = _tx_ops.value(state, self._ref)
            return succeed(items[0]) if items else tx_retry

        return _tx_ops.decide(decide)

    def peek_option(self) -> Effect[Option[A]]:
        """``Some`` of the smallest item, or ``None`` if the queue is empty."""
        return _tx_ops.read(self._ref, lambda items: Some(items[0]) if items else None)

    def offer(self, item: A) -> Effect[None]:
        return self._ref.update(lambda items: _merge_sorted(items, [item], self._key))

    def offer_all(self, items: Iterable[A]) -> Effect[None]:
        """Add several items. ``items`` is read once, here, so a one-shot
        iterator survives transaction retries."""
        added = sorted(items, key=self._key)
        return self._ref.update(lambda current: _merge_sorted(current, added, self._key))

    def take(self) -> Effect[A]:
        """Remove and succeed with the smallest item; waits while the queue
        is empty."""

        def decide(state: TransactionMeta) -> Effect[A, Never, Transaction]:
            items = _tx_ops.value(state, self._ref)
            if not items:
                return tx_retry
            _tx_ops.write(state, self._ref, items[1:])
            return succeed(items[0])

        return _tx_ops.decide(decide)

    def take_all(self) -> Effect[list[A]]:
        """Remove every item, smallest first."""
        return self._ref.modify(lambda items: (list(items), ()))

    def take_option(self) -> Effect[Option[A]]:
        """Remove the smallest item if there is one."""
        return self._ref.modify(
            lambda items: (Some(items[0]), items[1:]) if items else (None, items)
        )

    def take_up_to(self, n: int) -> Effect[list[A]]:
        """Remove up to ``n`` of the smallest items; none when ``n`` is 0 or
        less."""
        count = max(n, 0)
        return self._ref.modify(lambda items: (list(items[:count]), items[count:]))

    def remove_if(self, predicate: Callable[[A], bool]) -> Effect[None]:
        return self._ref.update(lambda items: tuple(item for item in items if not predicate(item)))

    def retain_if(self, predicate: Callable[[A], bool]) -> Effect[None]:
        return self._ref.update(lambda items: tuple(item for item in items if predicate(item)))

    def to_list(self) -> Effect[list[A]]:
        """The items, smallest first (Effect's ``toArray``)."""
        return _tx_ops.read(self._ref, list)

    def __repr__(self) -> str:
        return "TxPriorityQueue()"


__all__ = ["Key", "TxPriorityQueue"]
