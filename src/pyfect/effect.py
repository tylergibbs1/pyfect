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
import inspect
from collections.abc import Awaitable, Callable, Generator
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from typing import TYPE_CHECKING, Any, Never, Unpack, cast, overload

from pyfect._catch import catch_all, catch_if, catch_tag
from pyfect._catch_reason import catch_reason, catch_reasons, unwrap_reason
from pyfect._context_effects import (
    context,
    provide_context,
    provide_service_effect,
    service_option,
    update_service_scoped,
)
from pyfect._core import (
    Effect,
    _Callback,
    _FailCause,
    _FromExit,
    _Gen,
    _Locally,
    _Succeed,
    _Suspend,
    _Sync,
    _WithFiber,
    _YieldNow,
)
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect._os_wait import os_wait
from pyfect._root import loop_running_here, run_loop
from pyfect._stack_frame import CurrentStackFrame, StackFrame, call_site
from pyfect.cause import Cause
from pyfect.cause import die as die_cause
from pyfect.cause import fail as fail_cause_of
from pyfect.cause import interrupt as interrupt_cause
from pyfect.context import Context, TagLike, tag_class
from pyfect.errors import NoSuchElementException, UnknownError
from pyfect.exit import Exit
from pyfect.option import Option, Some
from pyfect.result import Ok, Result

if TYPE_CHECKING:
    from pyfect.tracer import SpanOptions

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


def fail_sync[E](thunk: Callable[[], E]) -> Effect[Never, E]:
    """Fail with ``thunk()``, computed each time the effect runs."""
    return _Suspend(lambda: fail(thunk()))


def fail_cause_sync[E](thunk: Callable[[], Cause[E]]) -> Effect[Never, E]:
    """Fail with the cause ``thunk()``, computed each time the effect runs."""
    return _Suspend(lambda: fail_cause(thunk()))


def from_result[A = Never, E = Never](result: Result[A, E]) -> Effect[A, E]:
    """Succeed with an ``Ok``'s value or fail with an ``Err``'s error."""
    return _Succeed(result.value) if isinstance(result, Ok) else fail(result.error)


@overload
def from_option[A = Never](option: Option[A]) -> Effect[A, NoSuchElementException]: ...
@overload
def from_option[E, A = Never](option: Option[A], on_none: Callable[[], E]) -> Effect[A, E]: ...
def from_option(option: Option[Any], on_none: Callable[[], Any] | None = None) -> Effect[Any, Any]:
    """Succeed with a ``Some``'s value. ``None`` fails with ``on_none()``,
    computed each time the effect runs, or a ``NoSuchElementException``."""
    if option is not None:
        return _Succeed(option.value)
    if on_none is None:
        return fail(NoSuchElementException("from_option: None"))
    return fail_sync(on_none)


def from_optional[A = Never](value: A | None) -> Effect[A, NoSuchElementException]:
    """Succeed with ``value``, or fail with ``NoSuchElementException`` if it
    is ``None``. When ``None`` can be a real value, use ``from_option``."""
    return fail(NoSuchElementException()) if value is None else _Succeed(value)


def transpose_option[A = Never, E = Never, R = Never](
    option: Option[Effect[A, E, R]],
) -> Effect[Option[A], E, R]:
    """Run the effect inside a ``Some``, keeping its value in a ``Some``."""
    if option is None:
        return _Succeed(None)
    require_effect(option.value, "option.value")
    return option.value.map(Some)


@overload
def try_[A](thunk: Callable[[], A]) -> Effect[A, UnknownError]: ...
@overload
def try_[A, E](thunk: Callable[[], A], catch: Callable[[Exception], E]) -> Effect[A, E]: ...
def try_(
    thunk: Callable[[], Any], catch: Callable[[Exception], Any] | None = None
) -> Effect[Any, Any]:
    """Run ``thunk``, mapping a raised exception to a typed error with
    ``catch``, or to an ``UnknownError``. If ``catch`` raises, that is a
    defect."""
    to_error = _unknown_error_in("try_") if catch is None else catch

    def run() -> Effect[Any, Any]:
        try:
            return _Succeed(thunk())
        except Exception as exc:
            return _failure_of(to_error, exc)

    return _Suspend(run)


