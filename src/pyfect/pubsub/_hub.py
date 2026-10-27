"""The state a ``PubSub`` shares with its subscriptions.

A parked publish owns its surplus items. The hub admits them into the store
as space frees, oldest publish first, and resumes the publisher once all of
them are in (Effect's ``BackPressureStrategy``). An interrupted publisher
withdraws what was not admitted and has delivered the rest.

As in Effect, the takes waiting on a subscription are served in the order
they parked, and a message published while one waits is read for it at
once, so it no longer takes room in the store. It is not handed to the
waiting fiber: it moves to the subscription's ``claimed`` buffer and the
fiber is woken to collect it. A take that does not wait never reads a
claimed message meant for a woken one. If the woken fiber is interrupted
before it collects, the message passes to the next waiting take (or the
next take), so nothing is lost.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from pyfect._core import Effect, _Succeed, _Sync  # pyright: ignore[reportPrivateUsage]
from pyfect._waiters import WaitList
from pyfect.option import Option
from pyfect.pubsub._atomic import Atomic, BackingSubscription
from pyfect.pubsub._replay import ReplayWindow
from pyfect.queue import Strategy
from pyfect.scope import CloseableScope


@dataclass(eq=False, slots=True)
class Publish[A]:
    """A parked publish. ``items[admitted:]`` are still waiting."""

    items: list[A]
    resume: Callable[[Effect[bool]], None]
    admitted: int = 0


@dataclass(eq=False, slots=True)
class Ticket:
    """A parked take. ``claimed`` once a message was read for it; it is
    woken without one when the hub ends or the subscription closes."""

    wake: Callable[[], None]
    claimed: bool = False


@dataclass(eq=False, slots=True)
class Reader[A]:
    """One subscription's state. A take that does not wait reads ``replay``,
    then the spare ``claimed`` messages (those no woken take is owed), then
    ``backing``."""

    backing: BackingSubscription[A]
    replay: ReplayWindow[A]
    waiting: deque[Ticket] = field(default_factory=deque[Ticket])
    claimed: deque[A] = field(default_factory=deque[A])
    # Woken tickets that have not collected their message yet.
    owed: int = 0
    unsubscribed: bool = False
    # The fiber that unsubscribed; it interrupts the takes then waiting.
    closed_by: int | None = None

    def size(self) -> int:
        """What a take that does not wait can read now."""
        return len(self.claimed) - self.owed + self.backing.size()

    def read_up_to(self, n: int) -> list[A]:
        """Read up to ``n`` messages for a take that does not wait. Messages
        owed to woken takes are not read; while takes wait there is nothing
        else (``dispatch`` gave it to them)."""
        if n <= 0:
            return []
        spare = min(n, len(self.claimed) - self.owed)
        out = [self.claimed.popleft() for _ in range(spare)]
        return out + self.backing.poll_up_to(n - spare)

    def collect(self, ticket: Ticket) -> A:
        """The message read for a woken ``ticket``."""
        ticket.claimed = False
        self.owed -= 1
        return self.claimed.popleft()

    def release(self, ticket: Ticket) -> bool:
        """A take ended without collecting: its message is spare again.
        Whether there was one."""
        if not ticket.claimed or self.unsubscribed:
            return False
        ticket.claimed = False
        self.owed -= 1
        return True

    def discard(self, ticket: Ticket) -> None:
        if ticket in self.waiting:
            self.waiting.remove(ticket)

    def dispatch(self) -> None:
        """Give each waiting take, oldest first, a message to collect."""
        while self.waiting:
            if len(self.claimed) == self.owed:
                polled = self.backing.poll()
                if polled is None:
                    return
                self.claimed.append(polled.value)
            ticket = self.waiting.popleft()
            ticket.claimed = True
            self.owed += 1
            ticket.wake()

    def wake_all(self) -> None:
        """Wake every waiting take without a message, to look again."""
        tickets, self.waiting = self.waiting, deque[Ticket]()
        for ticket in tickets:
            ticket.wake()


class Hub[A]:
    __slots__ = (
        "atomic",
        "ended",
        "is_shutdown",
        "publishers",
        "readers",
        "scope",
        "shutdown_waiters",
        "strategy",
    )

    def __init__(self, atomic: Atomic[A], strategy: Strategy) -> None:
        self.atomic = atomic
        self.strategy: Strategy = strategy
        self.publishers: deque[Publish[A]] = deque()
        self.readers: dict[Reader[A], None] = {}
        self.shutdown_waiters = WaitList()
        # Subscriptions are closed with this scope.
        self.scope = CloseableScope()
        self.ended: Option[A] = None
        self.is_shutdown = False

    def accepts(self) -> bool:
        """Whether a publish can still deliver."""
        return not self.is_shutdown and self.ended is None

    def subscribe(self) -> Reader[A]:
        reader = Reader(self.atomic.subscribe(), self.atomic.replay_window())
        self.readers[reader] = None
        return reader

    def unsubscribe(self, reader: Reader[A], by: int) -> None:
        if reader.unsubscribed:
            return
        reader.unsubscribed = True
        reader.closed_by = by
        del self.readers[reader]
        if reader.owed:
            # Effect runs a woken take before the unsubscribe goes on, so
            # it still gets its message and, for a batch, what is left.
            reader.claimed.extend(reader.backing.poll_up_to(reader.backing.size()))
        else:
            reader.claimed.clear()
        reader.backing.unsubscribe()
        reader.replay.close()
        reader.wake_all()
        self.deliver()

    def deliver(self) -> None:
        """Read new messages for waiting takes and admit parked publishes
        into the room that frees, until neither makes progress (Effect's
        ``completeSubscribers`` and ``onPubSubEmptySpace``); then resume the
        publishers that are done."""
        done: list[Publish[A]] = []
        while True:
            for reader in self.readers:
                reader.dispatch()
            if not self._admit(done):
                break
        for entry in done:
            entry.resume(_Succeed(True))

    def wake_takers(self) -> None:
        """The hub ended: every waiting take looks again."""
        for reader in self.readers:
            reader.wake_all()

    def _admit(self, done: list[Publish[A]]) -> bool:
        admitted = False
        while self.publishers and not self.atomic.is_full():
            entry = self.publishers[0]
            self.atomic.publish(entry.items[entry.admitted])
            entry.admitted += 1
            admitted = True
            if entry.admitted == len(entry.items):
                done.append(self.publishers.popleft())
        return admitted

    def park(self, entry: Publish[A]) -> Effect[None]:
        """Queue a publish's surplus; the canceler withdraws it."""
        self.publishers.append(entry)
        return _Sync(lambda: self._withdraw(entry))

    def _withdraw(self, entry: Publish[A]) -> None:
        if entry in self.publishers:
            self.publishers.remove(entry)

    def reject_publishers(self) -> None:
        """The hub ended: every parked publish returns ``False``."""
        entries, self.publishers = self.publishers, deque[Publish[A]]()
        for entry in entries:
            entry.resume(_Succeed(False))
