"""Constructors, generators, and the combinators that remove types.

Most combinators are methods on ``Effect``. The ones here are either
constructors or need ``.pipe(...)`` because they remove something from a
type (an error class, a service), which pyright can only infer when the
thing being removed is known before the effect is seen.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable, Generator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Never, overload

from pyfect._core import (
    Effect,
    _Callback,
    _FailCause,
    _FromExit,
    _Gen,
    _Locally,
    _MatchCause,
    _Succeed,
    _Suspend,
    _Sync,
    _WithFiber,
    _YieldNow,
)
from pyfect._fiber import Fiber
from pyfect.cause import Cause, Fail
from pyfect.cause import die as die_cause
from pyfect.cause import fail as fail_cause_of
from pyfect.cause import interrupt as interrupt_cause
from pyfect.context import TagLike, tag_class
from pyfect.exit import Exit

# --- constructors -------------------------------------------------------------


def succeed[A](value: A) -> Effect[A]:
    return _Succeed(value)


def fail[E](error: E) -> Effect[Never, E]:
    return _FailCause(fail_cause_of(error))


def fail_cause[E](cause: Cause[E]) -> Effect[Never, E]:
    return _FailCause(cause)


def die(defect: BaseException) -> Effect[Never]:
    return _FailCause(die_cause(defect))


def from_exit[A, E](ex: Exit[A, E]) -> Effect[A, E]:
    return _FromExit(ex)


def sync[A](thunk: Callable[[], A]) -> Effect[A]:
    """Run a side effect when the effect runs. If ``thunk`` raises, that is
    a defect; use ``try_`` to turn exceptions into typed errors."""
    return _Sync(thunk)


def try_[A, E](thunk: Callable[[], A], catch: Callable[[Exception], E]) -> Effect[A, E]:
    """Run ``thunk``, mapping a raised exception to a typed error."""

    def run() -> Effect[A, E]:
        try:
            return _Succeed(thunk())
        except Exception as exc:
            return _FailCause(fail_cause_of(catch(exc)))

    return _Suspend(run)


def suspend[A, E = Never, R = Never](thunk: Callable[[], Effect[A, E, R]]) -> Effect[A, E, R]:
    """Build the effect each time it runs. Useful for recursion."""
    return _Suspend(thunk)


def callback[A, E = Never, R = Never](
    register: Callable[[Callable[[Effect[A, E, R]], None]], Effect[object, Never, R] | None],
) -> Effect[A, E, R]:
    """Wrap a callback-based API. ``register`` receives ``resume``; call it
    once, from any thread, with the effect to continue with. Return an
    effect to run if the fiber is interrupted while waiting, or ``None``.
    """
    return _Callback(register)


def from_async[A](make: Callable[[], Awaitable[A]]) -> Effect[A]:
    """Await an awaitable. Requires ``run_async``/``run_main`` (an asyncio
    loop). Raised exceptions are defects; interruption cancels the task and
    waits for it to finish."""
    return _await(make, None)


def try_async[A, E](
    make: Callable[[], Awaitable[A]], catch: Callable[[Exception], E]
) -> Effect[A, E]:
    """Like ``from_async``, mapping raised exceptions to a typed error."""
    return _await(make, catch)


class AsyncioRequiredError(RuntimeError):
    """``from_async`` ran without an asyncio loop (e.g. under ``run_sync``)."""


def _await[A, E](
    make: Callable[[], Awaitable[A]], catch: Callable[[Exception], E] | None
) -> Effect[A, E]:
    def register(resume: Callable[[Effect[A, E]], None]) -> Effect[None]:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            raise AsyncioRequiredError(
                "from_async/try_async need an asyncio loop; run with run_async or run_main"
            ) from None
        task = loop.create_task(_as_coroutine(make()))

        def done(t: asyncio.Task[A]) -> None:
            if t.cancelled():
                resume(_FailCause(interrupt_cause()))
                return
            exc = t.exception()
            if exc is None:
                resume(_Succeed(t.result()))
            elif catch is not None and isinstance(exc, Exception):
                resume(_FailCause(fail_cause_of(catch(exc))))
            else:
                resume(_FailCause(die_cause(exc)))

        task.add_done_callback(done)
        return _cancel_task(task)

    return _Callback(register)


async def _as_coroutine[A](aw: Awaitable[A]) -> A:
    return await aw


def _cancel_task(task: asyncio.Task[Any]) -> Effect[None]:
    def register(resume: Callable[[Effect[None]], None]) -> None:
        task.cancel()
        task.add_done_callback(lambda _: resume(_Succeed(None)))

    return _Callback(register)


_executor: ThreadPoolExecutor | None = None


def _pool() -> ThreadPoolExecutor:
    global _executor  # noqa: PLW0603 - one lazily-created pool per process
    if _executor is None:
        _executor = ThreadPoolExecutor(thread_name_prefix="pyfect-blocking")
    return _executor


def blocking[A](thunk: Callable[[], A]) -> Effect[A]:
    """Run blocking code on a worker thread without blocking other fibers.
    Raised exceptions are defects. A running thread cannot be stopped, so
    interruption abandons it and does not wait."""
    return _blocking(thunk, None)


def try_blocking[A, E](thunk: Callable[[], A], catch: Callable[[Exception], E]) -> Effect[A, E]:
    """Like ``blocking``, mapping raised exceptions to a typed error."""
    return _blocking(thunk, catch)


def _blocking[A, E](thunk: Callable[[], A], catch: Callable[[Exception], E] | None) -> Effect[A, E]:
    def register(resume: Callable[[Effect[A, E]], None]) -> None:
        def done(fut: Future[A]) -> None:
            exc = fut.exception()
            if exc is None:
                resume(_Succeed(fut.result()))
            elif catch is not None and isinstance(exc, Exception):
                resume(_FailCause(fail_cause_of(catch(exc))))
            else:
                resume(_FailCause(die_cause(exc)))

        _pool().submit(thunk).add_done_callback(done)

    return _Callback(register)


never: Effect[Never] = _Callback(lambda _resume: None)
"""Never completes. Can be interrupted."""

void: Effect[None] = _Succeed(None)


def yield_now() -> Effect[None]:
    """Let other fibers run before continuing."""
    return _YieldNow()


def interrupt() -> Effect[Never]:
    """Interrupt the current fiber."""
    return _WithFiber(lambda f: _FailCause(interrupt_cause(f.id)))


def fiber_id() -> Effect[int]:
    return _WithFiber(lambda f: _Succeed(f.id))


def current_fiber() -> Effect[Fiber[Any, Any]]:
    return _WithFiber(_Succeed)


# --- generators -----------------------------------------------------------------


def gen[A, E = Never, R = Never](
    f: Callable[[], Generator[Effect[Any, E, R], Any, A]],
) -> Effect[A, E, R]:
    """Build an effect from a generator function. Inside it,
    ``x = yield from eff`` runs ``eff``. Works as a decorator::

        @gen
        def program():
            user = yield from find_user("u1")
            return user.name
    """
    return _Gen(f)


def fn[**P, A, E = Never, R = Never](
    f: Callable[P, Generator[Effect[Any, E, R], Any, A]],
) -> Callable[P, Effect[A, E, R]]:
    """Turn a generator function with parameters into a function that
    returns an effect::

        @fn
        def find_user(user_id: str):
            db = yield from Database()
            ...
    """

    @functools.wraps(f)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Effect[A, E, R]:
        return _Gen(lambda: f(*args, **kwargs))

    return wrapper


# --- combinators that remove types (use with .pipe) ---------------------------


class _CatchTag[EC, B, E2, R2]:
    __slots__ = ("handler", "tag")

    def __init__(self, tag: type[EC], handler: Callable[[EC], Effect[B, E2, R2]]) -> None:
        self.tag = tag
        self.handler = handler

    @overload
    def __call__[A, R = Never](self, eff: Effect[A, EC, R]) -> Effect[A | B, E2, R | R2]: ...
    @overload
    def __call__[A, R = Never, ER = Never](
        self, eff: Effect[A, EC | ER, R]
    ) -> Effect[A | B, ER | E2, R | R2]: ...
    def __call__(self, eff: Effect[Any, Any, Any]) -> Effect[Any, Any, Any]:
        tag, handler = self.tag, self.handler

        def on_failure(cause: Cause[Any]) -> Effect[Any, Any, Any]:
            found = cause.find_recoverable_error()
            if not isinstance(found, Fail):
                return _FailCause(found)
            if isinstance(found.error, tag):
                return handler(found.error)
            return _FailCause(cause)

        return _MatchCause(eff, on_failure, None)


def catch_tag[EC, B, E2 = Never, R2 = Never](
    tag: type[EC], handler: Callable[[EC], Effect[B, E2, R2]]
) -> _CatchTag[EC, B, E2, R2]:
    """Recover from one error class and remove it from ``E``::

    eff.pipe(catch_tag(NotFound, lambda e: succeed(None)))
    """
    return _CatchTag(tag, handler)


class _ProvideService[S, T]:
    __slots__ = ("service", "tag")

    def __init__(self, tag: type[Any], service: S) -> None:
        self.tag = tag
        self.service = service

    @overload
    def __call__[A, E = Never](self, eff: Effect[A, E, T]) -> Effect[A, E]: ...
    @overload
    def __call__[A, E = Never, R = Never](self, eff: Effect[A, E, T | R]) -> Effect[A, E, R]: ...
    def __call__(self, eff: Effect[Any, Any, Any]) -> Effect[Any, Any, Any]:
        tag, service = self.tag, self.service
        return _Locally(eff, lambda ctx: ctx.add(tag, service))


def provide_service[S, T](tag: TagLike[S, T], service: S) -> _ProvideService[S, T]:
    """Provide one service directly and remove it from ``R``::

    eff.pipe(provide_service(Database, InMemoryDb()))
    """
    return _ProvideService(tag_class(tag), service)


# Re-exported so ``pyfect.effect`` is a complete toolbox.
__all__ = [
    "AsyncioRequiredError",
    "blocking",
    "callback",
    "catch_tag",
    "current_fiber",
    "die",
    "fail",
    "fail_cause",
    "fiber_id",
    "fn",
    "from_async",
    "from_exit",
    "gen",
    "interrupt",
    "never",
    "provide_service",
    "succeed",
    "suspend",
    "sync",
    "try_",
    "try_async",
    "try_blocking",
    "void",
    "yield_now",
]
