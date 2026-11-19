"""Fail a test that runs longer than the ``test_timeout`` ini value (a hang).

A fiber parked forever (a lost wake-up, an uninterruptible wait) blocks
``run_blocking`` with no error. The alarm turns that into a failure with a
traceback that shows where the test was stuck.

An event loop running when the alarm fires would swallow ``pytest.fail``:
asyncio runs callbacks catching every exception but ``KeyboardInterrupt`` and
``SystemExit``, and reports the rest to its exception handler, so a test
spinning in a callback (anyio's repeated cancels, say) would hang for good.
There the alarm raises ``_Hung``, a ``KeyboardInterrupt`` the loop lets
through, and this plugin turns it back into the failure, naming where the
test was stuck. Until the test ends the alarm fires again every
``_AGAIN`` seconds at most: an exception caught on its way out (a loop's
shutdown cancelling a task that waits through cancels) is raised again, and
a ``pytest.fail`` swallowed elsewhere becomes a ``_Hung``.
"""

import asyncio
import signal
import traceback
from collections.abc import Generator
from contextlib import contextmanager
from types import FrameType
from typing import Any

import pytest

_AGAIN = 1.0
"""Seconds at most between the alarm's raises, after the first."""


class _Hung(KeyboardInterrupt):
    """The alarm's failure where an event loop would swallow ``pytest.fail``."""

    def __init__(self, stuck: str) -> None:
        super().__init__(stuck)
        self.stuck = stuck


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini("test_timeout", "Seconds a test may run before it fails as hung.", default="60")


def _running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _where_stuck(
    test_file: str, frame: FrameType | None, loop: asyncio.AbstractEventLoop | None
) -> str:
    """The test thread's stack from the test's own frame, then each other task of a running loop
    where it awaits: in a loop, the thread itself is mostly between callbacks."""
    stack = traceback.extract_stack(frame)
    starts = [at for at, entry in enumerate(stack) if entry.filename == test_file]
    parts = ["".join(traceback.format_list(stack[starts[0] if starts else 0 :]))]
    tasks: set[asyncio.Task[Any]] = set()
    if loop is not None:
        current = asyncio.current_task(loop)
        tasks = {task for task in asyncio.all_tasks(loop) if task is not current}
    for task in tasks:
        frames = [(f, f.f_lineno) for f in task.get_stack()]
        awaits = "".join(traceback.format_list(traceback.StackSummary.extract(frames)))
        parts.append(f"task {task.get_name()} awaits in:\n{awaits}")
    return "\n".join(parts)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None, object, object]:
    seconds = float(item.config.getini("test_timeout"))
    hung = f"test hung: still running after {seconds:g}s"
    fired = False
    stuck: str | None = None
    """Where the first ``_Hung`` found the test; a later one may land in its cleanup."""

    def on_alarm(signum: int, frame: FrameType | None) -> None:
        nonlocal fired, stuck
        signal.setitimer(signal.ITIMER_REAL, min(seconds, _AGAIN))
        loop = _running_loop()
        if fired or loop is not None:
            fired = True
            stuck = stuck or _where_stuck(str(item.path), frame, loop)
            raise _Hung(stuck)
        fired = True
        pytest.fail(hung)

    previous = signal.signal(signal.SIGALRM, on_alarm)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return (yield)
    except _Hung as error:
        signal.setitimer(signal.ITIMER_REAL, 0)
        pytest.fail(f"{hung}; stuck in:\n{error.stuck}", pytrace=False)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@contextmanager
def suspended() -> Generator[None]:
    """The running test's alarm stopped, and given back what it had left after: for a shared
    server's start (``oracle/_shared_server.py``), which waits on its own deadline and fails
    with its own cause instead of as the first test that happened to ask for it."""
    remaining, _ = signal.setitimer(signal.ITIMER_REAL, 0)
    try:
        yield
    finally:
        if remaining:
            signal.setitimer(signal.ITIMER_REAL, remaining)
