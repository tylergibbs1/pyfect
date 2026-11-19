"""``with`` / ``async with`` for scopes, from plain Python code.

A block exits a scope as an effect would end in it: normally (``Success``),
by a raise (a defect, as Effect makes anything thrown) or by Ctrl-C or
asyncio cancellation (an interruption). The scope closes with that exit,
running its finalizers as ``CloseableScope.close`` does. What is left to
raise is what ``run.unwrap`` raises for the cause ``scoped`` would end
with, except that a block's own exception always propagates, unchanged but
for a note holding the finalizers that failed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Never

from pyfect._cause_election import finalizer_cause
from pyfect.cause import Cause, empty
from pyfect.exit import Exit, Failure, Success, die, interrupt
from pyfect.run import run_async_exit, run_blocking_exit, unwrap

if TYPE_CHECKING:
    from pyfect.scope import CloseableScope


def exit_of(exc: BaseException | None) -> Exit[None, Never]:
    """How a block that raised ``exc`` (or nothing) ended, as a fiber's exit."""
    if exc is None:
        return Success(None)
    if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)):
        return interrupt()
    return die(exc)


def exit_blocking(scope: CloseableScope, exc: BaseException | None) -> None:
    """Close ``scope`` as a block that raised ``exc`` (or nothing) leaves it,
    blocking this thread."""
    _after_block(exc, run_blocking_exit(scope.close(exit_of(exc))))


async def exit_async(scope: CloseableScope, exc: BaseException | None) -> None:
    """``exit_blocking`` on the running loop."""
    _after_block(exc, await run_async_exit(scope.close(exit_of(exc))))


def fail_blocking(scope: CloseableScope, failure: Failure[Any]) -> Never:
    """Close ``scope`` with ``failure``, blocking this thread, and raise the
    cause ``scoped`` would end with."""
    _raise(_ended(failure, run_blocking_exit(scope.close(failure))))


async def fail_async(scope: CloseableScope, failure: Failure[Any]) -> Never:
    """``fail_blocking`` on the running loop."""
    _raise(_ended(failure, await run_async_exit(scope.close(failure))))


def _after_block(exc: BaseException | None, closed: Exit[None, Any]) -> None:
    if not isinstance(closed, Failure):
        return
    if exc is None:
        _raise(_ended(Success(None), closed))
    exc.add_note(_failed_finalizers(exc, closed.cause))


def _failed_finalizers(block: BaseException, finalizers: Cause[Any]) -> str:
    """The note on ``block``, the exception propagating, for the finalizers
    that failed after it. They ran while it was being handled, so it is their
    errors' context; the note leaves it out, as the exception is already shown."""
    with _context_hidden(block, finalizers.pretty_errors()):
        return "Failed finalizers:\n" + finalizers.pretty()


@contextmanager
def _context_hidden(context: BaseException, errors: Iterable[BaseException]) -> Generator[None]:
    """While inside, ``errors`` and their chains render without ``context``
    as an implicit context; they are left as they were on leaving."""
    hidden: list[BaseException] = []
    seen: set[int] = {id(context)}
    todo = list(errors)
    while todo:
        error = todo.pop()
        if id(error) in seen:
            continue
        seen.add(id(error))
        if error.__context__ is context and not error.__suppress_context__:
            error.__suppress_context__ = True
            hidden.append(error)
        todo.extend(e for e in (error.__cause__, error.__context__) if e is not None)
    try:
        yield
    finally:
        for error in hidden:
            error.__suppress_context__ = False


def _ended(body: Exit[Any, Any], closed: Exit[None, Any]) -> Cause[Any]:
    """The cause a scoped effect that ended with ``body`` fails with once its
    scope closed with ``closed`` (``combineFinalizerCause``)."""
    if isinstance(closed, Failure):
        return finalizer_cause(body, closed.cause)
    return body.cause if isinstance(body, Failure) else empty


def _raise(cause: Cause[Any]) -> Never:
    unwrap(Failure(cause))
    raise AssertionError("unreachable: unwrap raises every failure")


__all__ = ["exit_async", "exit_blocking", "exit_of", "fail_async", "fail_blocking"]
