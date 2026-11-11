"""Layers: recipes for building services.

``Layer[ROut, E, RIn]`` builds the services ``ROut``, may fail with ``E``,
and needs the services ``RIn`` to do it.

- Layers are shared by identity: a layer used in several places is built
  once, and a nested ``provide`` reuses what an enclosing one built. Keep
  layers in module-level constants. ``fresh(layer)`` and
  ``provide(layer, local=True)`` opt out.
- Resources a layer acquires (``acquire_release`` in its ``make``) are
  released when the last scope using it closes: for ``provide``, when the
  effect it was provided to finishes.
- ``merge`` builds, and releases, its layers concurrently.

``provide`` works on effects and on layers, and removes exactly what the
layer builds from ``R``, leaving the rest::

    program.pipe(provide(DatabaseLive))         # Effect, minus Database
    UsersLive.pipe(provide(DatabaseLive))       # Layer, its needs satisfied

Layer methods add to a layer (``build``, ``tap``, ``catch_all``, ...);
``catch_tag`` removes errors, so it is a function for ``.pipe``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Literal, Never, Protocol, cast, overload

from pyfect._concurrency import for_each
from pyfect._context_effects import _ProvideContext, provide_context
from pyfect._core import (
    Effect,
    _catching_if,
    _FailCause,
    _Locally,
    _MatchCause,
    _Succeed,
    _Suspend,
    _WithFiber,
)
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect._layer_core import (
    CurrentMemoMap,
    Layer,
    MemoMap,
    effect_context,
    feed,
    fork_or_create,
    from_build,
    from_build_memo,
    require_layer,
    require_layers,
)
from pyfect._layer_tracing import parent_span, span
from pyfect._tags import Tags
from pyfect.cause import Cause
from pyfect.cause import die as die_cause
from pyfect.context import Context, Provides, Tag, _Holding, tag_class
from pyfect.effect import sync as sync_effect
from pyfect.scope import CloseableScope, Scope

__all__ = [
    "CurrentMemoMap",
    "Layer",
    "MemoMap",
    "UnimplementedError",
    "catch_all",
    "catch_tag",
    "effect",
    "effect_context",
    "effect_discard",
    "empty",
    "fresh",
    "from_build",
    "from_build_memo",
    "merge",
    "mock",
    "parent_span",
    "provide",
    "provide_context",
    "provide_merge",
    "span",
    "succeed",
    "succeed_context",
    "suspend",
    "sync",
    "sync_context",
    "unwrap",
]

# --- constructors -------------------------------------------------------------


def succeed[S, T](tag: Provides[S, T], service: S) -> Layer[T]:
    """Provide ``service``. Not shared: there is nothing to build."""
    return succeed_context(Context.make(tag, service))


def succeed_context[A](ctx: Context[A]) -> Layer[A]:
    """Provide every service of ``ctx``."""
    built: Effect[Context] = _Succeed(ctx)
    return Layer(lambda _memo, _scope: built)


empty: Layer[Never] = succeed_context(Context.empty())
"""Builds nothing."""


def sync[S, T](tag: Provides[S, T], make: Callable[[], S]) -> Layer[T]:
    """Provide ``make()``, called once per build."""
    return sync_context(lambda: Context.make(tag, make()))


def sync_context[A](make: Callable[[], Context[A]]) -> Layer[A]:
    """Provide every service of ``make()``, called once per build."""
    built: Effect[Context] = sync_effect(make)
    return from_build_memo(lambda _memo, _scope: built)


@overload
def effect[S, T, E](tag: Provides[S, T], make: Effect[S, E, Scope]) -> Layer[T, E]: ...
@overload
def effect[S, T, E = Never, R = Never](
    tag: Provides[S, T], make: Effect[S, E, Scope | R]
) -> Layer[T, E, R]: ...
def effect(tag: Provides[Any, Any], make: Effect[Any, Any, Any]) -> Layer[Any, Any, Any]:
    """Build a service with an effect. ``make`` may acquire resources
    (it runs with a ``Scope``); they are released with the layer."""
    require_effect(make, "make")
    return effect_context(make.map(lambda service: Context.make(tag, service)))


@overload
def effect_discard[E](make: Effect[object, E, Scope]) -> Layer[Never, E]: ...
@overload
def effect_discard[E = Never, R = Never](
    make: Effect[object, E, Scope | R],
) -> Layer[Never, E, R]: ...
def effect_discard(make: Effect[object, Any, Any]) -> Layer[Any, Any, Any]:
    """Run ``make`` for its effects (and resources) when the layer builds.
    Builds no services."""
    require_effect(make, "make")
    return effect_context(make.as_(Context.empty()))


def suspend[O, E = Never, R = Never](make: Callable[[], Layer[O, E, R]]) -> Layer[O, E, R]:
    """The layer ``make()`` returns, made when building. Shared like any
    other layer, so ``make`` runs once per build."""
    return from_build_memo(lambda memo, scope: _Suspend(lambda: make()._build(memo, scope)))


class _Unwrapped(Tag[Layer[Any, Any, Any]]):
    """Carries the layer ``unwrap``'s effect makes."""


