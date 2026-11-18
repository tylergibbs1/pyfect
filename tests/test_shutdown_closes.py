"""A close started on a client's loop runs to its end before the loop closes, even when it
starts while the client is shutting down.

CI (run 44334314912) caught a response's ``aclose`` destroyed while pending: an abort
scheduled the close after the httpx backend had drained its closes, while
``client.aclose()`` ran, and the loop thread then cancelled it or closed under it. A
response dropped during shutdown must still be closed, or its connection leaks. Every
close a loop must wait for now goes through ``pyfect._background.start``, and a
``LoopThread`` drains those until none is left before its loop closes."""

from __future__ import annotations

import asyncio
import gc
import logging
from typing import Any

import pytest

import pyfect as fx
from pyfect import _background as background
from pyfect._loop_thread import LoopThread
from pyfect.http.httpx_client import _Backend  # pyright: ignore[reportPrivateUsage]

_SETTLED = 5.0


class _Response:
    """Stands in for an ``httpx.Response`` whose close is still running when its loop is
    asked to stop: it ends only after the stop request."""

    def __init__(self, thread: LoopThread) -> None:
        self.closed = False
        self._thread = thread

    async def aclose(self) -> None:
        await asyncio.shield(self._thread._stop)  # pyright: ignore[reportPrivateUsage]
        await asyncio.sleep(0)
        self.closed = True


def test_a_response_aborted_while_the_client_closes_is_closed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend = _Backend({})
    dropped = _Response(backend._thread)  # pyright: ignore[reportPrivateUsage]
    client_aclose = backend.client.aclose

    async def aclose_with_an_abort() -> None:
        # The drain has run; an abort lands now, as the client closes.
        backend._call_soon(lambda: backend._close_response(dropped))  # pyright: ignore[reportPrivateUsage, reportArgumentType]
        await asyncio.sleep(0)
        await client_aclose()

    backend.client.aclose = aclose_with_an_abort
    fx.run_blocking(backend.close())
    assert dropped.closed
    gc.collect()
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []


def test_a_close_started_as_the_loop_stops_runs_to_its_end() -> None:
    thread = LoopThread("test-loop")
    dropped = _Response(thread)

    def start_close() -> None:
        background.start(dropped.aclose(), thread.loop)

    async def stop_then_close() -> Any:
        thread.stop()
        # After the stop request, before the loop has settled.
        thread.loop.call_soon(start_close)

    thread.submit(stop_then_close).result(_SETTLED)
    thread.stopped.result(_SETTLED)
    assert dropped.closed
