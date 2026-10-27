"""``Effect[A, E, R]``: the lazy description of a computation, and its
sequencing methods.

An effect is an immutable description. Running it is the fiber's job
(``pyfect._fiber``). The runtime loop knows nothing about specific
primitives: each primitive reduces itself in ``_step``, and continuation
frames (often the primitive itself, pushed onto the fiber's stack) consume
the result in ``_on_success`` / ``_on_failure``. The step protocol is in
``pyfect._effect_base``.

``Effect`` gathers its methods from one module per concern:

- sequencing: here
- error handling: ``pyfect._effect_errors``
- folding (``match``, ``exit``, ``result``): ``pyfect._effect_folding``
- finalizers and interruptibility: ``pyfect._effect_resources``
- forking, racing and timeouts: ``pyfect._effect_concurrency``
- delays, caching and schedules: ``pyfect._effect_timing``

Every method is built from about a dozen primitives, defined in
``pyfect._primitives`` and re-exported from this module. Import effects and
primitives from here: loading this module loads the rest in the right order.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import TYPE_CHECKING, Any, Literal, Never, Self, TypeIs, overload

from pyfect._effect_base import SUSPEND, A_co, E_co, Frame, R_co, Step
from pyfect._effect_concurrency import ConcurrencyMethods
from pyfect._effect_errors import (
    ErrorMethods,
    _catching_if,
    _fail,
    _ignore_failure,
    _recovering,
    _succeed_none,
)
from pyfect._effect_folding import FoldingMethods
from pyfect._effect_resources import ResourceMethods, _call_user, _run_finalizer
from pyfect._effect_timing import TimingMethods

if TYPE_CHECKING:
    from pyfect._concurrency import Concurrency
    from pyfect._fiber import Fiber
    from pyfect.errors import NoSuchElementException
    from pyfect.option import Option


class Effect(
    ErrorMethods[A_co, E_co, R_co],
    FoldingMethods[A_co, E_co, R_co],
    ResourceMethods[A_co, E_co, R_co],
    ConcurrencyMethods[A_co, E_co, R_co],
    TimingMethods[A_co, E_co, R_co],
):
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


def _to_none(_: object) -> None:
    return None


def _identity[T](value: T) -> T:
    return value


def _pair[A, B](a: A, b: B) -> tuple[A, B]:
    return (a, b)


# The primitives subclass ``Effect``, so they load after it. The methods above
# use them only when called, and other modules import them from here.
from pyfect._primitives import (  # noqa: E402
    Register,
    Restore,
    _AfterStarted,
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
    "_AfterStarted",
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
    "_catching_if",
    "_fail",
    "_ignore_failure",
    "_recovering",
    "_run_finalizer",
    "_succeed_none",
    "_to_none",
    "interruptible_mask",
    "uninterruptible_mask",
]
