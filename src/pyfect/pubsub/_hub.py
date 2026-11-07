"""The state a ``PubSub`` shares with its subscriptions.

The hub's ``Strategy`` decides what a publish that does not fit does and
gives stored messages to parked takes (see ``_strategy.py``). As in Effect,
the takes parked on a subscription are served in the order they parked, a
message published while one waits is given to it at once (so it no longer
takes room in the store), and a take that does not wait never reads past a
parked one.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from dataclasses import dataclass, field

from pyfect._waiters import WaitList
from pyfect.cause import interrupt as interrupt_cause
from pyfect.exit import Failure
from pyfect.option import Option
from pyfect.pubsub._atomic import Atomic, BackingSubscription
from pyfect.pubsub._replay import ReplayWindow
from pyfect.pubsub._strategy import Pollers, Strategy, Subscribers
from pyfect.scope import CloseableScope


@dataclass(eq=False, slots=True)
class Reader[A]:
    """One subscription's state."""

    backing: BackingSubscription[A]
    replay: ReplayWindow[A]
    pollers: Pollers[A]
    unsubscribed: bool = False
    # What a woken batch take still reads once unsubscribed (Effect runs a
    # woken take before the unsubscribe goes on).
    leftover: list[A] = field(default_factory=list[A])

    def poll_up_to(self, n: int) -> list[A]:
        """Up to ``n`` messages for a take, none while takes are parked."""
        if self.unsubscribed:
            rest, self.leftover = self.leftover, []
            return rest
        return [] if self.pollers else self.backing.poll_up_to(n)


class Hub[A]:
    __slots__ = (
        "atomic",
        "ended",
        "is_shutdown",
        "scope",
        "shutdown_waiters",
        "strategy",
        "subscribers",
    )

    def __init__(self, atomic: Atomic[A], strategy: Strategy[A]) -> None:
        self.atomic = atomic
        self.strategy = strategy
        self.subscribers = Subscribers[A]()
        self.shutdown_waiters = WaitList()
        # Subscriptions are closed with this scope.
        self.scope = CloseableScope()
        self.ended: Option[A] = None
        self.is_shutdown = False

    def accepts(self) -> bool:
        """Whether a publish can still deliver."""
        return not self.is_shutdown and self.ended is None

    def is_shutdown_now(self) -> bool:
        return self.is_shutdown

    def ended_now(self) -> Option[A]:
        return self.ended

    def complete_subscribers(self) -> None:
        self.strategy.complete_subscribers_unsafe(self.atomic, self.subscribers)

    def on_empty_space(self) -> None:
        self.strategy.on_pubsub_empty_space_unsafe(self.atomic, self.subscribers)

    def subscribe(self) -> Reader[A]:
        backing = self.atomic.subscribe()
        return Reader(backing, self.atomic.replay_window(), Pollers(backing))

    def unsubscribe(self, reader: Reader[A], by: int) -> None:
        """Interrupt the parked takes (by fiber ``by``), then leave."""
        if reader.unsubscribed:
            return
        reader.unsubscribed = True
        pollers = reader.pollers
        if pollers._reserved:
            reader.leftover = reader.backing.poll_all()
        interrupted = Failure(interrupt_cause(by))
        for poller in pollers._take_all():
            poller.done(interrupted)
        self.subscribers.pop(reader.backing, None)
        reader.backing.unsubscribe()
        reader.replay.close()
        self.on_empty_space()

    def wake_takers(self) -> None:
        """The hub ended: every parked take looks again."""
        for subscription in self.subscribers:
            pollers = self.subscribers.get(subscription)
            if pollers is not None:
                for poller in pollers._take_all():
                    poller._retry()
        self.subscribers.clear()
