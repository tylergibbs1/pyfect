"""``SubscriptionRef[A]``: a ``SynchronizedRef`` that publishes every value
it stores.

``subscribe()`` gives a ``pubsub.Subscription`` for the current scope: its
first ``take`` is the current value, then every value stored after it, in
order. Each update stores (and publishes) once, under the ref's lock, so
subscribers see the values in the order they were set; a ``*_some``
update that keeps the value publishes nothing.

``changes()`` is the same as a ``Stream``: the current value, then every
later one, from a subscription made when the stream starts.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import TYPE_CHECKING, Never, overload

from pyfect._core import Effect, _Sync
from pyfect._locked_ref import LockedRef
from pyfect._unsubscripted import Unsubscripted
from pyfect.pubsub import Atomic, PubSub, Subscription
from pyfect.scope import Scope

if TYPE_CHECKING:
    from pyfect.stream import Stream


class SubscriptionRef[A = Unsubscripted](LockedRef[A]):
    __slots__ = ("_pubsub",)

    def __init__(self, value: A) -> None:
        super().__init__(value)
        self._pubsub = PubSub(Atomic[A].unbounded(replay=1), "dropping")
        self._pubsub.publish_unsafe(value)

    @overload
    @classmethod
    def make[T](
        cls: type[SubscriptionRef[Unsubscripted]], value: T
    ) -> Effect[SubscriptionRef[T]]: ...
    @overload
    @classmethod
    def make(cls, value: A) -> Effect[SubscriptionRef[A]]: ...
    @classmethod
    def make[T](cls, value: T) -> Effect[SubscriptionRef[T]]:
        return _Sync(lambda: SubscriptionRef(value))

    def _store(self, value: A) -> None:
        self._value = value
        self._pubsub.publish_unsafe(value)

    def subscribe(self) -> Effect[Subscription[A], Never, Scope]:
        """Subscribe until the current scope closes: the current value, then
        every later one."""
        return self._pubsub.subscribe()

    def changes(self) -> Stream[A]:
        """A stream of the current value, then every later one (Effect's
        ``SubscriptionRef.changes``). Each run subscribes anew."""
        from pyfect.stream import from_pubsub

        return from_pubsub(self._pubsub)


__all__ = ["SubscriptionRef"]
