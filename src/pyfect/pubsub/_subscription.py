"""``Subscription[A]``: one subscriber's view of a ``PubSub``.

A subscription reads its replayed messages first, then what was published
after it subscribed. Once the hub has ended, a subscription that has read
everything gets the final message from every ``take`` (``take_up_to`` never
waits, so it gets nothing). Once unsubscribed (its scope closed, or the hub
shut down), every take is interrupted, but for one already woken with a
message, which gets it (Effect runs that take before the unsubscribe).

The subscription only gives ``A``s, so it is covariant (Effect's ``out
A``): its state is kept as ``Any`` and typed by the methods, and batches
are typed ``Sequence`` (they are lists).
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator, Sequence
from typing import TYPE_CHECKING, Any, Never, cast

from pyfect._core import (
    WOKEN,
    Effect,
    Frame,
    Step,
    _Callback,
    _FailCause,
    _Gen,
    _Succeed,
    _Suspend,
    _Sync,
    _WithFiber,
)
from pyfect._waiters import unlocked
from pyfect.cause import Cause
from pyfect.cause import interrupt as interrupt_cause
from pyfect.exit import Failure, Success
from pyfect.pubsub._hub import Hub, Reader
from pyfect.pubsub._strategy import _FAILED, _RESERVED, Poller

if TYPE_CHECKING:
    from pyfect._fiber import Fiber


def _identity[T](value: T) -> T:
    return value


def _interrupt() -> Effect[Never]:
    return _WithFiber(lambda fiber: _FailCause(interrupt_cause(fiber.id)))


class Subscription[A]:
    __slots__ = ("_hub", "_reader")

    def __init__(self, hub: Hub[Any], reader: Reader[Any]) -> None:
        self._hub = hub
        self._reader = reader

    def take(self) -> Effect[A]:
        """Wait for the next message."""
        reader = self._reader
        hub = self._hub

        def attempt() -> Effect[A]:
            with hub.lock:
                if reader.unsubscribed:
                    return _interrupt()
                replayed = reader.replay.take()
                if replayed is not None:
                    return _Succeed(replayed.value)
                polled = reader.poll_up_to(1)
                if polled:
                    hub.on_empty_space()
                    return _Succeed(polled[0])
                if hub.ended is not None:
                    return _Succeed(hub.ended.value)
            return self._park(_identity, attempt)

        return _Suspend(attempt)

    def take_all(self) -> Effect[Sequence[A]]:
        """Wait for at least one message, then take every one there is."""
        reader = self._reader
        hub = self._hub

        def more(first: A) -> list[A]:
            # Called by ``_Collect`` holding the hub's lock.
            rest = reader.poll_up_to(reader.backing.size())
            hub.on_empty_space()
            return [first, *rest]

        def attempt() -> Effect[list[A]]:
            with hub.lock:
                if reader.unsubscribed:
                    return _interrupt()
                polled = reader.poll_up_to(reader.backing.size())
                hub.on_empty_space()
                if reader.replay.remaining:
                    return _Succeed(reader.replay.take_all() + polled)
                if polled:
                    return _Succeed(polled)
                if hub.ended is not None:
                    return _Succeed([hub.ended.value])
            return self._park(more, attempt)

        return _Suspend(attempt)

    def take_up_to(self, n: int) -> Effect[Sequence[A]]:
        """Take up to ``n`` messages without waiting (none if ``n`` is 0 or
        less, or while other takes wait)."""
        reader = self._reader
        hub = self._hub

        def attempt() -> Effect[list[A]]:
            with hub.lock:
                if reader.unsubscribed:
                    return _interrupt()
                limit = max(n, 0)
                if reader.replay.remaining >= limit:
                    return _Succeed(reader.replay.take_n(limit))
                replayed = reader.replay.take_all()
                polled = reader.poll_up_to(limit - len(replayed))
                hub.on_empty_space()
                return _Succeed(replayed + polled)

        return _Suspend(attempt)

    def take_between(self, minimum: int, maximum: int) -> Effect[Sequence[A]]:
        """Take at least ``minimum`` and at most ``maximum`` messages, waiting
        for the minimum. Nothing, at once, if ``maximum < minimum``."""

        def body() -> Generator[Effect[Any], Any, list[A]]:
            low, high = max(minimum, 0), max(maximum, 0)
            out: list[A] = []
            while high >= low:
                taken: Sequence[A] = yield self.take_up_to(high)
                out.extend(taken)
                missing = low - len(taken)
                if missing <= 0:
                    break
                out.append((yield self.take()))
                low, high = missing - 1, high - len(taken) - 1
                if low == 0:
                    break
            return out

        return _Gen(body)

    def remaining(self) -> Effect[int]:
        """How many messages there are to take now."""

        def attempt() -> Effect[int]:
            count = self.remaining_unsafe()
            return _interrupt() if count is None else _Succeed(count)

        return _Suspend(attempt)

    def remaining_unsafe(self) -> int | None:
        """``remaining`` now; ``None`` once unsubscribed."""
        reader = self._reader
        with self._hub.lock:
            if reader.unsubscribed:
                return None
            return reader.backing.size() + reader.replay.remaining

    def _park[X](self, then: Callable[[A], X], again: Callable[[], Effect[X]]) -> Effect[X]:
        """Wait behind the takes already parked (Effect's ``pollForItem``).
        Given a message, end with ``then(message)``; woken without one (the
        hub ended), look again with ``again()``."""
        reader = self._reader
        hub = self._hub
        pollers = reader.pollers
        poller = Poller(pollers)
        lock = hub.lock

        def register(resume: Callable[[Effect[None]], None]) -> Effect[None] | None:
            with lock:
                if reader.unsubscribed or hub.ended is not None:
                    resume(_VOID)
                    return None
                # Woken holding the hub's lock, which it lets go meanwhile. The
                # message waits in the subscription (``_Collect``), so an interrupt
                # reaching the take first still wins.
                poller._wake = lambda: unlocked(lock, [lambda: resume(WOKEN)])
                subscribers = hub.subscribers
                if reader.backing not in subscribers:
                    subscribers[reader.backing] = pollers
                pollers.append(poller)
                hub.strategy.complete_pollers_unsafe(
                    hub.atomic, subscribers, reader.backing, pollers
                )
            return _Sync(lambda: self._leave(poller))

        def run(fiber: Fiber[Any, Any]) -> Effect[None]:
            fiber._push(_Collect(hub, reader, poller, then, again))
            return _Callback(register)

        return cast("Effect[X]", _WithFiber(run))

    def _leave(self, poller: Poller[Any]) -> None:
        with self._hub.lock:
            self._reader.pollers._remove(poller)


_VOID: Effect[None] = _Succeed(None)


class _Collect[A, X](Frame):
    """Below a parked take. Given a message, collect it in this same step,
    so no interrupt can land between collecting and returning it. Failing
    before that (interrupted while parked, or given a message and
    interrupted before collecting), give the message back to the
    subscription for the next take."""

    __slots__ = ("again", "hub", "poller", "reader", "then")
    # Collecting claims the message; it reaches the caller with no pause.
    claims = True

    def __init__(
        self,
        hub: Hub[A],
        reader: Reader[A],
        poller: Poller[A],
        then: Callable[[A], X],
        again: Callable[[], Effect[X]],
    ) -> None:
        self.hub = hub
        self.reader = reader
        self.poller = poller
        self.then = then
        self.again = again

    def _on_success(self, value: Any, fiber: Fiber[Any, Any]) -> Step:
        poller = self.poller
        with self.hub.lock:
            state = poller._finish()
            if state == _RESERVED:
                return Success(self.then(self.reader.pollers._collect()))
        if state == _FAILED:
            return Failure(cast("Cause[Any]", poller._cause))
        return self.again()

    def _on_failure(self, cause: Cause[Any], fiber: Fiber[Any, Any]) -> Step:
        hub = self.hub
        with hub.lock:
            if self.poller._finish() == _RESERVED:
                reader = self.reader
                reader.pollers._release()
                hub.strategy.complete_pollers_unsafe(
                    hub.atomic, hub.subscribers, reader.backing, reader.pollers
                )
        return Failure(cause)
