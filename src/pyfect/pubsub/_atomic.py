"""``Atomic``: the message store under a ``PubSub``, with no waiting.

Each published message is stored once with a count of the subscribers that
still have to read it, and dropped when the count reaches 0. A message
published while nobody is subscribed is not stored (only replayed). A
subscriber reads messages published after it subscribed, in order.

Counts reach 0 oldest first: every subscriber still owing a message also
owes every later one. So the store is a deque whose head is the oldest
message anyone still has to read, and ``slide`` drops that head for
everyone.

Effect's bounded variants (single slot, power of two, arbitrary ring) and
its unbounded linked list behave alike; one deque with an optional capacity
does for all of them.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

from pyfect.option import Option, Some
from pyfect.pubsub._replay import ReplayBuffer, ReplayWindow


@dataclass(eq=False, slots=True)
class _Slot[A]:
    value: A
    unread: int
    replay_index: int


class Atomic[A]:
    """A store of messages for a set of subscribers. Its methods take no
    lock: a ``PubSub`` over it holds ``_lock`` around every use, so runs on
    several threads can share the hub."""

    __slots__ = ("_capacity", "_lock", "_replay", "_slots", "_start", "_subscribers")

    def __init__(self, capacity: int | None, replay: int | None = None) -> None:
        if capacity is not None and capacity <= 0:
            raise ValueError(f"Cannot construct PubSub with capacity of {capacity}")
        self._capacity = capacity
        self._replay = ReplayBuffer[A](replay) if replay is not None and replay > 0 else None
        self._slots: deque[_Slot[A]] = deque()
        # The publish index of the oldest stored message.
        self._start = 0
        self._subscribers = 0
        # The hub's lock: everything a ``PubSub`` over this store keeps (its
        # subscriptions, parked takes and publishers) changes holding it.
        self._lock = threading.Lock()

    @classmethod
    def bounded(cls, capacity: int | None, *, replay: int | None = None) -> Atomic[A]:
        """A store of at most ``capacity`` messages (``None``: unbounded),
        replaying the last ``replay`` to new subscribers (Effect's
        ``makeAtomicBounded``). A capacity below 1 is a ``ValueError``."""
        return cls(capacity, replay)

    @classmethod
    def unbounded(cls, *, replay: int | None = None) -> Atomic[A]:
        """Effect's ``makeAtomicUnbounded``."""
        return cls(None, replay)

    @property
    def capacity(self) -> int | None:
        return self._capacity

    def size(self) -> int:
        """How many messages are stored (each once, however many readers)."""
        return len(self._slots)

    def is_empty(self) -> bool:
        return not self._slots

    def is_full(self) -> bool:
        return len(self._slots) == self._capacity

    def publish(self, value: A) -> bool:
        """Store ``value`` for the current subscribers; ``False`` if full."""
        if self.is_full():
            return False
        replay_index = 0 if self._replay is None else self._replay.offer(value)
        if self._subscribers:
            self._slots.append(_Slot(value, self._subscribers, replay_index))
        return True

    def publish_all(self, items: Iterable[A]) -> list[A]:
        """Store what fits, in order; the items that did not."""
        if not self._subscribers:
            if self._replay is not None:
                for item in items:
                    self._replay.offer(item)
            return []
        batch = list(items)
        fits = len(batch) if self._capacity is None else self._capacity - len(self._slots)
        for item in batch[:fits]:
            self.publish(item)
        return batch[fits:]

    def slide(self) -> None:
        """Drop the oldest stored message for every subscriber."""
        if self._slots:
            slot = self._slots.popleft()
            self._start += 1
            if self._replay is not None:
                self._replay.slide(slot.value, slot.replay_index)

    def subscribe(self) -> BackingSubscription[A]:
        """A reader of the messages published from now on."""
        self._subscribers += 1
        return BackingSubscription(self)

    def replay_window(self) -> ReplayWindow[A]:
        """The messages a subscriber that joins now replays."""
        return ReplayWindow(self._replay)

    # --- for BackingSubscription ------------------------------------------

    def _end(self) -> int:
        """The publish index the next stored message gets."""
        return self._start + len(self._slots)

    def _read(self, index: int) -> A:
        """Read the message at publish ``index`` for one subscriber."""
        slot = self._slots[index - self._start]
        slot.unread -= 1
        if slot.unread == 0:
            self._slots.popleft()
            self._start += 1
        return slot.value

    def _leave(self, index: int) -> None:
        """A subscriber at ``index`` leaves without reading the rest."""
        self._subscribers -= 1
        for i in range(max(index, self._start), self._end()):
            self._read(i)


class BackingSubscription[A]:
    """One subscriber's position in an ``Atomic``. A message read for a
    parked take that was interrupted before collecting it is given back
    and read first."""

    __slots__ = ("_atomic", "_index", "_returned", "_unsubscribed")

    def __init__(self, atomic: Atomic[A]) -> None:
        self._atomic = atomic
        self._index = atomic._end()
        self._returned: deque[A] = deque()
        self._unsubscribed = False

    def size(self) -> int:
        """How many messages are there to read."""
        if self._unsubscribed:
            return 0
        atomic = self._atomic
        start = atomic._start
        index = self._index
        return (
            len(self._returned) + start + len(atomic._slots) - (index if index > start else start)
        )

    def is_empty(self) -> bool:
        return self.size() == 0

    def poll(self) -> Option[A]:
        """The next message, if there is one."""
        items = self.poll_up_to(1)
        return Some(items[0]) if items else None

    def poll_up_to(self, n: int) -> list[A]:
        """Up to ``n`` messages (none if ``n`` is 0 or less)."""
        count = min(n, self.size())
        if count <= 0:
            return []
        returned = self._returned
        out = [returned.popleft() for _ in range(min(count, len(returned)))]
        count -= len(out)
        if count:
            atomic = self._atomic
            start = max(self._index, atomic._start)
            self._index = start + count
            out.extend(atomic._read(i) for i in range(start, start + count))
        return out

    def poll_all(self) -> list[A]:
        return self.poll_up_to(self.size())

    def unsubscribe(self) -> None:
        """Stop reading; messages only this subscriber owed are dropped."""
        if not self._unsubscribed:
            self._unsubscribed = True
            self._returned.clear()
            self._atomic._leave(self._index)

    def _give_back(self, value: A) -> None:
        """``value`` was read but not taken: it is the next message read."""
        if not self._unsubscribed:
            self._returned.appendleft(value)
