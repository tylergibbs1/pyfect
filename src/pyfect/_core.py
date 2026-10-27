"""``Effect[A, E, R]`` and the primitives the fiber runtime interprets.

An effect is an immutable description. Running it is the fiber's job
(``pyfect._fiber``). The runtime loop knows nothing about specific
primitives: each primitive reduces itself in ``_step``, and continuation
frames (often the primitive itself, pushed onto the fiber's stack) consume
the result in ``_on_success`` / ``_on_failure``.

A step is one of:

- another ``Effect``: evaluate it next
- a ``Success`` / ``Failure``: hand it to the next frame on the stack
- ``SUSPEND``: the fiber parked itself; a callback will resume it

Every combinator here is built from about a dozen primitives. Anything
richer (racing, ``for_each``, timeouts) lives in other modules and is built
from these.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import TYPE_CHECKING, Any, Final, Generic, Never, Protocol, Self, TypeVar, final

from pyfect.cause import Cause, Die, Fail, _as_exception, merge
from pyfect.cause import die as die_cause
from pyfect.duration import Duration
from pyfect.exit import Exit, Failure, Success
from pyfect.result import Err, Ok

if TYPE_CHECKING:
    from pyfect._fiber import Fiber
    from pyfect.context import Context
    from pyfect.errors import TimeoutException
    from pyfect.schedule import Schedule
    from pyfect.scope import Scope

A_co = TypeVar("A_co", covariant=True)
E_co = TypeVar("E_co", covariant=True, default=Never)
R_co = TypeVar("R_co", covariant=True, default=Never)


@final
class _SuspendMarker:
    __slots__ = ()

    def __repr__(self) -> str:
        return "SUSPEND"


SUSPEND: Final = _SuspendMarker()

type Step = Effect[Any, Any, Any] | Success[Any] | Failure[Any] | _SuspendMarker


class Frame:
    """A continuation on the fiber's stack. Defaults pass results through."""

    __slots__ = ()

    def _on_success(self, value: Any, fiber: Fiber[Any, Any]) -> Step:
        return Success(value)

    def _on_failure(self, cause: Cause[Any], fiber: Fiber[Any, Any]) -> Step:
        return Failure(cause)


