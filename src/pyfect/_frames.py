"""Every thread's frames, without corrupting a subinterpreter.

CPython 3.14 before 3.14.8 has ``sys._current_frames()`` make a frame object for the running
frame of every thread of every interpreter, from the calling interpreter's allocator; the
subinterpreter later frees it into its own heap (python/cpython#158364). There
``current_frames()`` reads nothing while a pyfect subinterpreter runs code, and
``interpreter_pool`` runs all of its subinterpreter code inside ``running_subinterpreter()``.
``tests/test_current_frames_guard.py`` keeps every other ``sys._current_frames()`` out.
"""

import sys
import threading
from collections.abc import Generator
from contextlib import contextmanager
from types import FrameType

_READS_EVERY_INTERPRETER = (3, 14) <= sys.version_info < (3, 14, 8)


class _Running:
    """How many threads run code in a pyfect subinterpreter now."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.count = 0


_running = _Running()


@contextmanager
def running_subinterpreter() -> Generator[None]:
    """Around code this thread runs in a subinterpreter: creating, calling, destroying it."""
    with _running.lock:
        _running.count += 1
    try:
        yield
    finally:
        with _running.lock:
            _running.count -= 1


def current_frames() -> dict[int, FrameType]:
    """``sys._current_frames()`` as the caller would read it, its own thread at the caller's
    frame; only the caller's own thread where reading the others now would corrupt a running
    subinterpreter."""
    if not _READS_EVERY_INTERPRETER:
        frames = sys._current_frames()  # pyright: ignore[reportPrivateUsage]
    else:
        with _running.lock:
            frames = {} if _running.count else sys._current_frames()  # pyright: ignore[reportPrivateUsage]
    frames[threading.get_ident()] = sys._getframe(1)  # pyright: ignore[reportPrivateUsage]
    return frames
