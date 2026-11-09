"""``LayerRef[I, E]``: a layer built on first use and shared while in use.

The built services are cached in an ``RcRef``: ``context_effect()`` (or
building the ``get()`` layer) builds the layer once and holds it until the
caller's scope closes, and the last holder releases it, at once or after
``idle_time_to_live``. ``invalidate()`` forgets the build so the next use
rebuilds; ``refresh()`` also rebuilds now. ``preload=True`` builds when the
ref is made, and ``invalidation_schedule`` invalidates (with ``preload``,
refreshes) each time it recurs.

``LayerRefService[I, E]`` is a tag for a ``LayerRef``: subclass it, build
it with ``layer(...)``, and use ``get()``, ``context_effect()``,
``invalidate()`` and ``refresh()`` through the tag.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any, Literal, Never, Self, cast, overload

from pyfect._core import Effect, _Gen, _Succeed, _WithFiber
from pyfect._layer_core import Layer, effect_context, fork_or_create, require_layer
from pyfect._unsubscripted import Unsubscripted
from pyfect.context import Context, ServiceEffect, Tag
from pyfect.duration import Duration
from pyfect.layer import effect as layer_effect
from pyfect.layer import unwrap
from pyfect.rc_ref import RcRef
from pyfect.schedule import Schedule
from pyfect.scope import Scope, scoped


class LayerRef[I = Unsubscripted, E = Never]:
    """Make one with ``LayerRef.make(layer)`` inside a scope."""

    __slots__ = ("_layer", "rc_ref")

    def __init__(self, rc_ref: RcRef[Context[I], E]) -> None:
        self.rc_ref = rc_ref
        self._layer: Layer[I, E] = effect_context(rc_ref.get())

    @overload
    @classmethod
    def make[I2, X = Never, RR = Never](
        cls: type[LayerRef[Unsubscripted, Any]],
        layer: Layer[I2, X, RR],
        *,
        idle_time_to_live: Duration | None = None,
        preload: Literal[False] = False,
        invalidation_schedule: Schedule[object, object, object, RR] | None = None,
    ) -> Effect[LayerRef[I2, X], Never, Scope | RR]: ...
    @overload
    @classmethod
    def make[I2, X = Never, RR = Never](
        cls: type[LayerRef[Unsubscripted, Any]],
        layer: Layer[I2, X, RR],
        *,
        idle_time_to_live: Duration | None = None,
        preload: bool,
        invalidation_schedule: Schedule[object, object, object, RR] | None = None,
    ) -> Effect[LayerRef[I2, X], X, Scope | RR]: ...
    @overload
    @classmethod
    def make[RR = Never](
        cls,
        layer: Layer[I, E, RR],
        *,
        idle_time_to_live: Duration | None = None,
        preload: Literal[False] = False,
        invalidation_schedule: Schedule[object, object, object, RR] | None = None,
    ) -> Effect[LayerRef[I, E], Never, Scope | RR]: ...
    @overload
    @classmethod
    def make[RR = Never](
        cls,
        layer: Layer[I, E, RR],
        *,
        idle_time_to_live: Duration | None = None,
        preload: bool,
        invalidation_schedule: Schedule[object, object, object, RR] | None = None,
    ) -> Effect[LayerRef[I, E], E, Scope | RR]: ...
    @classmethod
    def make(
        cls,
        layer: Layer[Any, Any, Any],
        *,
        idle_time_to_live: Duration | None = None,
        preload: bool = False,
        invalidation_schedule: Schedule[object, object, object, Any] | None = None,
    ) -> Effect[LayerRef[Any, Any], Any, Any]:
        """A ref building ``layer`` (with the services in scope now, sharing
        what enclosing builds built) when first used. Released when the
        current scope closes."""
        require_layer(layer, "layer")

        def body():
            context: Context = yield from _WithFiber(lambda fiber: _Succeed(fiber._context))
            memo_map = fork_or_create(context)
            build: Effect[Context, Any, Any] = Scope().flat_map(
                lambda scope: layer.build_with_memo_map(memo_map, scope)
            )
            rc_ref = yield from RcRef.make(build, idle_time_to_live=idle_time_to_live)
            ref: LayerRef[Any, Any] = LayerRef(rc_ref)
            if preload:
                yield from ref.refresh()
            if invalidation_schedule is not None:
                on_recur = ref.refresh() if preload else ref.invalidate()
                yield from on_recur.ignore_cause().schedule(invalidation_schedule).fork_scoped()
            return ref

        return _Gen(body)

    def get(self) -> Layer[I, E]:
        """A layer giving the cached services, building them if needed."""
        return self._layer

    def context_effect(self) -> Effect[Context[I], E, Scope]:
        """The cached services, built if needed and held until the current
        scope closes."""
        return self.rc_ref.get()

    def invalidate(self) -> Effect[None]:
        """Forget the build, so the next use rebuilds the layer."""
        return self.rc_ref.invalidate()

    def refresh(self) -> Effect[None, E]:
        """Forget the build and build the layer again now."""
        return self.invalidate().and_then(scoped(self.rc_ref.get())).as_void()

    def __repr__(self) -> str:
        return f"LayerRef({self.rc_ref!r})"


class LayerRefService[I, E = Never](Tag[LayerRef[I, E]], base=True):
    """A tag for a ``LayerRef`` building the services ``I``::

    class Database(LayerRefService[Connection, DbError]): ...

    DatabaseLive = Database.layer(connection_layer, idle_time_to_live="1 minute")
    """

    @overload
    @classmethod
    def layer[RR = Never](
        cls,
        layer: Layer[I, E, RR],
        *,
        idle_time_to_live: Duration | None = None,
        preload: Literal[False] = False,
        invalidation_schedule: Schedule[object, object, object, RR] | None = None,
    ) -> Layer[Self, Never, RR]: ...
    @overload
    @classmethod
    def layer[RR = Never](
        cls,
        layer: Layer[I, E, RR],
        *,
        idle_time_to_live: Duration | None = None,
        preload: bool,
        invalidation_schedule: Schedule[object, object, object, RR] | None = None,
    ) -> Layer[Self, E, RR]: ...
    @classmethod
    def layer(
        cls,
        layer: Layer[I, E, Any],
        *,
        idle_time_to_live: Duration | None = None,
        preload: bool = False,
        invalidation_schedule: Schedule[object, object, object, Any] | None = None,
    ) -> Layer[Self, Any, Any]:
        """A layer making the ``LayerRef`` (see ``LayerRef.make``). Provide
        its dependencies with ``.pipe(provide(...))``."""
        require_layer(layer, "layer")
        return layer_effect(
            cls,
            LayerRef.make(
                layer,
                idle_time_to_live=idle_time_to_live,
                preload=preload,
                invalidation_schedule=invalidation_schedule,
            ),
        )

    @classmethod
    def _service(cls) -> ServiceEffect[LayerRef[I, E], Self]:
        return ServiceEffect(cls)

    @classmethod
    def get(cls) -> Layer[I, E, Self]:
        """A layer giving the cached services, through this tag."""
        # Pyright can't solve ``unwrap``'s overloads against ``Self``.
        layer_of: Effect[Any, Any, Any] = cls._service().map(lambda ref: ref.get())
        return cast("Layer[I, E, Self]", unwrap(layer_of))

    @classmethod
    def context_effect(cls) -> Effect[Context[I], E, Scope | Self]:
        return cls._service().flat_map(lambda ref: ref.context_effect())

    @classmethod
    def invalidate(cls) -> Effect[None, Never, Self]:
        return cls._service().flat_map(lambda ref: ref.invalidate())

    @classmethod
    def refresh(cls) -> Effect[None, E, Self]:
        return cls._service().flat_map(lambda ref: ref.refresh())


__all__ = ["LayerRef", "LayerRefService"]
