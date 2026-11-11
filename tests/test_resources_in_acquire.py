"""Resources that run background fibers close with their scope when they are
made inside ``acquire_release``'s acquire, as in Effect.

The acquire is uninterruptible. Effect forks background work there with
``restore(...)``, which outside an interruptible region is the identity, and
a forked fiber starts interruptible, so the resource's finalizer can
interrupt it. A background fiber that kept the acquire's uninterruptible
region would make closing the scope wait forever.

Effect 4.1.2 closes all four pool variants turnstile reported
(``Pool.makeWithTTL`` with ``min`` 0 and 1, ``Pool.make``, and a pool made
outside an acquire); the other cases extend the check to every resource
here that forks a background, strategy, idle-timer or daemon fiber.
"""

import itertools
import threading
from collections.abc import Callable
from typing import Any, Literal, Never

import pytest

import pyfect as fx

type _Use = fx.Effect[Any, Any, fx.Scope]
type _Make = Callable[[], fx.Effect[_Use, Any, fx.Scope]]

_ITEM = fx.acquire_release(fx.succeed("item"), lambda _item, _exit: fx.void)


def _lookup(_key: str) -> fx.Effect[str, Never, fx.Scope]:
    return _ITEM


def _pool_ttl(min_size: int, strategy: Literal["usage", "creation"]) -> _Make:
    def make() -> fx.Effect[_Use, Any, fx.Scope]:
        return fx.Pool.make_with_ttl(
            _ITEM, min=min_size, max=2, time_to_live="1 second", time_to_live_strategy=strategy
        ).map(lambda pool: pool.get())

    return make


def _pool_fixed() -> fx.Effect[_Use, Any, fx.Scope]:
    return fx.Pool.make(_ITEM, size=1).map(lambda pool: pool.get())


def _pool_ttl_use() -> fx.Effect[_Use, Any, fx.Scope]:
    return fx.Pool.make_with_ttl(_ITEM, min=0, max=2, time_to_live="1 second").map(
        lambda pool: pool.use(fx.succeed)
    )


def _rc_ref() -> fx.Effect[_Use, Any, fx.Scope]:
    return fx.RcRef.make(_ITEM, idle_time_to_live="1 second").map(lambda ref: ref.get())


def _rc_map() -> fx.Effect[_Use, Any, fx.Scope]:
    return fx.RcMap.make(_lookup, idle_time_to_live="1 second").map(lambda rc: rc.get("key"))


def _scoped_cache() -> fx.Effect[_Use, Any, fx.Scope]:
    return fx.ScopedCache.make(_lookup, capacity=4, time_to_live="1 second").map(
        lambda cache: cache.get("key")
    )


def _layer_map() -> fx.Effect[_Use, Any, fx.Scope]:
    layer = fx.layer.effect_discard(fx.never.fork_scoped())

    def build(_key: str) -> fx.Layer[Never]:
        return layer

    return fx.LayerMap.make(build, idle_time_to_live="1 second").map(
        lambda layers: layers.get("key").build()
    )


def _fiber_set() -> fx.Effect[_Use, Any, fx.Scope]:
    return fx.FiberSet.make().map(lambda fibers: fibers.run(fx.never))


def _fiber_map() -> fx.Effect[_Use, Any, fx.Scope]:
    return fx.FiberMap[str, Never, Never].make().map(lambda fibers: fibers.run("key", fx.never))


def _fiber_handle() -> fx.Effect[_Use, Any, fx.Scope]:
    return fx.FiberHandle.make().map(lambda handle: handle.run(fx.never))


def _stream_share() -> fx.Effect[_Use, Any, fx.Scope]:
    source = fx.stream.from_iterable(itertools.count())
    return source.share(capacity=4, idle_time_to_live="1 second").map(
        lambda shared: shared.take(1).run_drain()
    )


def _stream_broadcast() -> fx.Effect[_Use, Any, fx.Scope]:
    source = fx.stream.from_iterable(itertools.count())
    return source.broadcast(capacity=4).map(lambda shared: shared.take(1).run_drain())


def _fork_scoped() -> fx.Effect[_Use, Any, fx.Scope]:
    return fx.never.fork_scoped().as_(fx.void)


_CASES: dict[str, _Make] = {
    "pool-ttl-min0": _pool_ttl(0, "usage"),
    "pool-ttl-min1": _pool_ttl(1, "usage"),
    "pool-ttl-creation-min0": _pool_ttl(0, "creation"),
    "pool-fixed": _pool_fixed,
    "pool-ttl-use": _pool_ttl_use,
    "rc-ref-idle": _rc_ref,
    "rc-map-idle": _rc_map,
    "scoped-cache-ttl": _scoped_cache,
    "layer-map-idle": _layer_map,
    "fiber-set": _fiber_set,
    "fiber-map": _fiber_map,
    "fiber-handle": _fiber_handle,
    "stream-share-idle": _stream_share,
    "stream-broadcast": _stream_broadcast,
    "fork-scoped": _fork_scoped,
}

type _Mode = Literal["plain", "made-in-acquire", "used-in-acquire"]


def _program(make: _Make, mode: _Mode) -> fx.Effect[Any, Any]:
    def use(u: _Use) -> fx.Effect[Any, Any]:
        # The pause lets every background fiber start before the scope closes.
        return fx.scoped(u).tap(lambda _: fx.sleep("20 millis"))

    match mode:
        case "plain":
            return fx.scoped(make().flat_map(use))
        case "made-in-acquire":
            made = fx.acquire_release(make(), lambda _u, _exit: fx.void)
            return fx.scoped(made.flat_map(use))
        case "used-in-acquire":
            used = fx.acquire_release(make().tap(use), lambda _u, _exit: fx.void)
            return fx.scoped(used)


def _closes_within(program: fx.Effect[Any, Any], seconds: float) -> bool:
    # A thread, not ``timeout``: a hang inside an uninterruptible region
    # cannot be interrupted, so the run would never return to report it.
    thread = threading.Thread(target=lambda: fx.run_blocking(program), daemon=True)
    thread.start()
    thread.join(seconds)
    return not thread.is_alive()


@pytest.mark.parametrize("mode", ["plain", "made-in-acquire", "used-in-acquire"])
@pytest.mark.parametrize("name", list(_CASES))
def test_the_scope_closes(name: str, mode: _Mode):
    assert _closes_within(_program(_CASES[name], mode), 5), f"{name} ({mode}) did not close"


def test_restore_outside_an_interruptible_region_keeps_a_forked_fiber_interruptible():
    """Effect's ``uninterruptibleMask`` hands an uninterruptible caller the
    identity as ``restore``. A fiber forked with ``restore(...)`` starts
    interruptible, as every forked fiber does, and stays so."""

    def body(restore: fx.Restore) -> fx.Effect[None]:
        def stop(fiber: fx.Fiber[Never, Never]) -> fx.Effect[None]:
            return fiber.interrupt().and_then(fiber.await_exit()).as_void()

        return restore(fx.never).fork(start_immediately=True).flat_map(stop)

    assert _closes_within(fx.uninterruptible_mask(body).uninterruptible(), 5)
