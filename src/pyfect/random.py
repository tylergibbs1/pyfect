"""Pseudo-random numbers as a service. ``Random`` is a reference, so
effects draw numbers without declaring it; ``with_seed`` makes a run
reproducible, and tests can provide their own ``RandomService``.

The default service uses Python's ``random`` module and is not
cryptographically secure."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import math
import random
from collections.abc import Callable, Iterable
from typing import Protocol, overload

from pyfect._core import Effect
from pyfect._isaac import Isaac, safe_int_of
from pyfect._primitives import _Locally
from pyfect.context import Reference
from pyfect.effect import fail_sync, suspend
from pyfect.errors import NoSuchElementException


class RandomService(Protocol):
    def unsafe_next_int(self) -> int:
        """A random integer between ``-(2**53 - 1)`` and ``2**53 - 1``, both inclusive."""
        ...

    def unsafe_next_double(self) -> float:
        """A random float in ``[0, 1)``."""
        ...


class LiveRandom:
    def unsafe_next_int(self) -> int:
        return safe_int_of(random.random())

    def unsafe_next_double(self) -> float:
        return random.random()


class Random(Reference[RandomService]):
    @classmethod
    def default(cls) -> RandomService:
        return LiveRandom()


def _random_with[A](f: Callable[[RandomService], A]) -> Effect[A]:
    return Random().map(f)


def next() -> Effect[float]:
    """A random float in ``[0, 1)``."""
    return _random_with(lambda r: r.unsafe_next_double())


def next_boolean() -> Effect[bool]:
    return _random_with(lambda r: r.unsafe_next_double() > 0.5)


def next_int() -> Effect[int]:
    """A random integer between ``-(2**53 - 1)`` and ``2**53 - 1``, both inclusive."""
    return _random_with(lambda r: r.unsafe_next_int())


def _between(low: float, high: float, draw: float) -> float:
    value = draw * (high - low) + low
    if value != high or low >= high or not math.isfinite(high):
        return value
    # Rounding can reach the excluded bound even for a draw below 1.
    return math.nextafter(high, -math.inf)


def next_between(low: float, high: float) -> Effect[float]:
    """A random float in ``[low, high)``."""
    return _random_with(lambda r: _between(low, high, r.unsafe_next_double()))


def next_int_between(low: float, high: float, *, half_open: bool = False) -> Effect[int]:
    """A random integer from ``ceil(low)`` to ``floor(high)``, inclusive unless
    ``half_open``."""
    low_int, high_int = math.ceil(low), math.floor(high)
    span = high_int - low_int + (0 if half_open else 1)
    return _random_with(lambda r: math.floor(r.unsafe_next_double() * span) + low_int)


def shuffle[A](elements: Iterable[A]) -> Effect[list[A]]:
    """A shuffled copy of ``elements``."""

    def go(r: RandomService) -> list[A]:
        buffer = list(elements)
        for i in range(len(buffer) - 1, 0, -1):
            j = min(i, math.floor(r.unsafe_next_double() * (i + 1)))
            buffer[i], buffer[j] = buffer[j], buffer[i]
        return buffer

    return _random_with(go)


@overload
def choice[A](elements: tuple[A, *tuple[A, ...]]) -> Effect[A]: ...
@overload
def choice[A](elements: Iterable[A]) -> Effect[A, NoSuchElementException]: ...
def choice[A](elements: Iterable[A]) -> Effect[A, NoSuchElementException]:
    """A random element of ``elements``. A non-empty tuple cannot fail; any
    other iterable fails with ``NoSuchElementException`` when empty."""
    buffer = list(elements)
    if not buffer:
        return fail_sync(
            lambda: NoSuchElementException("Cannot select a random element from an empty array")
        )
    n = len(buffer)
    return _random_with(lambda r: buffer[min(n - 1, math.floor(r.unsafe_next_double() * n))])


class _WithSeed:
    __slots__ = ("seed",)

    def __init__(self, seed: str | float) -> None:
        self.seed = seed

    def __call__[A, E, R](self, eff: Effect[A, E, R]) -> Effect[A, E, R]:
        seed = self.seed

        def seeded() -> Effect[A, E, R]:
            generator = Isaac(seed)
            return _Locally(eff, lambda ctx: ctx.add(Random, generator))

        return suspend(seeded)


def with_seed(seed: str | float) -> _WithSeed:
    """Run an effect with a generator seeded by ``seed``, restarted on each
    run: the same seed gives the same numbers (the same as in Effect)::

    eff.pipe(random.with_seed("my-seed"))
    """
    return _WithSeed(seed)
