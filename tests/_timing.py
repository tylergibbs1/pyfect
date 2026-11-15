"""Waiting for another thread in a test, without timing it.

``wait_until`` polls for something another thread does, failing only once a hang is
certain. It is a hang detector, never a speed check: growth checks measure CPU time
through ``tests/_growth.py``, and timing a test checks (a timeout firing, a retry
spacing) goes through the ``TestClock``.
"""

from __future__ import annotations

import time
from collections.abc import Callable

HANG_SECONDS = 30.0
"""How long ``wait_until`` polls before it calls a wait a hang, well under the 60 s
per-test alarm (``tests/_timeout.py``)."""


def wait_until(ready: Callable[[], bool], *, what: str, poll: float = 0.001) -> None:
    """Poll ``ready`` until it is true; fail as hung after ``HANG_SECONDS``."""
    deadline = time.monotonic() + HANG_SECONDS
    while not ready():
        assert time.monotonic() < deadline, f"hung: waited {HANG_SECONDS:g}s for {what}"
        time.sleep(poll)
