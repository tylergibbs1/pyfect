"""The live terminal reads its descriptor on worker threads; once a reader
has stopped, none of those reads is left to run, so input that arrives
afterwards stays on the descriptor for whoever reads it next.

Each test holds every worker thread busy while the reader stops, so the
reader's next read is still waiting for a thread: a read abandoned there
would run once the threads free up and take the input. On Windows a read
cannot time out, so a stopped reader leaves it."""

import io
import os
import select
import sys
import threading
import time
from collections.abc import Generator
from typing import Any

import pytest

import pyfect as fx
from pyfect import terminal, testing
from pyfect.errors import TimeoutException

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Windows reads are abandoned")

_EVERY_WORKER = 32
"""At least as many tasks as ``fx.blocking`` has worker threads."""


def _read_now(fd: int) -> bytes:
    """What ``fd`` holds now, without blocking if it is empty."""
    if not select.select([fd], [], [], 0)[0]:
        return b""
    return os.read(fd, 100)


class _Workers:
    """Holds every worker thread busy until ``free`` (or a moment after
    ``hold``, so a reader that waits for its read can stop)."""

    def __init__(self) -> None:
        self._release = threading.Event()
        self._timer = threading.Timer(0.3, self._release.set)

    @fx.fn
    def hold(self) -> Generator[fx.Effect[Any, Any, Any], Any]:
        for _ in range(_EVERY_WORKER):
            yield from fx.blocking(self._release.wait).fork_daemon()
        # A read already running finishes and the reader queues its next.
        yield from fx.sleep("100 millis")
        self._timer.start()

    def free(self) -> None:
        self._timer.cancel()
        if not self._release.is_set():
            self._release.set()
            # A read left queued has run by now.
            time.sleep(0.3)


@testing.live
def test_input_after_a_key_reader_closes_stays_on_the_descriptor():
    read, write = os.pipe()
    workers = _Workers()
    try:
        os.write(write, b"y")
        service = terminal.live(input=read, output=io.StringIO())

        @fx.fn
        def take_one_key() -> Generator[fx.Effect[Any, Any, Any], Any]:
            queue = yield from service.read_input
            yield from queue.take()
            yield from workers.hold()

        yield from fx.scoped(take_one_key())
        os.write(write, b"z")
        workers.free()
        assert _read_now(read) == b"z"
    finally:
        workers.free()
        os.close(read)
        os.close(write)


@testing.live
def test_input_after_an_interrupted_line_read_stays_on_the_descriptor():
    read, write = os.pipe()
    workers = _Workers()
    try:
        service = terminal.live(input=read, output=io.StringIO())
        yield from workers.hold()
        timed_out = yield from service.read_line.timeout("20 millis").flip()
        assert isinstance(timed_out, TimeoutException)
        os.write(write, b"z")
        workers.free()
        assert _read_now(read) == b"z"
    finally:
        workers.free()
        os.close(read)
        os.close(write)
