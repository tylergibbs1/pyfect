"""``Logger.batched``: buffer outputs and flush them on a timer."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Never

from pyfect._core import Effect, Restore, _Succeed, _Suspend, uninterruptible_mask
from pyfect.clock import sleep
from pyfect.duration import Duration
from pyfect.logger._model import Logger, Options
from pyfect.scope import Scope, add_finalizer

_VOID: Effect[None] = _Succeed(None)


def batched[O](
    logger: Logger[O], window: Duration, flush: Callable[[Sequence[O]], Effect[object]]
) -> Effect[Logger[None], Never, Scope]:
    def make() -> Effect[Logger[None], Never, Scope]:
        buffer: list[O] = []

        def drain() -> Effect[object]:
            if not buffer:
                return _VOID
            batch = buffer.copy()
            buffer.clear()
            return flush(batch)

        flush_buffer = _Suspend(drain).uninterruptible()

        def push(options: Options) -> None:
            buffer.append(logger.log(options))

        def start(restore: Restore) -> Effect[Logger[None], Never, Scope]:
            timer = restore(sleep(window).and_then(flush_buffer).forever())
            return (
                timer.fork_daemon()
                .flat_map(
                    # Let a flush in progress finish, then flush what is left.
                    lambda fiber: add_finalizer(lambda _: fiber.interrupt().and_then(flush_buffer))
                )
                .as_(Logger(push))
            )

        return uninterruptible_mask(start)

    return _Suspend(make)
