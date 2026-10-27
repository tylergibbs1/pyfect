"""``Layer`` itself, the ``MemoMap`` that shares builds, and building.

A layer is a build function ``(memo_map, scope) -> Effect[Context]``.
``from_build`` gives each build a child of ``scope`` that closes if the
build fails; ``from_build_memo`` also shares the build through the memo map.

A memo map entry owns a scope of its own and counts its users: every scope
that builds or reuses the layer holds one count, and gives it back when it
closes. The last one to leave closes the entry, releasing the layer, and a
later build starts afresh. A forked map reuses its parent's entries but
keeps the layers first built through it to itself.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Generic, Never, Self, TypeVar, overload

from pyfect._core import Effect, _FailCause, _Locally, _Succeed, _Suspend, _WithFiber
from pyfect.cause import Cause
from pyfect.cause import fail as fail_cause
from pyfect.context import Context, Tag, TagLike
from pyfect.deferred import Deferred
from pyfect.effect import never
from pyfect.exit import Exit, Failure
from pyfect.scope import CloseableScope, Scope, scoped

ROut_contra = TypeVar("ROut_contra", contravariant=True)
E_co = TypeVar("E_co", covariant=True, default=Never)
RIn_co = TypeVar("RIn_co", covariant=True, default=Never)

type Builder = Callable[[MemoMap, CloseableScope], Effect[Context, Any, Any]]

_VOID: Effect[None] = _Succeed(None)


class _Entry:
    """A shared build: its result, its scope, and how many scopes use it."""

    __slots__ = ("deferred", "finalizer", "observers", "scope")

    def __init__(self, memo: MemoMap, layer: Layer[Any, Any, Any]) -> None:
        self.observers = 0
        self.deferred: Deferred[Context, Any] = Deferred()
        self.scope = CloseableScope()

        def leave(ex: Exit[Any, Any]) -> Effect[None]:
            self.observers -= 1
            if self.observers > 0:
                return _VOID
            memo._entries.pop(layer, None)
            return self.scope.close(ex)

        def finalizer(ex: Exit[Any, Any]) -> Effect[None]:
            return _Suspend(lambda: leave(ex))

        self.finalizer = finalizer

    def observe(self, scope: CloseableScope) -> bool:
        """Count ``scope`` as a user until it closes, at once, so no
        interruption can lose the count. A closed scope can't use it."""
        if scope._closed is not None:
            return False
        self.observers += 1
        scope._add(object(), self.finalizer)
        return True


class MemoMap:
    """Shares layer builds by layer identity, releasing each layer when the
    last scope using it closes. ``fork`` gives a map that reuses this one's
    layers and keeps its own builds to itself."""

    __slots__ = ("_entries", "_parent")

    def __init__(self, parent: MemoMap | None = None) -> None:
        self._parent = parent
        self._entries: dict[Layer[Any, Any, Any], _Entry] = {}

    def fork(self) -> MemoMap:
        return MemoMap(self)

    def get[O, E, R](
        self, layer: Layer[O, E, R], scope: CloseableScope
    ) -> Effect[Context[O], E, R] | None:
        """The shared build of ``layer``, if this map or a parent has one.
        ``scope`` uses it from now on, whether or not the effect runs."""
        entry = self._entries.get(layer)
        if entry is not None:
            entry.observe(scope)
            return entry.deferred.wait()
        return self._parent.get(layer, scope) if self._parent is not None else None

    def get_or_else_memoize[O, E, R](
        self,
        layer: Layer[O, E, R],
        scope: CloseableScope,
        build: Callable[[MemoMap, CloseableScope], Effect[Context[O], E, R]],
    ) -> Effect[Context[O], E, R]:
        """Reuse ``layer``'s shared build, or run ``build`` as it."""

        def run() -> Effect[Context[O], E, R]:
            published: list[Deferred[Context, Any]] = []

            def reuse_or_build() -> Effect[Context[O], E, R]:
                existing = self.get(layer, scope)
                if existing is not None:
                    return existing
                entry = _Entry(self, layer)
                if not entry.observe(scope):
                    return build(self, scope)
                published.append(entry.deferred)
                self._entries[layer] = entry
                return build(self, entry.scope)

            def settle(ex: Exit[Any, Any]) -> Effect[None]:
                for deferred in published:
                    deferred.unsafe_done(ex)
                return _VOID

            # ``settle`` is in place before the entry is published, so even
            # an interrupted first requester completes it for the others.
            return _Suspend(reuse_or_build).on_exit(settle)

        return _Suspend(run)


class CurrentMemoMap(Tag[MemoMap]):
    """The memo map of the enclosing build. ``provide`` and ``build`` fork
    it, so layers built further out are reused."""


