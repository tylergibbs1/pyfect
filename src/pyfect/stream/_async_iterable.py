"""``Stream.to_async_iterable``: reading a stream with ``async for``.

Each ``__aiter__`` starts a fresh run of the stream with a scope of its
own. ``__anext__`` runs one pull on a root fiber of the running asyncio
loop; ``aclose()`` (Effect's ``return``) interrupts a pull in flight and
closes the scope, and ``athrow(error)`` closes it with ``error`` as a
defect, then raises ``error``. ``async for`` does not close an iterator it
leaves early: use ``contextlib.aclosing`` for that.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any, Generic, NoReturn, TypeVar

from pyfect._core import Effect, _Succeed
from pyfect._fiber import Fiber
from pyfect.context import Context
from pyfect.exit import Exit, Failure, Success, die
from pyfect.logger import log_error
from pyfect.pull import is_done_cause
from pyfect.run import await_fiber, run_async, run_fork
from pyfect.scope import CloseableScope
from pyfect.stream._base import StreamChannel

A_co = TypeVar("A_co", covariant=True)

_VOID: Effect[None] = _Succeed(None)
_DONE: Exit[None, Any] = Success(None)


class StreamAsyncIterable(Generic[A_co]):
    """A stream to read with ``async for`` (Effect's ``AsyncIterable``).
    Make one with ``Stream.to_async_iterable`` (or ``_with`` / ``_effect``
    for a stream that needs services)."""

    __slots__ = ("_channel", "_context")

    def __init__(self, chunks: StreamChannel[A_co, Any, Any], context: Context) -> None:
        self._channel = chunks
        self._context = context

    def __aiter__(self) -> StreamAsyncIterator[A_co]:
        return StreamAsyncIterator(self._channel, self._context)


class StreamAsyncIterator(Generic[A_co]):
    """One run of a stream, read item by item. ``aclose()`` stops it."""

    __slots__ = ("_channel", "_chunk", "_closing", "_context", "_fiber", "_pull", "_scope")

    def __init__(self, chunks: StreamChannel[A_co, Any, Any], context: Context) -> None:
        self._channel = chunks
        self._context = context
        self._scope = CloseableScope()
        self._pull: Effect[tuple[A_co, ...], Any, Any] | None = None
        self._chunk: Iterator[A_co] | None = None
        self._fiber: Fiber[tuple[A_co, ...], Any] | None = None
        self._closing: asyncio.Task[None] | None = None

    def __aiter__(self) -> StreamAsyncIterator[A_co]:
        return self

    async def __anext__(self) -> A_co:
        if self._closing is not None:
            return await self._ended()
        if self._chunk is not None:
            for item in self._chunk:
                return item
            self._chunk = None
        fiber = run_fork(self._next_pull(), context=self._context)
        self._fiber = fiber
        try:
            ex = await await_fiber(fiber)
        finally:
            if self._fiber is fiber:
                self._fiber = None
        if isinstance(ex, Success):
            self._chunk = iter(ex.value)
            return next(self._chunk)
        if is_done_cause(ex.cause):
            await self._close(_DONE)
            raise StopAsyncIteration
        if self._closing is not None and ex.cause.has_interrupts_only:
            return await self._ended()
        await self._close_reporting(ex)
        raise ex.cause.raisable()

    async def aclose(self) -> None:
        """Interrupt a pull in flight and close the run's scope. Closing
        again does nothing; ``__anext__`` then ends at once."""
        await self._close(_DONE)

    async def athrow(self, error: BaseException) -> NoReturn:
        """Close the run's scope with ``error`` as a defect, then raise
        ``error``."""
        await self._close_reporting(die(error))
        raise error

    def _next_pull(self) -> Effect[tuple[A_co, ...], Any, Any]:
        if self._pull is not None:
            return self._pull

        def keep(pull: Effect[tuple[A_co, ...], Any, Any]) -> Effect[tuple[A_co, ...], Any, Any]:
            self._pull = pull
            return pull

        return self._channel.to_pull_scoped(self._scope).flat_map(keep)

    async def _ended(self) -> NoReturn:
        await self._close(_DONE)
        raise StopAsyncIteration

    def _close(self, ex: Exit[Any, Any]) -> asyncio.Task[None]:
        if self._closing is None:
            fiber = self._fiber
            stop = _VOID if fiber is None else fiber.interrupt()
            closing = stop.and_then(self._scope.close(ex))
            self._closing = asyncio.ensure_future(run_async(closing, context=self._context))
        return self._closing

    async def _close_reporting(self, ex: Failure[Any]) -> None:
        try:
            await self._close(ex)
        except Exception as error:
            report = log_error("Suppressed error while closing Stream async iterator", error)
            await run_async(report, context=self._context)
