"""The errors and values a ``retry``, ``repeat`` or ``schedule`` loop sees are freed
when the run ends, without the cycle collector: a loop built from closures that
reach themselves keeps its last error alive in a reference cycle, and an HTTP
response held that way keeps its socket open (``test_http_client_connection_release``)."""

from __future__ import annotations

import gc
import weakref
from collections.abc import Callable, Iterator

import pytest

import pyfect as fx
from pyfect.schedule import recurs


class _Seen:
    """An error or value whose lifetime the test watches."""


@pytest.fixture(autouse=True)
def _no_cycle_collector() -> Iterator[None]:
    gc.collect()
    gc.disable()
    try:
        yield
    finally:
        gc.enable()


def _freed_after(run: Callable[[_Seen], fx.Effect[object, object]]) -> bool:
    seen = _Seen()
    ref = weakref.ref(seen)
    fx.run_sync_exit(run(seen))
    del seen
    return ref() is None


def test_retry_frees_its_last_error() -> None:
    assert _freed_after(lambda seen: fx.fail(seen).retry(times=2))


def test_retry_frees_an_error_it_recovered_from() -> None:
    def run(seen: _Seen) -> fx.Effect[object, object]:
        failed = [False]

        def attempt() -> fx.Effect[object, _Seen]:
            if failed[0]:
                return fx.succeed(1)
            failed[0] = True
            return fx.fail(seen)

        return fx.suspend(attempt).retry(times=2)

    assert _freed_after(run)


def test_repeat_frees_its_last_value() -> None:
    assert _freed_after(lambda seen: fx.succeed(seen).repeat(times=2))


def test_schedule_frees_its_last_value() -> None:
    assert _freed_after(lambda seen: fx.succeed(seen).schedule(recurs(2)))