class Effect(Frame, Generic[A_co, E_co, R_co]):
    """A lazy description of a computation.

    - ``A``: the value it succeeds with
    - ``E``: the typed errors it can fail with (``Never`` if none)
    - ``R``: the services it needs (``Never`` if none)

    Build effects with the functions in ``pyfect`` (``succeed``, ``gen``,
    ...). Inside a generator, ``x = yield from eff`` runs ``eff`` and gives
    back its value; its errors and requirements join the generator's own.
    """

    __slots__ = ()

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        raise NotImplementedError(f"{type(self).__name__} is not a primitive")

    def __iter__(self) -> Generator[Effect[Any, E_co, R_co], Any, A_co]:
        return (yield self)

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        """Apply ``f`` to this effect. One step per call, on purpose:
        pyright only narrows types correctly for a single step, so chain
        ``.pipe(a).pipe(b)`` rather than passing several functions."""
        return f(self)

    # --- sequencing -------------------------------------------------------

    def map[B](self, f: Callable[[A_co], B]) -> Effect[B, E_co, R_co]:
        return _Map(self, f)

    def flat_map[B, E2 = Never, R2 = Never](
        self, f: Callable[[A_co], Effect[B, E2, R2]]
    ) -> Effect[B, E_co | E2, R_co | R2]:
        return _FlatMap(self, f)

    def and_then[B, E2 = Never, R2 = Never](
        self, that: Effect[B, E2, R2]
    ) -> Effect[B, E_co | E2, R_co | R2]:
        """Run ``that`` after this effect, keeping only its value."""
        return _FlatMap(self, lambda _: that)

    def tap[E2 = Never, R2 = Never](
        self, f: Callable[[A_co], Effect[object, E2, R2]]
    ) -> Effect[A_co, E_co | E2, R_co | R2]:
        """Run ``f(value)`` for its effects, keeping the original value."""
        return _FlatMap(self, lambda a: _Map(f(a), lambda _: a))

    def as_[B](self, value: B) -> Effect[B, E_co, R_co]:
        return _Map(self, lambda _: value)

    def as_void(self) -> Effect[None, E_co, R_co]:
        return _Map(self, _to_none)

    def zip[B, E2 = Never, R2 = Never](
        self, that: Effect[B, E2, R2]
    ) -> Effect[tuple[A_co, B], E_co | E2, R_co | R2]:
        """Run both in order and pair the results. For concurrency use
        ``pyfect.all(a, b, concurrency="unbounded")``."""
        return _FlatMap(self, lambda a: _Map(that, lambda b: (a, b)))

    def forever(self) -> Effect[Never, E_co, R_co]:
        loop: Effect[Never, E_co, R_co] = _Suspend(lambda: _FlatMap(self, lambda _: loop))
        return loop

    # --- errors -----------------------------------------------------------

    def map_error[E2](self, f: Callable[[E_co], E2]) -> Effect[A_co, E2, R_co]:
        def on_failure(cause: Cause[E_co]) -> Effect[Never, E2, Never]:
            return _FailCause(cause.map(f))

        return _MatchCause(self, on_failure, None)

    def catch_all[B, E2 = Never, R2 = Never](
        self, f: Callable[[E_co], Effect[B, E2, R2]]
    ) -> Effect[A_co | B, E2, R_co | R2]:
        """Recover from every typed error. Defects and interruptions pass
        through. To handle one error class, use ``pipe(catch_tag(...))``."""

        def on_failure(cause: Cause[E_co]) -> Effect[Any, Any, Any]:
            found = cause.find_recoverable_error()
            return f(found.error) if isinstance(found, Fail) else _FailCause(found)

        return _MatchCause(self, on_failure, None)

    def catch_cause[B, E2 = Never, R2 = Never](
        self, f: Callable[[Cause[E_co]], Effect[B, E2, R2]]
    ) -> Effect[A_co | B, E2, R_co | R2]:
        """Recover from any failure, including defects. Interruption still
        wins: an interrupted fiber skips this handler."""
        return _MatchCause(self, f, None)

    def catch_defect[B, E2 = Never, R2 = Never](
        self, f: Callable[[BaseException], Effect[B, E2, R2]]
    ) -> Effect[A_co | B, E_co | E2, R_co | R2]:
        def on_failure(cause: Cause[E_co]) -> Effect[Any, Any, Any]:
            for r in cause.reasons:
                if isinstance(r, Die):
                    return f(r.defect)
            return _FailCause(cause)

        return _MatchCause(self, on_failure, None)

    def or_die(self) -> Effect[A_co, Never, R_co]:
        """Die with the first typed error instead of failing with it."""
        return self.catch_all(lambda e: _FailCause(die_cause(_as_exception(e))))

    def tap_error[E2 = Never, R2 = Never](
        self, f: Callable[[E_co], Effect[object, E2, R2]]
    ) -> Effect[A_co, E_co | E2, R_co | R2]:
        def on_failure(cause: Cause[E_co]) -> Effect[Any, Any, Any]:
            found = cause.find_fail()
            if not isinstance(found, Fail):
                return _FailCause(cause)
            return _FlatMap(f(found.error), lambda _: _FailCause(cause))

        return _MatchCause(self, on_failure, None)

    def tap_cause[E2 = Never, R2 = Never](
        self, f: Callable[[Cause[E_co]], Effect[object, E2, R2]]
    ) -> Effect[A_co, E_co | E2, R_co | R2]:
        return _MatchCause(self, lambda c: _FlatMap(f(c), lambda _: _FailCause(c)), None)

    def ignore(self) -> Effect[None, Never, R_co]:
        """Discard the value and any typed error."""
        return _MatchCause(self, _ignore_failure, _succeed_none)

    # --- folding ----------------------------------------------------------

    def match[B, C](
        self, *, on_failure: Callable[[E_co], B], on_success: Callable[[A_co], C]
    ) -> Effect[B | C, Never, R_co]:
        def handle(cause: Cause[E_co]) -> Effect[Any, Any, Any]:
            found = cause.find_recoverable_error()
            return (
                _Succeed(on_failure(found.error)) if isinstance(found, Fail) else _FailCause(found)
            )

        return _MatchCause(self, handle, lambda a: _Succeed(on_success(a)))

    def match_effect[B, C, EE = Never, RR = Never](
        self,
        *,
        on_failure: Callable[[E_co], Effect[B, EE, RR]],
        on_success: Callable[[A_co], Effect[C, EE, RR]],
    ) -> Effect[B | C, EE, R_co | RR]:
        def handle(cause: Cause[E_co]) -> Effect[Any, Any, Any]:
            found = cause.find_recoverable_error()
            return on_failure(found.error) if isinstance(found, Fail) else _FailCause(found)

        return _MatchCause(self, handle, on_success)

    def match_cause_effect[B, C, EE = Never, RR = Never](
        self,
        *,
        on_failure: Callable[[Cause[E_co]], Effect[B, EE, RR]],
        on_success: Callable[[A_co], Effect[C, EE, RR]],
    ) -> Effect[B | C, EE, R_co | RR]:
        return _MatchCause(self, on_failure, on_success)

    def exit(self) -> Effect[Exit[A_co, E_co], Never, R_co]:
        """Succeed with the outcome as a value. Interruption still
        propagates; it is not something a fiber can catch."""
        return _MatchCause(self, lambda c: _Succeed(Failure(c)), lambda a: _Succeed(Success(a)))

    def result(self) -> Effect[Ok[A_co] | Err[E_co], Never, R_co]:
        """Succeed with ``Ok(value)`` or ``Err(error)``. Defects and
        interruptions still propagate."""

        def handle(cause: Cause[E_co]) -> Effect[Any, Any, Any]:
            found = cause.find_recoverable_error()
            return _Succeed(Err(found.error)) if isinstance(found, Fail) else _FailCause(found)

        return _MatchCause(self, handle, lambda a: _Succeed(Ok(a)))

    # --- resource safety --------------------------------------------------

    def on_exit[R2 = Never](
        self, f: Callable[[Exit[A_co, E_co]], Effect[object, Never, R2]]
    ) -> Effect[A_co, E_co, R_co | R2]:
        """Run ``f`` after this effect however it ends. ``f`` runs
        uninterruptibly; if it fails, its cause is added to the result."""
        return uninterruptible_mask(
            lambda restore: _MatchCause(
                restore(self),
                lambda c: _run_finalizer(_call_user(f, Failure(c)), Failure(c)),
                lambda a: _run_finalizer(_call_user(f, Success(a)), Success(a)),
            )
        )

    def ensuring[R2 = Never](
        self, finalizer: Effect[object, Never, R2]
    ) -> Effect[A_co, E_co, R_co | R2]:
        return self.on_exit(lambda _: finalizer)

    def on_error[R2 = Never](
        self, f: Callable[[Cause[E_co]], Effect[object, Never, R2]]
    ) -> Effect[A_co, E_co, R_co | R2]:
        def handle(ex: Exit[A_co, E_co]) -> Effect[object, Never, R2]:
            return f(ex.cause) if isinstance(ex, Failure) else _Succeed(None)

        return self.on_exit(handle)

    def on_interrupt[R2 = Never](
        self, finalizer: Effect[object, Never, R2]
    ) -> Effect[A_co, E_co, R_co | R2]:
        def handle(ex: Exit[A_co, E_co]) -> Effect[object, Never, R2]:
            if isinstance(ex, Failure) and ex.cause.has_interrupts:
                return finalizer
            return _Succeed(None)

        return self.on_exit(handle)

    def uninterruptible(self) -> Effect[A_co, E_co, R_co]:
        return _SetInterruptible(self, False)

    def interruptible(self) -> Effect[A_co, E_co, R_co]:
        return _SetInterruptible(self, True)

    # --- concurrency ------------------------------------------------------

    def fork(self) -> Effect[Fiber[A_co, E_co], Never, R_co]:
        """Start this effect on a child fiber. The child is interrupted if
        it is still running when the parent fiber finishes."""
        return _Fork(self, daemon=False)

    def fork_daemon(self) -> Effect[Fiber[A_co, E_co], Never, R_co]:
        """Start this effect on a fiber that outlives its parent."""
        return _Fork(self, daemon=True)

    def fork_scoped(self) -> Effect[Fiber[A_co, E_co], Never, R_co | Scope]:
        """Start this effect on a fiber that is interrupted when the
        enclosing ``Scope`` closes."""
        from pyfect.scope import fork_scoped

        return fork_scoped(self)

    def race[B, E2 = Never, R2 = Never](
        self, that: Effect[B, E2, R2]
    ) -> Effect[A_co | B, E_co | E2, R_co | R2]:
        """The first to succeed wins and the other is interrupted. Fails
        only if both fail."""
        from pyfect._concurrency import race

        return race(self, that)

    def race_first[B, E2 = Never, R2 = Never](
        self, that: Effect[B, E2, R2]
    ) -> Effect[A_co | B, E_co | E2, R_co | R2]:
        """The first to finish wins, success or failure."""
        from pyfect._concurrency import race_first

        return race_first(self, that)

    def timeout(self, duration: Duration) -> Effect[A_co, E_co | TimeoutException, R_co]:
        """Fail with ``TimeoutException`` if this takes longer than
        ``duration``. The effect is interrupted when time runs out."""
        from pyfect._concurrency import timeout

        return timeout(self, duration)

    def delay(self, duration: Duration) -> Effect[A_co, E_co, R_co]:
        from pyfect.clock import sleep

        return sleep(duration).and_then(self)

    def timed(self) -> Effect[tuple[float, A_co], E_co, R_co]:
        """Pair the value with how long it took, in seconds."""
        from pyfect.clock import timed

        return timed(self)

    def retry(self, schedule: Schedule[E_co, object]) -> Effect[A_co, E_co, R_co]:
        """Retry on typed failure, as long as ``schedule`` allows."""
        from pyfect.schedule import retry

        return retry(self, schedule)

    def repeat[B](self, schedule: Schedule[A_co, B]) -> Effect[B, E_co, R_co]:
        """Repeat after each success, as long as ``schedule`` allows.
        Succeeds with the schedule's last output."""
        from pyfect.schedule import repeat

        return repeat(self, schedule)