def _unknown_error_in(name: str) -> Callable[[Exception], UnknownError]:
    return lambda exc: UnknownError(exc, f"An error occurred in {name}")


def _failure_of[E](catch: Callable[[Exception], E] | None, exc: BaseException) -> Effect[Never, E]:
    """The failure for ``exc`` raised by user code. ``catch`` runs when the
    effect runs, on the fiber, so a raising ``catch`` is a defect rather than
    an exception lost in a done callback. Without ``catch``, or for a
    ``BaseException`` that is not an ``Exception``, ``exc`` is a defect."""
    if catch is None or not isinstance(exc, Exception):
        return _FailCause(die_cause(exc))
    return _Suspend(lambda: fail(catch(exc)))


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


@overload
def try_async[A](make: Callable[[], Awaitable[A]]) -> Effect[A, UnknownError]: ...
@overload
def try_async[A, E](
    make: Callable[[], Awaitable[A]], catch: Callable[[Exception], E]
) -> Effect[A, E]: ...
def try_async(
    make: Callable[[], Awaitable[Any]], catch: Callable[[Exception], Any] | None = None
) -> Effect[Any, Any]:
    """Like ``from_async``, mapping an exception raised by ``make`` or the
    awaitable to a typed error with ``catch``, or to an ``UnknownError``. If
    ``catch`` raises, that is a defect."""
    return _await(make, _unknown_error_in("try_async") if catch is None else catch)


class AsyncioRequiredError(RuntimeError):
    """``from_async`` ran without an asyncio loop (e.g. under ``run_sync``)."""


def _await[A, E](
    make: Callable[[], Awaitable[A]], catch: Callable[[Exception], E] | None
) -> Effect[A, E]:
    def start() -> Effect[A, E]:
        loop = run_loop()
        if loop is None:
            raise AsyncioRequiredError(
                "from_async/try_async need an asyncio loop, and run_sync blocks this thread's "
                "loop until it returns; use await run_async(...) inside a coroutine"
                if loop_running_here()
                else "from_async/try_async need an asyncio loop; run with run_async or run_main"
            )
        try:
            awaitable = make()
        except KeyboardInterrupt:
            raise  # Ctrl-C: the loop interrupts the fiber (Fiber._raised)
        except BaseException as exc:
            return _failure_of(catch, exc)
        return _Callback(lambda resume: register(loop, awaitable, resume))

    def register(
        loop: asyncio.AbstractEventLoop,
        awaitable: Awaitable[A],
        resume: Callable[[Effect[A, E]], None],
    ) -> Effect[None]:
        task = loop.create_task(_as_coroutine(awaitable))

        def done(t: asyncio.Task[A]) -> None:
            if t.cancelled():
                resume(_FailCause(interrupt_cause()))
                return
            exc = t.exception()
            if isinstance(exc, _Exited):
                exc = exc.exit
            resume(_Succeed(t.result()) if exc is None else _failure_of(catch, exc))

        task.add_done_callback(done)
        return _cancel_task(task)

    return _Suspend(start)


async def _as_coroutine[A](aw: Awaitable[A]) -> A:
    try:
        return await aw
    except SystemExit as exc:
        # asyncio would re-raise it out of the loop, past the fiber.
        raise _Exited(exc) from None


class _Exited(Exception):
    """A ``SystemExit`` raised by an awaited coroutine, on its way to the
    fiber, which makes it a defect as from any other user code."""

    def __init__(self, exit: SystemExit) -> None:
        super().__init__(exit)
        self.exit = exit


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


