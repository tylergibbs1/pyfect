"""Fail a test during which asyncio reports lost work.

asyncio only logs a task collected while still pending ("Task was
destroyed but it is pending") or a failed task nobody awaited ("exception
was never retrieved"); neither is a warning, so ``filterwarnings`` misses
them. Each is work cut short or an error lost, and fails the test running
when it is reported (as an unraisable exception does).
"""

import logging
from collections.abc import Generator

import pytest

_LOST = ("Task was destroyed but it is pending", "exception was never retrieved")


class _Reports(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.ERROR)
        self.lost: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if any(lost in message for lost in _LOST):
            self.lost.append(message)


_reports = _Reports()


def pytest_configure(config: pytest.Config) -> None:
    logging.getLogger("asyncio").addHandler(_reports)


def pytest_unconfigure(config: pytest.Config) -> None:
    logging.getLogger("asyncio").removeHandler(_reports)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None, object, object]:
    result = yield
    lost, _reports.lost = _reports.lost, []
    if lost:
        pytest.fail("asyncio lost work during this test:\n" + "\n".join(lost))
    return result
