"""Scopes: where resources register their release.

``acquire_release`` adds a finalizer to the current ``Scope`` (which joins
``R``); ``scoped`` creates a scope, runs the effect in it, and closes it
however the effect ends, removing ``Scope`` from ``R``. For a scope made
with ``make``, ``eff.pipe(provide(scope))`` runs ``eff`` in it and leaves
it open; ``eff.pipe(use(scope))`` also closes it when ``eff`` ends. Finalizers run in
reverse order of registration, uninterruptibly, and all of them run even if
some fail.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any, Literal, Never, overload

from pyfect._concurrency import for_each
from pyfect._core import (
    Effect,
    _AfterStarted,
    _call_user,
    _FromExit,
    _Gen,
    _Locally,
    _RestoreInterruptible,
    _Succeed,
    _Suspend,
    _Sync,
    _WithFiber,
    uninterruptible_mask,
)
from pyfect._effect_args import require_effect
from pyfect._effect_resources import _call_user_now
from pyfect._fiber import Fiber, Uninterruptible
from pyfect._interrupt_reason import closed
from pyfect.context import Tag
from pyfect.exit import Exit, as_void_all

type Finalizer = Callable[[Exit[Any, Any]], Effect[object, Never, Any]]

_VOID: Effect[None] = _Succeed(None)


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
    def strategy(self) -> Strategy:
        """How finalizers run on close: one after the other, last added
        first, or all at once."""
        return self._strategy

    @property
    def finalizer_count(self) -> int:
        """How many finalizers are registered and not yet run."""
        return len(self._finalizers)

    @property
    def is_empty(self) -> bool:
        """Open with no finalizers, so it can be handed on for reuse
        (Effect's ``Empty`` state). A closed scope is never empty."""
        return self._closed is None and not self._finalizers

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
                return _Locally(_call_user_now(f, ex), lambda current: current.merge(ctx))

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
        fiber.add_observer_unsafe(lambda _: self._remove(fiber))

    def _add_finalizer_exit(self, f: Finalizer) -> Effect[object, Never, Any]:
        """Register ``f``, or run it now if the scope is closed (the body of
        Effect's ``scopeAddFinalizerExit``)."""
        if self._closed is not None:
            return f(self._closed)
        self._add(object(), f)
        return _VOID

    def close(self, ex: Exit[Any, Any]) -> Effect[None]:
        """Run every finalizer, last added first (all at once in a parallel
        scope). Closing twice is a no-op."""

        # Uninterruptible before the scope is marked closed, so an interrupt
        # can't land between marking it and running its finalizers (Effect's
        # ``withFiber`` with ``fiberEnterUninterruptibleUnsafe``).
        def body(fiber: Fiber[Any, Any]) -> Effect[None]:
            if fiber._interruptible:
                fiber._push(_RestoreInterruptible(True))
                fiber._interruptible = False
            return self.close_unsafe(ex) or _Succeed(None)

        return _WithFiber(body)

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

        return _Sync(lambda: self.fork_unsafe(strategy))

    def fork_unsafe(self, strategy: Strategy = "sequential") -> CloseableScope:
        """``fork``, run at once."""
        child = CloseableScope(strategy)
        if self._closed is not None:
            child._closed = self._closed
            return child
        child._parent = self
        self._add(child, child.close)
        return child


type _Entries = list[tuple[object, Finalizer]]


def _fail_with_all(exits: list[Exit[Any, Never]]) -> Effect[None]:
    """Every finalizer's failure, as Effect's ``Exit.asVoidAll``: reasons
    concatenated, not deduped nor elected."""
    return _FromExit(as_void_all(exits))


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


def make(strategy: Strategy = "sequential") -> Effect[CloseableScope]:
    """A new open scope (``CloseableScope(strategy)``, made when the effect
    runs)."""
    return _Sync(lambda: CloseableScope(strategy))


class _InScope:
    """``provide(scope)`` / ``use(scope)``: run in ``scope``, removing
    ``Scope`` from ``R``; ``use`` also closes it with the effect's exit."""

    __slots__ = ("close", "scope")

    def __init__(self, scope: CloseableScope, *, close: bool) -> None:
        self.scope = scope
        self.close = close

    @overload
    def __call__[A, E](self, eff: Effect[A, E, Scope]) -> Effect[A, E]: ...
    @overload
    def __call__[A, E, R](self, eff: Effect[A, E, Scope | R]) -> Effect[A, E, R]: ...
    def __call__(self, eff: Effect[Any, Any, Any]) -> Effect[Any, Any, Any]:
        require_effect(eff, "eff")
        scope = self.scope
        inner: Effect[Any, Any, Any] = _Locally(eff, lambda ctx: ctx.add(Scope, scope))
        return inner.on_exit(scope.close) if self.close else inner


def provide(scope: CloseableScope) -> _InScope:
    """Run an effect in ``scope``, removing ``Scope`` from ``R``; the scope
    stays open::

        eff.pipe(scope.provide(resources))
    """
    return _InScope(scope, close=False)


def use(scope: CloseableScope) -> _InScope:
    """Run an effect in ``scope`` and close the scope with the effect's
    exit, however it ends, removing ``Scope`` from ``R``::

        eff.pipe(scope.use(resources))
    """
    return _InScope(scope, close=True)


@overload
def scoped[A, E](eff: Effect[A, E, Scope]) -> Effect[A, E]: ...
@overload
def scoped[A, E, R](eff: Effect[A, E, Scope | R]) -> Effect[A, E, R]: ...
def scoped(eff: Effect[Any, Any, Any]) -> Effect[Any, Any, Any]:
    """Run ``eff`` in a new scope and close it when ``eff`` ends."""
    require_effect(eff, "eff")

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
    """Run ``f`` with the exit of the current ``Scope`` when it closes."""
    return Scope().flat_map(lambda scope: scope.add_finalizer(f))


def acquire_release[A, E = Never, RR = Never](
    acquire: Effect[A, E, RR],
    release: Callable[[A, Exit[Any, Any]], Effect[object, Never, RR]],
) -> Effect[A, E, RR | Scope]:
    """Acquire uninterruptibly and register ``release`` on the current
    scope."""
    require_effect(acquire, "acquire")

    # Effect's op for op: ``contextWith``, ``uninterruptibleMask``, the
    # scope, then ``tap`` adding the finalizer (``scopeAddFinalizerExit``).
    def with_context(fiber: Fiber[Any, Any]) -> Effect[A, E, RR | Scope]:
        ctx = fiber._context

        def add(scope: CloseableScope, a: A) -> Effect[object]:
            def finalizer(ex: Exit[Any, Any]) -> Effect[object, Never, Any]:
                return _Locally(_call_user_now(release, a, ex), lambda current: current.merge(ctx))

            return _Suspend(lambda: scope._add_finalizer_exit(finalizer))

        return uninterruptible_mask(
            lambda _: Scope().flat_map(lambda scope: acquire.tap(partial(add, scope)))
        )

    return _WithFiber(with_context)


def acquire_use_release[A, B, EE = Never, RR = Never](
    acquire: Effect[A, EE, RR],
    use: Callable[[A], Effect[B, EE, RR]],
    release: Callable[[A, Exit[B, EE]], Effect[object, EE, RR]],
) -> Effect[B, EE, RR]:
    """Acquire, use, and always release, without needing a scope. A failing release adds its
    cause to the result, after the use's."""
    require_effect(acquire, "acquire")
    return uninterruptible_mask(
        lambda restore: acquire.flat_map(
            lambda a: _call_user(lambda: restore(use(a))).on_exit_primitive(
                lambda ex: release(a, ex)
            )
        )
    )


def fork_scoped[A, E, R](
    eff: Effect[A, E, R],
    *,
    start_immediately: bool = False,
    uninterruptible: Uninterruptible = False,
) -> Effect[Fiber[A, E], Never, R | Scope]:
    """Fork ``eff`` into the current scope (see ``fork_in``)."""
    require_effect(eff, "eff")
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
    require_effect(eff, "eff")

    def body(parent: Fiber[Any, Any]) -> Effect[Fiber[A, E]]:
        if scope._closed is not None:
            unstarted: Fiber[A, E] = Fiber(parent._run_scheduler, parent._context, None)
            unstarted.interrupt_as_unsafe(
                parent.id, closed("Scope", parent._interruptor_annotations())
            )
            return _Succeed(unstarted)
        fiber: Fiber[A, E] = parent._fork(
            eff, daemon=True, start_immediately=start_immediately, uninterruptible=uninterruptible
        )
        scope._watch(fiber)
        return _AfterStarted(fiber)

    return _WithFiber(body)


def _interrupt_unless_self(fiber: Fiber[Any, Any], current: Fiber[Any, Any]) -> Effect[None]:
    return _Succeed(None) if current is fiber else fiber.interrupt()


__all__ = [
    "CloseableScope",
    "Finalizer",
    "Scope",
    "Strategy",
    "acquire_release",
    "acquire_use_release",
    "add_finalizer",
    "fork_in",
    "fork_scoped",
    "make",
    "provide",
    "scoped",
    "scoped_with",
    "use",
]