@overload
def try_blocking[A](thunk: Callable[[], A]) -> Effect[A, UnknownError]: ...
@overload
def try_blocking[A, E](thunk: Callable[[], A], catch: Callable[[Exception], E]) -> Effect[A, E]: ...
def try_blocking(
    thunk: Callable[[], Any], catch: Callable[[Exception], Any] | None = None
) -> Effect[Any, Any]:
    """Like ``blocking``, mapping a raised exception to a typed error with
    ``catch``, or to an ``UnknownError``. If ``catch`` raises, that is a
    defect."""
    return _blocking(thunk, _unknown_error_in("try_blocking") if catch is None else catch)


def _blocking[A, E](thunk: Callable[[], A], catch: Callable[[Exception], E] | None) -> Effect[A, E]:
    def register(resume: Callable[[Effect[A, E]], None]) -> None:
        def done(fut: Future[A]) -> None:
            exc = fut.exception()
            resume(_Succeed(fut.result()) if exc is None else _failure_of(catch, exc))

        _pool().submit(thunk).add_done_callback(done)

    return os_wait(register, waits_for="work")


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
    _generator_function(f, "gen")
    return _Gen(f)


@overload
def fn[**P, A, E = Never, R = Never](
    f: Callable[P, Generator[Effect[Any, E, R], Any, A]], /
) -> Callable[P, Effect[A, E, R]]: ...
@overload
def fn(name: str, /, **options: Unpack[SpanOptions]) -> _Traced: ...
def fn(
    f: Callable[..., Generator[Effect[Any, Any, Any], Any, Any]] | str,
    /,
    **options: Unpack[SpanOptions],
) -> Callable[..., Effect[Any, Any, Any]] | _Traced:
    """Turn a generator function with parameters into a function that
    returns an effect::

        @fn
        def find_user(user_id: str):
            db = yield from Database()
            ...

    ``@fn("name")`` (with span options as keywords) also runs every call
    inside a span of that name, the parent of the spans made inside.

    Each call of a named function also runs inside a stack frame for its
    call site under one for the definition (``"name (definition)"``), so a
    failure inside records both (``tracer.StackTrace``). The bare ``@fn``
    is Effect's ``fnUntraced``: no span and no frames.
    """
    if isinstance(f, str):
        return _Traced(f, options, call_site(1))
    _generator_function(f, "fn")

    @functools.wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Effect[Any, Any, Any]:
        return _Gen(lambda: f(*args, **kwargs))

    return wrapper


def _traced(
    f: Callable[..., Generator[Effect[Any, Any, Any], Any, Any] | Effect[Any, Any, Any]],
    name: str,
    definition: Callable[[], str | None],
    span: SpanOptions,
) -> Callable[..., Effect[Any, Any, Any]]:
    """``f`` as a function returning an effect that runs inside a span
    ``name`` and a stack frame for the call (``name`` at the call site)
    under one for the definition."""
    from pyfect.tracer._spans import in_parent_span, span_using

    definition_name = f"{name} (definition)"

    # Built apart from ``wrapper`` so the frame never holds the call's
    # arguments, which forked fibers inheriting it would keep alive.
    def enter_at(stack: Callable[[], str | None]) -> Callable[[Context], Context]:
        def enter(ctx: Context) -> Context:
            caller = ctx.lookup(CurrentStackFrame)[1]
            frame = StackFrame(name, stack, StackFrame(definition_name, definition, caller))
            return ctx.add(CurrentStackFrame, frame)

        return enter

    def run_body(result: object) -> Effect[Any, Any, Any]:
        # Effect.fn's ``isEffect(iter) ? iter : fromIteratorUnsafe(iter)``.
        if isinstance(result, Effect):
            return cast("Effect[Any, Any, Any]", result)
        if isinstance(result, Generator):
            generator = cast("Generator[Effect[Any, Any, Any], Any, Any]", result)
            return _Gen(lambda: generator)
        return _FailCause(
            die_cause(
                TypeError(
                    f"fn({name!r}): {f.__qualname__} returned {type(result).__name__}, "
                    "not an effect or a generator; an effect inside it runs only with "
                    "`yield from effect`"
                )
            )
        )

    @functools.wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Effect[Any, Any, Any]:
        body: Effect[Any, Any, Any] = _Suspend(lambda: run_body(f(*args, **kwargs)))
        traced = span_using(name, partial(in_parent_span, body), span)
        return _Locally(traced, enter_at(call_site(1)))

    return wrapper


