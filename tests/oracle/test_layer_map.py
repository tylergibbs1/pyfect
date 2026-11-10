"""Ports of Effect's ``LayerMap.test.ts``.

Each test's docstring is the Effect test title. ``Scope.provide(scope)`` is
``provide_service(fx.Scope, scope)``, and ``LayerMap.Service<Self>()(id,
options)`` is a ``LayerMapService[K, I]`` subclass built with ``layer(lookup,
...)`` or ``layer_from_record(layers, ...)``. Durations are seconds.
"""

import math
from typing import Never

import pyfect as fx
from pyfect import layer, testing
from pyfect.duration import millis


def make_layer(key: str, acquired: list[str], released: list[str]) -> fx.Layer[Never]:
    return layer.effect_discard(
        fx.acquire_release(
            fx.sync(lambda: acquired.append(key)),
            lambda _a, _e: fx.sync(lambda: released.append(key)),
        )
    )


def _short_or_long(key: str) -> float:
    return millis(500) if key.startswith("short:") else millis(2000)


def _record_ttl(key: str) -> float:
    return millis(500) if key == "short" else millis(2000)


@testing.effect
def test_context_effect_option_does_not_build_missing_entries_and_returns_existing_entries():
    """contextEffectOption does not build missing entries and returns existing entries"""
    acquired: list[str] = []

    def lookup(key: str) -> fx.Layer[Never]:
        return layer.effect_discard(fx.sync(lambda: acquired.append(key)))

    layer_map = yield from fx.LayerMap.make(lookup)

    assert (yield from layer_map.context_effect_option("key")) is None
    assert acquired == []

    owner_scope = fx.CloseableScope()
    borrower_scope = fx.CloseableScope()
    yield from layer_map.context_effect("key").pipe(fx.provide_service(fx.Scope, owner_scope))
    cached = yield from layer_map.context_effect_option("key").pipe(
        fx.provide_service(fx.Scope, borrower_scope)
    )
    assert isinstance(cached, fx.Some)
    assert acquired == ["key"]

    yield from owner_scope.close(fx.Success(None))
    yield from borrower_scope.close(fx.Success(None))


class _OptionMap(fx.LayerMapService[str, Never]): ...


@testing.effect
def test_service_context_effect_option_does_not_build_missing_entries_and_returns_existing_entries():  # noqa: E501
    """Service contextEffectOption does not build missing entries and returns existing entries"""
    acquired: list[str] = []

    def lookup(key: str) -> fx.Layer[Never]:
        return layer.effect_discard(fx.sync(lambda: acquired.append(key)))

    @fx.gen
    def program():
        assert (yield from _OptionMap.context_effect_option("key")) is None
        assert acquired == []

        owner_scope = fx.CloseableScope()
        borrower_scope = fx.CloseableScope()
        yield from _OptionMap.context_effect("key").pipe(fx.provide_service(fx.Scope, owner_scope))
        cached = yield from _OptionMap.context_effect_option("key").pipe(
            fx.provide_service(fx.Scope, borrower_scope)
        )
        assert isinstance(cached, fx.Some)
        assert acquired == ["key"]

        yield from owner_scope.close(fx.Success(None))
        yield from borrower_scope.close(fx.Success(None))

    yield from program.pipe(fx.provide(_OptionMap.layer(lookup)))


@testing.effect
def test_make_does_not_preload_with_the_default_idle_ttl():
    """make does not preload with the default idle TTL"""
    acquired: list[str] = []
    released: list[str] = []

    def lookup(key: str) -> fx.Layer[Never]:
        return make_layer(key, acquired, released)

    yield from fx.LayerMap.make(lookup, preload_keys=["a", "b"])
    assert acquired == []
    assert released == []


