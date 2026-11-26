"""Scopes: where resources register their release.

``acquire_release`` adds a finalizer to the current ``Scope`` (which joins
``R``); ``scoped`` creates a scope, runs the effect in it, and closes it
however the effect ends, removing ``Scope`` from ``R``. For a scope made
with ``make``, ``eff.pipe(provide(scope))`` runs ``eff`` in it and leaves
it open; ``eff.pipe(use(scope))`` also closes it when ``eff`` ends. Finalizers run in
reverse order of registration, uninterruptibly, and all of them run even if
some fail.

From plain Python code, ``with`` / ``async with`` stand in for ``scoped``:
a ``CloseableScope`` closes when the block ends, and ``managed(eff)`` runs a
scoped effect (a resource, ``layer.build()``) on entering and closes its
scope on leaving, with the block's exit.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import threading
from collections.abc import Callable, Generator
from functools import partial
from types import TracebackType
from typing import Any, Literal, Never, Self, cast, overload

from pyfect._concurrency import for_each
from pyfect._core import (
    Effect,
    _AfterStarted,
    _call_user,
    _FromExit,
    _Gen,
    _Locally,
    _OnExit,
    _RestoreInterruptible,
    _Succeed,
    _Suspend,
    _Sync,
    _WithFiber,
    uninterruptible_mask,
)
from pyfect._effect_args import require_effect
from pyfect._effect_base import Step
from pyfect._effect_resources import _call_user_now, _run_finalizer
from pyfect._fiber import Fiber, Uninterruptible
from pyfect._interrupt_reason import closed
from pyfect.context import Context, Tag
from pyfect.exit import Exit, Failure, as_void_all

type Finalizer = Callable[[Exit[Any, Any]], Effect[object, Never, Any]]

_VOID: Effect[None] = _Succeed(None)


type Strategy = Literal["sequential", "parallel"]

_LOCK = threading.Lock()
"""Held to change any scope's finalizers or close it: runs on other threads
share scopes (a layer's, a ``ManagedRuntime``'s), and a scope is made too
often for a lock of its own. Nothing runs under it but dict operations."""


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

            ended = self._add(object(), finalizer)
            return _Succeed(None) if ended is None else finalizer(ended).as_void()

        return _WithFiber(body)

    def _add(self, key: object, finalizer: Finalizer) -> Exit[Any, Any] | None:
        """Register under ``key``, which ``_remove`` takes. ``None``, or the
        scope's exit if it is closed (another run may just have closed it):
        then nothing is registered, and the caller runs ``finalizer`` itself."""
        with _LOCK:
            ended = self._closed
            if ended is None:
                self._finalizers[key] = finalizer
            return ended

    def _remove(self, key: object) -> None:
        with _LOCK:
            self._finalizers.pop(key, None)

    def _watch(self, fiber: Fiber[Any, Any]) -> None:
        """Interrupt ``fiber`` on close (unless it is the fiber closing the
        scope), until it exits. Watching again moves its finalizer last, so
        it runs first. A scope closed meanwhile interrupts it at once."""
        with _LOCK:
            ended = self._closed
            if ended is None:
                self._finalizers.pop(fiber, None)
                self._finalizers[fiber] = lambda _: _WithFiber(
                    lambda current: _interrupt_unless_self(fiber, current)
                )
        if ended is not None:
            fiber.interrupt_as_unsafe(fiber.id, closed("Scope"))
            return
        fiber.add_observer_unsafe(lambda _: self._remove(fiber))

    def _add_finalizer_exit(self, f: Finalizer) -> Effect[object, Never, Any]:
        """Register ``f``, or run it now if the scope is closed (the body of
        Effect's ``scopeAddFinalizerExit``)."""
        ended = self._add(object(), f)
        return _VOID if ended is None else f(ended)

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
        with _LOCK:
            if self._closed is not None:
                return None
            self._closed = ex
            parent = self._parent
            entries = list(reversed(self._finalizers.items()))
            self._finalizers = {}
        if parent is not None:
            parent._remove(self)
        if not entries:
            return None
        if len(entries) == 1:
            # As Effect's ``scopeCloseUnsafe``: a lone finalizer runs as it is.
            # Its value is the finalizer's; callers only sequence on it.
            return cast("Effect[None]", _call_user_now(entries[0][1], ex))
        run = _run_parallel if self._strategy == "parallel" else _run_sequential
        return run(entries, ex)

    def fork(self, strategy: Strategy = "sequential") -> Effect[CloseableScope]:
        """A child scope, closed when this one closes (if not before). The
        child of a closed scope starts closed."""

        return _Sync(lambda: self.fork_unsafe(strategy))

    def __enter__(self) -> Self:
        """``with scope:`` closes the scope when the block ends, blocking
        this thread: with ``Success(None)``, or with the block's raise as a
        defect (Ctrl-C as an interruption). The block's exception
        propagates; failed finalizers are raised as ``run.unwrap`` raises
        their cause, or added to the block's exception as a note."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        from pyfect._scope_with import exit_blocking

        exit_blocking(self, exc)

    async def __aenter__(self) -> Self:
        """``async with scope:``, closing on the running loop; a cancelled
        block closes it as interrupted."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        from pyfect._scope_with import exit_async

        await exit_async(self, exc)

    def fork_unsafe(self, strategy: Strategy = "sequential") -> CloseableScope:
        """``fork``, run at once."""
        child = CloseableScope(strategy)
        child._parent = self
        ended = self._add(child, child.close)
        if ended is not None:
            child._parent = None
            child._closed = ended
        return child


type _Entries = list[tuple[object, Finalizer]]


def _fail_with_all(exits: list[Exit[Any, Never]]) -> Effect[None]:
    """Every finalizer's failure, as Effect's ``Exit.asVoidAll``: reasons
    concatenated, not deduped nor elected."""
    return _FromExit(as_void_all(exits))


def _run_sequential(entries: _Entries, ex: Exit[Any, Any]) -> Effect[None]:
    def run_all() -> Generator[Effect[Any, Any, Any], Any]:
        exits: list[Exit[Any, Never]] = []
        for _key, fin in entries:
            exits.append((yield _call_user_now(fin, ex).exit()))
        yield _fail_with_all(exits)

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
    """Tag of the scope resources register their release in, closed when it ends."""


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

    # Effect's op for op: one ``withFiber`` that adds the scope to the
    # fiber's context and pushes an ``OnExit`` frame, which puts the context
    # back and closes the scope (handing the exit straight on if it is empty).
    def enter(fiber: Fiber[Any, Any]) -> Effect[Any, Any, Any]:
        before = fiber._view
        scope = CloseableScope()
        fiber._set_context(fiber._context.add(Scope, scope))

        def finish(ex: Exit[Any, Any]) -> Step:
            fiber._use_view(before)
            after = scope.close_unsafe(ex)
            return _FromExit(ex) if after is None else _run_finalizer(after, ex)

        fiber._stack.append(_OnExit(eff, finish))
        return eff

    return _WithFiber(enter)


def scoped_with[A, E = Never, R = Never](
    f: Callable[[CloseableScope], Effect[A, E, R]],
) -> Effect[A, E, R]:
    """Run ``f`` with a new scope and close it when the effect ``f`` gives
    ends."""

    def body() -> Effect[A, E, R]:
        scope = CloseableScope()
        return _call_user(f, scope).on_exit(scope.close)

    return _Suspend(body)


class Managed[A]:
    """``managed(eff)``: ``eff`` run in a new scope on entering, its value
    bound by ``as``, and the scope closed when the block ends (see
    ``CloseableScope.__enter__``). Each one is entered once."""

    __slots__ = ("_claim", "_context", "_eff", "_scope")

    def __init__(self, eff: Effect[A, Any, Any], context: Context[Any]) -> None:
        self._eff = eff
        self._context = context
        self._scope: CloseableScope | None = None
        # Held from the first entry on, so of threads entering at once exactly one does.
        self._claim = threading.Lock()

    def _open(self) -> tuple[CloseableScope, Effect[A, Any]]:
        if not self._claim.acquire(blocking=False):
            raise RuntimeError("managed(...) is entered once: call managed(eff) again")
        scope = self._scope = CloseableScope()
        return scope, _Locally(self._eff, lambda ctx: ctx.add(Scope, scope))

    def _entered(self) -> CloseableScope:
        if self._scope is None:
            raise RuntimeError("managed(...) exited before it was entered")
        return self._scope

    def __enter__(self) -> A:
        """Run the effect, blocking this thread as ``run_blocking``. If it
        fails, the scope closes with its exit and the failure is raised as
        ``run.unwrap`` raises it."""
        from pyfect._scope_with import exit_blocking, fail_blocking
        from pyfect.run import run_blocking_exit

        scope, eff = self._open()
        try:
            ex = run_blocking_exit(eff, context=self._context)
        except BaseException as exc:
            exit_blocking(scope, exc)
            raise
        if isinstance(ex, Failure):
            fail_blocking(scope, ex)
        return ex.value

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        from pyfect._scope_with import exit_blocking

        exit_blocking(self._entered(), exc)

    async def __aenter__(self) -> A:
        """``__enter__`` on the running loop, as ``run_async``."""
        from pyfect._scope_with import exit_async, fail_async
        from pyfect.run import run_async_exit

        scope, eff = self._open()
        try:
            ex = await run_async_exit(eff, context=self._context)
        except BaseException as exc:
            await exit_async(scope, exc)
            raise
        if isinstance(ex, Failure):
            await fail_async(scope, ex)
        return ex.value

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        from pyfect._scope_with import exit_async

        await exit_async(self._entered(), exc)


@overload
def managed[A](eff: Effect[A, Any, Scope]) -> Managed[A]: ...
@overload
def managed[A, R](eff: Effect[A, Any, Scope | R], *, context: Context[R]) -> Managed[A]: ...
def managed(eff: Effect[Any, Any, Any], *, context: Context[Any] | None = None) -> Managed[Any]:
    """A scoped effect as a context manager, for plain Python code (Effect's
    ``scoped`` around the block)::

        with fx.managed(connection) as conn:   # acquire_release(...)
            ...
        # released here, with the block's exit

        async with fx.managed(AppLive.build()) as services:   # a layer
            ...

    ``context`` gives the services the effect needs besides ``Scope``. A
    failure to acquire is raised; resources acquired before it are
    released first."""
    require_effect(eff, "eff")
    return Managed(eff, Context.empty() if context is None else context)


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
    "Managed",
    "Scope",
    "Strategy",
    "acquire_release",
    "acquire_use_release",
    "add_finalizer",
    "fork_in",
    "fork_scoped",
    "make",
    "managed",
    "provide",
    "scoped",
    "scoped_with",
    "use",
]
