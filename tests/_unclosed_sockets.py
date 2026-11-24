"""Fail the test that leaves a socket for the garbage collector to close.

A socket (or the asyncio transport over it) dropped while still open warns only when the
collector reaches it, and that may be many tests later, in whichever test then allocates
enough to start a collection: the ``ResourceWarning`` fails a test that did nothing wrong
and says nothing of who opened the socket (CI run 45294143911 failed an RPC test that way).
So after the teardown of each test that made a socket, the collector runs, and a
``ResourceWarning`` it raises fails that test, naming the transport's protocol (who owned
it). A test that made no socket skips the collection.
"""

import gc
import sys
import tracemalloc
import warnings
from collections.abc import Generator

import pytest

_made = [False]


def _note(event: str, _args: tuple[object, ...]) -> None:
    if event == "socket.__new__":
        _made[0] = True


def pytest_configure(config: pytest.Config) -> None:
    # Audit hooks stay for the life of the process; this one only sets a flag.
    sys.addaudithook(_note)


def _owner(source: object) -> str:
    """Who held ``source``: an asyncio transport's protocol, and where it was made when
    tracemalloc traces (``PYTHONTRACEMALLOC=20``)."""
    protocol = getattr(source, "_protocol", None)
    owner = "" if protocol is None else f" (protocol {type(protocol).__qualname__})"
    made = tracemalloc.get_object_traceback(source) if source is not None else None
    return owner if made is None else owner + "\n" + "\n".join(made.format())


def unclosed_after_collecting() -> list[str]:
    """The ``ResourceWarning``s a full collection raises now; other warnings it raises
    are issued again as they would have been."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        gc.collect()
    unclosed: list[str] = []
    for warning in caught:
        if issubclass(warning.category, ResourceWarning):
            unclosed.append(f"{warning.message}{_owner(warning.source)}")
        else:
            warnings.warn_explicit(
                warning.message,
                warning.category,
                warning.filename,
                warning.lineno,
                source=warning.source,
            )
    return unclosed


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item: pytest.Item) -> Generator[None, object, object]:
    result = yield
    if _made[0]:
        _made[0] = False
        unclosed = unclosed_after_collecting()
        if unclosed:
            pytest.fail(
                "this test left sockets for the garbage collector to close:\n" + "\n".join(unclosed)
            )
    return result
