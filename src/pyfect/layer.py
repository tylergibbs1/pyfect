"""Layers: recipes for building services.

``Layer[ROut, E, RIn]`` builds the services ``ROut``, may fail with ``E``,
and needs the services ``RIn`` to do it.

- Layers are memoized by identity: a layer used in several places is
  built once, and a nested ``provide`` reuses what an enclosing one built.
  Keep layers in module-level constants. ``fresh(layer)`` and
  ``provide(layer, local=True)`` opt out.
- Resources a layer acquires (``acquire_release`` in its ``make``) are
  released when the effect it was provided to finishes.
- ``merge`` builds, and releases, its layers concurrently.

``provide`` works on effects and on layers, and removes exactly what the
layer builds from ``R``, leaving the rest::

    program.pipe(provide(DatabaseLive))         # Effect, minus Database
    UsersLive.pipe(provide(DatabaseLive))       # Layer, its needs satisfied
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Generic, Literal, Never, Self, TypeVar, overload

from pyfect._concurrency import for_each
from pyfect._core import Effect, _Gen, _Locally, _Succeed, _Suspend, _Sync, _WithFiber
from pyfect._fiber import Fiber
from pyfect.context import Context, Tag, TagLike, tag_class
from pyfect.deferred import Deferred
from pyfect.scope import CloseableScope, Scope

ROut_contra = TypeVar("ROut_contra", contravariant=True)
E_co = TypeVar("E_co", covariant=True, default=Never)
RIn_co = TypeVar("RIn_co", covariant=True, default=Never)

type Builder = Callable[[MemoMap, CloseableScope], Effect[Context, Any, Any]]


class MemoMap:
    """One build's cache: each layer object is built at most once. A forked
    map also reuses what its parent built."""

    __slots__ = ("_entries", "_parent")

    def __init__(self, parent: MemoMap | None = None) -> None:
        self._parent = parent
        self._entries: dict[int, tuple[Layer[Any, Any, Any], Deferred[Context, Any]]] = {}

    def fork(self) -> MemoMap:
        return MemoMap(self)

    def _lookup(self, layer: Layer[Any, Any, Any]) -> Deferred[Context, Any] | None:
        entry = self._entries.get(id(layer))
        if entry is not None:
            return entry[1]
        return self._parent._lookup(layer) if self._parent is not None else None

    def get_or_build(
        self, layer: Layer[Any, Any, Any], scope: CloseableScope
    ) -> Effect[Context, Any, Any]:
        def body() -> Effect[Context, Any, Any]:
            if not layer._shared:
                return layer._builder(self, scope)
            existing = self._lookup(layer)
            if existing is not None:
                return existing.wait()
            deferred: Deferred[Context, Any] = Deferred()
            # Holding the layer keeps id(layer) from being reused mid-build.
            self._entries[id(layer)] = (layer, deferred)
            return layer._builder(self, scope).on_exit(deferred.done)

        return _Suspend(body)


class CurrentMemoMap(Tag[MemoMap]):
    """The memo map of the enclosing ``provide``. A nested ``provide`` forks
    it, so layers the outer one built are reused."""


def _build_with(
    layer: Layer[Any, Any, Any], memo: MemoMap, scope: CloseableScope
) -> Effect[Context, Any, Any]:
    building: Effect[Context, Any, Any] = _Locally(
        memo.get_or_build(layer, scope), lambda ctx: ctx.add(CurrentMemoMap, memo)
    )
    return building.map(lambda built: built.add(CurrentMemoMap, memo))


def _fork_or_create(ctx: Context) -> MemoMap:
    found, current = ctx.lookup(CurrentMemoMap)
    return current.fork() if found else MemoMap()


class Layer(Generic[ROut_contra, E_co, RIn_co]):
    __slots__ = ("_builder", "_shared")

    def __init__(self, builder: Builder, *, shared: bool = True) -> None:
        self._builder = builder
        self._shared = shared

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        return f(self)

    def build(self, scope: CloseableScope) -> Effect[Context, E_co, RIn_co]:
        """Build into ``scope``, reusing what an enclosing ``provide`` built.
        Mostly for runtimes; programs use ``provide``."""
        return _WithFiber(lambda fiber: _build_with(self, _fork_or_create(fiber._context), scope))


# --- constructors -------------------------------------------------------------


def succeed[S, T](tag: TagLike[S, T], service: S) -> Layer[T]:
    cls = tag_class(tag)
    ctx = Context({cls: service})
    return Layer(lambda _memo, _scope: _Succeed(ctx))


def sync[S, T](tag: TagLike[S, T], make: Callable[[], S]) -> Layer[T]:
    cls = tag_class(tag)
    return Layer(lambda _memo, _scope: _Sync(lambda: Context({cls: make()})))


@overload
def effect[S, T, E](tag: TagLike[S, T], make: Effect[S, E, Scope]) -> Layer[T, E]: ...
@overload
def effect[S, T, E = Never, R = Never](
    tag: TagLike[S, T], make: Effect[S, E, Scope | R]
) -> Layer[T, E, R]: ...
def effect(tag: TagLike[Any, Any], make: Effect[Any, Any, Any]) -> Layer[Any, Any, Any]:
    """Build a service with an effect. ``make`` may acquire resources
    (it runs with a ``Scope``); they are released with the layer."""
    cls = tag_class(tag)

    def builder(_memo: MemoMap, scope: CloseableScope) -> Effect[Context, Any, Any]:
        built: Effect[Any, Any, Any] = _Locally(make, lambda ctx: ctx.add(Scope, scope))
        return built.map(lambda service: Context({cls: service}))

    return Layer(builder)


empty: Layer[object] = Layer(lambda _memo, _scope: _Succeed(Context.empty()))
"""Builds nothing."""


def fresh[O, E, R](layer: Layer[O, E, R]) -> Layer[O, E, R]:
    """A copy of ``layer`` that is not shared: each use builds it, and
    everything under it, anew."""
    return Layer(lambda _memo, scope: MemoMap().get_or_build(layer, scope), shared=False)


# --- combining ------------------------------------------------------------------


@overload
def merge[O1, O2, EE = Never, RR = Never](
    l1: Layer[O1, EE, RR], l2: Layer[O2, EE, RR], /
) -> Layer[O1 | O2, EE, RR]: ...
@overload
def merge[O1, O2, O3, EE = Never, RR = Never](
    l1: Layer[O1, EE, RR], l2: Layer[O2, EE, RR], l3: Layer[O3, EE, RR], /
) -> Layer[O1 | O2 | O3, EE, RR]: ...
@overload
def merge[O1, O2, O3, O4, EE = Never, RR = Never](
    l1: Layer[O1, EE, RR], l2: Layer[O2, EE, RR], l3: Layer[O3, EE, RR], l4: Layer[O4, EE, RR], /
) -> Layer[O1 | O2 | O3 | O4, EE, RR]: ...
@overload
def merge[O1, O2, O3, O4, O5, EE = Never, RR = Never](
    l1: Layer[O1, EE, RR],
    l2: Layer[O2, EE, RR],
    l3: Layer[O3, EE, RR],
    l4: Layer[O4, EE, RR],
    l5: Layer[O5, EE, RR],
    /,
) -> Layer[O1 | O2 | O3 | O4 | O5, EE, RR]: ...
def merge(*layers: Layer[Any, Any, Any]) -> Layer[Any, Any, Any]:
    """Build all layers, concurrently, and provide everything they build.
    Their resources are released concurrently too."""

    def builder(memo: MemoMap, scope: CloseableScope) -> Effect[Context, Any, Any]:
        def build_each(parallel: CloseableScope) -> Effect[list[Context], Any, Any]:
            return for_each(
                layers,
                lambda layer: parallel.fork().flat_map(lambda own: memo.get_or_build(layer, own)),
                concurrency="unbounded",
            )

        return scope.fork("parallel").flat_map(build_each).map(_merge_contexts)

    return Layer(builder)


def _merge_contexts(contexts: list[Context]) -> Context:
    merged = Context.empty()
    for ctx in contexts:
        merged = merged.merge(ctx)
    return merged


def _feed(
    dep: Layer[Any, Any, Any], target: Layer[Any, Any, Any], *, keep_dep: bool
) -> Layer[Any, Any, Any]:
    def builder(memo: MemoMap, scope: CloseableScope) -> Effect[Context, Any, Any]:
        def body():
            dep_ctx = yield from memo.get_or_build(dep, scope)
            target_build: Effect[Context, Any, Any] = _Locally(
                memo.get_or_build(target, scope), lambda ctx: ctx.merge(dep_ctx)
            )
            ctx = yield from target_build
            return dep_ctx.merge(ctx) if keep_dep else ctx

        return _Gen(body)

    return Layer(builder)


def _provide_to_effect(
    layer: Layer[Any, Any, Any], eff: Effect[Any, Any, Any], *, local: bool
) -> Effect[Any, Any, Any]:
    def body(fiber: Fiber[Any, Any]) -> Effect[Any, Any, Any]:
        memo = MemoMap() if local else _fork_or_create(fiber._context)
        scope = CloseableScope()
        run: Effect[Any, Any, Any] = _build_with(layer, memo, scope).flat_map(
            lambda built: _Locally(eff, lambda ctx: ctx.merge(built))
        )
        return run.on_exit(scope.close)

    return _WithFiber(body)


class _Provide[RO, E2, RI]:
    __slots__ = ("layer",)

    def __init__(self, layer: Layer[RO, E2, RI]) -> None:
        self.layer = layer

    @overload
    def __call__[A, E = Never](self, target: Effect[A, E, RO]) -> Effect[A, E | E2, RI]: ...
    @overload
    def __call__[A, E = Never, R = Never](
        self, target: Effect[A, E, RO | R]
    ) -> Effect[A, E | E2, R | RI]: ...
    @overload
    def __call__[O, E = Never](self, target: Layer[O, E, RO]) -> Layer[O, E | E2, RI]: ...
    @overload
    def __call__[O, E = Never, R = Never](
        self, target: Layer[O, E, RO | R]
    ) -> Layer[O, E | E2, R | RI]: ...
    def __call__(self, target: Effect[Any, Any, Any] | Layer[Any, Any, Any]) -> Any:
        if isinstance(target, Layer):
            return _feed(self.layer, target, keep_dep=False)
        return _provide_to_effect(self.layer, target, local=False)


class _ProvideLocal[RO, E2, RI]:
    """``provide(layer, local=True)``: effects only. A layer target always
    builds in its caller's memo map."""

    __slots__ = ("layer",)

    def __init__(self, layer: Layer[RO, E2, RI]) -> None:
        self.layer = layer

    @overload
    def __call__[A, E = Never](self, target: Effect[A, E, RO]) -> Effect[A, E | E2, RI]: ...
    @overload
    def __call__[A, E = Never, R = Never](
        self, target: Effect[A, E, RO | R]
    ) -> Effect[A, E | E2, R | RI]: ...
    def __call__(self, target: Effect[Any, Any, Any]) -> Any:
        return _provide_to_effect(self.layer, target, local=True)