class _Traced:
    """``@fn("name")``: the decorator that adds the span."""

    __slots__ = ("definition", "name", "options")

    def __init__(
        self, name: str, options: SpanOptions, definition: Callable[[], str | None]
    ) -> None:
        self.name = name
        self.options = options
        self.definition = definition

    @overload
    def __call__[**P, A, E = Never, R = Never](
        self, f: Callable[P, Generator[Effect[Any, E, R], Any, A]], /
    ) -> Callable[P, Effect[A, E, R]]: ...
    @overload
    def __call__[**P, A, E = Never, R = Never](
        self, f: Callable[P, Effect[A, E, R]], /
    ) -> Callable[P, Effect[A, E, R]]: ...
    def __call__(
        self,
        f: Callable[..., Generator[Effect[Any, Any, Any], Any, Any] | Effect[Any, Any, Any]],
        /,
    ) -> Callable[..., Effect[Any, Any, Any]]:
        # Effect.fn's body may return an effect, so it is checked when it runs.
        return functools.wraps(f)(_traced(f, self.name, self.definition, self.options))


def _generator_function(f: Callable[..., Any], api: str) -> None:
    """``f``, checked to be a generator function when it is a ``def``: one
    with no ``yield`` would run its effects' constructors and none of them.
    (A lambda returning a generator is checked when it runs.)"""
    if inspect.isfunction(f) and f.__name__ != "<lambda>" and not inspect.isgeneratorfunction(f):
        raise TypeError(
            f"{api}: {f.__qualname__} is not a generator function; an effect inside it "
            "runs only with `yield from effect`"
        )


# --- combinators that remove types (use with .pipe) ---------------------------


@overload
def catch_no_such_element[A, R = Never](
    eff: Effect[A, NoSuchElementException, R],
) -> Effect[Option[A], Never, R]: ...
@overload
def catch_no_such_element[A, R = Never, ER = Never](
    eff: Effect[A, NoSuchElementException | ER, R],
) -> Effect[Option[A], ER, R]: ...
def catch_no_such_element(eff: Effect[Any, Any, Any]) -> Effect[Option[Any], Any, Any]:
    """Succeed with ``None`` on a ``NoSuchElementException`` and with
    ``Some(value)`` on success, removing the error from ``E``::

    eff.pipe(catch_no_such_element)
    """
    require_effect(eff, "eff")
    return eff.match_effect(
        on_failure=lambda e: _Succeed(None) if isinstance(e, NoSuchElementException) else fail(e),
        on_success=lambda a: _Succeed(Some(a)),
    )


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
    "catch_all",
    "catch_if",
    "catch_no_such_element",
    "catch_reason",
    "catch_reasons",
    "catch_tag",
    "context",
    "current_fiber",
    "die",
    "fail",
    "fail_cause",
    "fail_cause_sync",
    "fail_sync",
    "fiber_id",
    "fn",
    "from_async",
    "from_exit",
    "from_option",
    "from_optional",
    "from_result",
    "gen",
    "interrupt",
    "never",
    "provide_context",
    "provide_service",
    "provide_service_effect",
    "service_option",
    "succeed",
    "suspend",
    "sync",
    "transpose_option",
    "try_",
    "try_async",
    "try_blocking",
    "unwrap_reason",
    "update_service_scoped",
    "void",
    "yield_now",
]
