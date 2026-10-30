"""The queue a subscription to an outside publisher (a PostgreSQL
``LISTEN``, a Redis ``SUBSCRIBE``) hands the program.

It holds at most ``capacity`` messages the program has not taken. A
publisher that gets further ahead fails the subscription with a
``FellBehind`` cause (the messages already held are taken first), the way
Redis drops a subscriber whose output buffer is full: memory stays bounded
and nothing is lost silently.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Final

from pyfect.cause import fail as fail_cause
from pyfect.queue import Queue

DEFAULT_CAPACITY: Final = 1024


class FellBehind(Exception):
    """The program left ``capacity`` messages untaken while more arrived."""

    def __init__(self, what: str, capacity: int) -> None:
        super().__init__(
            f"{what}: the subscriber fell behind, holding {capacity} messages it had not "
            "taken; take faster or pass a larger capacity"
        )


def check_capacity(capacity: int) -> int:
    """``capacity`` when it can hold a message; raises ``ValueError``."""
    if isinstance(capacity, bool) or capacity < 1:
        raise ValueError(f"capacity must be a positive int, got {capacity!r}")
    return capacity


def offer[A, E](queue: Queue[A, E], items: Sequence[A], behind: Callable[[], E]) -> bool:
    """Add ``items`` to ``queue`` (a ``Queue.dropping(capacity)``) without
    waiting; when they do not all fit, fail
    ``queue`` with ``behind()`` and give ``False``: stop delivering. Call on
    the queue's fibers' scheduler thread."""
    if not queue.unsafe_offer_all(items):
        return True
    queue.unsafe_fail_cause(fail_cause(behind()))
    return False