@overload
def provide[RO, E2 = Never, RI = Never](
    layer: Layer[RO, E2, RI], *, local: Literal[False] = False
) -> _Provide[RO, E2, RI]: ...
@overload
def provide[RO, E2 = Never, RI = Never](
    layer: Layer[RO, E2, RI], *, local: bool
) -> _ProvideLocal[RO, E2, RI]: ...
def provide(
    layer: Layer[Any, Any, Any], *, local: bool = False
) -> _Provide[Any, Any, Any] | _ProvideLocal[Any, Any, Any]:
    """Satisfy what ``layer`` builds, for an effect or another layer. Use
    with ``.pipe``. For a layer, the result builds only the target's
    services; ``provide_merge`` keeps both.

    For an effect, layers an enclosing ``provide`` already built are
    reused; ``local=True`` builds everything anew (effects only)."""
    return _ProvideLocal(layer) if local else _Provide(layer)


class _ProvideMerge[RO, E2, RI]:
    __slots__ = ("layer",)

    def __init__(self, layer: Layer[RO, E2, RI]) -> None:
        self.layer = layer

    @overload
    def __call__[O, E = Never](self, target: Layer[O, E, RO]) -> Layer[O | RO, E | E2, RI]: ...
    @overload
    def __call__[O, E = Never, R = Never](
        self, target: Layer[O, E, RO | R]
    ) -> Layer[O | RO, E | E2, R | RI]: ...
    def __call__(self, target: Layer[Any, Any, Any]) -> Layer[Any, Any, Any]:
        return _feed(self.layer, target, keep_dep=True)


def provide_merge[RO, E2 = Never, RI = Never](
    layer: Layer[RO, E2, RI],
) -> _ProvideMerge[RO, E2, RI]:
    """Like ``provide`` for layers, but the result builds both layers'
    services."""
    return _ProvideMerge(layer)