def fork_or_create(ctx: Context) -> MemoMap:
    """A fork of ``ctx``'s memo map, or a new map if it has none."""
    found, current = ctx.lookup(CurrentMemoMap)
    return current.fork() if found else MemoMap()


class Layer(Generic[ROut_contra, E_co, RIn_co]):
    """Builds the services ``ROut``, may fail with ``E``, needs ``RIn``.

    ``Layer(build)`` is Effect's ``fromBuildUnsafe``: no child scope and no
    sharing. Use ``from_build`` / ``from_build_memo`` or the constructors in
    ``pyfect.layer``."""

    __slots__ = ("_build",)

    def __init__(self, build: Builder) -> None:
        self._build = build

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        return f(self)

    # --- building ---------------------------------------------------------------

    def build_with_memo_map(
        self, memo_map: MemoMap, scope: CloseableScope
    ) -> Effect[Context[ROut_contra], E_co, RIn_co]:
        """Build with ``memo_map``, releasing into ``scope``. The memo map is
        ``CurrentMemoMap`` during the build and in the built context."""
        building: Effect[Context, Any, Any] = _Locally(
            _Suspend(lambda: self._build(memo_map, scope)),
            lambda ctx: ctx.add(CurrentMemoMap, memo_map),
        )
        return building.map(lambda built: built.add(CurrentMemoMap, memo_map))

    def build_with_scope(self, scope: CloseableScope) -> Effect[Context[ROut_contra], E_co, RIn_co]:
        """Build into ``scope``, reusing what an enclosing build built."""
        return _WithFiber(
            lambda fiber: self.build_with_memo_map(fork_or_create(fiber._context), scope)
        )

    def build(self) -> Effect[Context[ROut_contra], E_co, RIn_co | Scope]:
        """Build into the current ``Scope``, reusing what an enclosing build
        built."""
        return _WithFiber(
            lambda fiber: self.build_with_memo_map(
                fork_or_create(fiber._context), fiber._context.unsafe_get(Scope)
            )
        )

    def launch(self) -> Effect[Never, E_co, RIn_co]:
        """Build the layer and keep it until interrupted, as for a server."""
        return scoped(self.build().and_then(never))

    # --- sequencing -------------------------------------------------------------

    def flat_map[O2, E2 = Never, R2 = Never](
        self, f: Callable[[Context[ROut_contra]], Layer[O2, E2, R2]]
    ) -> Layer[O2, E_co | E2, RIn_co | R2]:
        """Build the layer ``f`` makes from this one's services."""
        return from_build(
            lambda memo, scope: self._build(memo, scope).flat_map(
                lambda ctx: f(ctx)._build(memo, scope)
            )
        )

    @overload
    def tap[E2 = Never](
        self, f: Callable[[Context[ROut_contra]], Effect[object, E2, Scope]]
    ) -> Layer[ROut_contra, E_co | E2, RIn_co]: ...
    @overload
    def tap[E2 = Never, R2 = Never](
        self, f: Callable[[Context[ROut_contra]], Effect[object, E2, Scope | R2]]
    ) -> Layer[ROut_contra, E_co | E2, RIn_co | R2]: ...
    def tap(self, f: Callable[[Context], Effect[object, Any, Any]]) -> Layer[Any, Any, Any]:
        """Run ``f`` on the built services, in the layer's scope."""
        return from_build(
            lambda memo, scope: self._build(memo, scope).flat_map(
                lambda ctx: _in_scope(f(ctx), scope).as_(ctx)
            )
        )

    @overload
    def tap_error[E2 = Never](
        self, f: Callable[[E_co], Effect[object, E2, Scope]]
    ) -> Layer[ROut_contra, E_co | E2, RIn_co]: ...
    @overload
    def tap_error[E2 = Never, R2 = Never](
        self, f: Callable[[E_co], Effect[object, E2, Scope | R2]]
    ) -> Layer[ROut_contra, E_co | E2, RIn_co | R2]: ...
    def tap_error(self, f: Callable[[Any], Effect[object, Any, Any]]) -> Layer[Any, Any, Any]:
        """Run ``f`` on a typed build error, in the layer's scope; the build
        still fails with it."""
        return from_build(
            lambda memo, scope: self._build(memo, scope).catch_all(
                lambda e: _in_scope(f(e), scope).and_then(_FailCause(fail_cause(e)))
            )
        )

    @overload
    def tap_cause[E2 = Never](
        self, f: Callable[[Cause[E_co]], Effect[object, E2, Scope]]
    ) -> Layer[ROut_contra, E_co | E2, RIn_co]: ...
    @overload
    def tap_cause[E2 = Never, R2 = Never](
        self, f: Callable[[Cause[E_co]], Effect[object, E2, Scope | R2]]
    ) -> Layer[ROut_contra, E_co | E2, RIn_co | R2]: ...
    def tap_cause(
        self, f: Callable[[Cause[Any]], Effect[object, Any, Any]]
    ) -> Layer[Any, Any, Any]:
        """Run ``f`` on the cause of a failed build, in the layer's scope;
        the build still fails with it."""
        return from_build(
            lambda memo, scope: self._build(memo, scope).catch_cause(
                lambda c: _in_scope(f(c), scope).and_then(_FailCause(c))
            )
        )

    # --- errors -----------------------------------------------------------------

    def or_die(self) -> Layer[ROut_contra, Never, RIn_co]:
        """Die with a typed build error instead of failing with it."""
        return Layer(lambda memo, scope: self._build(memo, scope).or_die())

    def catch_all[O, E, R, E2 = Never, R2 = Never](
        self: Layer[O, E, R], f: Callable[[E], Layer[O, E2, R2]]
    ) -> Layer[O, E2, R | R2]:
        """Build ``f(error)`` instead when the build fails with a typed
        error. The fallback must build at least what this layer builds."""
        return Layer(
            lambda memo, scope: self._build(memo, scope).catch_all(
                lambda e: f(e)._build(memo, scope)
            )
        )

    def catch_cause[O, E, R, E2 = Never, R2 = Never](
        self: Layer[O, E, R], f: Callable[[Cause[E]], Layer[O, E2, R2]]
    ) -> Layer[O, E2, R | R2]:
        """Build ``f(cause)`` instead when the build fails, defects
        included. The fallback must build at least what this layer builds."""
        return Layer(
            lambda memo, scope: self._build(memo, scope).catch_cause(
                lambda c: f(c)._build(memo, scope)
            )
        )

    # --- services ---------------------------------------------------------------

    def update_service[S, T](
        self, tag: TagLike[S, T], f: Callable[[S], S]
    ) -> Layer[ROut_contra, E_co, RIn_co | T]:
        """Build with ``f`` applied to the service of ``tag`` that this
        layer needs (which it then needs from outside)."""
        updated = effect_context(tag().map(lambda service: Context.make(tag, f(service))))
        return feed(updated, self, keep_dep=False)