# --- helpers ----------------------------------------------------------------


def _to_none(_: object) -> None:
    return None


def _ignore_failure(cause: Cause[Any]) -> Effect[Any, Any, Any]:
    found = cause.find_recoverable_error()
    return _Succeed(None) if isinstance(found, Fail) else _FailCause(found)


def _succeed_none(_: object) -> Effect[None]:
    return _Succeed(None)


def _call_user[*Ts, A, E, R](f: Callable[[*Ts], Effect[A, E, R]], *args: *Ts) -> Effect[A, E, R]:
    """Call user code when the effect runs, not when it is built. A raise
    then becomes a defect at that point of the program, inside whatever
    finalizer or region surrounds it. Resource and finalizer combinators
    call every user callback through this."""
    return _Suspend(lambda: f(*args))


def _run_finalizer(finalizer: Effect[object, Never, Any], ex: Exit[Any, Any]) -> Step:
    """Run ``finalizer``, then end with ``ex``. A failing finalizer adds
    its cause to the result."""

    def after_failure(fin_cause: Cause[Any]) -> Effect[Any, Any, Any]:
        base = ex.cause if isinstance(ex, Failure) else Cause(())
        return _FailCause(merge(base, fin_cause))

    return _MatchCause(finalizer, after_failure, lambda _: _FromExit(ex))


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
        nxt = self.thunk()
        if isinstance(nxt, _Succeed | _FailCause | _FromExit):
            return nxt._step(fiber)
        return nxt


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
        fiber._context = self.f(fiber._context)
        return self.inner


