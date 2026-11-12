"""The two primitives that keep pull loops fast: a loop that pulls until
the pull fails, and a pull reading a Python iterator.

Both run on the fiber's explicit stack, so a loop over millions of items
never grows Python's stack, and each item costs one or two fiber steps.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator, Iterator
from itertools import islice
from typing import TYPE_CHECKING, Any, Never, final

from pyfect._core import Effect, Step
from pyfect.cause import Cause, Fail
from pyfect.errors import Done
from pyfect.exit import Failure, Success

if TYPE_CHECKING:
    from pyfect._fiber import Fiber


@final
class PullLoop(Effect[Never, Any, Any]):
    """Run ``pull`` again and again, handing each item to ``step``, until it
    fails; the failure (``Done`` included) is the loop's."""

    __slots__ = ("pull", "step")

    def __init__(self, pull: Effect[Any, Any, Any], step: Callable[[Any], object]) -> None:
        self.pull = pull
        self.step = step

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        fiber._push(self)
        return self.pull

    def _on_success(self, value: Any, fiber: Fiber[Any, Any]) -> Step:
        self.step(value)
        fiber._push(self)
        return self.pull


def _done(leftover: object) -> Failure[Done[Any]]:
    return Failure(Cause((Fail(Done(leftover)),)))


@final
class IteratorPull(Effect[Any, Done[Any], Never]):
    """The next item of ``iterator``; ``Done(return value)`` when it stops.
    An exception from the iterator is a defect."""

    __slots__ = ("iterator",)

    def __init__(self, iterator: Iterator[Any]) -> None:
        self.iterator = iterator

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        try:
            return Success(next(self.iterator))
        except StopIteration as stop:
            return _done(stop.value)


@final
class ChunkPull(Effect[tuple[Any, ...], Done[Any], Never]):
    """Up to ``size`` items of ``iterator`` as a non-empty tuple; ``Done``
    once it stops. A generator's return value is the ``Done``'s leftover."""

    __slots__ = ("ended", "generator", "iterator", "leftover", "size")

    def __init__(self, iterator: Iterator[Any], size: int) -> None:
        self.iterator = iterator
        self.size = size
        # Only a generator has a return value to keep; other iterators are
        # read in C, a chunk at a time.
        self.generator = isinstance(iterator, Generator)
        self.ended: bool = False
        self.leftover: object = None

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        if self.ended:
            return _done(self.leftover)
        if not self.generator:
            chunk = tuple(islice(self.iterator, self.size))
            if len(chunk) < self.size:
                self.ended = True
            return Success(chunk) if chunk else _done(None)
        items: list[Any] = []
        try:
            while len(items) < self.size:
                items.append(next(self.iterator))
        except StopIteration as stop:
            if not items:
                # As Effect's: the next pull asks the generator again.
                return _done(stop.value)
            self.ended = True
            self.leftover = stop.value
        return Success(tuple(items))
