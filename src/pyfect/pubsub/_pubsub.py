"""``PubSub[A]`` itself. See the package docstring for its behavior."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Never

from pyfect._core import Effect, _Callback, _Gen, _Succeed, _Suspend, _Sync, _WithFiber
from pyfect._fiber import Fiber
from pyfect.cause import interrupt as interrupt_cause
from pyfect.exit import Failure
from pyfect.option import Some
from pyfect.pubsub._atomic import Atomic
from pyfect.pubsub._hub import Hub, Publish
from pyfect.pubsub._subscription import Subscription
from pyfect.queue import Strategy
from pyfect.scope import Scope


class PubSub[A]:
    __slots__ = ("_hub",)

    def __init__(self, atomic: Atomic[A], strategy: Strategy) -> None:
        self._hub = Hub(atomic, strategy)

    @staticmethod
    def make[T](atomic: Callable[[], Atomic[T]], strategy: Strategy) -> Effect[PubSub[T]]:
        """A hub over the store ``atomic()`` builds, handling a full store by
        ``strategy`` (Effect's ``make``, with the built-in strategies)."""
        return _Sync(lambda: PubSub(atomic(), strategy))

    @classmethod
    def bounded(cls, capacity: int | None, *, replay: int | None = None) -> Effect[PubSub[A]]:
        """Publishers wait while ``capacity`` messages are unread. ``replay``
        messages are kept for new subscribers. A capacity below 1 is a
        defect; ``None`` is unbounded."""
        return _Sync(lambda: cls(Atomic(capacity, replay), "suspend"))

    @classmethod
    def dropping(cls, capacity: int | None, *, replay: int | None = None) -> Effect[PubSub[A]]:
        """A publish to a full hub drops the message and returns ``False``."""
        return _Sync(lambda: cls(Atomic(capacity, replay), "dropping"))

    @classmethod
    def sliding(cls, capacity: int | None, *, replay: int | None = None) -> Effect[PubSub[A]]:
        """A publish to a full hub drops the oldest unread message."""
        return _Sync(lambda: cls(Atomic(capacity, replay), "sliding"))

    @classmethod
    def unbounded(cls, *, replay: int | None = None) -> Effect[PubSub[A]]:
        return _Sync(lambda: cls(Atomic(None, replay), "dropping"))

    @property
    def capacity(self) -> int | None:
        """How many unread messages the hub holds; ``None`` if unbounded."""
        return self._hub.atomic.capacity

    # --- publishing -------------------------------------------------------

    def publish(self, value: A) -> Effect[bool]:
        """Publish to every current subscriber. ``False`` if the hub ended or
        shut down, or a dropping hub is full; a bounded hub waits for room."""

        def register(resume: Callable[[Effect[bool]], None]) -> Effect[None] | None:
            hub = self._hub
            if self.publish_unsafe(value):
                resume(_Succeed(True))
            elif not hub.accepts() or hub.strategy == "dropping":
                resume(_Succeed(False))
            elif hub.strategy == "sliding":
                resume(_Succeed(self._slide_in([value])))
            else:
                return self._park([value], resume)
            return None

        return _Callback(register)

    def publish_unsafe(self, value: A) -> bool:
        """Publish without waiting, sliding or dropping: ``False`` if the
        store is full. Call on the scheduler thread of the hub's fibers."""
        hub = self._hub
        if not hub.accepts() or not hub.atomic.publish(value):
            return False
        hub.deliver()
        return True

    def publish_all(self, items: Iterable[A]) -> Effect[bool]:
        """Publish ``items`` in order; ``True`` if every one was published.
        A bounded hub publishes what fits and waits to publish the rest."""

        def register(resume: Callable[[Effect[bool]], None]) -> Effect[None] | None:
            hub = self._hub
            if not hub.accepts():
                resume(_Succeed(False))
                return None
            surplus = hub.atomic.publish_all(items)
            hub.deliver()
            if not surplus:
                resume(_Succeed(True))
            elif hub.strategy == "dropping":
                resume(_Succeed(False))
            elif hub.strategy == "sliding":
                resume(_Succeed(self._slide_in(surplus)))
            else:
                return self._park(surplus, resume)
            return None

        return _Callback(register)

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
        hub.reject_publishers()
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
        """Unsubscribe everyone, interrupting their takes. Later publishes
        return ``False``. Waiting publishes complete: with nobody subscribed
        the store empties and admits them (as in Effect, whose strategy
        shutdown then finds no publisher left to interrupt)."""

        def body(fiber: Fiber[Any, Any]) -> Effect[None]:
            hub = self._hub
            if hub.is_shutdown:
                return _Succeed(None)
            hub.is_shutdown = True
            hub.shutdown_waiters.notify_all()
            return hub.scope.close(Failure(interrupt_cause(fiber.id)))

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

    # --- internals --------------------------------------------------------

    def _park(self, surplus: list[A], resume: Callable[[Effect[bool]], None]) -> Effect[None]:
        """Wait to publish ``surplus``. Room a waiting subscriber freed is
        filled at once, as Effect's ``handleSurplus`` does."""
        canceler = self._hub.park(Publish(surplus, resume))
        self._hub.deliver()
        return canceler

    def _slide_in(self, items: list[A]) -> bool:
        """Publish each item after dropping the oldest stored message, as
        Effect's ``SlidingStrategy`` does (also when a waiting subscriber
        has just read one and made room)."""
        atomic = self._hub.atomic
        for item in items:
            atomic.slide()
            atomic.publish(item)
        self._hub.deliver()
        return True
