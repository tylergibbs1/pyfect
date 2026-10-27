"""Scopes: where resources register their release.

``acquire_release`` adds a finalizer to the current ``Scope`` (which joins
``R``); ``scoped`` creates a scope, runs the effect in it, and closes it
however the effect ends, removing ``Scope`` from ``R``. Finalizers run in
reverse order of registration, uninterruptibly, and all of them run even if
some fail.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, Never, overload

from pyfect._concurrency import for_each
from pyfect._core import (
    Effect,
    _AfterStarted,
    _call_user,
    _FailCause,
    _Gen,
    _Locally,
    _Succeed,
    _Suspend,
    _Sync,
    _WithFiber,
    uninterruptible_mask,
)
from pyfect._fiber import Fiber, Uninterruptible
from pyfect.cause import merge
from pyfect.context import Tag
from pyfect.exit import Exit, Failure

type Finalizer = Callable[[Exit[Any, Any]], Effect[object, Never, Any]]


type Strategy = Literal["sequential", "parallel"]


class CloseableScope:
    """A scope that can be closed. Use through the ``Scope`` tag.

    Finalizers are keyed, so whatever registered one can take it back when
    it no longer needs it: a child scope leaves its parent when it closes,
    and a ``fork_scoped`` fiber leaves its scope when it exits. A
    ``"parallel"`` scope runs its finalizers concurrently on close."""

    __slots__ = ("_closed", "_finalizers", "_parent", "_strategy")

    def __init__(self, strategy: Strategy = "sequential") -> None:
        self._strategy: Strategy = strategy
        self._finalizers: dict[object, Finalizer] = {}
        self._closed: Exit[Any, Any] | None = None
        self._parent: CloseableScope | None = None

    @property
    def finalizer_count(self) -> int:
        """How many finalizers are registered and not yet run."""
        return len(self._finalizers)

    @property
    def is_closed(self) -> bool:
        """Whether ``close`` has started (later finalizers run at once)."""
        return self._closed is not None

    def add_finalizer(
        self, f: Callable[[Exit[Any, Any]], Effect[object, Never, Any]]
    ) -> Effect[None]:
        """Register ``f`` to run on close, with the services in scope now.
        If the scope is already closed, ``f`` runs immediately."""

        def body(fiber: Fiber[Any, Any]) -> Effect[None]:
            ctx = fiber._context

            # As Effect's ``provideContext``: the closing fiber's services,
            # overridden by those in scope at registration.
            def finalizer(ex: Exit[Any, Any]) -> Effect[object, Never, Any]:
                return _Locally(_call_user(f, ex), lambda current: current.merge(ctx))

            if self._closed is not None:
                return finalizer(self._closed).as_void()
            self._add(object(), finalizer)
            return _Succeed(None)

        return _WithFiber(body)

    def _add(self, key: object, finalizer: Finalizer) -> None:
        """Register under ``key``, which ``_remove`` takes. The scope must be
        open."""
        self._finalizers[key] = finalizer

    def _remove(self, key: object) -> None:
        self._finalizers.pop(key, None)

    def _watch(self, fiber: Fiber[Any, Any]) -> None:
        """Interrupt ``fiber`` on close (unless it is the fiber closing the
        scope), until it exits. Watching again moves its finalizer last, so
        it runs first. The scope must be open."""
        self._remove(fiber)
        self._add(
            fiber, lambda _: _WithFiber(lambda current: _interrupt_unless_self(fiber, current))
        )
        fiber.unsafe_add_observer(lambda _: self._remove(fiber))

    def close(self, ex: Exit[Any, Any]) -> Effect[None]:
        """Run every finalizer, last added first (all at once in a parallel
        scope). Closing twice is a no-op."""

        # Uninterruptible before the scope is marked closed, so an interrupt
        # can't land between marking it and running its finalizers.
        return _Suspend(lambda: self.close_unsafe(ex) or _Succeed(None)).uninterruptible()

    def close_unsafe(self, ex: Exit[Any, Any]) -> Effect[None] | None:
        """Mark the scope closed now and return the effect that runs its
        finalizers, or ``None`` if it was closed already or had none. The
        caller must run the effect uninterruptibly (Effect's ``closeUnsafe``)."""
        if self._closed is not None:
            return None
        self._closed = ex
        if self._parent is not None:
            self._parent._remove(self)
        if not self._finalizers:
            return None
        entries = list(reversed(self._finalizers.items()))
        self._finalizers = {}
        run = _run_parallel if self._strategy == "parallel" else _run_sequential
        return run(entries, ex)

    def fork(self, strategy: Strategy = "sequential") -> Effect[CloseableScope]:
        """A child scope, closed when this one closes (if not before). The
        child of a closed scope starts closed."""

        return _Sync(lambda: self._fork_now(strategy))

    def _fork_now(self, strategy: Strategy = "sequential") -> CloseableScope:
        """``fork``, run at once (Effect's ``Scope.forkUnsafe``)."""
        child = CloseableScope(strategy)
        if self._closed is not None:
            child._closed = self._closed
            return child
        child._parent = self
        self._add(child, child.close)
        return child


type _Entries = list[tuple[object, Finalizer]]


def _fail_with_all(exits: list[Exit[Any, Never]]) -> Effect[None]:
    cause = merge(*(e.cause for e in exits if isinstance(e, Failure)))
    return _FailCause(cause) if cause.reasons else _Succeed(None)


def _run_sequential(entries: _Entries, ex: Exit[Any, Any]) -> Effect[None]:
    def run_all():
        exits: list[Exit[Any, Never]] = []
        for _key, fin in entries:
            exits.append((yield from _call_user(fin, ex).exit()))
        return (yield from _fail_with_all(exits))

    return _Gen(run_all)


def _run_parallel(entries: _Entries, ex: Exit[Any, Any]) -> Effect[None]:
    # The closing fiber skips its own fork_scoped finalizer: running it on
    # another fiber would wait for the closing fiber to exit.
    def body(closing: Fiber[Any, Any]) -> Effect[None]:
        others = [fin for key, fin in entries if key is not closing]
        exits = for_each(
            others,
            lambda fin: _call_user(fin, ex).uninterruptible().exit(),
            concurrency="unbounded",
        )
        return exits.flat_map(_fail_with_all)

    return _WithFiber(body)


class Scope(Tag[CloseableScope]):
    pass


@overload
def scoped[A, E](eff: Effect[A, E, Scope]) -> Effect[A, E]: ...
@overload
def scoped[A, E, R](eff: Effect[A, E, Scope | R]) -> Effect[A, E, R]: ...
def scoped(eff: Effect[Any, Any, Any]) -> Effect[Any, Any, Any]:
    """Run ``eff`` in a new scope and close it when ``eff`` ends."""

    def body() -> Effect[Any, Any, Any]:
        scope = CloseableScope()
        inner: Effect[Any, Any, Any] = _Locally(eff, lambda ctx: ctx.add(Scope, scope))
        return inner.on_exit(scope.close)

    return _Suspend(body)


def scoped_with[A, E = Never, R = Never](
    f: Callable[[CloseableScope], Effect[A, E, R]],
) -> Effect[A, E, R]:
    """Run ``f`` with a new scope and close it when the effect ``f`` gives
    ends."""

    def body() -> Effect[A, E, R]:
        scope = CloseableScope()
        return _call_user(f, scope).on_exit(scope.close)

    return _Suspend(body)


def add_finalizer[R = Never](
    f: Callable[[Exit[Any, Any]], Effect[object, Never, R]],
) -> Effect[None, Never, Scope | R]:
    return Scope().flat_map(lambda scope: scope.add_finalizer(f))


def acquire_release[A, E = Never, RR = Never](
    acquire: Effect[A, E, RR],
    release: Callable[[A, Exit[Any, Any]], Effect[object, Never, RR]],
) -> Effect[A, E, RR | Scope]:
    """Acquire uninterruptibly and register ``release`` on the current
    scope."""

    def body():
        a = yield from acquire
        scope = yield from Scope()
        yield from scope.add_finalizer(lambda ex: release(a, ex))
        return a

    return _Gen(body).uninterruptible()


def acquire_use_release[A, B, EE = Never, RR = Never](
    acquire: Effect[A, EE, RR],
    use: Callable[[A], Effect[B, EE, RR]],
    release: Callable[[A, Exit[B, EE]], Effect[object, Never, RR]],
) -> Effect[B, EE, RR]:
    """Acquire, use, and always release, without needing a scope."""
    return uninterruptible_mask(
        lambda restore: acquire.flat_map(
            lambda a: restore(_call_user(use, a)).on_exit(lambda ex: release(a, ex))
        )
    )


def fork_scoped[A, E, R](
    eff: Effect[A, E, R],
    *,
    start_immediately: bool = False,
    uninterruptible: Uninterruptible = False,
) -> Effect[Fiber[A, E], Never, R | Scope]:
    """Fork ``eff`` into the current scope (see ``fork_in``)."""
    return Scope().flat_map(
        lambda scope: fork_in(
            eff, scope, start_immediately=start_immediately, uninterruptible=uninterruptible
        )
    )


def fork_in[A, E, R](
    eff: Effect[A, E, R],
    scope: CloseableScope,
    *,
    start_immediately: bool = False,
    uninterruptible: Uninterruptible = False,
) -> Effect[Fiber[A, E], Never, R]:
    """Fork ``eff`` on a fiber that outlives its parent but is interrupted
    when ``scope`` closes, and leaves the scope when it exits. Into a
    closed scope it gives an already-interrupted fiber that never ran
    ``eff``."""

    def body(parent: Fiber[Any, Any]) -> Effect[Fiber[A, E]]:
        if scope._closed is not None:
            unstarted: Fiber[A, E] = Fiber(parent._run_scheduler, parent._context, None)
            unstarted.unsafe_interrupt_as(parent.id)
            return _Succeed(unstarted)
        fiber: Fiber[A, E] = parent._fork(
            eff, daemon=True, start_immediately=start_immediately, uninterruptible=uninterruptible
        )
        scope._watch(fiber)
        return _AfterStarted(fiber)

    return _WithFiber(body)


def _interrupt_unless_self(fiber: Fiber[Any, Any], current: Fiber[Any, Any]) -> Effect[None]:
    return _Succeed(None) if current is fiber else fiber.interrupt()
