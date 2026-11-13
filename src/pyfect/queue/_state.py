"""The states of a ``Queue``, as a closed union.

``Open`` accepts offers. ``Closing(cause)`` was ended or failed but still
holds items or parked offers, which takers drain. ``Done(cause)`` is
finished: nothing is parked, so there is nowhere to drop an offer, a taker
or an ``await_done`` waiter. Matches over ``State`` are checked for
exhaustiveness by pyright.

A parked offer owns its items. The queue admits them as space frees (or
hands them straight to a taker when the capacity is 0) and only then
resumes the offerer. Items move *into* the queue, never out to a parked
fiber, so an interrupt can't lose one: an offerer interrupted before
admission withdraws its entry, and one interrupted after has delivered.

That holds only for an offerer of the run doing the admitting, which runs at
once, before anything else can interrupt it. An offerer of another run is
*woken* instead (``wake``): it admits its own items in its own step, where its
run decides whether an interrupt (a timeout) came first. Until then it keeps
its place and holds up the offers behind it.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pyfect._core import Effect, _Succeed  # pyright: ignore[reportPrivateUsage]
from pyfect._fiber import current_fiber
from pyfect._waiters import Lock, WaitList, of_this_run, unlocked
from pyfect.cause import Cause

if TYPE_CHECKING:
    from pyfect._fiber import Fiber


@dataclass(eq=False, slots=True)
class OfferOne[A]:
    item: A
    resume: Callable[[Effect[bool]], None]
    fiber: Fiber[Any, Any] | None = field(default_factory=current_fiber)
    # Woken to admit its items itself; it keeps its place meanwhile.
    woken: bool = False


@dataclass(eq=False, slots=True)
class OfferMany[A]:
    """A batch offer. ``items[admitted:]`` are still waiting."""

    items: list[A]
    resume: Callable[[Effect[list[A]]], None]
    admitted: int = 0
    fiber: Fiber[Any, Any] | None = field(default_factory=current_fiber)
    woken: bool = False


type Offer[A] = OfferOne[A] | OfferMany[A]


@dataclass(eq=False, slots=True)
class Open[A]:
    takers: WaitList
    offers: deque[Offer[A]]
    awaiters: WaitList


@dataclass(eq=False, slots=True)
class Closing[A, E]:
    takers: WaitList
    offers: deque[Offer[A]]
    awaiters: WaitList
    cause: Cause[E]


@dataclass(frozen=True, slots=True)
class Done[E]:
    cause: Cause[E]


type State[A, E] = Open[A] | Closing[A, E] | Done[E]


def woke_other_run[A](entry: Offer[A], lock: Lock, wake: Callable[[Offer[A]], None]) -> bool:
    """Whether ``entry`` belongs to another run, in which case it is woken to
    admit its items itself. ``lock`` is let go meanwhile."""
    if of_this_run(entry.fiber):
        return False
    entry.woken = True
    unlocked(lock, [lambda: wake(entry)])
    return True


def take_offer[A](
    offers: deque[Offer[A]], lock: Lock, wake: Callable[[Offer[A]], None]
) -> A | None:
    """Take the next item straight from the oldest parked offer, or ``None``
    if it belongs to another run and was woken to add the item itself.
    ``lock`` is the queue's, which the caller holds and which is let go to
    resume the offerer."""
    if woke_other_run(offers[0], lock, wake):
        return None
    match offers[0]:
        case OfferOne(item=item, resume=resume):
            offers.popleft()
            unlocked(lock, [lambda: resume(_Succeed(True))])
            return item
        case OfferMany() as entry:
            item = entry.items[entry.admitted]
            entry.admitted += 1
            if entry.admitted == len(entry.items):
                offers.popleft()
                unlocked(lock, [lambda: entry.resume(_Succeed([]))])
            return item


def admit[A](
    offers: deque[Offer[A]],
    buffer: deque[A],
    capacity: int,
    lock: Lock,
    wake: Callable[[Offer[A]], None],
) -> None:
    """Move parked items into ``buffer`` while it holds fewer than
    ``capacity``, oldest first, resuming each offer once all of its items
    are in. A resumed offerer runs at once and may offer again, and other
    runs may too while ``lock`` is let go to resume it, so the free space is
    read again after each resume (Effect's ``releaseCapacity``). Stops at an
    offer of another run, which is woken to admit its items itself."""
    while offers and len(buffer) < capacity:
        if offers[0].woken or woke_other_run(offers[0], lock, wake):
            return
        match offers[0]:
            case OfferOne(item=item, resume=resume):
                buffer.append(item)
                offers.popleft()
                unlocked(lock, [lambda: resume(_Succeed(True))])
            case OfferMany() as entry:
                n = min(capacity - len(buffer), len(entry.items) - entry.admitted)
                buffer.extend(entry.items[entry.admitted : entry.admitted + n])
                entry.admitted += n
                if entry.admitted < len(entry.items):
                    return
                offers.popleft()
                unlocked(lock, [lambda: entry.resume(_Succeed([]))])


def reject[A](entry: Offer[A], lock: Lock) -> None:
    """Resume a parked offer the queue will never admit."""
    match entry:
        case OfferOne(resume=resume):
            unlocked(lock, [lambda: resume(_Succeed(False))])
        case OfferMany(items=items, admitted=admitted, resume=resume):
            unlocked(lock, [lambda: resume(_Succeed(items[admitted:]))])
