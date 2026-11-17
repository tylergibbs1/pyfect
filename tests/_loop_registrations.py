"""Fail a test that leaves the socket loop watching a closed descriptor.

A descriptor closed while ``pyfect-net``'s selector still has it registered
stays registered: the kernel drops a closed descriptor from epoll and kqueue,
but the selector keeps its entry. The next socket given that descriptor's
number then never reads, because ``add_reader`` sees the entry and only
replaces its callback, so a later test times out waiting for data it was
sent. The check runs on the loop after the callbacks the test queued, so a
removal the test queued before closing has had its turn.
"""

import os
import threading
from collections.abc import Generator

import pytest

from pyfect.socket import _loop


def _closed_registrations() -> list[int]:
    loop = _loop._Shared.loop  # pyright: ignore[reportPrivateUsage]
    if loop is None:
        return []
    found: list[int] = []
    checked = threading.Event()

    def check() -> None:
        for key in loop._selector.get_map().values():  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]
            try:
                os.fstat(key.fd)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            except OSError:
                found.append(key.fd)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        checked.set()

    loop.call_soon_threadsafe(check)
    assert checked.wait(10), "the socket loop did not run the registration check"
    return found


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None, object, object]:
    result = yield
    closed = _closed_registrations()
    if closed:
        pytest.fail(
            f"the socket loop still watches closed descriptors {closed}: remove the reader on "
            "the loop before closing the socket (as _NativeSocket.close does), or the next "
            "socket given that number never reads"
        )
    return result
