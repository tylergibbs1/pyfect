"""The built-in strategies (Effect's ``BackPressureStrategy``,
``DroppingStrategy`` and ``SlidingStrategy``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal

from pyfect._core import Effect, _Callback, _FailCause, _Succeed, _Sync, _WithFiber
from pyfect._fiber import _MAX_NESTED_RUNS, Fiber
from pyfect._waiters import Lock, unlocked
from pyfect.cause import interrupt as interrupt_cause
from pyfect.option import Option
from pyfect.pubsub._atomic import Atomic
from pyfect.pubsub._strategy import Strategy, Subscribers

_TRUE: Effect[bool] = _Succeed(True)
_FALSE: Effect[bool] = _Succeed(False)
_VOID: Effect[None] = _Succeed(None)


def _interrupt_self() -> Effect[bool]:
    return _WithFiber(lambda fiber: _FailCause(interrupt_cause(fiber.id)))


@dataclass(eq=False, slots=True)
class _Publish[A]:
    """A parked publish (Effect keeps one ``(value, deferred, last)`` entry
    per message). ``items[admitted:]`` still wait. ``outcome`` is set when
    it ended before its fiber was resumable. ``lock`` is the hub's."""

    items: list[A]
    lock: Lock
    admitted: int = 0
    resume: Callable[[Effect[bool]], None] | None = None
    outcome: Effect[bool] | None = None

    def complete(self, outcome: Effect[bool]) -> None:
        """Call holding ``lock``; it is let go while the publisher resumes."""
        resume = self.resume
        if resume is None:
            self.outcome = outcome
        else:
            unlocked(self.lock, [lambda: resume(outcome)])


class BackPressureStrategy[A](Strategy[A]):
    """Publishers wait until every message they publish fits, oldest
    publish first; a slow subscriber slows everyone."""

    __slots__ = ("_depth", "_lock", "publishers")

    def __init__(self) -> None:
        self.publishers: deque[_Publish[A]] = deque()
        # Nested ``on_pubsub_empty_space_unsafe`` calls.
        self._depth = 0
        # The hub's lock, known once a publisher has parked.
        self._lock: Lock | None = None

    @property
    def shutdown(self) -> Effect[None]:
        """Interrupt the publishers still waiting."""

        def interrupt_all(fiber: Fiber[Any, Any]) -> Effect[None]:
            # The hub is shut down, so no publisher parks from now on.
            lock = self._lock
            if lock is None:
                return _VOID
            with lock:
                entries, self.publishers = self.publishers, deque[_Publish[A]]()
                for entry in entries:
                    entry.complete(_FailCause(interrupt_cause(fiber.id)))
            return _VOID

        return _WithFiber(interrupt_all)

    def handle_surplus(
        self,
        pubsub: Atomic[A],
        subscribers: Subscribers[A],
        elements: Iterable[A],
        is_shutdown: Callable[[], bool],
        ended: Callable[[], Option[A]],
    ) -> Effect[bool]:
        def register(resume: Callable[[Effect[bool]], None]) -> Effect[None] | None:
            with pubsub._lock:
                self._lock = pubsub._lock
                # ``end`` only rejects publishers already waiting.
                if ended() is not None:
                    resume(_FALSE)
                    return None
                entry = _Publish(list(elements), pubsub._lock)
                if entry.items:
                    self.publishers.append(entry)
                else:
                    entry.outcome = _TRUE
                self.on_pubsub_empty_space_unsafe(pubsub, subscribers)
                self.complete_subscribers_unsafe(pubsub, subscribers)
                if is_shutdown():
                    self._remove(entry)
                    resume(_interrupt_self())
                    return None
                if entry.outcome is not None:
                    resume(entry.outcome)
                    return None
                entry.resume = resume
            return _Sync(lambda: self._leave(entry))

        return _Callback(register)

    def on_pubsub_empty_space_unsafe(self, pubsub: Atomic[A], subscribers: Subscribers[A]) -> None:
        """Admit parked publishes into the room there is. Giving a message to
        a parked take can free room and call this again, as in Effect, which
        recurses once per message and overflows its stack. Here a call
        ``_MAX_NESTED_RUNS`` deep does nothing: it runs inside the loop below
        of the call at that depth, which looks for room again next."""
        if not self.publishers or self._depth >= _MAX_NESTED_RUNS:
            return
        self._depth += 1
        try:
            self._admit(pubsub, subscribers)
        finally:
            self._depth -= 1

    def _admit(self, pubsub: Atomic[A], subscribers: Subscribers[A]) -> None:
        # ``self.publishers`` is read again after each resume: a run on
        # another thread may have ended or shut the hub down meanwhile.
        while (publishers := self.publishers) and not pubsub.is_full():
            entry = publishers[0]
            published = pubsub.publish(entry.items[entry.admitted])
            last = False
            if published:
                entry.admitted += 1
                last = entry.admitted == len(entry.items)
                if last:
                    publishers.popleft()
            self.complete_subscribers_unsafe(pubsub, subscribers)
            # Resuming the publisher can end the hub at once, so the parked
            # takes are given their messages first.
            if last:
                entry.complete(_TRUE)

    def _remove(self, entry: _Publish[A]) -> None:
        if entry in self.publishers:
            self.publishers.remove(entry)

    def _leave(self, entry: _Publish[A]) -> None:
        with entry.lock:
            self._remove(entry)

    def _end_publishers(self) -> None:
        """The hub ended: every waiting publish returns ``False``."""
        entries, self.publishers = self.publishers, deque[_Publish[A]]()
        for entry in entries:
            entry.complete(_FALSE)


class DroppingStrategy[A](Strategy[A]):
    """A publish to a full hub drops the messages that do not fit and
    returns ``False``."""

    __slots__ = ()

    @property
    def shutdown(self) -> Effect[None]:
        return _VOID

    def handle_surplus(
        self,
        pubsub: Atomic[A],
        subscribers: Subscribers[A],
        elements: Iterable[A],
        is_shutdown: Callable[[], bool],
        ended: Callable[[], Option[A]],
    ) -> Effect[bool]:
        return _FALSE

    def on_pubsub_empty_space_unsafe(self, pubsub: Atomic[A], subscribers: Subscribers[A]) -> None:
        pass


class SlidingStrategy[A](Strategy[A]):
    """A publish to a full hub drops the oldest stored message for each
    message that does not fit."""

    __slots__ = ()

    @property
    def shutdown(self) -> Effect[None]:
        return _VOID

    def handle_surplus(
        self,
        pubsub: Atomic[A],
        subscribers: Subscribers[A],
        elements: Iterable[A],
        is_shutdown: Callable[[], bool],
        ended: Callable[[], Option[A]],
    ) -> Effect[bool]:
        def publish() -> bool:
            with pubsub._lock:
                if ended() is not None:
                    return False
                for item in elements:
                    pubsub.slide()
                    while not pubsub.publish(item):
                        pubsub.slide()
                self.complete_subscribers_unsafe(pubsub, subscribers)
                return True

        return _Sync(publish)

    def on_pubsub_empty_space_unsafe(self, pubsub: Atomic[A], subscribers: Subscribers[A]) -> None:
        pass


type StrategyName = Literal["suspend", "dropping", "sliding"]
"""The built-in strategies by name (``pyfect.queue.Strategy``)."""


BUILT_IN: dict[StrategyName, Callable[[], Strategy[Any]]] = {
    "suspend": BackPressureStrategy,
    "dropping": DroppingStrategy,
    "sliding": SlidingStrategy,
}
"""A new built-in strategy by name."""
