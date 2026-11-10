"""``LayerMap[K, I, E]``: layers built by key and shared while in use.

``LayerMap.make(lookup)`` builds ``lookup(key)`` the first time a key is
used and caches the services in an ``RcMap``: they are shared while any
scope holds them and released when the last one closes, at once or after
``idle_time_to_live``. ``from_record`` takes a fixed mapping of layers.
Preloaded keys are built when the map is made and kept for their idle time
to live (keys whose time to live is 0, the default, are not preloaded).

``LayerMapService[K, I, E]`` is a tag for a ``LayerMap``: subclass it,
build it with ``layer(...)`` or ``layer_from_record(...)``, and use
``get(key)``, ``context_effect(key)``, ``context_effect_option(key)`` and
``invalidate(key)`` through the tag.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Mapping
from typing import Any, Literal, Never, Self, cast, overload

from pyfect._core import Effect, _Gen, _Succeed, _WithFiber
from pyfect._layer_core import Layer, effect_context, fork_or_create
from pyfect._unsubscripted import Unsubscripted
from pyfect.context import Context, ServiceEffect, Tag
from pyfect.layer import effect as layer_effect
from pyfect.layer import unwrap
from pyfect.option import Option
from pyfect.rc_map import IdleTimeToLive, RcMap
from pyfect.scope import Scope, scoped


class LayerMap[K: Hashable = Unsubscripted, I = Unsubscripted, E = Never]:
    """Make one with ``LayerMap.make(lookup)`` or ``LayerMap.from_record``
    inside a scope."""

    __slots__ = ("rc_map",)

    def __init__(self, rc_map: RcMap[K, Context[I], E]) -> None:
        self.rc_map = rc_map

    @overload
    @classmethod
    def make[K2: Hashable, I2, X = Never, R = Never](
        cls: type[LayerMap[Unsubscripted, Unsubscripted, Any]],
        lookup: Callable[[K2], Layer[I2, X, R]],
        *,
        idle_time_to_live: IdleTimeToLive[K2] | None = None,
        preload_keys: None = None,
    ) -> Effect[LayerMap[K2, I2, X], Never, Scope | R]: ...
    @overload
    @classmethod
    def make[K2: Hashable, I2, X = Never, R = Never](
        cls: type[LayerMap[Unsubscripted, Unsubscripted, Any]],
        lookup: Callable[[K2], Layer[I2, X, R]],
        *,
        idle_time_to_live: IdleTimeToLive[K2] | None = None,
        preload_keys: Iterable[K2],
    ) -> Effect[LayerMap[K2, I2, X], X, Scope | R]: ...
    @overload
    @classmethod
    def make[R = Never](
        cls,
        lookup: Callable[[K], Layer[I, E, R]],
        *,
        idle_time_to_live: IdleTimeToLive[K] | None = None,
        preload_keys: None = None,
    ) -> Effect[LayerMap[K, I, E], Never, Scope | R]: ...
    @overload
    @classmethod
    def make[R = Never](
        cls,
        lookup: Callable[[K], Layer[I, E, R]],
        *,
        idle_time_to_live: IdleTimeToLive[K] | None = None,
        preload_keys: Iterable[K],
    ) -> Effect[LayerMap[K, I, E], E, Scope | R]: ...
    @classmethod
    def make(
        cls,
        lookup: Callable[[Any], Layer[Any, Any, Any]],
        *,
        idle_time_to_live: IdleTimeToLive[Any] | None = None,
        preload_keys: Iterable[Any] | None = None,
    ) -> Effect[LayerMap[Any, Any, Any], Any, Any]:
        """A map building ``lookup(key)`` per key (with the services in scope
        now, sharing what enclosing builds built). Released when the
        current scope closes."""

        def body():
            context: Context = yield from _WithFiber(lambda fiber: _Succeed(fiber._context))
            memo_map = fork_or_create(context)

            def build(key: Any) -> Effect[Context, Any, Any]:
                return Scope().flat_map(
                    lambda scope: lookup(key).build_with_memo_map(memo_map, scope)
                )

            rc_map = yield from RcMap.make(build, idle_time_to_live=idle_time_to_live)
            for key in preload_keys or ():
                if rc_map._idle_time_to_live(key) != 0:
                    yield from scoped(rc_map.get(key))
            return LayerMap(rc_map)

        return _Gen(body)

    @overload
    @classmethod
    def from_record[K2: Hashable, I2, X = Never, R = Never](
        cls: type[LayerMap[Unsubscripted, Unsubscripted, Any]],
        layers: Mapping[K2, Layer[I2, X, R]],
        *,
        idle_time_to_live: IdleTimeToLive[K2] | None = None,
        preload: Literal[False] = False,
    ) -> Effect[LayerMap[K2, I2, X], Never, Scope | R]: ...
    @overload
    @classmethod
    def from_record[K2: Hashable, I2, X = Never, R = Never](
        cls: type[LayerMap[Unsubscripted, Unsubscripted, Any]],
        layers: Mapping[K2, Layer[I2, X, R]],
        *,
        idle_time_to_live: IdleTimeToLive[K2] | None = None,
        preload: bool,
    ) -> Effect[LayerMap[K2, I2, X], X, Scope | R]: ...
    @overload
    @classmethod
    def from_record[R = Never](
        cls,
        layers: Mapping[K, Layer[I, E, R]],
        *,
        idle_time_to_live: IdleTimeToLive[K] | None = None,
        preload: Literal[False] = False,
    ) -> Effect[LayerMap[K, I, E], Never, Scope | R]: ...
    @overload
    @classmethod
    def from_record[R = Never](
        cls,
        layers: Mapping[K, Layer[I, E, R]],
        *,
        idle_time_to_live: IdleTimeToLive[K] | None = None,
        preload: bool,
    ) -> Effect[LayerMap[K, I, E], E, Scope | R]: ...
    @classmethod
    def from_record(
        cls,
        layers: Mapping[Any, Layer[Any, Any, Any]],
        *,
        idle_time_to_live: IdleTimeToLive[Any] | None = None,
        preload: bool = False,
    ) -> Effect[LayerMap[Any, Any, Any], Any, Any]:
        """``make`` over a fixed mapping of layers; ``preload`` preloads
        every key."""
        return LayerMap.make(
            layers.__getitem__,
            idle_time_to_live=idle_time_to_live,
            preload_keys=list(layers) if preload else None,
        )

    def get(self, key: K) -> Layer[I, E]:
        """A layer giving the services for ``key``, building them if needed."""
        return effect_context(self.rc_map.get(key))

    def context_effect(self, key: K) -> Effect[Context[I], E, Scope]:
        """The services for ``key``, built if needed and held until the
        current scope closes."""
        return self.rc_map.get(key)

    def context_effect_option(self, key: K) -> Effect[Option[Context[I]], E, Scope]:
        """The services for ``key`` if they are cached (or being built), held
        until the current scope closes; ``None`` otherwise, without
        building anything."""
        return self.rc_map.get_option(key)

    def invalidate(self, key: K) -> Effect[None]:
        """Forget ``key``'s services, so the next use rebuilds them."""
        return self.rc_map.invalidate(key)

    def __repr__(self) -> str:
        return f"LayerMap({self.rc_map!r})"


