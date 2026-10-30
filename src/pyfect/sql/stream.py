"""Streams from drivers that push rows (Effect's ``effect/sql/SqlStream``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from pyfect._core import Effect, _Suspend, _Sync, _WithFiber
from pyfect.cause import fail
from pyfect.errors import Done
from pyfect.queue import Queue
from pyfect.run import run_fork
from pyfect.scheduler import CurrentScheduler
from pyfect.scope import Scope

if TYPE_CHECKING:
    from pyfect._fiber import Fiber
    from pyfect.stream import Stream


class PauseResume(Protocol):
    """How the stream tells the source to stop and start pushing."""

    def on_pause(self) -> None: ...
    def on_resume(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Emit[A, E]:
    """What the source calls to push rows, fail or end. Call it on the
    stream's scheduler thread."""

    single: Callable[[A], None]
    array: Callable[[Sequence[A]], None]
    fail: Callable[[E], None]
    end: Callable[[], None]


def async_pause_resume[A, E, R](
    register: Callable[[Emit[A, E]], Effect[PauseResume, E, R | Scope]],
    buffer_size: int = 128,
) -> Stream[A, E, R]:
    """A stream of what the source pushes through ``Emit``. When the
    buffer of ``buffer_size`` rows is full, the source is paused until the
    rows it pushed meanwhile fit."""
    from pyfect import stream

    def start(queue: Queue[A, E | Done]) -> Effect[None, E, R | Scope]:
        def body(fiber: Fiber[Any, Any]) -> Effect[None, E, R | Scope]:
            scheduler = fiber.get_ref(CurrentScheduler)
            callbacks: list[PauseResume] = []
            paused = [False]

            def resumed() -> None:
                callbacks[0].on_resume()
                paused[0] = False

            def offer(items: Sequence[A]) -> None:
                if not items:
                    return
                full = queue.is_full_unsafe()
                if not full or paused[0]:
                    run_fork(queue.offer_all(items), scheduler=scheduler)
                    return
                paused[0] = True
                callbacks[0].on_pause()
                run_fork(queue.offer_all(items).tap(lambda _: _Sync(resumed)), scheduler=scheduler)

            emit = Emit[A, E](
                single=lambda item: offer((item,)),
                array=offer,
                fail=lambda error: _discard(queue.fail_cause_unsafe(fail(error))),
                end=lambda: _discard(queue.fail_cause_unsafe(fail(Done()))),
            )
            return register(emit).map(callbacks.append)

        return _WithFiber(body)

    return stream.callback(lambda queue: _Suspend(lambda: start(queue)), buffer_size=buffer_size)


def _discard(_: object) -> None:
    return None


__all__ = ["Emit", "PauseResume", "async_pause_resume"]
