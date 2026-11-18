"""Names the threads a test file's tests leave running after the file is done.

A thread a test started and never stopped runs on through the tests after it, in the same
process: its work lands in their call counters, timers and stall samples. The check notes the
threads alive when a test's setup starts and, after its teardown, the new ones still alive.
Once the file's last test is torn down (its module-scoped layers with it), it warns about each
of those still running, naming the test that left it and the frames it is running: as an
error in that last test's teardown, or with ``leaked_threads = warn`` as a warning. Within a
file, a thread may outlive a test: a module's shared layer (``testing.layer_fixture``, Effect's
``it.layer``) keeps its connections, and their server threads, for every test in the file.

pyfect's own runtime threads (the blocking pools' workers, the background scheduler, the
loop threads) start on first use and outlive the test that started them; parked at their
idle point they run nothing, so they are not reported. A runtime thread still running a
test's work, such as an abandoned blocking call, is. Test peers kept for the whole process
name their threads with ``_threads.process_wide`` and are skipped too.
"""

import concurrent.futures.thread
import sys
import threading
import traceback
from collections.abc import Generator
from pathlib import Path
from types import FrameType

import pytest
from _threads import PROCESS_WIDE, live_threads

import pyfect

_BEFORE = pytest.StashKey[frozenset[threading.Thread]]()
_LEFT = pytest.StashKey[dict[threading.Thread, str]]()
"""The threads tests of the current file left alive, with the test that left each."""
_LEAKED = pytest.StashKey[list[str]]()
"""What the file's last test found still running once the file was done."""
_SRC = str(Path(pyfect.__file__).parent) + "/"
_IDLE = frozenset(
    {
        ("_blocking_pool.py", "_next"),
        ("scheduler.py", "_run_until"),
        ("_loop_thread.py", "_run"),
    }
)
"""Where each runtime thread waits for work: its innermost pyfect frame while it waits."""
_EXECUTOR_IDLE = concurrent.futures.thread._worker.__code__  # pyright: ignore[reportPrivateUsage]
"""An executor worker waiting for work: a pyfect loop's (``<loop>-executor``) is runtime too."""
_SETTLE_TRIES = 50
_SETTLE_STEP = 0.01
"""A thread finishing (a worker between its thunk and its idle point) gets up to 0.5 s."""
_FRAMES = 4


class LeakedThreadWarning(pytest.PytestWarning):
    """A test left a thread it started running after its file was done."""


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini(
        "leaked_threads",
        "A thread a test file's tests leave running past the file: fail or warn.",
        default="fail",
    )


def _frame(thread: threading.Thread) -> FrameType | None:
    return sys._current_frames().get(thread.ident or -1)  # pyright: ignore[reportPrivateUsage]


def _parked(thread: threading.Thread, frame: FrameType) -> bool:
    if thread.name.startswith("pyfect-") and frame.f_code is _EXECUTOR_IDLE:
        return True
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
        if not thread.is_alive() or frame is None or _parked(thread, frame):
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
def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> Generator[None]:
    yield
    before = item.stash.get(_BEFORE, None)
    if before is None:
        return
    left = item.config.stash.setdefault(_LEFT, {})
    for thread in live_threads(""):
        if thread not in before and not thread.name.startswith(PROCESS_WIDE):
            left.setdefault(thread, item.nodeid)
    if nextitem is not None and nextitem.path == item.path:
        return
    item.stash[_LEAKED] = [
        f"{test} left thread {thread.name!r} running past its file: {_where(frame)}"
        for thread, test in left.items()
        if (frame := _running(thread)) is not None
    ]
    left.clear()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Fails the teardown of a file's last test with the threads its tests left running."""
    report = yield
    leaked = item.stash.get(_LEAKED, None) if call.when == "teardown" else None
    if not leaked:
        return report
    if item.config.getini("leaked_threads") == "warn":
        for leak in leaked:
            item.warn(LeakedThreadWarning(leak))
    elif report.passed:
        report.outcome = "failed"
        report.longrepr = "\n".join(leaked)
    return report


__all__ = ["LeakedThreadWarning"]
