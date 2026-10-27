"""``Effect[A, E, R]``: the step protocol and the method combinators.

An effect is an immutable description. Running it is the fiber's job
(``pyfect._fiber``). The runtime loop knows nothing about specific
primitives: each primitive reduces itself in ``_step``, and continuation
frames (often the primitive itself, pushed onto the fiber's stack) consume
the result in ``_on_success`` / ``_on_failure``.

A step is one of:

- another ``Effect``: evaluate it next
- a ``Success`` / ``Failure``: hand it to the next frame on the stack
- ``SUSPEND``: the fiber parked itself; a callback will resume it

Every combinator here is built from about a dozen primitives, defined in
``pyfect._primitives`` and re-exported from this module. Anything
richer (racing, ``for_each``, timeouts) lives in other modules and is built
from these.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import (
    TYPE_CHECKING,
    Any,
    Final,
    Generic,
    Literal,
    Never,
    Self,
    TypeIs,
    TypeVar,
    final,
    overload,
)

from pyfect.cause import Cause, Fail, _as_exception, merge
from pyfect.cause import die as die_cause
from pyfect.cause import fail as fail_cause
from pyfect.duration import Duration
from pyfect.exit import Exit, Failure, Success
from pyfect.result import Err, Ok

if TYPE_CHECKING:
    from pyfect._concurrency import Concurrency
    from pyfect._fiber import Fiber
    from pyfect.errors import NoSuchElementException, TimeoutException
    from pyfect.option import Option
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
        self, that: Effect[B, E2, R2], *, concurrent: bool = False
    ) -> Effect[tuple[A_co, B], E_co | E2, R_co | R2]:
        """Pair the results: in order, or both at once with ``concurrent``."""
        return self.zip_with(that, _pair, concurrent=concurrent)

    def zip_with[B, C, E2 = Never, R2 = Never](
        self, that: Effect[B, E2, R2], f: Callable[[A_co, B], C], *, concurrent: bool = False
    ) -> Effect[C, E_co | E2, R_co | R2]:
        """Combine the results with ``f``. With ``concurrent``, both run at
        once and the first failure interrupts the other."""
        if not concurrent:
            return _FlatMap(self, lambda a: _Map(that, lambda b: f(a, b)))
        from pyfect._all import all

        return all(self, that, concurrency=2).map(lambda ab: f(*ab))

    @overload
    def replicate_effect(
        self, n: int, *, concurrency: Concurrency = None, discard: Literal[False] = False
    ) -> Effect[list[A_co], E_co, R_co]: ...
    @overload
    def replicate_effect(
        self, n: int, *, concurrency: Concurrency = None, discard: Literal[True]
    ) -> Effect[None, E_co, R_co]: ...
    def replicate_effect(
        self, n: int, *, concurrency: Concurrency = None, discard: bool = False
    ) -> Effect[Any, E_co, R_co]:
        """Run this effect ``n`` times, like ``for_each``, collecting the
        values (or none, with ``discard``)."""
        from pyfect._concurrency import for_each

        repeated = for_each([self] * n, _identity, concurrency=concurrency)
        return repeated.as_void() if discard else repeated

    def forever(self) -> Effect[Never, E_co, R_co]:
        loop: Effect[Never, E_co, R_co] = _Suspend(lambda: _FlatMap(self, lambda _: loop))
        return loop

    def flatten[B, E2, R2](
        self: Effect[Effect[B, E2, R2], E_co, R_co],
    ) -> Effect[B, E_co | E2, R_co | R2]:
        """Run the effect this effect succeeds with."""
        return _FlatMap(self, _identity)

    def when[E2 = Never, R2 = Never](
        self, condition: Effect[bool, E2, R2]
    ) -> Effect[Option[A_co], E_co | E2, R_co | R2]:
        """Run this effect only if ``condition`` succeeds with ``True``:
        ``Some(value)`` if it ran, ``None`` if it did not."""
        from pyfect.option import Some

        return _FlatMap(condition, lambda run: _Map(self, Some) if run else _Succeed(None))

    @overload
    def filter_or_fail[B](
        self, predicate: Callable[[A_co], TypeIs[B]]
    ) -> Effect[B, E_co | NoSuchElementException, R_co]: ...
    @overload
    def filter_or_fail(
        self, predicate: Callable[[A_co], bool]
    ) -> Effect[A_co, E_co | NoSuchElementException, R_co]: ...
    @overload
    def filter_or_fail[B, E2](
        self, predicate: Callable[[A_co], TypeIs[B]], or_fail_with: Callable[[A_co], E2]
    ) -> Effect[B, E_co | E2, R_co]: ...
    @overload
    def filter_or_fail[E2](
        self, predicate: Callable[[A_co], bool], or_fail_with: Callable[[A_co], E2]
    ) -> Effect[A_co, E_co | E2, R_co]: ...
    def filter_or_fail(
        self, predicate: Callable[[Any], bool], or_fail_with: Callable[[Any], Any] | None = None
    ) -> Effect[Any, Any, Any]:
        """Fail with ``or_fail_with(value)`` (by default a
        ``NoSuchElementException``) when the value fails ``predicate``."""
        if or_fail_with is None:
            from pyfect.errors import NoSuchElementException

            return self.filter_or_else(predicate, lambda _: _fail(NoSuchElementException()))
        return self.filter_or_else(predicate, lambda a: _fail(or_fail_with(a)))

    @overload
    def filter_or_else[B, C, E2 = Never, R2 = Never](
        self, predicate: Callable[[A_co], TypeIs[B]], or_else: Callable[[A_co], Effect[C, E2, R2]]
    ) -> Effect[B | C, E_co | E2, R_co | R2]: ...
    @overload
    def filter_or_else[C, E2 = Never, R2 = Never](
        self, predicate: Callable[[A_co], bool], or_else: Callable[[A_co], Effect[C, E2, R2]]
    ) -> Effect[A_co | C, E_co | E2, R_co | R2]: ...
    def filter_or_else(
        self, predicate: Callable[[Any], bool], or_else: Callable[[Any], Effect[Any, Any, Any]]
    ) -> Effect[Any, Any, Any]:
        """Continue with ``or_else(value)`` when the value fails ``predicate``."""
        return _FlatMap(self, lambda a: _Succeed(a) if predicate(a) else or_else(a))

    # --- errors -----------------------------------------------------------

    def map_error[E2](self, f: Callable[[E_co], E2]) -> Effect[A_co, E2, R_co]:
        def on_failure(cause: Cause[E_co]) -> Effect[Never, E2, Never]:
            return _FailCause(cause.map(f))

        return _MatchCause(self, on_failure, None)

    def map_both[B, E2](
        self, *, on_failure: Callable[[E_co], E2], on_success: Callable[[A_co], B]
    ) -> Effect[B, E2, R_co]:
        """``map_error`` and ``map`` at once."""
        return _MatchCause(
            self, lambda c: _FailCause(c.map(on_failure)), lambda a: Success(on_success(a))
        )

    def catch_all[B, E2 = Never, R2 = Never](
        self, f: Callable[[E_co], Effect[B, E2, R2]]
    ) -> Effect[A_co | B, E2, R_co | R2]:
        """Recover from every typed error. Defects and interruptions pass
        through. To handle one error class, use ``pipe(catch_tag(...))``."""
        return _MatchCause(self, _recovering(f), None)

    @overload
    def catch_if[B, E2 = Never, R2 = Never](
        self, predicate: Callable[[E_co], bool], f: Callable[[E_co], Effect[B, E2, R2]]
    ) -> Effect[A_co | B, E_co | E2, R_co | R2]: ...
    @overload
    def catch_if[B, C, EE = Never, RR = Never](
        self,
        predicate: Callable[[E_co], bool],
        f: Callable[[E_co], Effect[B, EE, RR]],
        *,
        or_else: Callable[[E_co], Effect[C, EE, RR]],
    ) -> Effect[A_co | B | C, EE, R_co | RR]: ...
    def catch_if(
        self,
        predicate: Callable[[Any], bool],
        f: Callable[[Any], Effect[Any, Any, Any]],
        *,
        or_else: Callable[[Any], Effect[Any, Any, Any]] | None = None,
    ) -> Effect[Any, Any, Any]:
        """Recover from the typed errors that pass ``predicate``; ``or_else``,
        if given, handles the rest. To remove the caught errors from ``E``,
        use ``pipe(catch_if(refinement, ...))`` with a ``TypeIs`` refinement."""
        return _MatchCause(self, _catching_if(predicate, f, or_else), None)

    def catch_cause[B, E2 = Never, R2 = Never](
        self, f: Callable[[Cause[E_co]], Effect[B, E2, R2]]
    ) -> Effect[A_co | B, E2, R_co | R2]:
        """Recover from any failure, including defects. Interruption still
        wins: an interrupted fiber skips this handler."""
        return _MatchCause(self, f, None)

    def catch_cause_if[B, E2 = Never, R2 = Never](
        self,
        predicate: Callable[[Cause[E_co]], bool],
        f: Callable[[Cause[E_co]], Effect[B, E2, R2]],
    ) -> Effect[A_co | B, E_co | E2, R_co | R2]:
        """``catch_cause`` for the causes that pass ``predicate``."""
        return _MatchCause(self, lambda c: f(c) if predicate(c) else _FailCause(c), None)

    def catch_defect[B, E2 = Never, R2 = Never](
        self, f: Callable[[BaseException], Effect[B, E2, R2]]
    ) -> Effect[A_co | B, E_co | E2, R_co | R2]:
        """Recover from the first defect. Typed errors pass through."""

        def on_failure(cause: Cause[E_co]) -> Effect[Any, Any, Any]:
            defect = cause.find_defect()
            return _FailCause(cause) if defect is None else f(defect)

        return _MatchCause(self, on_failure, None)

    def or_else_succeed[B](self, f: Callable[[E_co], B]) -> Effect[A_co | B, Never, R_co]:
        """Succeed with ``f(error)`` instead of failing."""
        return self.catch_all(lambda e: _Sync(lambda: f(e)))

    def eventually(self) -> Effect[A_co, Never, R_co]:
        """Run again after each typed failure, yielding in between, until it
        succeeds."""
        loop: Effect[A_co, Never, R_co] = self.catch_all(
            lambda _: _FlatMap(_YieldNow(), lambda _: loop)
        )
        return loop

    def flip(self) -> Effect[E_co, A_co, R_co]:
        """Swap the error and the value: fail with the value, succeed with
        the error. Defects and interruptions stay failures."""
        return _MatchCause(self, _recovering(_Succeed), _fail)

    def sandbox(self) -> Effect[A_co, Cause[E_co], R_co]:
        """Fail with the whole ``Cause``, defects and interruptions included,
        as the typed error."""
        return _MatchCause(self, _fail, None)

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

    def tap_cause_if[E2 = Never, R2 = Never](
        self,
        predicate: Callable[[Cause[E_co]], bool],
        f: Callable[[Cause[E_co]], Effect[object, E2, R2]],
    ) -> Effect[A_co, E_co | E2, R_co | R2]:
        """``tap_cause`` for the causes that pass ``predicate``."""

        def on_failure(cause: Cause[E_co]) -> Effect[Any, Any, Any]:
            if not predicate(cause):
                return _FailCause(cause)
            return _FlatMap(f(cause), lambda _: _FailCause(cause))

        return _MatchCause(self, on_failure, None)

    def tap_defect[E2 = Never, R2 = Never](
        self, f: Callable[[BaseException], Effect[object, E2, R2]]
    ) -> Effect[A_co, E_co | E2, R_co | R2]:
        """Run ``f(defect)`` for the first defect, then keep failing."""

        def on_failure(cause: Cause[E_co]) -> Effect[Any, Any, Any]:
            defect = cause.find_defect()
            if defect is None:
                return _FailCause(cause)
            return _FlatMap(f(defect), lambda _: _FailCause(cause))

        return _MatchCause(self, on_failure, None)

    @overload
    def tap_error_tag[T1, E2 = Never, R2 = Never](
        self, tag: type[T1], f: Callable[[T1], Effect[object, E2, R2]]
    ) -> Effect[A_co, E_co | E2, R_co | R2]: ...
    @overload
    def tap_error_tag[T1, T2, E2 = Never, R2 = Never](
        self, tag: tuple[type[T1], type[T2]], f: Callable[[T1 | T2], Effect[object, E2, R2]]
    ) -> Effect[A_co, E_co | E2, R_co | R2]: ...
    @overload
    def tap_error_tag[T1, T2, T3, E2 = Never, R2 = Never](
        self,
        tag: tuple[type[T1], type[T2], type[T3]],
        f: Callable[[T1 | T2 | T3], Effect[object, E2, R2]],
    ) -> Effect[A_co, E_co | E2, R_co | R2]: ...
    def tap_error_tag(
        self,
        tag: type[Any] | tuple[type[Any], ...],
        f: Callable[[Any], Effect[object, Any, Any]],
    ) -> Effect[Any, Any, Any]:
        """``tap_error`` for the errors that are instances of ``tag`` (a
        class or a tuple of classes)."""
        return self.tap_error(lambda e: f(e) if isinstance(e, tag) else _Succeed(None))

    def ignore(self) -> Effect[None, Never, R_co]:
        """Discard the value and any typed error."""
        return _MatchCause(self, _ignore_failure, _succeed_none)

    # --- folding ----------------------------------------------------------

    def match[B, C](
        self, *, on_failure: Callable[[E_co], B], on_success: Callable[[A_co], C]
    ) -> Effect[B | C, Never, R_co]:
        return _MatchCause(
            self,
            _recovering(lambda e: _Succeed(on_failure(e))),
            lambda a: _Succeed(on_success(a)),
        )

    def match_cause[B, C](
        self, *, on_failure: Callable[[Cause[E_co]], B], on_success: Callable[[A_co], C]
    ) -> Effect[B | C, Never, R_co]:
        """``match`` over the whole ``Cause``: defects reach ``on_failure``
        too. Interruption still propagates."""
        return _MatchCause(
            self, lambda c: _Succeed(on_failure(c)), lambda a: _Succeed(on_success(a))
        )

    def option(self) -> Effect[Option[A_co], Never, R_co]:
        """Succeed with ``Some(value)``, or ``None`` on a typed error.
        Defects and interruptions still propagate."""
        from pyfect.option import Some

        return _MatchCause(self, _recovering(_succeed_none), lambda a: _Succeed(Some(a)))

    def match_effect[B, C, EE = Never, RR = Never](
        self,
        *,
        on_failure: Callable[[E_co], Effect[B, EE, RR]],
        on_success: Callable[[A_co], Effect[C, EE, RR]],
    ) -> Effect[B | C, EE, R_co | RR]:
        return _MatchCause(self, _recovering(on_failure), on_success)

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
        return _MatchCause(self, _recovering(lambda e: _Succeed(Err(e))), lambda a: _Succeed(Ok(a)))

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

    def timeout_option(self, duration: Duration) -> Effect[Option[A_co], E_co, R_co]:
        """``Some(value)``, or ``None`` if this takes longer than
        ``duration``. The effect is interrupted when time runs out."""
        from pyfect._concurrency import timeout_option

        return timeout_option(self, duration)

    def timeout_or_else[B, E2 = Never, R2 = Never](
        self, duration: Duration, or_else: Callable[[], Effect[B, E2, R2]]
    ) -> Effect[A_co | B, E_co | E2, R_co | R2]:
        """Continue with ``or_else()`` if this takes longer than
        ``duration``. ``or_else`` runs once this effect has been
        interrupted and has finished cleaning up."""
        from pyfect._concurrency import timeout_or_else

        return timeout_or_else(self, duration, or_else)

    def delay(self, duration: Duration) -> Effect[A_co, E_co, R_co]:
        from pyfect.clock import sleep

        return sleep(duration).and_then(self)

    def timed(self) -> Effect[tuple[float, A_co], E_co, R_co]:
        """Pair the value with how long it took, in seconds."""
        from pyfect.clock import timed

        return timed(self)

    # --- caching --------------------------------------------------------

    def cached(self) -> Effect[Effect[A_co, E_co, R_co]]:
        """An effect that runs this one on first use and then replays its
        exit. Concurrent callers share one run; an interrupted run is not
        cached (see ``cached_invalidate_with_ttl``)."""
        from pyfect._cached import cached

        return cached(self)

    def cached_with_ttl(
        self, time_to_live: Duration | Callable[[Exit[A_co, E_co]], Duration]
    ) -> Effect[Effect[A_co, E_co, R_co]]:
        """``cached``, but each exit is replayed only for ``time_to_live``
        (or ``time_to_live(exit)``) after it was produced."""
        from pyfect._cached import cached_invalidate_with_ttl

        return cached_invalidate_with_ttl(self, time_to_live).map(lambda pair: pair[0])

    def cached_invalidate_with_ttl(
        self, time_to_live: Duration | Callable[[Exit[A_co, E_co]], Duration]
    ) -> Effect[tuple[Effect[A_co, E_co, R_co], Effect[None]]]:
        """``cached_with_ttl`` plus an effect that drops the cached exit.

        Callers already waiting on a run keep waiting on it; later callers
        start a fresh run. A run is interrupted once every caller waiting on
        it has gone, and an interrupted run is never cached."""
        from pyfect._cached import cached_invalidate_with_ttl

        return cached_invalidate_with_ttl(self, time_to_live)

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


def _identity[T](value: T) -> T:
    return value


def _pair[A, B](a: A, b: B) -> tuple[A, B]:
    return (a, b)


def _fail[E](error: E) -> Effect[Never, E]:
    return _FailCause(fail_cause(error))


def _succeed_none(_: object) -> Effect[None]:
    return _Succeed(None)


def _recovering(
    f: Callable[[Any], Effect[Any, Any, Any]],
) -> Callable[[Cause[Any]], Effect[Any, Any, Any]]:
    """A failure handler that passes the recoverable typed error to ``f``.
    Every typed recovery goes through this, so a defect always wins: the
    cause is then re-failed with its typed errors elected to defects."""

    def handle(cause: Cause[Any]) -> Effect[Any, Any, Any]:
        found = cause.find_recoverable_error()
        return f(found.error) if isinstance(found, Fail) else _FailCause(found)

    return handle


_ignore_failure = _recovering(_succeed_none)


def _catching_if(
    predicate: Callable[[Any], bool],
    f: Callable[[Any], Effect[Any, Any, Any]],
    or_else: Callable[[Any], Effect[Any, Any, Any]] | None,
) -> Callable[[Cause[Any]], Effect[Any, Any, Any]]:
    """The failure handler of ``catch_if`` and ``catch_tag``. An error that
    fails ``predicate`` goes to ``or_else``, or re-fails with the whole cause."""

    def handle(cause: Cause[Any]) -> Effect[Any, Any, Any]:
        found = cause.find_recoverable_error()
        if not isinstance(found, Fail):
            return _FailCause(found)
        if predicate(found.error):
            return f(found.error)
        return _FailCause(cause) if or_else is None else or_else(found.error)

    return handle


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


# The primitives subclass ``Effect``, so they load after it. The methods above
# use them only when called, and other modules import them from here.
from pyfect._primitives import (  # noqa: E402
    Register,
    Restore,
    _Callback,
    _FailCause,
    _FlatMap,
    _Fork,
    _FromExit,
    _Gen,
    _GenFrame,
    _Locally,
    _Map,
    _MatchCause,
    _RestoreContext,
    _RestoreInterruptible,
    _SetInterruptible,
    _Succeed,
    _Suspend,
    _Sync,
    _WithFiber,
    _YieldNow,
    interruptible_mask,
    uninterruptible_mask,
)

__all__ = [
    "SUSPEND",
    "Effect",
    "Frame",
    "Register",
    "Restore",
    "Step",
    "_Callback",
    "_FailCause",
    "_FlatMap",
    "_Fork",
    "_FromExit",
    "_Gen",
    "_GenFrame",
    "_Locally",
    "_Map",
    "_MatchCause",
    "_RestoreContext",
    "_RestoreInterruptible",
    "_SetInterruptible",
    "_Succeed",
    "_Suspend",
    "_Sync",
    "_WithFiber",
    "_YieldNow",
    "_call_user",
    "_ignore_failure",
    "_run_finalizer",
    "_succeed_none",
    "_to_none",
    "interruptible_mask",
    "uninterruptible_mask",
]
