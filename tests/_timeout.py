"""Fail a test that runs longer than the ``test_timeout`` ini value (a hang).

A fiber parked forever (a lost wake-up, an uninterruptible wait) blocks
``run_sync`` with no error. The alarm turns that into a failure with a
traceback that shows where the test was stuck.
"""

import signal
from collections.abc import Generator
from types import FrameType

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini("test_timeout", "Seconds a test may run before it fails as hung.", default="60")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None, object, object]:
    seconds = float(item.config.getini("test_timeout"))

    def on_alarm(signum: int, frame: FrameType | None) -> None:
        pytest.fail(f"test hung: still running after {seconds:g}s")

    previous = signal.signal(signal.SIGALRM, on_alarm)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return (yield)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
