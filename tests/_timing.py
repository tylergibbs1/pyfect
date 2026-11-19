"""Waiting for another thread in a test, without timing it.

``wait_until`` polls for something another thread does, failing only once a hang is
certain (``settled`` says whether it came, for a caller that reports what is stuck). It is
a hang detector, never a speed check: growth checks measure CPU time
through ``tests/_growth.py``, and timing a test checks (a timeout firing, a retry
spacing) goes through the ``TestClock``. ``at_least`` checks real I/O took at least so
long (a server waiting out its own timer); it has no upper bound to give, as load only
ever slows a block down. Check that something real happens promptly by ordering it
before a later event instead.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Generator
from contextlib import contextmanager

HANG_SECONDS = 30.0
"""How long ``wait_until`` polls before it calls a wait a hang, well under the 60 s
per-test alarm (``tests/_timeout.py``)."""


def settled(ready: Callable[[], bool], *, poll: float = 0.001) -> bool:
    """Poll ``ready`` until it is true; false once ``HANG_SECONDS`` have passed."""
    deadline = time.monotonic() + HANG_SECONDS
    while not ready():
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll)
    return True


def wait_until(ready: Callable[[], bool], *, what: str, poll: float = 0.001) -> None:
    """Poll ``ready`` until it is true; fail as hung after ``HANG_SECONDS``."""
    assert settled(ready, poll=poll), f"hung: waited {HANG_SECONDS:g}s for {what}"


@contextmanager
def at_least(seconds: float, *, what: str) -> Generator[None]:
    """Fail unless the block took ``seconds`` of real time or more."""
    started = time.monotonic()
    yield
    took = time.monotonic() - started
    assert took >= seconds, f"{what} took {took:.3f}s, under {seconds:g}s"
