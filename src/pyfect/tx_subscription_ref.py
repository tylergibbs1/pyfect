"""``TxSubscriptionRef[A]``: a ``TxRef`` that publishes every value it
stores to an unbounded ``TxPubSub`` (Effect's ``TxSubscriptionRef``).

``changes()`` subscribes for the current scope: the queue's first value is
the current one, then every value stored after it, in commit order.
``changes_stream()`` is the same as a ``Stream``, subscribing when it
starts. A write publishes in the same transaction, so a transaction that
rolls back publishes nothing.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Never, overload

from pyfect._core import Effect
from pyfect._unsubscripted import Unsubscripted
from pyfect.effect import gen
from pyfect.scope import Scope, acquire_release
from pyfect.transaction import tx
from pyfect.tx_pubsub import TxPubSub
from pyfect.tx_queue import TxDequeue
from pyfect.tx_ref import TxRef

if TYPE_CHECKING:
    from pyfect.stream import Stream


class TxSubscriptionRef[A = Unsubscripted]:
    """``make`` is the effect; ``isinstance(x, TxSubscriptionRef)`` is
    Effect's ``isTxSubscriptionRef``."""

    __slots__ = ("_pubsub", "_ref")

    def __init__(self, ref: TxRef[A], pubsub: TxPubSub[A]) -> None:
        self._ref = ref
        self._pubsub = pubsub

    @overload
    @classmethod
    def make[T](
        cls: type[TxSubscriptionRef[Unsubscripted]], value: T
    ) -> Effect[TxSubscriptionRef[T]]: ...
    @overload
    @classmethod
    def make(cls, value: A) -> Effect[TxSubscriptionRef[A]]: ...
    @classmethod
    def make[T](cls, value: T) -> Effect[TxSubscriptionRef[T]]:
        return TxPubSub[T].unbounded().map(lambda pubsub: TxSubscriptionRef(TxRef(value), pubsub))

    @property
    def ref(self) -> TxRef[A]:
        return self._ref

    @property
    def pubsub(self) -> TxPubSub[A]:
        return self._pubsub

    def get(self) -> Effect[A]:
        return self._ref.get()

    def modify[B](self, f: Callable[[A], tuple[B, A]]) -> Effect[B]:
        """Store the second item of ``f(value)`` and publish it; succeed with
        the first."""

        @gen
        def body():
            result, value = f((yield from self._ref.get()))
            yield from self._ref.set(value)
            yield from self._pubsub.publish(value)
            return result

        return tx(body)

    def set(self, value: A) -> Effect[None]:
        return self.modify(lambda _: (None, value))

    def update(self, f: Callable[[A], A]) -> Effect[None]:
        return self.modify(lambda current: (None, f(current)))

    def get_and_set(self, value: A) -> Effect[A]:
        return self.modify(lambda current: (current, value))

    def get_and_update(self, f: Callable[[A], A]) -> Effect[A]:
        return self.modify(lambda current: (current, f(current)))

    def update_and_get(self, f: Callable[[A], A]) -> Effect[A]:
        def step(current: A) -> tuple[A, A]:
            new = f(current)
            return new, new

        return self.modify(step)

    def changes(self) -> Effect[TxDequeue[A, Never], Never, Scope]:
        """A queue of the current value, then every later one, until the
        current scope closes."""

        @gen
        def acquire():
            queue = yield from self._pubsub._acquire_queue()
            yield from queue.offer((yield from self._ref.get()))
            return queue

        return acquire_release(tx(acquire), lambda queue, _: self._pubsub.release_subscriber(queue))

    def changes_stream(self) -> Stream[A]:
        """A stream of the current value, then every later one (Effect's
        ``changesStream``). Each run subscribes anew."""
        from pyfect.stream import from_effect_repeat, unwrap

        return unwrap(self.changes().map(lambda queue: from_effect_repeat(queue.take())))

    def __repr__(self) -> str:
        return "TxSubscriptionRef()"


__all__ = ["TxSubscriptionRef"]
