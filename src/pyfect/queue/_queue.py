"""``Queue[A, E]`` itself. See the package docstring for its behavior."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Generator, Iterable
from typing import Any, Literal, Never, overload

from pyfect._core import (
    Effect,
    _Callback,
    _FailCause,
    _FromExit,
    _Gen,
    _Succeed,
    _Suspend,
    _Sync,
    _WithFiber,
    uninterruptible_mask,
)
from pyfect._effect_args import require_effect
from pyfect._fiber import FiberDispatcher, current_fiber
from pyfect._non_empty import non_empty
from pyfect._waiters import WaitList
from pyfect.cause import Cause
from pyfect.cause import fail as fail_cause
from pyfect.cause import interrupt as interrupt_cause
from pyfect.errors import Done, filter_done
from pyfect.exit import Exit, Failure, Success
from pyfect.option import Option, Some
from pyfect.queue import _state as st
from pyfect.queue._views import Dequeue, Enqueue
from pyfect.result import Ok
from pyfect.scheduler import Scheduler, SyncOnlyScheduler

type Strategy = Literal["suspend", "dropping", "sliding"]

_TRUE: Effect[bool] = _FromExit(Success(True))
_FALSE: Effect[bool] = _FromExit(Success(False))


def _as_taken[A](items: list[A]) -> list[A]:
    return items


class Queue[A, E = Never](Enqueue[A, E], Dequeue[A, E]):
    __slots__ = ("_capacity", "_items", "_scheduler", "_state", "_strategy")

    def __init__(self, capacity: int | None = None, strategy: Strategy = "suspend") -> None:
        self._capacity = capacity
        # The dispatcher of the fiber making the queue holds its wakes, as
        # Effect keeps that fiber's (see ``_waker``).
        fiber = current_fiber()
        self._scheduler: Scheduler | None = None if fiber is None else fiber.dispatcher()
        self._strategy: Strategy = strategy
        self._items: deque[A] = deque()
        self._state: st.State[A, E] = st.Open()

    def _waker(self) -> Scheduler | None:
        """Where the queue's wakes wait: its maker's dispatcher, unless that
        fiber's run is not the one running here (a queue can outlive its run),
        nor under ``run_sync``, whose root flushes them; then the offering
        fiber's (``notify_ready_soon``)."""
        found = self._scheduler
        if isinstance(found, FiberDispatcher) and not found.runs_here():
            return None
        return None if isinstance(found, SyncOnlyScheduler) else found

    @classmethod
    def make(
        cls, capacity: int | None = None, *, strategy: Strategy = "suspend"
    ) -> Effect[Queue[A, E]]:
        """A queue of ``capacity`` items (``None``: unbounded) that handles a
        full queue by ``strategy``."""
        return _Sync(lambda: cls(capacity, strategy))

    @classmethod
    def unbounded(cls) -> Effect[Queue[A, E]]:
        """A queue with no capacity limit: ``offer`` never waits or drops."""
        return _Sync(cls)

    @classmethod
    def bounded(cls, capacity: int) -> Effect[Queue[A, E]]:
        """A queue of ``capacity`` items whose ``offer`` waits while it is
        full. Capacity 0 is a rendezvous: an offer completes when a taker
        takes it."""
        return _Sync(lambda: cls(capacity, "suspend"))

    @classmethod
    def dropping(cls, capacity: int) -> Effect[Queue[A, E]]:
        """A queue of ``capacity`` items that drops a new item offered while
        it is full: ``offer`` returns ``False`` and ``offer_all`` the items it
        refused."""
        return _Sync(lambda: cls(capacity, "dropping"))

    @classmethod
    def sliding(cls, capacity: int) -> Effect[Queue[A, E]]:
        """A queue of ``capacity`` items that drops its oldest item to make
        room for a new one, so ``offer`` always returns ``True`` and the
        newest item is never the one dropped. Nothing reports the drops.

        As in Effect, ``sliding(0)`` keeps only the newest offered item and
        wakes no parked taker: a taker waiting on it gets that item only when
        the queue ends. Use a capacity of at least 1."""
        return _Sync(lambda: cls(capacity, "sliding"))

    @property
    def capacity(self) -> int | None:
        """How many items the queue holds; ``None`` if unbounded."""
        return self._capacity

    # --- producing --------------------------------------------------------

    def offer(self, item: A) -> Effect[bool]:
        """Add an item. ``False`` if the queue is finished, or if it is full
        and drops new items."""

        def register(resume: Callable[[Effect[bool]], None]) -> Effect[None] | None:
            if self.offer_unsafe(item):
                resume(_TRUE)
            elif isinstance(self._state, st.Open):
                return self._park(self._state.offers, st.OfferOne(item, resume))
            else:
                resume(_FALSE)
            return None

        def attempt() -> Effect[bool]:
            # As Effect's ``offer``: an item that fits is added in this step,
            # and only a full suspending queue parks the offer.
            if self.offer_unsafe(item):
                return _TRUE
            if isinstance(self._state, st.Open) and self._strategy == "suspend":
                return _Callback(register)
            return _FALSE

        return _Suspend(attempt)

    def flush(self) -> Effect[None]:
        """Wake the takers that can go on now, not in a scheduled task."""
        return _Sync(self.flush_unsafe)

    def flush_unsafe(self) -> None:
        if isinstance(self._state, (st.Open, st.Closing)):
            self._state.takers.notify_ready()

    def offer_unsafe(self, item: A) -> bool:
        """``offer`` without waiting, from outside an effect: ``False`` if it
        would have to wait. Call on the queue's fibers' scheduler thread."""
        match self._state:
            case st.Open(takers=takers):
                if self._strategy == "sliding" and self._is_full():
                    # As Effect's ``offerUnsafe``: a full sliding queue swaps
                    # its oldest item for this one, even at capacity 0, and
                    # releases no taker.
                    if self._items:
                        self._items.popleft()
                    self._items.append(item)
                    return True
                if self._free(takers) > 0:
                    # A rendezvous queue hands the item to its waiting takers
                    # at once.
                    self._push(
                        [item], takers, now=self._capacity is not None and self._capacity <= 0
                    )
                    return True
                return False
            case st.Closing() | st.Done():
                return False

    def offer_all[T](self: Queue[T, Any], items: Iterable[T]) -> Effect[list[T]]:
        """Add items in order; succeeds with those not added. What fits is
        added at once. A suspending queue waits to add the rest, and returns
        what is left if the queue is finished meanwhile."""

        def register(resume: Callable[[Effect[list[T]]], None]) -> Effect[None] | None:
            rest = self.offer_all_unsafe(items)
            if rest and isinstance(self._state, st.Open) and self._strategy == "suspend":
                return self._park(self._state.offers, st.OfferMany(rest, resume))
            resume(_Succeed(rest))
            return None

        return _Callback(register)

    def offer_all_unsafe[T](self: Queue[T, Any], items: Iterable[T]) -> list[T]:
        """``offer_all`` without waiting: the items that did not fit."""
        batch = list(items)
        match self._state:
            case st.Open(takers=takers):
                fits = len(batch) if self._strategy == "sliding" else self._free(takers)
                self._push(batch[:fits], takers)
                return batch[fits:]
            case st.Closing() | st.Done():
                return batch

    def end(self: Enqueue[Any, Done]) -> Effect[bool]:
        """No more items. Takers fail with ``Done()`` once the queue drains.
        Only available on queues whose error type includes ``Done``."""
        return self.fail_cause(fail_cause(Done()))

    def end_unsafe(self: Queue[Any, Done]) -> bool:
        return self.fail_cause_unsafe(fail_cause(Done()))

    def fail(self, error: E) -> Effect[bool]:
        """Takers fail with ``error`` once the queue drains."""
        return self.fail_cause(fail_cause(error))

    def interrupt(self) -> Effect[bool]:
        """Takers are interrupted (by the calling fiber) once the queue
        drains."""
        return _WithFiber(lambda fiber: self.fail_cause(interrupt_cause(fiber.id)))

    def fail_cause(self, cause: Cause[E]) -> Effect[bool]:
        """``False`` if the queue was already ended, failed or shut down."""
        return _Sync(lambda: self.fail_cause_unsafe(cause))

    def fail_cause_unsafe(self, cause: Cause[E]) -> bool:
        match self._state:
            case st.Open(takers=takers, offers=offers, awaiters=awaiters):
                self._state = st.Closing(takers, offers, awaiters, cause)
                # A batch take waiting for its minimum can now drain the rest.
                takers.notify_ready_soon(self._waker())
                self._finish_if_drained()
                return True
            case st.Closing() | st.Done():
                return False

    def shutdown(self) -> Effect[bool]:
        """Drop all items and waiting offers; takers are interrupted (or see
        the failure of a queue that was closing). ``False`` if the queue was
        already done."""
        return _Sync(self.shutdown_unsafe)

    def shutdown_unsafe(self) -> bool:
        match self._state:
            case st.Done():
                return False
            case st.Open(offers=offers):
                self._shut(interrupt_cause(), offers)
            case st.Closing(offers=offers, cause=cause):
                self._shut(cause, offers)
        return True

    def into[R, EE](
        self: Queue[Any, EE | Done], eff: Effect[object, EE | Done, R]
    ) -> Effect[bool, Never, R]:
        """Run ``eff``, then end the queue, or fail it with ``eff``'s cause.
        The queue is finished even if the running fiber is interrupted."""
        require_effect(eff, "eff")
        return uninterruptible_mask(
            lambda restore: restore(eff).match_cause_effect(
                on_failure=self.fail_cause, on_success=lambda _: self.end()
            )
        )

    # --- consuming --------------------------------------------------------

    def take(self) -> Effect[A, E]:
        """Wait for an item."""

        def attempt() -> Effect[A, E]:
            ex = self.take_unsafe()
            return self._wait_then(1, attempt) if ex is None else _FromExit(ex)

        return _Suspend(attempt)

    def take_unsafe(self) -> Exit[A, E] | None:
        """An item, the failure of a finished queue, or ``None`` if ``take``
        would wait."""
        match self._state:
            case st.Done(cause=cause):
                return Failure(cause)
            case st.Open(offers=offers) | st.Closing(offers=offers):
                if not self._items and not self._takes_from(offers):
                    return None
                item = self._take_one(offers)
                self._release()
                return Success(item)

    def take_between(self, minimum: int, maximum: int) -> Effect[list[A], E]:
        """Wait until ``minimum`` items are there (or the queue is finishing),
        then take up to ``maximum``. A bounded queue never holds more than
        its capacity, so it waits for at most that many. A count of 0 or less
        takes nothing and does not wait (but still fails on a finished
        queue)."""
        return self._take_between(minimum, maximum)

    def take_n(self, n: int) -> Effect[list[A], E]:
        """``take_between(n, n)``."""
        return self._take_between(n, n)

    def take_all(self) -> Effect[tuple[A, *tuple[A, ...]], E]:
        """Wait for at least one item, then take everything (Effect's
        ``NonEmptyArray``)."""
        return self._take_between(1, None, lambda items: non_empty(items[0], items[1:]))

    def poll(self) -> Effect[Option[A]]:
        """An item if one is there now; ``None`` if not, or if the queue is
        finished."""

        def attempt() -> Effect[Option[A]]:
            ex = self.take_unsafe()
            return _Succeed(Some(ex.value) if isinstance(ex, Success) else None)

        return _Suspend(attempt)

    def peek(self) -> Effect[A, E]:
        """Wait for an item and succeed with it, leaving it in the queue.
        Offers waiting on a rendezvous queue are not visible to ``peek``."""

        def attempt() -> Effect[A, E]:
            match self._state:
                case st.Done(cause=cause):
                    return _FailCause(cause)
                case st.Open(takers=takers) | st.Closing(takers=takers):
                    if not self._items:
                        ready = self._finished_or(lambda: bool(self._items))
                        return takers.wait(ready).and_then(_Suspend(attempt))
                    return _Succeed(self._items[0])

        return _Suspend(attempt)

    @overload
    def clear[AA](self: Queue[AA, Done[Any]]) -> Effect[list[AA], Never]: ...
    @overload
    def clear[AA, EE](self: Queue[AA, EE | Done[Any]]) -> Effect[list[AA], EE]: ...
    @overload
    def clear(self) -> Effect[list[A], E]: ...
    def clear(self: Queue[Any, Any]) -> Effect[list[Any], Any]:
        """Take every item there is now, without waiting. On a queue that
        was ended, succeeds with ``[]``; on one that failed, fails with that
        failure (without ``Done``)."""

        def attempt() -> Effect[list[Any], Any]:
            match self._state:
                case st.Done(cause=cause):
                    return _catch_done(cause, [])
                case st.Open(offers=offers) | st.Closing(offers=offers):
                    if self._items:
                        items = self._take_buffered(len(self._items))
                    elif self._takes_from(offers):
                        items = [st.take_offer(offers)]
                    else:
                        return _Succeed([])
                    self._release()
                    return _Succeed(items)

        return _Suspend(attempt)

    @overload
    def collect[AA](self: Queue[AA, Done[Any]]) -> Effect[list[AA], Never]: ...
    @overload
    def collect[AA, EE](self: Queue[AA, EE | Done[Any]]) -> Effect[list[AA], EE]: ...
    @overload
    def collect(self) -> Effect[list[A], E]: ...
    def collect(self: Queue[Any, Any]) -> Effect[list[Any], Any]:
        """Take items until the queue is ended, and succeed with all of them.
        If the queue fails instead, fail with that failure."""

        def body() -> Generator[Effect[Any, Any, Any], Any, list[Any]]:
            out: list[Any] = []
            while True:
                taken: Exit[tuple[Any, ...], Any] = yield self.take_all().exit()
                match taken:
                    case Success(value=items):
                        out.extend(items)
                    case Failure(cause=cause):
                        return (yield _catch_done(cause, out))

        return _Gen(body)

    @overload
    def await_done(self: Queue[Any, Done[Any]]) -> Effect[None]: ...
    @overload
    def await_done[EE](self: Queue[Any, EE | Done[Any]]) -> Effect[None, EE]: ...
    @overload
    def await_done(self) -> Effect[None, E]: ...
    def await_done(self: Queue[Any, Any]) -> Effect[None, Any]:
        """Wait until the queue is finished: ended, failed or shut down, and
        drained. Succeeds if it was ended; otherwise fails as its takers do
        (Effect's ``Queue.await``)."""

        def attempt() -> Effect[None, Any]:
            match self._state:
                case st.Done(cause=cause):
                    return _catch_done(cause, None)
                case st.Open(awaiters=awaiters) | st.Closing(awaiters=awaiters):
                    return awaiters.wait(self._finished_or(lambda: False)).and_then(
                        _Suspend(attempt)
                    )

        return _Suspend(attempt)

    def size(self) -> Effect[int]:
        """How many items the queue holds (0 once it is finished)."""
        return _Sync(self.size_unsafe)

    def size_unsafe(self) -> int:
        return 0 if isinstance(self._state, st.Done) else len(self._items)

    def is_full(self) -> Effect[bool]:
        """Whether the queue holds ``capacity`` items."""
        return _Sync(self.is_full_unsafe)

    def is_full_unsafe(self) -> bool:
        return self.size_unsafe() == self._capacity

    def is_done_unsafe(self) -> bool:
        """Whether the queue has ended, failed or shut down and has no items
        left (Effect's ``queue.state._tag === "Done"``)."""
        return isinstance(self._state, st.Done)

    # --- internals --------------------------------------------------------

    def _is_full(self) -> bool:
        return self._capacity is not None and len(self._items) >= self._capacity

    def _free(self, takers: WaitList) -> int:
        """How many items can be added now. A rendezvous queue admits one per
        parked taker."""
        if self._capacity is None:
            return 2**62
        if self._capacity <= 0:
            return len(takers)
        return max(0, self._capacity - len(self._items))

    def _push(self, batch: list[A], takers: WaitList, *, now: bool = False) -> None:
        """Add ``batch``; a sliding queue then drops its oldest items down to
        its capacity. Takers are woken in a
        scheduled task (Effect's ``scheduleReleaseTaker``), so an offerer
        parks what did not fit before a taker makes room; ``now`` wakes
        them at once (Effect's rendezvous offer)."""
        self._items.extend(batch)
        if self._strategy == "sliding" and self._capacity is not None:
            for _ in range(len(self._items) - max(self._capacity, 0)):
                self._items.popleft()
        if now:
            takers.notify_ready()
        else:
            takers.notify_ready_soon(self._waker())

    def _shut(self, cause: Cause[E], offers: deque[st.Offer[A]]) -> None:
        self._items.clear()
        self._finish(cause)
        # A rejected offerer runs at once and may touch the queue again.
        rejected = list(offers)
        offers.clear()
        for entry in rejected:
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

    @overload
    def _take_between(self, minimum: int, maximum: int | None) -> Effect[list[A], E]: ...
    @overload
    def _take_between[T](
        self, minimum: int, maximum: int | None, shape: Callable[[list[A]], T]
    ) -> Effect[T, E]: ...
    def _take_between(
        self,
        minimum: int,
        maximum: int | None,
        shape: Callable[[list[A]], Any] = _as_taken,
    ) -> Effect[Any, E]:
        """``maximum=None`` takes every buffered item. The items are taken in
        the taking fiber's own step, so none is handed to a parked fiber;
        ``shape`` makes the result in that step too, as nothing may come
        between a take and the step that returns it."""

        def attempt() -> Effect[Any, E]:
            match self._state:
                case st.Done(cause=cause):
                    return _FailCause(cause)
                case st.Open(offers=offers) | st.Closing(offers=offers):
                    if minimum <= 0 or (maximum is not None and maximum <= 0):
                        return _Succeed(shape([]))
                    if not self._can_take(minimum):
                        return self._wait_then(minimum, attempt)
                    if self._items:
                        items = self._take_buffered(maximum or len(self._items))
                    else:
                        items = [st.take_offer(offers)]
                    self._release()
                    return _Succeed(shape(items))

        return _Suspend(attempt)

    def _wait_then[T](self, minimum: int, retry: Callable[[], Effect[T, E]]) -> Effect[T, E]:
        """Park until a take of ``minimum`` items can complete (or the queue
        is done), then ``retry``."""
        match self._state:
            case st.Done(cause=cause):
                return _FailCause(cause)
            case st.Open(takers=takers) | st.Closing(takers=takers):
                ready = self._finished_or(lambda: self._can_take(minimum))
                return takers.wait(ready).and_then(_Suspend(retry))

    def _finished_or(self, ready: Callable[[], bool]) -> Callable[[], bool]:
        return lambda: isinstance(self._state, st.Done) or ready()

    def _can_take(self, minimum: int) -> bool:
        """Whether a take of at least ``minimum`` items can complete now. A
        closing queue gets no more items, so whatever is left will do."""
        match self._state:
            case st.Done():
                return True
            case st.Closing(offers=offers):
                return bool(self._items) or self._takes_from(offers)
            case st.Open(offers=offers):
                limit = minimum if self._capacity is None else (self._capacity or 1)
                return len(self._items) >= min(minimum, limit) or self._takes_from(offers)

    def _takes_from(self, offers: deque[st.Offer[A]]) -> bool:
        """Whether a take goes straight to a waiting offer: on a rendezvous
        queue with nothing buffered."""
        return self._capacity is not None and self._capacity <= 0 and bool(offers)

    def _take_one(self, offers: deque[st.Offer[A]]) -> A:
        """Buffered items come first; a rendezvous queue then takes straight
        from the oldest waiting offer."""
        return self._items.popleft() if self._items else st.take_offer(offers)

    def _take_buffered(self, n: int) -> list[A]:
        return [self._items.popleft() for _ in range(min(n, len(self._items)))]

    def _release(self) -> None:
        """Admit waiting offers into the space a take freed, and finish a
        closing queue that is now empty. No taker needs waking: offers wait
        only on a full queue, where every taker is ready (as in Effect's
        ``releaseCapacity``)."""
        match self._state:
            case st.Open(offers=offers) | st.Closing(offers=offers):
                if self._capacity is not None:
                    st.admit(offers, self._items, self._capacity)
                self._finish_if_drained()
            case st.Done():
                pass

    def _finish_if_drained(self) -> None:
        state = self._state
        if isinstance(state, st.Closing) and not self._items and not state.offers:
            self._finish(state.cause)

    def _finish(self, cause: Cause[E]) -> None:
        match self._state:
            case (
                st.Open(takers=takers, awaiters=awaiters)
                | st.Closing(takers=takers, awaiters=awaiters)
            ):
                self._state = st.Done(cause)
                takers.notify_all()
                awaiters.notify_all()
            case st.Done():
                pass


def _catch_done[T](cause: Cause[Any], value: T) -> Effect[T, Any]:
    """Succeed with ``value`` if the queue was ended; otherwise fail with
    ``cause`` without its ``Done``."""
    match filter_done(cause):
        case Ok():
            return _Succeed(value)
        case rest:
            return _FailCause(rest.error)