@final
class _RestoreContext(Frame):
    __slots__ = ("context",)

    def __init__(self, context: Context) -> None:
        self.context = context

    def _on_success(self, value: Any, fiber: Fiber[Any, Any]) -> Step:
        fiber._context = self.context
        return Success(value)

    def _on_failure(self, cause: Cause[Any], fiber: Fiber[Any, Any]) -> Step:
        fiber._context = self.context
        return Failure(cause)


@final
class _Fork[A, E, R](Effect[Any, Never, R]):
    __slots__ = ("daemon", "inner")

    def __init__(self, inner: Effect[A, E, R], *, daemon: bool) -> None:
        self.inner = inner
        self.daemon = daemon

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        return Success(fiber._fork(self.inner, daemon=self.daemon))


@final
class _YieldNow(Effect[None, Never, Never]):
    __slots__ = ()

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        return fiber._yield_now()


@final
class _Gen[A, E, R](Effect[A, E, R]):
    __slots__ = ("factory",)

    def __init__(self, factory: Callable[[], Generator[Effect[Any, E, R], Any, A]]) -> None:
        self.factory = factory

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        return _GenFrame(self.factory())._on_success(None, fiber)


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
        except Exception as exc:
            return Failure(merge(cause, die_cause(exc)))
        return Failure(cause)


# --- interruptibility regions -------------------------------------------------


class Restore(Protocol):
    """Runs an effect with the interruptibility from outside the mask."""

    def __call__[A, E, R](self, eff: Effect[A, E, R], /) -> Effect[A, E, R]: ...


def uninterruptible_mask[A, E, R](f: Callable[[Restore], Effect[A, E, R]]) -> Effect[A, E, R]:
    """Run ``f`` uninterruptibly. ``f`` receives ``restore``, which runs an
    inner effect with the interruptibility the caller had."""

    def body(fiber: Fiber[Any, Any]) -> Effect[A, E, R]:
        previous = fiber._interruptible

        class _Restore:
            def __call__[A2, E2, R2](self, eff: Effect[A2, E2, R2], /) -> Effect[A2, E2, R2]:
                return _SetInterruptible(eff, previous)

        restore = _Restore()

        return _SetInterruptible(_Suspend(lambda: f(restore)), False)

    return _WithFiber(body)
