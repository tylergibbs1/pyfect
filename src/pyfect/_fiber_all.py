"""Waiting on and interrupting several fibers at once (``Fiber.await_all``,
``join_all``, ``interrupt_all``, ``interrupt_all_as``), and
``Effect.await_all_children``.

Every wait here registers observers on the fibers and removes them when it
is interrupted, so an abandoned wait leaves nothing behind.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Any, Never

from pyfect._core import Effect, _Callback, _FromExit, _Succeed, _Sync, _WithFiber
from pyfect._fiber import Fiber
from pyfect.exit import Exit, Failure


def await_all[A, E](fibers: Iterable[Fiber[A, E]]) -> Effect[list[Exit[A, E]]]:
    """Wait for every fiber, one after another; succeed with their exits in
    order. ``fibers`` is read when the effect runs."""

    def register(resume: Callable[[Effect[list[Exit[A, E]]]], None]) -> Effect[None]:
        state = _AwaitAll(iter(fibers), resume)
        state.loop()
        return _Sync(state.cancel)

    return _Callback(register)


class _AwaitAll[A, E]:
    """One ``await_all`` wait: a loop on a state object, not closures that
    reach each other (that cycle would keep the exits alive after the wait).
    ``remove`` holds the observer, so it is cleared once used."""

    __slots__ = ("exits", "remaining", "remove", "resume")

    def __init__(
        self, remaining: Iterator[Fiber[A, E]], resume: Callable[[Effect[list[Exit[A, E]]]], None]
    ) -> None:
        self.remaining = remaining
        self.resume = resume
        self.exits: list[Exit[A, E]] = []
        self.remove: Callable[[], None] | None = None

    def loop(self) -> None:
        for fiber in self.remaining:
            ex = fiber.poll_unsafe()
            if ex is not None:
                self.exits.append(ex)
                continue
            self.remove = fiber.add_observer_unsafe(self.observe)
            return
        self.resume(_Succeed(self.exits))

    def observe(self, ex: Exit[A, E]) -> None:
        self.remove = None
        self.exits.append(ex)
        self.loop()

    def cancel(self) -> None:
        remove = self.remove
        if remove is not None:
            self.remove = None
            remove()


def join_all[A, E](fibers: Iterable[Fiber[A, E]]) -> Effect[list[A], E]:
    """Wait for every fiber and succeed with their values in order. The
    first failure ends the wait with that failure; the other fibers keep
    running."""

    def register(resume: Callable[[Effect[list[A], E]], None]) -> Effect[None] | None:
        joined = list(fibers)
        if not joined:
            resume(_Succeed([]))
            return None
        values: list[Any] = [None] * len(joined)
        removers: list[Callable[[], None]] = []
        done = 0
        failed = False

        def stop() -> None:
            nonlocal failed
            failed = True
            for remove in removers:
                remove()

        def observer_for(index: int) -> Callable[[Exit[A, E]], None]:
            def observer(ex: Exit[A, E]) -> None:
                nonlocal done
                done += 1
                if isinstance(ex, Failure):
                    stop()
                    resume(_FromExit(ex))
                    return
                values[index] = ex.value
                if done == len(joined):
                    resume(_Succeed(values))

            return observer

        for index, fiber in enumerate(joined):
            if failed:
                break
            removers.append(fiber.add_observer_unsafe(observer_for(index)))
        return _Sync(stop)

    return _Callback(register)


def interrupt_all_as(fibers: Iterable[Fiber[Any, Any]], by: int | None) -> Effect[None]:
    """Interrupt every fiber as the fiber with id ``by``, then wait for all
    of them to finish. Each fiber is interrupted as it is drawn from
    ``fibers``, so a lazy iterable sees what earlier interrupts changed."""

    def body(me: Fiber[Any, Any]) -> Effect[None]:
        annotations = me._interruptor_annotations()
        interrupted: list[Fiber[Any, Any]] = []
        for fiber in fibers:
            fiber.interrupt_as_unsafe(by, annotations)
            interrupted.append(fiber)
        return await_all(interrupted).as_void()

    return _WithFiber(body)


def interrupt_all(fibers: Iterable[Fiber[Any, Any]]) -> Effect[None]:
    """Interrupt every fiber, then wait for all of them to finish."""
    return _WithFiber(lambda me: interrupt_all_as(fibers, me.id))


def await_all_children[A, E, R](eff: Effect[A, E, R]) -> Effect[A, E, R]:
    def body(fiber: Fiber[Any, Any]) -> Effect[A, E, R]:
        before = fiber._children.copy()
        interruptible = fiber._interruptible

        def wait_for_children(_: Exit[A, E]) -> Effect[None, Never, Never]:
            forked = [child for child in fiber._children if child not in before]
            if not forked:
                return _Succeed(None)
            waiting = await_all(forked).as_void()
            return waiting.interruptible() if interruptible else waiting

        return eff.on_exit(wait_for_children)

    return _WithFiber(body)