@testing.effect
def test_make_preloads_only_keys_with_non_zero_idle_ttl():
    """make preloads only keys with non-zero idle TTL"""
    acquired: list[str] = []
    released: list[str] = []

    def lookup(key: str) -> fx.Layer[Never]:
        return make_layer(key, acquired, released)

    def ttl(key: str) -> float:
        return 0 if key == "zero" else millis(1000) if key == "finite" else math.inf

    layer_map = yield from fx.LayerMap.make(
        lookup, preload_keys=["zero", "finite", "infinite"], idle_time_to_live=ttl
    )
    assert acquired == ["finite", "infinite"]
    assert released == []
    yield from fx.scoped(layer_map.context_effect("finite"))
    assert acquired == ["finite", "infinite"]
    yield from testing.adjust("999 millis")
    assert released == []
    yield from testing.adjust("1 millis")
    assert released == ["finite"]
    yield from fx.scoped(layer_map.context_effect("infinite"))
    assert acquired == ["finite", "infinite"]
    assert released == ["finite"]


@testing.effect
def test_make_fails_construction_when_a_non_zero_ttl_preload_fails():
    """make fails construction when a non-zero TTL preload fails"""

    def lookup(key: str) -> fx.Layer[Never, str]:
        return layer.effect_discard(fx.fail(key))

    ex = yield from fx.LayerMap.make(
        lookup, preload_keys=["broken"], idle_time_to_live="1 second"
    ).exit()
    assert isinstance(ex, fx.Failure)


@testing.effect
def test_make_supports_dynamic_idle_time_to_live():
    """make supports dynamic idleTimeToLive"""
    acquired: list[str] = []
    released: list[str] = []

    def lookup(key: str) -> fx.Layer[Never]:
        return make_layer(key, acquired, released)

    layer_map = yield from fx.LayerMap.make(lookup, idle_time_to_live=_short_or_long)

    yield from fx.scoped(layer_map.context_effect("short:a"))
    yield from fx.scoped(layer_map.context_effect("long:b"))
    assert acquired == ["short:a", "long:b"]
    assert released == []

    yield from testing.adjust("500 millis")
    assert released == ["short:a"]

    yield from testing.adjust("1500 millis")
    assert released == ["short:a", "long:b"]


@testing.effect
def test_from_record_supports_dynamic_idle_time_to_live():
    """fromRecord supports dynamic idleTimeToLive"""
    acquired: list[str] = []
    released: list[str] = []
    layers = {
        "short": make_layer("short", acquired, released),
        "long": make_layer("long", acquired, released),
    }
    layer_map = yield from fx.LayerMap.from_record(layers, idle_time_to_live=_record_ttl)

    yield from fx.scoped(layer_map.context_effect("short"))
    yield from fx.scoped(layer_map.context_effect("long"))
    assert acquired == ["short", "long"]
    assert released == []

    yield from testing.adjust("500 millis")
    assert released == ["short"]

    yield from testing.adjust("1500 millis")
    assert released == ["short", "long"]


class _LookupMap(fx.LayerMapService[str, Never]): ...


class _RecordMap(fx.LayerMapService[str, Never]): ...


@testing.effect
def test_service_supports_dynamic_idle_time_to_live():
    """Service supports dynamic idleTimeToLive"""
    acquired: list[str] = []
    released: list[str] = []

    def lookup(key: str) -> fx.Layer[Never]:
        return make_layer(key, acquired, released)

    lookup_live = _LookupMap.layer(lookup, idle_time_to_live=_short_or_long)
    record_live = _RecordMap.layer_from_record(
        {
            "short": make_layer("short", acquired, released),
            "long": make_layer("long", acquired, released),
        },
        idle_time_to_live=_record_ttl,
    )

    yield from fx.scoped(_LookupMap.context_effect("short:a").pipe(fx.provide(lookup_live)))
    yield from fx.scoped(_RecordMap.context_effect("short").pipe(fx.provide(record_live)))
    assert acquired == ["short:a", "short"]

    yield from testing.adjust("500 millis")
    assert released == ["short:a", "short"]
