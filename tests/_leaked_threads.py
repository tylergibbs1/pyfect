"""Names the threads a test leaves running after its teardown.

A thread a test started and never stopped runs on through the tests after it, in the same
process: its work lands in their call counters, timers and stall samples. The check notes the
threads alive when a test's setup starts and, after its teardown, warns about each new thread
still running, with the frames it is running.

pyfect's own runtime threads (the blocking pools' workers, the background scheduler, the
loop threads) start on first use and outlive the test that started them; parked at their
idle point they run nothing, so they are not reported. A runtime thread still running a
test's work, such as an abandoned blocking call, is.
"""

import sys
import threading
import traceback
from collections.abc import Generator
from pathlib import Path
from types import FrameType

import pytest
from _threads import live_threads

import pyfect

_BEFORE = pytest.StashKey[frozenset[threading.Thread]]()
_SRC = str(Path(pyfect.__file__).parent) + "/"
_IDLE = frozenset(
    {
        ("_blocking_pool.py", "_next"),
        ("scheduler.py", "_run_until"),
        ("_loop_thread.py", "_run"),
    }
)
"""Where each runtime thread waits for work: its innermost pyfect frame while it waits."""
_SETTLE_TRIES = 50
_SETTLE_STEP = 0.01
"""A thread finishing (a worker between its thunk and its idle point) gets up to 0.5 s."""
_FRAMES = 4


class LeakedThreadWarning(pytest.PytestWarning):
    """A test left a thread it started running after its teardown."""


def _frame(thread: threading.Thread) -> FrameType | None:
    return sys._current_frames().get(thread.ident or -1)  # pyright: ignore[reportPrivateUsage]


def _parked(frame: FrameType) -> bool:
    current: FrameType | None = frame
    while current is not None:
        code = current.f_code
        if code.co_filename.startswith(_SRC):
            return (Path(code.co_filename).name, code.co_name) in _IDLE
        current = current.f_back
    return False


def _running(thread: threading.Thread) -> FrameType | None:
    """The frame ``thread`` is running once it settles, or None once it ends or parks."""
    for _ in range(_SETTLE_TRIES):
        frame = _frame(thread)
        if not thread.is_alive() or frame is None or _parked(frame):
            return None
        thread.join(_SETTLE_STEP)
    return _frame(thread)


def _where(frame: FrameType) -> str:
    stack = traceback.extract_stack(frame)[-_FRAMES:]
    return "; ".join(f"in {f.name} ({f.filename}:{f.lineno})" for f in reversed(stack))


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    item.stash[_BEFORE] = frozenset(live_threads(""))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    before = item.stash.get(_BEFORE, None)
    if call.when == "teardown" and before is not None:
        for thread in live_threads(""):
            frame = None if thread in before else _running(thread)
            if frame is not None:
                item.warn(
                    LeakedThreadWarning(f"left thread {thread.name!r} running: {_where(frame)}")
                )
    return report


__all__ = ["LeakedThreadWarning"]
