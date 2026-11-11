"""The primitives the fiber runtime interprets, and the helpers built on them.

Each primitive reduces itself in ``_step``; continuation frames consume
results in ``_on_success`` / ``_on_failure`` (see ``pyfect._core``).

Import these through ``pyfect._core``, which loads this module once
``Effect`` exists: importing this module first is a circular import.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import TYPE_CHECKING, Any, Never, Protocol, cast, final

from pyfect._cause_election import finalizer_cause
from pyfect._core import Effect, Frame, Step
from pyfect.cause import Cause
from pyfect.cause import die as die_cause
from pyfect.exit import Exit, Failure, Success

if TYPE_CHECKING:
    from pyfect._fiber import Fiber, Uninterruptible
    from pyfect.context import Context


# --- primitives ---------------------------------------------------------------


@final
class _Succeed[A](Effect[A, Never, Never]):
    __slots__ = ("value",)

    def __init__(self, value: A) -> None:
        self.value = value

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        return Success(self.value)


@final
class _FailCause[E](Effect[Never, E, Never]):
    __slots__ = ("cause",)

    def __init__(self, cause: Cause[E]) -> None:
        self.cause = cause

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        return Failure(self.cause)


@final
class _FromExit[A, E](Effect[A, E, Never]):
    __slots__ = ("outcome",)

    def __init__(self, ex: Exit[A, E]) -> None:
        self.outcome = ex

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        return self.outcome


def known_exit[A, E](eff: Effect[A, E, Any]) -> Exit[A, E] | None:
    """The outcome of an effect that is nothing but its outcome
    (``succeed``, ``fail_cause``, ``from_exit``), without running it; else
    ``None``. Lets a caller stay synchronous where Effect returns an
    ``Exit`` (which is an ``Effect`` there)."""
    if isinstance(eff, _Succeed):
        return Success(eff.value)
    if isinstance(eff, _FailCause):
        return Failure(eff.cause)
    if isinstance(eff, _FromExit):
        return eff.outcome
    return None


def run_known(eff: Effect[Any, Any, Any]) -> Step:
    """``eff``'s outcome if it is nothing but that (``known_exit``), else
    ``eff``. A step or continuation that has just claimed state returns
    this, so the claimed result reaches its continuation in the same step:
    returned as an effect, it would run in a later step, and a yield in
    between could let an interrupt drop it."""
    ex = known_exit(eff)
    return eff if ex is None else ex


@final
class _Sync[A](Effect[A, Never, Never]):
    """Run a side-effecting thunk. If it raises, that is a defect."""

    __slots__ = ("thunk",)

    def __init__(self, thunk: Callable[[], A]) -> None:
        self.thunk = thunk

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        return Success(self.thunk())


@final
class _Suspend[A, E, R](Effect[A, E, R]):
    """Build the effect lazily, each time it runs."""

    __slots__ = ("thunk",)

    def __init__(self, thunk: Callable[[], Effect[A, E, R]]) -> None:
        self.thunk = thunk

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        # A thunk that has already decided its result (a queue take, a permit
        # grab) hands it on in this same step: as a separate step it could be
        # parked at a yield, where an interrupt would drop it.
        return run_known(self.thunk())


@final
class _Map(Effect[Any, Any, Any]):
    __slots__ = ("f", "inner")

    def __init__(self, inner: Effect[Any, Any, Any], f: Callable[[Any], Any]) -> None:
        self.inner = inner
        self.f = f

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        fiber._push(self)
        return self.inner

    def _on_success(self, value: Any, fiber: Fiber[Any, Any]) -> Step:
        return Success(self.f(value))


@final
class _FlatMap(Effect[Any, Any, Any]):
    __slots__ = ("f", "inner")

    def __init__(
        self, inner: Effect[Any, Any, Any], f: Callable[[Any], Effect[Any, Any, Any]]
    ) -> None:
        self.inner = inner
        self.f = f

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        fiber._push(self)
        return self.inner

    def _on_success(self, value: Any, fiber: Fiber[Any, Any]) -> Step:
        return self.f(value)


@final
class _MatchCause(Effect[Any, Any, Any]):
    """The one recovery primitive. ``on_failure`` is skipped when the fiber
    has been interrupted and is interruptible: an interrupted fiber can
    clean up (finalizers run in uninterruptible regions) but not recover.
    """

    __slots__ = ("inner", "on_failure", "on_success")

    def __init__(
        self,
        inner: Effect[Any, Any, Any],
        on_failure: Callable[[Cause[Any]], Step] | None,
        on_success: Callable[[Any], Step] | None,
    ) -> None:
        self.inner = inner
        self.on_failure = on_failure
        self.on_success = on_success

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        fiber._push(self)
        return self.inner

    def _on_success(self, value: Any, fiber: Fiber[Any, Any]) -> Step:
        return Success(value) if self.on_success is None else self.on_success(value)

    def _on_failure(self, cause: Cause[Any], fiber: Fiber[Any, Any]) -> Step:
        if self.on_failure is None:
            return Failure(cause)
        if fiber._interrupted_and_interruptible():
            # Skipping a recovery handler: the fiber can no longer act on
            # typed errors, so only defects and the interruption remain.
            return Failure(cause.without_failures())
        return self.on_failure(cause)


type Register[A, E, R] = Callable[
    [Callable[[Effect[A, E, R]], None]], Effect[object, Never, R] | None
]


@final
class _Callback[A, E, R](Effect[A, E, R]):
    """Suspend the fiber until ``register``'s resume callback is called.

    ``register`` may return a canceler effect, run if the fiber is
    interrupted while waiting.
    """

    __slots__ = ("register",)

    def __init__(self, register: Register[A, E, R]) -> None:
        self.register = register

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        return fiber._suspend(self.register)


@final
class _WithFiber[A, E, R](Effect[A, E, R]):
    """Read the running fiber. Internal building block for concurrency."""

    __slots__ = ("f",)

    def __init__(self, f: Callable[[Fiber[Any, Any]], Effect[A, E, R]]) -> None:
        self.f = f

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        return self.f(fiber)


@final
class _SetInterruptible[A, E, R](Effect[A, E, R]):
    __slots__ = ("flag", "inner")

    def __init__(self, inner: Effect[A, E, R], flag: bool) -> None:
        self.inner = inner
        self.flag = flag

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        if fiber._interruptible != self.flag:
            fiber._push(_RestoreInterruptible(fiber._interruptible))
            fiber._interruptible = self.flag
        return self.inner


@final
class _RestoreInterruptible(Frame):
    __slots__ = ("flag",)

    def __init__(self, flag: bool) -> None:
        self.flag = flag

    def _on_success(self, value: Any, fiber: Fiber[Any, Any]) -> Step:
        fiber._interruptible = self.flag
        return Success(value)

    def _on_failure(self, cause: Cause[Any], fiber: Fiber[Any, Any]) -> Step:
        fiber._interruptible = self.flag
        return Failure(cause)


@final
class _Locally[A, E, R](Effect[A, E, R]):
    """Run ``inner`` with a modified context, restoring it afterwards."""

    __slots__ = ("f", "inner")

    def __init__(self, inner: Effect[A, E, Any], f: Callable[[Context], Context]) -> None:
        self.inner = inner
        self.f = f

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        fiber._push(_RestoreContext(fiber._context))
        fiber._set_context(self.f(fiber._context))
        return self.inner


@final
class _RestoreContext(Frame):
    __slots__ = ("context",)

    def __init__(self, context: Context) -> None:
        self.context = context

    def _on_success(self, value: Any, fiber: Fiber[Any, Any]) -> Step:
        fiber._set_context(self.context)
        return Success(value)

    def _on_failure(self, cause: Cause[Any], fiber: Fiber[Any, Any]) -> Step:
        fiber._set_context(self.context)
        return Failure(cause)


@final
class _Fork[A, E, R](Effect[Any, Never, R]):
    __slots__ = ("daemon", "inner", "start_immediately", "start_uninterruptible")

    def __init__(
        self,
        inner: Effect[A, E, R],
        *,
        daemon: bool,
        start_immediately: bool,
        uninterruptible: Uninterruptible,
    ) -> None:
        self.inner = inner
        self.daemon = daemon
        self.start_immediately = start_immediately
        self.start_uninterruptible: Uninterruptible = uninterruptible

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        child = fiber._fork(
            self.inner,
            daemon=self.daemon,
            start_immediately=self.start_immediately,
            uninterruptible=self.start_uninterruptible,
        )
        return fiber._after_started(Success(child))


@final
class _AfterStarted[A](Effect[A, Never, Never]):
    """Succeed with ``value`` once the fibers this run started immediately
    have run, up to their first wait or yield."""

    __slots__ = ("value",)

    def __init__(self, value: A) -> None:
        self.value = value

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        return fiber._after_started(Success(self.value))


@final
class _YieldNow(Effect[None, Never, Never]):
    __slots__ = ("priority",)

    def __init__(self, priority: int = 0) -> None:
        self.priority = priority

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        return fiber._yield_now(self.priority)


@final
class _Gen[A, E, R](Effect[A, E, R]):
    __slots__ = ("factory",)

    def __init__(self, factory: Callable[[], Generator[Effect[Any, E, R], Any, A]]) -> None:
        self.factory = factory

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        gen = cast(object, self.factory())  # a lambda may return anything
        if not isinstance(gen, Generator):
            return Failure(
                die_cause(TypeError(f"gen expected a generator, got {type(gen).__name__}"))
            )
        return _GenFrame(cast("Generator[Effect[Any, Any, Any], Any, Any]", gen))._on_success(
            None, fiber
        )


@final
class _GenFrame(Frame):
    """One running generator. It is resumed with each yielded effect's
    value. On failure it is closed, so ``finally`` and ``with`` blocks run.
    (They cannot yield effects; use ``ensuring`` for effectful cleanup.)
    """

    __slots__ = ("gen",)

    def __init__(self, gen: Generator[Effect[Any, Any, Any], Any, Any]) -> None:
        self.gen = gen

    def _on_success(self, value: Any, fiber: Fiber[Any, Any]) -> Step:
        try:
            nxt = self.gen.send(value)
        except StopIteration as stop:
            return Success(stop.value)
        fiber._push(self)
        return nxt

    def _on_failure(self, cause: Cause[Any], fiber: Fiber[Any, Any]) -> Step:
        try:
            self.gen.close()
        except KeyboardInterrupt:
            raise  # Ctrl-C: the loop interrupts the fiber (Fiber._raised)
        except BaseException as exc:
            # A ``finally`` that raises while the generator unwinds a failure
            # is a failing finalizer.
            return Failure(finalizer_cause(Failure(cause), die_cause(exc)))
        return Failure(cause)


# --- interruptibility regions -------------------------------------------------


class Restore(Protocol):
    """Runs an effect with the interruptibility from outside the mask."""

    def __call__[A, E, R](self, eff: Effect[A, E, R], /) -> Effect[A, E, R]: ...


def uninterruptible_mask[A, E, R](f: Callable[[Restore], Effect[A, E, R]]) -> Effect[A, E, R]:
    """Run ``f`` uninterruptibly. ``f`` receives ``restore``, which runs an
    inner effect with the interruptibility the caller had."""

    def body(fiber: Fiber[Any, Any]) -> Effect[A, E, R]:
        restore = _interruptible if fiber._interruptible else _uninterruptible
        return _SetInterruptible(_Suspend(lambda: f(restore)), False)

    return _WithFiber(body)


def interruptible_mask[A, E, R](f: Callable[[Restore], Effect[A, E, R]]) -> Effect[A, E, R]:
    """Run ``f`` interruptibly. ``f`` receives ``restore``, which runs an
    inner effect with the interruptibility the caller had. An interrupt that
    arrived while the caller was uninterruptible lands at once."""

    def body(fiber: Fiber[Any, Any]) -> Effect[A, E, R]:
        if fiber._interruptible:
            return f(_keep_interruptibility)
        # As in Effect, ``f`` runs even when an interrupt is already waiting.
        return _SetInterruptible(f(_uninterruptible), True)

    return _WithFiber(body)


class _KeepInterruptibility:
    def __call__[A, E, R](self, eff: Effect[A, E, R], /) -> Effect[A, E, R]:
        return eff


class _Uninterruptible:
    def __call__[A, E, R](self, eff: Effect[A, E, R], /) -> Effect[A, E, R]:
        return _SetInterruptible(eff, False)


class _Interruptible:
    def __call__[A, E, R](self, eff: Effect[A, E, R], /) -> Effect[A, E, R]:
        return _SetInterruptible(eff, True)


_keep_interruptibility = _KeepInterruptibility()
_interruptible = _Interruptible()
_uninterruptible = _Uninterruptible()
