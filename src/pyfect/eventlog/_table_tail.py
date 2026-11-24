"""The change stream of a SQL event log storage, read from the table it
writes. Effect streams new batches from an in-process PubSub, so a server
streams only the writes it took, while servers sharing the database store
others and report them as the latest sequence. Read from the table, the
stream holds every write, whichever server took it.

A storage's ``wakes`` carries no data: a write publishes to it after its
commit, so readers on the same server see it at once. Writes of other
servers are found every ``poll_interval``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Never

from pyfect._core import Effect
from pyfect.duration import Duration, from_input_unsafe
from pyfect.duration import Input as DurationInput
from pyfect.effect import die, succeed, suspend
from pyfect.errors import IllegalArgumentError
from pyfect.option import Some
from pyfect.pubsub import PubSub, Subscription
from pyfect.scope import Scope, acquire_release
from pyfect.stream import Stream, paginate

type Page[A] = tuple[Sequence[A], int]
"""The items read and the sequence to read from next."""


def parse_poll_interval(poll_interval: DurationInput) -> Effect[Duration]:
    """``poll_interval`` as a ``Duration``. Dies with an
    ``IllegalArgumentError`` unless it is positive and finite: a reader
    that never polls misses entries ``latest_sequence`` reports."""

    def parse() -> Effect[Duration]:
        parsed = from_input_unsafe(poll_interval)
        if not (parsed.is_positive() and parsed.is_finite()):
            return die(IllegalArgumentError("poll_interval must be positive and finite"))
        return succeed(parsed)

    return suspend(parse)


def make_wakes() -> Effect[PubSub[None], Never, Scope]:
    """A storage's wakes, shut down with the scope. A reader keeps at most
    one unread wake: one is enough to read again."""
    return acquire_release(PubSub[None].sliding(1), lambda p, _: p.shutdown())


def tail[A, E](
    *,
    wakes: Subscription[None],
    poll_interval: Duration,
    first: Effect[Page[A], E],
    after: Callable[[int], Effect[Page[A], E]],
) -> Stream[A, E]:
    """The items of ``first``, then of ``after(next)`` each time a wake
    comes or ``poll_interval`` passes. Subscribe to ``wakes`` before
    ``first`` reads, so no commit falls between a read and the wait."""
    wait = wakes.take_all().timeout_option(poll_interval)

    def page(read: Effect[Page[A], E]) -> Effect[tuple[Sequence[A], Some[Effect[Page[A], E]]], E]:
        return read.map(lambda found: (found[0], Some(wait.and_then(after(found[1])))))

    return paginate(first, page)
