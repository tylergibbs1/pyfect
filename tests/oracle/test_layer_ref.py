"""Ports of Effect's ``LayerRef.test.ts``.

Each test's docstring is the Effect test title. ``Scope.provide(scope)`` is
``provide_service(fx.Scope, scope)``, the ref's ``get`` / ``contextEffect``
/ ``invalidate`` are methods, and ``LayerRef.Service<Self>()(id, options)``
is a ``LayerRefService[I]`` subclass whose ``layer(...)`` takes the
options. Durations are seconds.
"""

from dataclasses import dataclass

import pyfect as fx
from pyfect import layer, testing


@dataclass(frozen=True)
class _Resource:
    id: int


class Resource(fx.Tag[_Resource]): ...


def make_layer(acquired: list[int], released: list[int]) -> fx.Layer[Resource]:
    def acquire() -> _Resource:
        acquired.append(len(acquired) + 1)
        return _Resource(acquired[-1])

    return layer.effect(
        Resource,
        fx.acquire_release(
            fx.sync(acquire), lambda resource, _: fx.sync(lambda: released.append(resource.id))
        ),
    )


@testing.effect
def test_make_lazily_acquires_and_releases_resources():
    """make lazily acquires and releases resources"""
    acquired: list[int] = []
    released: list[int] = []
    ref_scope = fx.CloseableScope()
    ref = yield from fx.LayerRef.make(make_layer(acquired, released)).pipe(
        fx.provide_service(fx.Scope, ref_scope)
    )

    assert acquired == []
    assert released == []

    context = yield from fx.scoped(ref.context_effect())
    assert context.get(Resource).id == 1
    assert acquired == [1]
    assert released == [1]

    context_from_layer = yield from fx.scoped(ref.get().build())
    assert context_from_layer.get(Resource).id == 2
    assert acquired == [1, 2]
    assert released == [1, 2]

    yield from ref_scope.close(fx.Success(None))
    assert released == [1, 2]


@testing.effect
def test_invalidate_releases_an_idle_resource_and_acquires_a_fresh_one():
    """invalidate releases an idle resource and acquires a fresh one"""
    acquired: list[int] = []
    released: list[int] = []
    ref_scope = fx.CloseableScope()
    ref = yield from fx.LayerRef.make(make_layer(acquired, released), idle_time_to_live=60).pipe(
        fx.provide_service(fx.Scope, ref_scope)
    )

    context = yield from fx.scoped(ref.context_effect())
    assert context.get(Resource).id == 1
    assert acquired == [1]
    assert released == []

    cached_context = yield from fx.scoped(ref.context_effect())
    assert cached_context.get(Resource).id == 1
    assert acquired == [1]
    assert released == []

    yield from ref.invalidate()
    assert released == [1]

    fresh_context = yield from fx.scoped(ref.context_effect())
    assert fresh_context.get(Resource).id == 2
    assert acquired == [1, 2]
    assert released == [1]

    yield from ref_scope.close(fx.Success(None))
    assert released == [1, 2]


@testing.effect
def test_preload_acquires_the_resource_when_the_layer_ref_is_created():
    """preload acquires the resource when the LayerRef is created"""
    acquired: list[int] = []
    released: list[int] = []
    ref_scope = fx.CloseableScope()
    ref = yield from fx.LayerRef.make(
        make_layer(acquired, released), idle_time_to_live=60, preload=True
    ).pipe(fx.provide_service(fx.Scope, ref_scope))

    assert acquired == [1]
    assert released == []

    context = yield from fx.scoped(ref.context_effect())
    assert context.get(Resource).id == 1
    assert acquired == [1]
    assert released == []

    yield from ref_scope.close(fx.Success(None))
    assert released == [1]


class ResourceRef(fx.LayerRefService[Resource]): ...


@testing.effect
def test_service_exposes_layer_get_context_effect_and_invalidate():
    """Service exposes layer, get, contextEffect, and invalidate"""
    acquired: list[int] = []
    released: list[int] = []
    resource_ref_live = ResourceRef.layer(make_layer(acquired, released), idle_time_to_live=60)

    @fx.gen
    def program():
        context = yield from fx.scoped(ResourceRef.context_effect())
        assert context.get(Resource).id == 1

        context_from_layer = yield from fx.scoped(ResourceRef.get().build())
        assert context_from_layer.get(Resource).id == 1
        assert acquired == [1]
        assert released == []

        yield from ResourceRef.invalidate()
        assert released == [1]

        fresh_context = yield from fx.scoped(ResourceRef.context_effect())
        assert fresh_context.get(Resource).id == 2
        assert acquired == [1, 2]

    yield from program.pipe(fx.provide(resource_ref_live))

    assert released == [1, 2]
