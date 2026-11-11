"""``PubSub[A]`` itself. See the package docstring for its behavior."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Never, overload

from pyfect._core import Effect, _Gen, _Succeed, _Suspend, _Sync, _WithFiber
from pyfect._fiber import Fiber
from pyfect._unsubscripted import Unsubscripted
from pyfect.cause import interrupt as interrupt_cause
from pyfect.exit import Failure
from pyfect.option import Some
from pyfect.pubsub._atomic import Atomic
from pyfect.pubsub._hub import Hub
from pyfect.pubsub._strategies import (
    BUILT_IN,
    BackPressureStrategy,
    DroppingStrategy,
    SlidingStrategy,
    StrategyName,
)
from pyfect.pubsub._strategy import Strategy
from pyfect.pubsub._subscription import Subscription
from pyfect.scope import Scope


class PubSub[A = Unsubscripted]:
    __slots__ = ("_hub",)

    def __init__(self, atomic: Atomic[A], strategy: Strategy[A] | StrategyName) -> None:
        self._hub = Hub(atomic, strategy if not isinstance(strategy, str) else BUILT_IN[strategy]())

    @overload
    @classmethod
    def make[T](
        cls: type[PubSub[Unsubscripted]],
        atomic: Callable[[], Atomic[T]],
        strategy: Callable[[], Strategy[T]] | StrategyName,
    ) -> Effect[PubSub[T]]: ...
    @overload
    @classmethod
    def make(
        cls, atomic: Callable[[], Atomic[A]], strategy: Callable[[], Strategy[A]] | StrategyName
    ) -> Effect[PubSub[A]]: ...
    @classmethod
    def make[T](
        cls, atomic: Callable[[], Atomic[T]], strategy: Callable[[], Strategy[T]] | StrategyName
    ) -> Effect[PubSub[T]]:
        """A hub over the store ``atomic()`` builds, run by the strategy
        ``strategy()`` builds (Effect's ``make``). A built-in strategy can be
        named: ``"suspend"`` (``BackPressureStrategy``), ``"dropping"``,
        ``"sliding"``."""
        if callable(strategy):
            build = strategy
            return _Sync(lambda: PubSub(atomic(), build()))
        name = strategy
        return _Sync(lambda: PubSub(atomic(), BUILT_IN[name]()))

    @classmethod
    def bounded(cls, capacity: int | None, *, replay: int | None = None) -> Effect[PubSub[A]]:
        """Publishers wait while ``capacity`` messages are unread. ``replay``
        messages are kept for new subscribers. A capacity below 1 is a
        defect; ``None`` is unbounded."""
        return _Sync(lambda: cls(Atomic(capacity, replay), BackPressureStrategy[A]()))

    @classmethod
    def dropping(cls, capacity: int | None, *, replay: int | None = None) -> Effect[PubSub[A]]:
        """A publish to a full hub drops the message and returns ``False``."""
        return _Sync(lambda: cls(Atomic(capacity, replay), DroppingStrategy[A]()))

    @classmethod
    def sliding(cls, capacity: int | None, *, replay: int | None = None) -> Effect[PubSub[A]]:
        """A publish to a full hub drops the oldest unread message."""
        return _Sync(lambda: cls(Atomic(capacity, replay), SlidingStrategy[A]()))

    @classmethod
    def unbounded(cls, *, replay: int | None = None) -> Effect[PubSub[A]]:
        """A hub with no capacity limit: publishing never waits or drops.
        ``replay`` messages are kept for new subscribers."""
        return _Sync(lambda: cls(Atomic(None, replay), DroppingStrategy[A]()))

    @property
    def strategy(self) -> Strategy[A]:
        return self._hub.strategy

    @property
    def capacity(self) -> int | None:
        """How many unread messages the hub holds; ``None`` if unbounded."""
        return self._hub.atomic.capacity

    # --- publishing -------------------------------------------------------

    def publish(self, value: A) -> Effect[bool]:
        """Publish to every current subscriber. ``False`` if the hub ended or
        shut down; otherwise what the strategy does with a full hub (a
        bounded hub waits for room)."""
        hub = self._hub

        def run() -> Effect[bool]:
            if not hub.accepts():
                return _FALSE
            if hub.atomic.publish(value):
                hub.complete_subscribers()
                return _TRUE
            return hub.strategy.handle_surplus(
                hub.atomic, hub.subscribers, [value], hub.is_shutdown_now, hub.ended_now
            )

        return _Suspend(run)

    def publish_unsafe(self, value: A) -> bool:
        """Publish without waiting, sliding or dropping: ``False`` if the
        store is full. Call on the scheduler thread of the hub's fibers."""
        hub = self._hub
        if not hub.accepts() or not hub.atomic.publish(value):
            return False
        hub.complete_subscribers()
        return True

    def publish_all(self, items: Iterable[A]) -> Effect[bool]:
        """Publish ``items`` in order; ``True`` if every one was published.
        A bounded hub publishes what fits and waits to publish the rest."""
        hub = self._hub

        def run() -> Effect[bool]:
            if not hub.accepts():
                return _FALSE
            surplus = hub.atomic.publish_all(items)
            hub.complete_subscribers()
            if not surplus:
                return _TRUE
            return hub.strategy.handle_surplus(
                hub.atomic, hub.subscribers, surplus, hub.is_shutdown_now, hub.ended_now
            )

        return _Suspend(run)

    def end(self, value: A) -> Effect[bool]:
        """Publish nothing more. Subscribers take what they have not read,
        then ``value`` from every take; waiting publishes return ``False``.
        ``False`` if the hub already ended or shut down."""
        return _Sync(lambda: self.end_unsafe(value))

    def end_unsafe(self, value: A) -> bool:
        hub = self._hub
        if not hub.accepts():
            return False
        hub.ended = Some(value)
        if isinstance(hub.strategy, BackPressureStrategy):
            hub.strategy._end_publishers()
        hub.wake_takers()
        return True

    # --- subscribing ------------------------------------------------------

    def subscribe(self) -> Effect[Subscription[A], Never, Scope]:
        """Subscribe until the current scope closes (or the hub shuts down).
        The subscription reads the replayed messages, then everything
        published from now on."""
        hub = self._hub

        def body():
            local = yield from Scope()
            scope = yield from hub.scope.fork()
            reader = hub.subscribe()
            yield from scope.add_finalizer(
                lambda _: _WithFiber(lambda fiber: _Sync(lambda: hub.unsubscribe(reader, fiber.id)))
            )
            yield from local.add_finalizer(scope.close)
            return Subscription[A](hub, reader)

        return _Gen(body).uninterruptible()

    # --- lifecycle --------------------------------------------------------

    def shutdown(self) -> Effect[None]:
        """Unsubscribe everyone, interrupting their takes, then run the
        strategy's ``shutdown`` (a bounded hub interrupts the publishers
        still waiting). Later publishes return ``False``."""

        def body(fiber: Fiber[Any, Any]) -> Effect[None]:
            hub = self._hub
            if hub.is_shutdown:
                return _VOID
            hub.is_shutdown = True
            hub.shutdown_waiters.notify_all()
            return hub.scope.close(Failure(interrupt_cause(fiber.id))).and_then(
                _Suspend(lambda: hub.strategy.shutdown)
            )

        return _WithFiber(body).uninterruptible()

    def is_shutdown(self) -> Effect[bool]:
        return _Sync(self.is_shutdown_unsafe)

    def is_shutdown_unsafe(self) -> bool:
        return self._hub.is_shutdown

    def await_shutdown(self) -> Effect[None]:
        """Wait until the hub is shut down."""
        return _Suspend(lambda: self._hub.shutdown_waiters.wait(self.is_shutdown_unsafe))

    def size(self) -> Effect[int]:
        """How many messages are stored unread (0 once shut down)."""
        return _Sync(self.size_unsafe)

    def size_unsafe(self) -> int:
        return 0 if self._hub.is_shutdown else self._hub.atomic.size()

    def is_full(self) -> Effect[bool]:
        return _Sync(lambda: self.size_unsafe() == self.capacity)

    def is_empty(self) -> Effect[bool]:
        return _Sync(lambda: self.size_unsafe() == 0)


_TRUE: Effect[bool] = _Succeed(True)
_FALSE: Effect[bool] = _Succeed(False)
_VOID: Effect[None] = _Succeed(None)
