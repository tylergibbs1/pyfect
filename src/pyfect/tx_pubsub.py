"""``TxPubSub[A]``: a transactional publish/subscribe hub (Effect's
``TxPubSub``).

Every subscriber gets its own ``TxQueue``, made with the hub's strategy and
capacity, and ``publish`` offers each value to all of them in one
transaction. A ``bounded`` hub's publisher waits (``tx_retry``) while any
subscriber's queue is full; ``dropping`` drops the value for full
subscribers, ``sliding`` drops their oldest value, ``unbounded`` always
accepts. ``subscribe`` hands out the read side of the queue for the current
scope; closing the scope removes the subscriber and shuts its queue down.

Publishing inside a larger transaction is visible to subscribers only when
it commits, so a rolled-back transaction publishes nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Never

from pyfect import _tx_ops
from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect.effect import gen, succeed, sync
from pyfect.scope import Scope, acquire_release
from pyfect.transaction import Transaction, TransactionMeta, transactional, tx, tx_retry
from pyfect.tx_queue import Strategy, TxDequeue, TxQueue
from pyfect.tx_ref import TxRef


class TxPubSub[A]:
    """Build one with ``TxPubSub[int].bounded(16)`` (or ``unbounded``,
    ``dropping``, ``sliding``). ``isinstance(x, TxPubSub)`` is Effect's
    ``isTxPubSub``."""

    __slots__ = ("_capacity", "_shutdown", "_strategy", "_subscribers")

    def __init__(self, strategy: Strategy, capacity: int | None) -> None:
        self._strategy: Strategy = strategy
        self._capacity = capacity
        self._subscribers: TxRef[tuple[TxQueue[A], ...]] = TxRef(())
        self._shutdown = TxRef(False)

    @classmethod
    def bounded(cls, capacity: int) -> Effect[TxPubSub[A]]:
        """``publish`` waits while a subscriber holds ``capacity`` values."""
        return cls._make("bounded", capacity)

    @classmethod
    def unbounded(cls) -> Effect[TxPubSub[A]]:
        return cls._make("unbounded", None)

    @classmethod
    def dropping(cls, capacity: int) -> Effect[TxPubSub[A]]:
        """A full subscriber misses the new value."""
        return cls._make("dropping", capacity)

    @classmethod
    def sliding(cls, capacity: int) -> Effect[TxPubSub[A]]:
        """A full subscriber drops its oldest value for the new one."""
        return cls._make("sliding", capacity)

    @classmethod
    def _make(cls, strategy: Strategy, capacity: int | None) -> Effect[TxPubSub[A]]:
        return sync(lambda: cls(strategy, capacity))

    @property
    def strategy(self) -> Strategy:
        return self._strategy

    @property
    def capacity(self) -> int | None:
        """Each subscriber's capacity; ``None`` if unbounded."""
        return self._capacity

    # --- getters ----------------------------------------------------------

    def size(self) -> Effect[int]:
        """The most values any subscriber has waiting; 0 without
        subscribers."""
        return tx(self._each(lambda queue: queue.size()).map(lambda sizes: max(sizes, default=0)))

    def is_empty(self) -> Effect[bool]:
        return self.size().map(lambda size: size == 0)

    def is_non_empty(self) -> Effect[bool]:
        return self.size().map(lambda size: size > 0)

    def is_full(self) -> Effect[bool]:
        """Whether any subscriber's queue is at capacity."""
        if self._capacity is None:
            return succeed(False)
        return tx(self._each(lambda queue: queue.is_full()).map(any))

    def is_shutdown(self) -> Effect[bool]:
        return self._shutdown.get()

    # --- publishing -------------------------------------------------------

    def publish(self, value: A) -> Effect[bool]:
        """Offer ``value`` to every subscriber. ``False`` if the hub is shut
        down or a dropping subscriber was full; ``True`` without
        subscribers."""
        return self.publish_all((value,))

    def publish_all(self, values: Iterable[A]) -> Effect[bool]:
        """Publish each value in one transaction; ``False`` if the hub is shut
        down or any value was dropped for a subscriber. ``values`` is read
        once, here, so a one-shot iterator survives transaction retries."""
        batch = tuple(values)

        @gen
        def body():
            if (yield from self._shutdown.get()):
                return False
            subscribers = yield from self._subscribers.get()
            accepted = True
            for value in batch:
                for queue in subscribers:
                    accepted = (yield from queue.offer(value)) and accepted
            return accepted

        return tx(body)

    # --- subscribing ------------------------------------------------------

    def subscribe(self) -> Effect[TxDequeue[A, Never], Never, Scope]:
        """A queue of the values published from now on, until the current
        scope closes."""
        return acquire_release(
            self.acquire_subscriber(), lambda queue, _: self.release_subscriber(queue)
        )

    def acquire_subscriber(self) -> Effect[TxDequeue[A, Never]]:
        """Add a subscriber, in the running transaction or one of its own.
        Pair it with ``release_subscriber``; ``subscribe`` does both."""
        return self._acquire_queue()

    def _acquire_queue(self) -> Effect[TxQueue[A]]:
        """``acquire_subscriber``, giving the queue's write side too."""

        def add(meta: TransactionMeta) -> TxQueue[A]:
            queue = TxQueue[A](self._strategy, self._capacity)
            _tx_ops.write(meta, self._subscribers, (*_tx_ops.value(meta, self._subscribers), queue))
            return queue

        return transactional(add)

    def release_subscriber(self, queue: TxDequeue[A, Never]) -> Effect[None]:
        """Remove ``queue``'s subscriber and shut its queue down."""

        @gen
        def body():
            subscribers = yield from self._subscribers.get()
            mine = tuple(q for q in subscribers if q is queue)
            if mine:
                yield from self._subscribers.set(tuple(q for q in subscribers if q is not queue))
            yield from for_each(mine, lambda q: q.shutdown())

        return tx(body)

    # --- shutdown ---------------------------------------------------------

    def shutdown(self) -> Effect[None]:
        """Stop accepting values and shut every subscriber's queue down.
        Shutting down twice does nothing more."""

        @gen
        def body():
            if (yield from self._shutdown.get()):
                return
            yield from self._shutdown.set(True)
            yield from self._each(lambda queue: queue.shutdown())

        return tx(body)

    def await_shutdown(self) -> Effect[None]:
        """Wait until the hub is shut down."""

        def decide(meta: TransactionMeta) -> Effect[None, Never, Transaction]:
            return succeed(None) if _tx_ops.value(meta, self._shutdown) else tx_retry

        return _tx_ops.decide(decide)

    # --- helpers ----------------------------------------------------------

    def _each[B](self, f: Callable[[TxQueue[A]], Effect[B]]) -> Effect[list[B]]:
        return self._subscribers.get().flat_map(lambda queues: for_each(queues, f))

    def __repr__(self) -> str:
        return f"TxPubSub({self._strategy}, {self._capacity})"


__all__ = ["TxPubSub"]
