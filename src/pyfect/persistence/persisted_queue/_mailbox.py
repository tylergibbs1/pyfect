"""The local mailbox of a polled store (Redis, SQL): one poller per queue
claims as many elements as there are waiting takers and hands them out
through an in-memory queue."""

from __future__ import annotations

from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass, field
from typing import Any, Never

from pyfect._core import Effect, Restore, uninterruptible_mask
from pyfect.clock import sleep
from pyfect.duration import Seconds
from pyfect.effect import gen, sync, yield_now
from pyfect.latch import Latch
from pyfect.logger import log_warning
from pyfect.queue import Queue
from pyfect.rc_map import RcMap
from pyfect.schedule import spaced
from pyfect.scope import Scope, scoped


@dataclass(slots=True)
class Mailbox[T]:
    """Elements claimed for this process's takers, ``takers`` of them
    waiting. The poller runs while ``poll_latch`` is open, and after
    handing out a batch waits at ``taken_latch`` until every taker of the
    batch has its element."""

    queue: Queue[T] = field(default_factory=Queue[T])
    takers: int = 0
    poll_latch: Latch = field(default_factory=Latch)
    taken_latch: Latch = field(default_factory=Latch)


def run_poller[T](
    mailbox: Mailbox[T],
    *,
    poll: Callable[[int], Effect[Sequence[T], Any]],
    nudge: Latch,
    poll_interval: Seconds,
) -> Effect[None, Never, Scope]:
    """Fork the mailbox's poller into the scope: while takers wait it
    claims up to that many elements with ``poll``, and when there are none
    waits ``poll_interval`` or until ``nudge`` opens. A failed poll is
    logged and the poller restarts after 500 ms."""

    def body() -> Generator[Any, Any]:
        while True:
            yield from mailbox.poll_latch.wait()
            yield from yield_now()
            nudge.unsafe_close()
            results: Sequence[T] = [] if mailbox.takers == 0 else (yield from poll(mailbox.takers))
            if not results:
                yield from sleep(poll_interval).race(nudge.wait())
                continue
            mailbox.taken_latch.unsafe_close()
            yield from mailbox.queue.offer_all(results)
            yield from mailbox.taken_latch.wait()
            yield from yield_now()

    return (
        gen(body)
        .tap_cause(log_warning)
        .sandbox()
        .retry(spaced(0.5))
        .interruptible()
        .fork_scoped()
        .as_void()
    )


def take_from[K, T, A, E](
    mailboxes: RcMap[K, Mailbox[T], Any],
    key: K,
    then: Callable[[T], Effect[A, E, Scope]],
) -> Effect[A, E, Scope]:
    """Wait for the next element of ``key``'s mailbox and run ``then`` on
    it uninterruptibly, so no interruption loses a claimed element. The
    taker is counted while it waits (an interrupted wait stops counting
    too, so the poller never fetches for a taker that left)."""

    def body(restore: Restore) -> Effect[A, E, Scope]:
        def wait(mailbox: Mailbox[T]) -> Effect[T, Never]:
            mailbox.takers += 1
            if mailbox.takers == 1:
                mailbox.poll_latch.unsafe_open()

            def leave() -> None:
                mailbox.takers -= 1
                if mailbox.takers == 0:
                    mailbox.poll_latch.unsafe_close()
                    mailbox.taken_latch.unsafe_open()
                elif mailbox.queue.unsafe_size() == 0:
                    mailbox.taken_latch.unsafe_open()

            return restore(mailbox.queue.take()).on_exit(lambda _: sync(leave))

        return scoped(mailboxes.get(key).flat_map(wait)).flat_map(then)

    return uninterruptible_mask(body)
