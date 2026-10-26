"""``Queue[A, E]``: an async queue fibers can share.

Capacity and overflow behavior are fixed at creation:

- ``"suspend"`` (default): ``offer`` waits while the queue is full.
  Capacity 0 is a rendezvous: an offer completes when a taker takes it.
- ``"dropping"``: ``offer`` on a full queue drops the new item.
- ``"sliding"``: ``offer`` on a full queue drops the oldest item.

A queue can be finished. After ``fail(error)``, new offers return
``False``, but takers still drain the items and the offers that were
already waiting, and then fail with ``error``. A queue that should be
endable declares it in its type, ``Queue[int, Done]``; only then does
``end()`` type-check, and takers fail with ``Done`` once drained.
``shutdown()`` drops everything at once: items are cleared, waiting offers
return ``False`` and takers are interrupted.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from typing import Literal, Never

from pyfect import _queue_state as st
from pyfect._core import Effect, _Callback, _FailCause, _Succeed, _Suspend, _Sync
from pyfect._waiters import WaitList
from pyfect.cause import Cause
from pyfect.cause import fail as fail_cause
from pyfect.cause import interrupt as interrupt_cause
from pyfect.errors import TaggedError

type Strategy = Literal["suspend", "dropping", "sliding"]


class Done(TaggedError):
    """The queue was ended and has no more items."""


class Queue[A, E = Never]:
    __slots__ = ("_capacity", "_items", "_state", "_strategy")

    def __init__(self, capacity: int | None = None, strategy: Strategy = "suspend") -> None:
        if capacity is not None and capacity < 0:
            raise ValueError(f"capacity must be >= 0, got {capacity}")
        self._capacity = capacity
        self._strategy: Strategy = strategy
        self._items: deque[A] = deque()
        self._state: st.State[A, E] = st.Open()

    @classmethod
    def unbounded(cls) -> Effect[Queue[A, E]]:
        return _Sync(cls)

    @classmethod
    def bounded(cls, capacity: int) -> Effect[Queue[A, E]]:
        """``offer`` waits while the queue holds ``capacity`` items."""
        return _Sync(lambda: cls(capacity, "suspend"))

    @classmethod
    def dropping(cls, capacity: int) -> Effect[Queue[A, E]]:
        return _Sync(lambda: cls(capacity, "dropping"))

    @classmethod
    def sliding(cls, capacity: int) -> Effect[Queue[A, E]]:
        return _Sync(lambda: cls(capacity, "sliding"))

    # --- producing --------------------------------------------------------

    def offer(self, item: A) -> Effect[bool]:
        """Add an item. ``False`` if the queue is finished, or if it is full
        and drops new items."""

        def register(resume: Callable[[Effect[bool]], None]) -> Effect[None] | None:
            match self._state:
                case st.Open(takers=takers, offers=offers):
                    if self._free(takers) > 0 or self._strategy == "sliding":
                        self._push([item], takers)
                        resume(_Succeed(True))
                    elif self._strategy == "suspend":
                        return self._park(offers, st.OfferOne(item, resume))
                    else:
                        resume(_Succeed(False))
                case st.Closing() | st.Done():
                    resume(_Succeed(False))
            return None

        return _Callback(register)

    def offer_all(self, items: Iterable[A]) -> Effect[list[A]]:
        """Add items in order; succeeds with those not added. What fits is
        added at once. A suspending queue waits to add the rest, and returns
        what is left if the queue is finished meanwhile."""

        def register(resume: Callable[[Effect[list[A]]], None]) -> Effect[None] | None:
            batch = list(items)
            match self._state:
                case st.Open(takers=takers, offers=offers):
                    fits = len(batch) if self._strategy == "sliding" else self._free(takers)
                    self._push(batch[:fits], takers)
                    rest = batch[fits:]
                    if rest and self._strategy == "suspend":
                        return self._park(offers, st.OfferMany(rest, resume))
                    resume(_Succeed(rest))
                case st.Closing() | st.Done():
                    resume(_Succeed(batch))
            return None

        return _Callback(register)

    def end[AA, EE](self: Queue[AA, EE | Done]) -> Effect[bool]:
        """No more items. Takers fail with ``Done`` once the queue drains.
        Only available on queues whose error type includes ``Done``."""
        return self.fail_cause(fail_cause(Done()))

    def fail(self, error: E) -> Effect[bool]:
        """Takers fail with ``error`` once the queue drains."""
        return self.fail_cause(fail_cause(error))

    def fail_cause(self, cause: Cause[E]) -> Effect[bool]:
        """``False`` if the queue was already ended, failed or shut down."""

        def run() -> bool:
            match self._state:
                case st.Open(takers=takers, offers=offers):
                    self._state = st.Closing(takers, offers, cause)
                    self._finish_if_drained()
                    return True
                case st.Closing() | st.Done():
                    return False

        return _Sync(run)

    def shutdown(self) -> Effect[bool]:
        """Drop all items and waiting offers; takers are interrupted (or see
        the failure of a queue that was closing). ``False`` if the queue was
        already done."""

        def run() -> bool:
            match self._state:
                case st.Done():
                    return False
                case st.Open(offers=offers):
                    self._shut(interrupt_cause(), offers)
                case st.Closing(offers=offers, cause=cause):
                    self._shut(cause, offers)
            return True

        return _Sync(run)

    # --- consuming --------------------------------------------------------

    def take(self) -> Effect[A, E]:
        """Wait for an item."""
        return self._take(self._take_one)

    def take_up_to(self, n: int) -> Effect[list[A], E]:
        """Wait for at least one item, then take up to ``n``. ``n <= 0``
        takes nothing and does not wait (but still fails on a finished
        queue)."""
        if n <= 0:
            return self._take(lambda _offers: list[A](), wait=False)
        return self._take(lambda offers: [self._take_one(offers), *self._take_buffered(n - 1)])

    def take_all(self) -> Effect[list[A], E]:
        """Wait for at least one item, then take everything."""
        return self._take(
            lambda offers: [self._take_one(offers), *self._take_buffered(len(self._items))]
        )

    @property
    def size(self) -> Effect[int]:
        return _Sync(lambda: len(self._items))

    # --- internals --------------------------------------------------------

    def _free(self, takers: WaitList) -> int:
        """How many items can be added now. A rendezvous queue admits one per
        parked taker."""
        if self._capacity is None:
            return 2**62
        if self._capacity == 0:
            return len(takers)
        return max(0, self._capacity - len(self._items))

    def _push(self, batch: list[A], takers: WaitList) -> None:
        self._items.extend(batch)
        if self._strategy == "sliding" and self._capacity is not None:
            for _ in range(len(self._items) - self._capacity):
                self._items.popleft()
        _wake(takers, len(batch))

    def _shut(self, cause: Cause[E], offers: deque[st.Offer[A]]) -> None:
        self._items.clear()
        self._finish(cause)
        for entry in offers:
            st.reject(entry)

    def _park(self, offers: deque[st.Offer[A]], entry: st.Offer[A]) -> Effect[None]:
        offers.append(entry)
        return _Sync(lambda: self._withdraw(entry))

    def _withdraw(self, entry: st.Offer[A]) -> None:
        """An interrupted offer gives up the items not yet admitted."""
        match self._state:
            case st.Open(offers=offers) | st.Closing(offers=offers):
                if entry in offers:
                    offers.remove(entry)
                self._finish_if_drained()
            case st.Done():
                pass

    def _take[T](
        self, grab: Callable[[deque[st.Offer[A]]], T], *, wait: bool = True
    ) -> Effect[T, E]:
        """Run ``grab`` in the taking fiber's own step once something is
        available, so a taken item is never handed to a parked fiber."""

        def attempt() -> Effect[T, E]:
            match self._state:
                case st.Done(cause=cause):
                    return _FailCause(cause)
                case (
                    st.Open(takers=takers, offers=offers) | st.Closing(takers=takers, offers=offers)
                ):
                    if wait and not self._items and not offers:
                        return takers.wait().and_then(_Suspend(attempt))
                    taken = grab(offers)
                    self._refill(offers, takers)
                    return _Succeed(taken)

        return _Suspend(attempt)

    def _take_one(self, offers: deque[st.Offer[A]]) -> A:
        """Buffered items come first; a rendezvous queue then takes straight
        from the oldest waiting offer."""
        return self._items.popleft() if self._items else st.take_offer(offers)

    def _take_buffered(self, n: int) -> list[A]:
        return [self._items.popleft() for _ in range(min(n, len(self._items)))]

    def _refill(self, offers: deque[st.Offer[A]], takers: WaitList) -> None:
        """Admit waiting offers into the space a take freed."""
        before = len(self._items)
        if self._capacity is not None:
            st.admit(offers, self._items, self._capacity - before)
        _wake(takers, len(self._items) - before)
        self._finish_if_drained()

    def _finish_if_drained(self) -> None:
        state = self._state
        if isinstance(state, st.Closing) and not self._items and not state.offers:
            self._finish(state.cause)

    def _finish(self, cause: Cause[E]) -> None:
        match self._state:
            case st.Open(takers=takers) | st.Closing(takers=takers):
                self._state = st.Done(cause)
                takers.notify_all()
            case st.Done():
                pass


def _wake(takers: WaitList, n: int) -> None:
    for _ in range(min(n, len(takers))):
        takers.notify_one()