class LayerMapService[K: Hashable, I, E = Never](Tag[LayerMap[K, I, E]], base=True):
    """A tag for a ``LayerMap`` from ``K`` to the services ``I``::

    class Tenants(LayerMapService[str, Database]): ...

    TenantsLive = Tenants.layer(tenant_database, idle_time_to_live="1 minute")
    """

    @overload
    @classmethod
    def layer[R = Never](
        cls,
        lookup: Callable[[K], Layer[I, E, R]],
        *,
        idle_time_to_live: IdleTimeToLive[K] | None = None,
        preload_keys: None = None,
    ) -> Layer[Self, Never, R]: ...
    @overload
    @classmethod
    def layer[R = Never](
        cls,
        lookup: Callable[[K], Layer[I, E, R]],
        *,
        idle_time_to_live: IdleTimeToLive[K] | None = None,
        preload_keys: Iterable[K],
    ) -> Layer[Self, E, R]: ...
    @classmethod
    def layer(
        cls,
        lookup: Callable[[K], Layer[I, E, Any]],
        *,
        idle_time_to_live: IdleTimeToLive[K] | None = None,
        preload_keys: Iterable[K] | None = None,
    ) -> Layer[Self, Any, Any]:
        """A layer making the ``LayerMap`` (see ``LayerMap.make``). Provide
        its dependencies with ``.pipe(provide(...))``."""
        made: Effect[Any, Any, Any] = LayerMap.make(
            lookup, idle_time_to_live=idle_time_to_live, preload_keys=preload_keys
        )
        return layer_effect(cls, made)

    @overload
    @classmethod
    def layer_from_record[R = Never](
        cls,
        layers: Mapping[K, Layer[I, E, R]],
        *,
        idle_time_to_live: IdleTimeToLive[K] | None = None,
        preload: Literal[False] = False,
    ) -> Layer[Self, Never, R]: ...
    @overload
    @classmethod
    def layer_from_record[R = Never](
        cls,
        layers: Mapping[K, Layer[I, E, R]],
        *,
        idle_time_to_live: IdleTimeToLive[K] | None = None,
        preload: bool,
    ) -> Layer[Self, E, R]: ...
    @classmethod
    def layer_from_record(
        cls,
        layers: Mapping[K, Layer[I, E, Any]],
        *,
        idle_time_to_live: IdleTimeToLive[K] | None = None,
        preload: bool = False,
    ) -> Layer[Self, Any, Any]:
        """A layer making the ``LayerMap`` with ``LayerMap.from_record``."""
        made: Effect[Any, Any, Any] = LayerMap.from_record(
            layers, idle_time_to_live=idle_time_to_live, preload=preload
        )
        return layer_effect(cls, made)

    @classmethod
    def _service(cls) -> ServiceEffect[LayerMap[K, I, E], Self]:
        return ServiceEffect(cls)

    @classmethod
    def get(cls, key: K) -> Layer[I, E, Self]:
        """A layer giving the services for ``key``, through this tag."""
        # Pyright can't solve ``unwrap``'s overloads against ``Self``.
        layer_of: Effect[Any, Any, Any] = cls._service().map(lambda m: m.get(key))
        return cast("Layer[I, E, Self]", unwrap(layer_of))

    @classmethod
    def context_effect(cls, key: K) -> Effect[Context[I], E, Scope | Self]:
        return cls._service().flat_map(lambda m: m.context_effect(key))

    @classmethod
    def context_effect_option(cls, key: K) -> Effect[Option[Context[I]], E, Scope | Self]:
        return cls._service().flat_map(lambda m: m.context_effect_option(key))

    @classmethod
    def invalidate(cls, key: K) -> Effect[None, Never, Self]:
        return cls._service().flat_map(lambda m: m.invalidate(key))


__all__ = ["LayerMap", "LayerMapService"]