def _in_scope[A, E](eff: Effect[A, E, Any], scope: CloseableScope) -> Effect[A, E, Any]:
    return _Locally(eff, lambda ctx: ctx.add(Scope, scope))


def from_build[O, E = Never, R = Never](
    build: Callable[[MemoMap, CloseableScope], Effect[Context[O], E, R]],
) -> Layer[O, E, R]:
    """A layer from its build function. Each build gets a child of the
    scope it is given, closed at once if the build fails."""

    def child_scoped(memo: MemoMap, scope: CloseableScope) -> Effect[Context, Any, Any]:
        def run() -> Effect[Context, Any, Any]:
            layer_scope = scope._fork_now()
            return build(memo, layer_scope).on_exit(
                lambda ex: layer_scope.close(ex) if isinstance(ex, Failure) else _VOID
            )

        return _Suspend(run)

    return Layer(child_scoped)


def from_build_memo[O, E = Never, R = Never](
    build: Callable[[MemoMap, CloseableScope], Effect[Context[O], E, R]],
) -> Layer[O, E, R]:
    """``from_build``, shared through the memo map: within one build, and
    across builds with the same memo map while a scope still uses it."""
    layer: Layer[O, E, R] = from_build(
        lambda memo, scope: memo.get_or_else_memoize(layer, scope, build)
    )
    return layer


@overload
def effect_context[A, E](eff: Effect[Context[A], E, Scope]) -> Layer[A, E]: ...
@overload
def effect_context[A, E = Never, R = Never](
    eff: Effect[Context[A], E, Scope | R],
) -> Layer[A, E, R]: ...
def effect_context(eff: Effect[Context, Any, Any]) -> Layer[Any, Any, Any]:
    """Build every service of the context ``eff`` makes. ``eff`` may acquire
    resources (it runs with a ``Scope``); they are released with the layer."""
    return from_build_memo(lambda _memo, scope: _in_scope(eff, scope))


def feed(
    dep: Layer[Any, Any, Any], target: Layer[Any, Any, Any], *, keep_dep: bool
) -> Layer[Any, Any, Any]:
    """Build ``target`` with ``dep``'s services (both in one scope), giving
    ``target``'s services, plus ``dep``'s when ``keep_dep``."""

    def build(memo: MemoMap, scope: CloseableScope) -> Effect[Context, Any, Any]:
        def with_dep(dep_ctx: Context) -> Effect[Context, Any, Any]:
            built: Effect[Context, Any, Any] = _Locally(
                target._build(memo, scope), lambda ctx: ctx.merge(dep_ctx)
            )
            return built.map(dep_ctx.merge) if keep_dep else built

        return dep._build(memo, scope).flat_map(with_dep)

    return from_build_memo(build)
