"""``Strategy``: how a ``PubSub`` handles a full store and wakes the takes
waiting on it (Effect's ``PubSub.Strategy``), and what a strategy works on.

A strategy sees the store (``Atomic``), the subscriptions with parked takes
(``Subscribers``: each ``BackingSubscription`` with its ``Pollers``) and,
for a publish that did not fit, the surplus messages. Where Effect's
strategy completes a parked take's ``Deferred`` with a message, a pyfect
strategy calls ``poller.succeed(message)``: the message is kept for that
take on its subscription, the take is woken, and it collects the message in
the step it resumes. A take interrupted before collecting gives it back to
its subscription, to be read first, so a woken take never loses a message.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Iterator, MutableMapping
from typing import Never, Protocol

from pyfect._core import Effect
from pyfect.cause import Cause
from pyfect.exit import Exit, Success
from pyfect.option import Option
from pyfect.pubsub._atomic import Atomic, BackingSubscription

_PENDING = 0
_RESERVED = 1
_FAILED = 2
_RETRY = 3
_FINISHED = 4


def _not_parked() -> None:
    pass


class Poller[A]:
    """One parked take (Effect's ``Deferred`` in a pollers list)."""

    __slots__ = ("_cause", "_pollers", "_state", "_wake")

    def __init__(self, pollers: Pollers[A]) -> None:
        self._pollers = pollers
        self._wake: Callable[[], None] = _not_parked
        self._state = _PENDING
        self._cause: Cause[Never] | None = None

    def succeed(self, value: A) -> bool:
        """Give the take ``value`` and wake it. ``False``, keeping nothing,
        if the take was already completed or has ended."""
        if self._state != _PENDING:
            return False
        self._pollers._reserved.append(value)
        self._state = _RESERVED
        self._wake()
        return True

    def done(self, exit: Exit[A, Never]) -> bool:
        """End the take with ``exit``: ``succeed`` its value, or fail it
        with its cause (an interrupt, a defect)."""
        if isinstance(exit, Success):
            return self.succeed(exit.value)
        if self._state != _PENDING:
            return False
        self._cause = exit.cause
        self._state = _FAILED
        self._wake()
        return True

    # --- for the take and the hub -----------------------------------------

    def _retry(self) -> None:
        """Wake the take to look again (the hub ended)."""
        if self._state == _PENDING:
            self._state = _RETRY
            self._wake()

    def _finish(self) -> int:
        """The take resumed or failed; what it had been given."""
        state, self._state = self._state, _FINISHED
        return state


class Pollers[A]:
    """The takes parked on one subscription, oldest first (Effect's
    ``MutableList<Deferred<A>>``), and the messages given to woken ones
    that have not collected them yet."""

    __slots__ = ("_reserved", "_subscription", "_waiting")

    def __init__(self, subscription: BackingSubscription[A]) -> None:
        self._subscription = subscription
        self._waiting: deque[Poller[A]] = deque()
        self._reserved: deque[A] = deque()

    def __len__(self) -> int:
        return len(self._waiting)

    def take(self) -> Poller[A] | None:
        """Remove and return the oldest parked take, if any."""
        return self._waiting.popleft() if self._waiting else None

    def prepend(self, poller: Poller[A]) -> None:
        self._waiting.appendleft(poller)

    def append(self, poller: Poller[A]) -> None:
        self._waiting.append(poller)

    # --- for the take and the hub -----------------------------------------

    def _remove(self, poller: Poller[A]) -> None:
        if poller in self._waiting:
            self._waiting.remove(poller)

    def _take_all(self) -> list[Poller[A]]:
        waiting, self._waiting = list(self._waiting), deque[Poller[A]]()
        return waiting

    def _collect(self) -> A:
        return self._reserved.popleft()

    def _release(self) -> None:
        """A woken take ended without collecting: the newest kept message
        goes back to the front of the subscription (the older ones are
        still owed to the takes woken before)."""
        self._subscription._give_back(self._reserved.pop())


class Subscribers[A](MutableMapping[BackingSubscription[A], Pollers[A]]):
    """The subscriptions with parked takes (Effect's ``PubSub.Subscribers``,
    one ``Pollers`` per subscription). Iteration is live, as a JavaScript
    ``Map``'s: in insertion order, seeing entries added meanwhile and
    skipping removed ones, as a woken take may subscribe or park again."""

    __slots__ = ("_entries", "_next")

    def __init__(self) -> None:
        self._entries: dict[BackingSubscription[A], tuple[int, Pollers[A]]] = {}
        self._next = 0

    def __getitem__(self, key: BackingSubscription[A]) -> Pollers[A]:
        return self._entries[key][1]

    def __setitem__(self, key: BackingSubscription[A], value: Pollers[A]) -> None:
        entry = self._entries.get(key)
        if entry is None:
            self._entries[key] = (self._next, value)
            self._next += 1
        else:
            self._entries[key] = (entry[0], value)

    def __delitem__(self, key: BackingSubscription[A]) -> None:
        del self._entries[key]

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: object) -> bool:
        return key in self._entries

    def __iter__(self) -> Iterator[BackingSubscription[A]]:
        entries = self._entries
        seen = -1
        while entries:
            last = seen
            for key, (order, _) in list(entries.items()):
                current = entries.get(key)
                if order > seen and current is not None and current[0] == order:
                    seen = order
                    yield key
            if seen == last:
                return

    def clear(self) -> None:
        self._entries.clear()


class Strategy[A](Protocol):
    """How a ``PubSub`` handles messages that do not fit and wakes parked
    takes (Effect's ``PubSub.Strategy``). ``BackPressureStrategy``,
    ``DroppingStrategy`` and ``SlidingStrategy`` implement it; so can user
    code. Subclassing it inherits the two ``complete_*`` hooks as the
    built-ins have them."""

    @property
    def shutdown(self) -> Effect[None]:
        """Run after the hub shut down and unsubscribed everyone."""
        ...

    def handle_surplus(
        self,
        pubsub: Atomic[A],
        subscribers: Subscribers[A],
        elements: Iterable[A],
        is_shutdown: Callable[[], bool],
        ended: Callable[[], Option[A]],
    ) -> Effect[bool]:
        """A publish's ``elements`` did not fit. The publisher may have
        yielded since ``publish`` checked ``ended()``, so check it again
        before parking or publishing the surplus."""
        ...

    def on_pubsub_empty_space_unsafe(self, pubsub: Atomic[A], subscribers: Subscribers[A]) -> None:
        """A subscriber read, so the store may have room."""
        ...

    def complete_pollers_unsafe(
        self,
        pubsub: Atomic[A],
        subscribers: Subscribers[A],
        subscription: BackingSubscription[A],
        pollers: Pollers[A],
    ) -> None:
        """Give ``subscription``'s messages to its parked takes."""
        while not subscription.is_empty():
            poller = pollers.take()
            if poller is None:
                subscribers.pop(subscription, None)
                return
            polled = subscription.poll()
            if polled is None:
                pollers.prepend(poller)
            else:
                poller.succeed(polled.value)
                self.on_pubsub_empty_space_unsafe(pubsub, subscribers)

    def complete_subscribers_unsafe(self, pubsub: Atomic[A], subscribers: Subscribers[A]) -> None:
        """New messages were stored: give them to the parked takes."""
        for subscription in subscribers:
            pollers = subscribers.get(subscription)
            if pollers is not None:
                self.complete_pollers_unsafe(pubsub, subscribers, subscription, pollers)
