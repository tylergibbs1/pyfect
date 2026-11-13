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
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from pyfect._core import Effect, _Succeed  # pyright: ignore[reportPrivateUsage]
from pyfect._waiters import Lock, WaitList, unlocked
from pyfect.cause import Cause


@dataclass(eq=False, slots=True)
class OfferOne[A]:
    item: A
    resume: Callable[[Effect[bool]], None]


@dataclass(eq=False, slots=True)
class OfferMany[A]:
    """A batch offer. ``items[admitted:]`` are still waiting."""

    items: list[A]
    resume: Callable[[Effect[list[A]]], None]
    admitted: int = 0


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


def take_offer[A](offers: deque[Offer[A]], lock: Lock) -> A:
    """Take the next item straight from the oldest parked offer. ``lock`` is
    the queue's, which the caller holds and which is let go to resume the
    offerer."""
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


def admit[A](offers: deque[Offer[A]], buffer: deque[A], capacity: int, lock: Lock) -> None:
    """Move parked items into ``buffer`` while it holds fewer than
    ``capacity``, oldest first, resuming each offer once all of its items
    are in. A resumed offerer runs at once and may offer again, and other
    runs may too while ``lock`` is let go to resume it, so the free space is
    read again after each resume (Effect's ``releaseCapacity``)."""
    while offers and len(buffer) < capacity:
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
