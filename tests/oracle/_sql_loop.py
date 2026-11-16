"""Hold the asyncio loop the SQL drivers run on (``pyfect.sql._loop``), so
work a test starts through it stays in flight until the test lets go.

``_loop.call`` resumes its fiber at once when the loop thread settles the
call before the fiber waits, so a fiber forked with ``start_immediately``
can finish its statements before ``fork`` returns (a loaded runner
deschedules the test's thread). A test that needs a call still in flight
starts it inside ``held()``: the loop runs callbacks in order, and the one
parking it was queued first. ``tests/test_sql_in_flight_guard.py`` makes
such tests use it.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Generator

from pyfect.sql._loop import get_loop


@contextlib.contextmanager
def held() -> Generator[None]:
    """Park the SQL loop's thread until the block exits: every call started
    inside waits until then."""
    go = threading.Event()
    get_loop().call_soon_threadsafe(go.wait)
    try:
        yield
    finally:
        go.set()