@overload
def unwrap[O, EE](eff: Effect[Layer[O, EE], EE, Scope]) -> Layer[O, EE]: ...
@overload
def unwrap[O, EE = Never, RR = Never](
    eff: Effect[Layer[O, EE, RR], EE, Scope | RR],
) -> Layer[O, EE, RR]: ...
def unwrap(eff: Effect[Layer[Any, Any, Any], Any, Any]) -> Layer[Any, Any, Any]:
    """Build the layer that ``eff`` makes. ``eff`` runs once per build, in
    the layer's scope."""
    require_effect(eff, "eff")
    holder: Layer[_Unwrapped, Any, Any] = effect(_Unwrapped, eff)
    return holder.flat_map(lambda ctx: ctx.get(_Unwrapped))


def fresh[O, E, R](layer: Layer[O, E, R]) -> Layer[O, E, R]:
    """A copy of ``layer`` that is not shared: each use builds it, and
    everything under it, anew."""
    require_layer(layer, "layer")
    return Layer(lambda _memo, scope: layer._build(MemoMap(), scope))


class UnimplementedError(Exception):
    """A defect: a mocked service was used for a member the mock lacks."""


def mock[S, T](tag: Provides[S, T], /, **members: object) -> Layer[T]:
    """Provide a service made of ``members``. Any other attribute is an
    effect that dies with ``UnimplementedError``, and a function returning
    that effect, so a test mocks only what it uses."""
    return succeed(tag, _Mock(tag_class(tag).key, members))  # pyright: ignore[reportArgumentType]


class _Mock:
    __slots__ = ("_key", "_members")

    def __init__(self, key: str, members: Mapping[str, object]) -> None:
        self._key = key
        self._members = dict(members)

    def __getattr__(self, name: str) -> object:
        # Python's protocols (copy, pickle, inspect) probe dunders.
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        if name in self._members:
            return self._members[name]
        return _Unimplemented(UnimplementedError(f'{self._key}: Unimplemented method "{name}"'))


class _Unimplemented(Effect[Never]):
    """Dies with its error; calling it gives itself, so it stands in for an
    effect member and for a method returning one."""

    __slots__ = ("error",)

    def __init__(self, error: UnimplementedError) -> None:
        self.error = error

    def __call__(self, *_args: object, **_kwargs: object) -> Effect[Never]:
        return self

    def _step(self, fiber: Fiber[Any, Any]) -> Effect[Never]:
        return _FailCause(die_cause(self.error))


# --- combining ------------------------------------------------------------------


class _Builds[O, E, R](Protocol):
    """A layer building ``O``, matched covariantly: ``_Builds[Never, ...]``
    is a layer that builds nothing, which ``Layer[Never]`` cannot say (every
    layer is one, its services being contravariant). ``merge`` takes those
    first, as two separately solved ``Never`` services join to ``Unknown``
    (``research/typing/workflow_2_exact_schemas.py``). Keep ``O`` a
    parameter: pyright caches a failed match of a non-generic protocol
    against ``Layer`` and then rejects ``Layer[Never]`` too."""

    def build_with_scope(self, scope: CloseableScope, /) -> Effect[_Holding[O], E, R]: ...


@overload
def merge[EE = Never, RR = Never](
    l1: _Builds[Never, EE, RR], l2: _Builds[Never, EE, RR], /
) -> Layer[Never, EE, RR]: ...
@overload
def merge[EE = Never, RR = Never](
    l1: _Builds[Never, EE, RR], l2: _Builds[Never, EE, RR], l3: _Builds[Never, EE, RR], /
) -> Layer[Never, EE, RR]: ...
@overload
def merge[EE = Never, RR = Never](
    l1: _Builds[Never, EE, RR],
    l2: _Builds[Never, EE, RR],
    l3: _Builds[Never, EE, RR],
    l4: _Builds[Never, EE, RR],
    /,
) -> Layer[Never, EE, RR]: ...
@overload
def merge[EE = Never, RR = Never](
    l1: _Builds[Never, EE, RR],
    l2: _Builds[Never, EE, RR],
    l3: _Builds[Never, EE, RR],
    l4: _Builds[Never, EE, RR],
    l5: _Builds[Never, EE, RR],
    /,
) -> Layer[Never, EE, RR]: ...
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
@overload
def merge[O, EE = Never, RR = Never](
    first: _Builds[O, EE, RR], /, *rest: _Builds[O, EE, RR]
) -> Layer[O, EE, RR]: ...
def merge(*layers: _Builds[Any, Any, Any] | Layer[Any, Any, Any]) -> Layer[Any, Any, Any]:
    """Build all layers, concurrently, and provide everything they build
    (Effect's ``mergeAll``, which takes any number of layers). Their
    resources are released concurrently too."""
    require_layers(layers, "layers")
    built_layers = cast("tuple[Layer[Any, Any, Any], ...]", layers)

    def build(memo: MemoMap, scope: CloseableScope) -> Effect[Context, Any, Any]:
        parallel = scope.fork_unsafe("parallel")
        built = for_each(
            built_layers,
            lambda layer: layer._build(memo, parallel.fork_unsafe()),
            concurrency="unbounded",
        )
        return built.map(lambda contexts: Context.merge_all(*contexts))

    return from_build_memo(build)


