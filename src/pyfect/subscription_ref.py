"""``SubscriptionRef[A]``: a ``SynchronizedRef`` that publishes every value
it stores.

``subscribe()`` gives a ``pubsub.Subscription`` for the current scope: its
first ``take`` is the current value, then every value stored after it, in
order. Each update stores (and publishes) once, under the ref's lock, so
subscribers see the values in the order they were set; a ``*_some``
update that keeps the value publishes nothing.

Effect's ``changes`` is a ``Stream`` over this subscription
(``Stream.fromPubSub``); it arrives with Stream in M6, built on
``subscribe``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Never

from pyfect._core import Effect, _Sync
from pyfect._locked_ref import LockedRef
from pyfect.pubsub import Atomic, PubSub, Subscription
from pyfect.scope import Scope


class SubscriptionRef[A](LockedRef[A]):
    __slots__ = ("_pubsub",)

    def __init__(self, value: A) -> None:
        super().__init__(value)
        self._pubsub = PubSub(Atomic[A].unbounded(replay=1), "dropping")
        self._pubsub.unsafe_publish(value)

    @staticmethod
    def make[T](value: T) -> Effect[SubscriptionRef[T]]:
        return _Sync(lambda: SubscriptionRef(value))

    def _store(self, value: A) -> None:
        self._value = value
        self._pubsub.unsafe_publish(value)

    def subscribe(self) -> Effect[Subscription[A], Never, Scope]:
        """Subscribe until the current scope closes: the current value, then
        every later one."""
        return self._pubsub.subscribe()
