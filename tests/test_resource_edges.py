"""Resource edge cases Effect's tests leave out. Each expected value was
checked by running the same program against Effect's TS source under Node."""

from typing import Never

import pyfect as fx
from pyfect import layer, testing


class Tenant(fx.Tag[str]): ...


@testing.effect
def test_rc_ref_acquire_sees_the_first_callers_services():
    ref = yield from fx.RcRef.make(fx.service_option(Tenant))
    got = yield from fx.scoped(ref.get()).pipe(fx.provide_service(Tenant, "caller"))
    assert got == fx.Some("caller")


@testing.effect
def test_rc_map_lookup_sees_the_callers_services_over_the_makers():
    def lookup(key: str) -> fx.Effect[str, Never, Tenant]:
        return Tenant().map(lambda tenant: f"{key}:{tenant}")

    rc_map = yield from fx.RcMap.make(lookup).pipe(fx.provide_service(Tenant, "maker"))
    from_caller = yield from fx.scoped(rc_map.get("a")).pipe(fx.provide_service(Tenant, "caller"))
    from_maker = yield from fx.scoped(rc_map.get("b"))
    assert (from_caller, from_maker) == ("a:caller", "b:maker")


@testing.effect
def test_resource_refresh_uses_the_services_captured_at_creation():
    count = 0

    def acquire(tenant: str) -> str:
        nonlocal count
        count += 1
        return f"{tenant}{count}"

    resource = yield from fx.Resource.manual(Tenant().map(acquire)).pipe(
        fx.provide_service(Tenant, "maker")
    )
    yield from resource.refresh()
    assert (yield from resource.get()) == "maker2"


@testing.effect
def test_scoped_ref_set_in_flight_when_the_owner_closes_is_interrupted():
    owner = fx.CloseableScope()
    ref = yield from fx.ScopedRef.make(lambda: 0).pipe(fx.provide_service(fx.Scope, owner))
    gate = yield from fx.Deferred[None].make()
    setter = yield from ref.set(gate.wait().as_(1)).fork_daemon(start_immediately=True)
    yield from owner.close(fx.Success(None))
    yield from gate.succeed(None)
    ex = yield from setter.await_exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts
    assert ref.get_unsafe() == 0


@testing.effect
def test_scoped_ref_releases_the_replacement_at_once_when_the_old_release_dies():
    released = 0

    def count() -> None:
        nonlocal released
        released += 1

    ref = yield from fx.ScopedRef.from_acquire(
        fx.acquire_release(fx.succeed(0), lambda _a, _e: fx.die(Exception("x")))
    )
    yield from ref.set(fx.acquire_release(fx.succeed(1), lambda _a, _e: fx.sync(count))).exit()
    assert released == 1


@testing.effect
def test_scoped_ref_sets_run_one_at_a_time():
    log: list[str] = []
    ref = yield from fx.ScopedRef.make(lambda: 0)
    gate = yield from fx.Deferred[None].make()

    def acquire(n: int, wait: bool) -> fx.Effect[int, Never, fx.Scope]:
        @fx.gen
        def body():
            log.append(f"start {n}")
            if wait:
                yield from gate.wait()
            log.append(f"end {n}")
            return n

        return fx.acquire_release(body, lambda _a, _e: fx.sync(lambda: log.append(f"release {n}")))

    first = yield from ref.set(acquire(1, True)).fork(start_immediately=True)
    second = yield from ref.set(acquire(2, False)).fork(start_immediately=True)
    yield from fx.yield_now()
    log.append("open")
    yield from gate.succeed(None)
    yield from first.join()
    yield from second.join()
    assert log == ["start 1", "open", "end 1", "start 2", "end 2", "release 1"]
    assert ref.get_unsafe() == 2


class _Dep(fx.Tag[int]): ...


class _Keyed(fx.Tag[str]): ...


def test_layer_map_and_layer_ref_share_what_the_enclosing_build_built():
    log: list[str] = []
    dep_live = layer.effect(
        _Dep,
        fx.acquire_release(
            fx.sync(lambda: log.append("D+") or 1), lambda _a, _e: fx.sync(lambda: log.append("D-"))
        ),
    )

    def keyed(key: str) -> fx.Layer[_Keyed]:
        return layer.effect(_Keyed, _Dep().as_(key)).pipe(fx.provide(dep_live))

    @fx.gen
    def use():
        yield from _Dep()
        log.append("outer has D")
        layer_map = yield from fx.LayerMap.make(keyed)
        yield from fx.scoped(layer_map.context_effect("z"))
        layer_ref = yield from fx.LayerRef.make(keyed("r"))
        yield from fx.scoped(layer_ref.context_effect())
        log.append("built")

    fx.run_blocking(
        fx.scoped(layer.effect_discard(use).pipe(layer.provide_merge(dep_live)).build())
    )
    assert log == ["D+", "outer has D", "built", "D-"]


@testing.effect
def test_rc_map_keeps_an_interrupted_lookups_scope_until_its_borrower_lets_go():
    finalized = False

    def finalize() -> None:
        nonlocal finalized
        finalized = True

    def lookup(_key: str) -> fx.Effect[Never, Never, fx.Scope]:
        return fx.add_finalizer(lambda _: fx.sync(finalize)).and_then(fx.interrupt())

    rc_map = yield from fx.RcMap.make(lookup, idle_time_to_live=60)
    borrower = fx.CloseableScope()
    ex = yield from rc_map.get("k").pipe(fx.provide_service(fx.Scope, borrower)).exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts
    assert (finalized, (yield from rc_map.has("k"))) == (False, False)
    yield from borrower.close(fx.Success(None))
    assert finalized