def _provide_to_effect(
    layer: Layer[Any, Any, Any], eff: Effect[Any, Any, Any], *, local: bool
) -> Effect[Any, Any, Any]:
    def body(fiber: Fiber[Any, Any]) -> Effect[Any, Any, Any]:
        memo = MemoMap() if local else fork_or_create(fiber._context)
        scope = CloseableScope()
        run: Effect[Any, Any, Any] = layer.build_with_memo_map(memo, scope).flat_map(
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
            return feed(self.layer, target, keep_dep=False)
        require_effect(target, "target")
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
        require_effect(target, "target")
        return _provide_to_effect(self.layer, target, local=True)


@overload
def provide[RO](source: Context[RO], /) -> _ProvideContext[RO]: ...
@overload
def provide[RO, E2 = Never, RI = Never](
    source: Layer[RO, E2, RI], /, *, local: Literal[False] = False
) -> _Provide[RO, E2, RI]: ...
@overload
def provide[RO, E2 = Never, RI = Never](
    source: Layer[RO, E2, RI], /, *, local: bool
) -> _ProvideLocal[RO, E2, RI]: ...
def provide(
    source: Layer[Any, Any, Any] | Context[Any], /, *, local: bool = False
) -> _Provide[Any, Any, Any] | _ProvideLocal[Any, Any, Any] | _ProvideContext[Any]:
    """Satisfy what a layer builds, for an effect or another layer, or
    provide a context's services to an effect. Use with ``.pipe``. For a
    layer target, the result builds only the target's services;
    ``provide_merge`` keeps both.

    For an effect, layers an enclosing ``provide`` already built are
    reused; ``local=True`` builds everything anew (effects only)."""
    if isinstance(source, Context):
        return _ProvideContext(source)
    require_layer(source, "source", "a Layer or a Context")
    return _ProvideLocal(source) if local else _Provide(source)


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
        require_layer(target, "target")
        return feed(self.layer, target, keep_dep=True)


def provide_merge[RO, E2 = Never, RI = Never](
    layer: Layer[RO, E2, RI],
) -> _ProvideMerge[RO, E2, RI]:
    """Like ``provide`` for layers, but the result builds both layers'
    services."""
    require_layer(layer, "layer")
    return _ProvideMerge(layer)


# --- recovery that removes errors -------------------------------------------------


type _Handler = Callable[[MemoMap, CloseableScope], Callable[[Cause[Any]], Effect[Any, Any, Any]]]


class _CatchTag[EC, O, E2, R2]:
    """Removes ``EC`` from a layer's errors."""

    __slots__ = ("handle",)

    def __init__(self, handle: _Handler) -> None:
        self.handle = handle

    @overload
    def __call__[R = Never](self, target: Layer[O, EC, R]) -> Layer[O, E2, R | R2]: ...
    @overload
    def __call__[R = Never, ER = Never](
        self, target: Layer[O, EC | ER, R]
    ) -> Layer[O, ER | E2, R | R2]: ...
    def __call__(self, target: Layer[Any, Any, Any]) -> Layer[Any, Any, Any]:
        require_layer(target, "target")
        handle = self.handle
        return Layer(
            lambda memo, scope: _MatchCause(target._build(memo, scope), handle(memo, scope), None)
        )


class _CatchEvery[O, E, E2, R2]:
    """Handles every typed error ``E`` of a layer's build."""

    __slots__ = ("f",)

    def __init__(self, f: Callable[[E], Layer[O, E2, R2]]) -> None:
        self.f = f

    def __call__[R = Never](self, target: Layer[O, E, R]) -> Layer[O, E2, R | R2]:
        require_layer(target, "target")
        return target.catch_all(self.f)


def catch_all[O, E, E2 = Never, R2 = Never](
    f: Callable[[E], Layer[O, E2, R2]],
) -> _CatchEvery[O, E, E2, R2]:
    """``target.catch_all(f)`` for ``.pipe`` (Effect's ``Layer.catch``):
    build ``f(error)`` instead when the build fails with any typed error.
    Annotate ``f``'s parameter (a ``def``): pyright checks it covers every
    error."""
    return _CatchEvery(f)


def catch_tag[T, O, E2 = Never, R2 = Never](
    tag: Tags[T], f: Callable[[T], Layer[O, E2, R2]]
) -> _CatchTag[T, O, E2, R2]:
    """Build ``f(error)`` instead when the build fails with an instance of
    ``tag`` (a class or a tuple of classes), and remove those errors::

    LayerLive.pipe(layer.catch_tag(ConnectError, lambda e: Fallback))

    The result builds what the fallback builds, which the layer must build
    too (pyright can't spell Effect's ``ROut & ROut2``; the ``catch_all``
    method keeps the layer's services instead)."""
    return _CatchTag[Any, Any, Any, Any](
        lambda memo, scope: _catching_if(
            lambda e: isinstance(e, tag), lambda e: f(e)._build(memo, scope), None
        )
    )
