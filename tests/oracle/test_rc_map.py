"""Ports of Effect's ``RcMap.test.ts``.

Each test's docstring is the Effect test title. ``Scope.provide(scope)`` is
``provide_service(fx.Scope, scope)``, durations are seconds (Effect's
milliseconds divided by 1000), ``Effect.die(message)`` dies with
``Exception(message)``, ``Data.Class`` keys are frozen dataclasses, and the
map's ``state`` is its private ``_entries`` dict (``None`` once closed).
"""
# pyright: reportPrivateUsage=false

import math
import warnings
from dataclasses import dataclass
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.cause import Die


def _interrupted(ex: fx.Exit[Any, Any] | None) -> bool:
    return isinstance(ex, fx.Failure) and ex.cause.has_interrupts


def _died_with(ex: fx.Exit[Any, Any], message: str) -> bool:
    if not isinstance(ex, fx.Failure):
        return False
    reasons: tuple[object, ...] = ex.cause.reasons
    return [str(r.defect) for r in reasons if isinstance(r, Die)] == [message]


def _same(key: str) -> fx.Effect[str]:
    return fx.succeed(key)


def _in[A, E](scope: fx.CloseableScope, eff: fx.Effect[A, E, fx.Scope]) -> fx.Effect[A, E]:
    return eff.pipe(fx.provide_service(fx.Scope, scope))


def _lookup(acquired: list[str], released: list[str]):
    def lookup(key: str) -> fx.Effect[str, Any, fx.Scope]:
        def acquire() -> str:
            acquired.append(key)
            return key

        return fx.acquire_release(
            fx.sync(acquire), lambda _a, _e: fx.sync(lambda: released.append(key))
        )

    return lookup


def _counting(released: fx.Ref[int]):
    def lookup(key: str) -> fx.Effect[str, Any, fx.Scope]:
        return fx.acquire_release(fx.succeed(key), lambda _a, _e: released.update(lambda n: n + 1))

    return lookup


@pytest.mark.parametrize(
    ("idle_time_to_live", "outstanding"), [(1.0, False), (math.inf, False), (0, True)]
)
@testing.effect
def test_releases_every_entry_and_propagates_all_defects_with_ttl(
    idle_time_to_live: float, outstanding: bool
):
    """releases every entry and propagates all defects with TTL ${idleTimeToLive}"""
    released: list[str] = []
    owner = fx.CloseableScope()
    borrower = fx.CloseableScope()

    def release(key: str) -> fx.Effect[None]:
        def run() -> fx.Effect[None]:
            released.append(key)
            return fx.void if key == "ok" else fx.die(Exception(f"release {key}"))

        return fx.suspend(run)

    def lookup(key: str) -> fx.Effect[str, Never, fx.Scope]:
        return fx.acquire_release(fx.succeed(key), lambda _a, _e: release(key))

    rc_map = yield from _in(
        owner,
        fx.RcMap.make(lookup, idle_time_to_live=idle_time_to_live),
    )

    for key in ["a", "b", "ok"]:
        yield from _in(borrower, rc_map.get(key))
    if not outstanding:
        yield from borrower.close(fx.Success(None))
    assert released == []

    ex = yield from owner.close(fx.Success(None)).exit()
    yield from borrower.close(fx.Success(None))

    assert sorted(released) == ["a", "b", "ok"]
    assert (yield from rc_map.get_option("a")) is None
    assert isinstance(ex, fx.Failure), "owner shutdown discarded release defects"
    reasons: tuple[object, ...] = ex.cause.reasons
    assert sorted(str(r.defect) if isinstance(r, Die) else type(r).__name__ for r in reasons) == [
        "release a",
        "release b",
    ]


def _bad_lookup(throws: bool):
    def lookup(key: str) -> fx.Effect[str]:
        if key != "bad":
            return fx.succeed(key)
        if throws:
            raise Exception("boom")
        return fx.die(Exception("boom"))

    return lookup


@pytest.mark.parametrize("idle_time_to_live", [0, 1.0])
@pytest.mark.parametrize("throws", [False, True])
@testing.effect
def test_releases_capacity_after_a_failed_lookup(throws: bool, idle_time_to_live: float):
    """releases capacity after a ${throws ? "throwing" : "dying"} lookup with TTL %s"""
    rc_map = yield from fx.RcMap.make(
        _bad_lookup(throws), capacity=1, idle_time_to_live=idle_time_to_live
    )

    assert _died_with((yield from fx.scoped(rc_map.get("bad")).exit()), "boom")
    if idle_time_to_live > 0:
        assert (yield from rc_map.has("bad"))
        yield from testing.adjust(idle_time_to_live)
    assert (yield from rc_map.get("good").exit()) == fx.Success("good")
    assert not (yield from rc_map.has("bad"))


@pytest.mark.parametrize("throws", [False, True])
@testing.effect
def test_shares_a_failed_lookups_defect_with_later_borrowers(throws: bool):
    """shares a ${throws ? "throwing" : "dying"} lookup's defect with later borrowers"""
    rc_map = yield from fx.RcMap.make(_bad_lookup(throws))

    assert _died_with((yield from rc_map.get("bad").exit()), "boom")
    borrower = yield from (
        rc_map.get_option("bad").exit().timeout_option(1.0).fork(start_immediately=True)
    )
    yield from testing.adjust(1.0)
    result = yield from borrower.join()
    assert isinstance(result, fx.Some)
    assert _died_with(result.value, "boom")


@pytest.mark.parametrize("idle_time_to_live", [0, 1.0, math.inf])
@testing.effect
def test_releases_only_the_invalidated_entry_with_ttl(idle_time_to_live: float):
    """releases only the invalidated entry with TTL %s"""
    acquired: list[int] = []
    released: list[int] = []
    map_scope, old_scope, new_scope = (fx.CloseableScope() for _ in range(3))

    def acquire() -> int:
        acquired.append(len(acquired) + 1)
        return acquired[-1]

    def lookup(_key: str) -> fx.Effect[int, Never, fx.Scope]:
        return fx.acquire_release(
            fx.sync(acquire), lambda v, _: fx.sync(lambda: released.append(v))
        )

    rc_map = yield from _in(map_scope, fx.RcMap.make(lookup, idle_time_to_live=idle_time_to_live))

    assert (yield from _in(old_scope, rc_map.get("key"))) == 1
    yield from rc_map.invalidate("key")
    assert not (yield from rc_map.has("key"))
    assert released == []
    assert (yield from _in(new_scope, rc_map.get("key"))) == 2

    yield from old_scope.close(fx.Success(None))
    after_old_release = (list(released), (yield from rc_map.has("key")))
    replacement = yield from fx.scoped(rc_map.get_option("key"))
    yield from new_scope.close(fx.Success(None))
    after_new_release = list(released)
    if idle_time_to_live == 1.0:
        yield from testing.adjust(0.999)
        assert (yield from rc_map.has("key"))
        yield from testing.adjust(0.001)
        assert not (yield from rc_map.has("key"))
    yield from map_scope.close(fx.Success(None))

    assert acquired == [1, 2]
    assert after_old_release == ([1], True)
    assert replacement == fx.Some(2)
    assert after_new_release == ([1, 2] if idle_time_to_live == 0 else [1])
    assert released == [1, 2]


@testing.effect
def test_an_invalidated_entrys_idle_timer_cannot_remove_its_replacement():
    """an invalidated entry's idle timer cannot remove its replacement"""
    acquired = yield from fx.Ref.make(0)
    released: list[int] = []
    map_scope = fx.CloseableScope()

    def lookup(_key: str) -> fx.Effect[int, Never, fx.Scope]:
        return fx.acquire_release(
            acquired.update_and_get(lambda n: n + 1),
            lambda v, _: fx.sync(lambda: released.append(v)),
        )

    rc_map = yield from _in(map_scope, fx.RcMap.make(lookup, idle_time_to_live=1.0))

    assert (yield from fx.scoped(rc_map.get("key"))) == 1
    yield from testing.adjust(0.5)
    assert rc_map._entries is not None
    idle_fiber = rc_map._entries["key"].fiber
    assert idle_fiber is not None
    old_scope = fx.CloseableScope()
    new_scope = fx.CloseableScope()
    assert (yield from _in(old_scope, rc_map.get("key"))) == 1
    yield from rc_map.invalidate("key")
    assert released == []
    assert (yield from _in(new_scope, rc_map.get("key"))) == 2
    yield from old_scope.close(fx.Success(None))
    assert _interrupted(idle_fiber.poll_unsafe())
    yield from testing.adjust(1.0)
    replacement = yield from fx.scoped(rc_map.get_option("key"))
    after_timer = list(released)
    yield from map_scope.close(fx.Success(None))
    assert released == [1, 2]
    yield from new_scope.close(fx.Success(None))

    assert replacement == fx.Some(2)
    assert after_timer == [1]
    assert released == [1, 2]
    assert (yield from acquired.get()) == 2


@testing.effect
def test_returns_none_without_lookup_or_capacity_acquisition_when_missing():
    """returns None without lookup or capacity acquisition when missing"""
    lookups = yield from fx.Ref.make(0)

    def lookup(key: str) -> fx.Effect[str]:
        return lookups.update(lambda n: n + 1).as_(key)

    rc_map = yield from fx.RcMap.make(lookup, capacity=0)

    assert (yield from rc_map.get_option("missing")) is None
    assert (yield from lookups.get()) == 0


@testing.effect
def test_retains_a_ready_entry_until_the_caller_scope_closes():
    """retains a ready entry until the caller scope closes"""
    released = yield from fx.Ref.make(0)
    rc_map = yield from fx.RcMap.make(_counting(released))
    owner_scope = fx.CloseableScope()
    borrower_scope = fx.CloseableScope()

    yield from _in(owner_scope, rc_map.get("ready"))
    assert (yield from _in(borrower_scope, rc_map.get_option("ready"))) == fx.Some("ready")

    yield from owner_scope.close(fx.Success(None))
    assert (yield from released.get()) == 0
    yield from borrower_scope.close(fx.Success(None))
    assert (yield from released.get()) == 1


@testing.effect
def test_shares_an_in_flight_entry():
    """shares an in-flight entry"""
    started = yield from fx.Deferred[None].make()
    complete = yield from fx.Deferred[None].make()
    released = yield from fx.Ref.make(0)

    def lookup(key: str) -> fx.Effect[str, Never, fx.Scope]:
        return fx.acquire_release(
            started.succeed(None).and_then(complete.wait()).as_(key),
            lambda _a, _e: released.update(lambda n: n + 1),
        )

    rc_map = yield from fx.RcMap.make(lookup)
    owner_scope = fx.CloseableScope()
    borrower_scope = fx.CloseableScope()
    owner = yield from _in(owner_scope, rc_map.get("pending")).fork(start_immediately=True)
    yield from started.wait()
    borrower = yield from _in(borrower_scope, rc_map.get_option("pending")).fork(
        start_immediately=True
    )

    assert rc_map._entries is not None
    assert rc_map._entries["pending"].ref_count == 2
    yield from complete.succeed(None)
    assert (yield from owner.join()) == "pending"
    assert (yield from borrower.join()) == fx.Some("pending")

    yield from owner_scope.close(fx.Success(None))
    assert (yield from released.get()) == 0
    yield from borrower_scope.close(fx.Success(None))
    assert (yield from released.get()) == 1


@testing.effect
def test_propagates_a_cached_failure():
    """propagates a cached failure"""
    lookups = yield from fx.Ref.make(0)

    def lookup(_key: str) -> fx.Effect[Never, str]:
        return lookups.update(lambda n: n + 1).and_then(fx.fail("boom"))

    rc_map = yield from fx.RcMap.make(lookup)
    owner_scope = fx.CloseableScope()
    borrower_scope = fx.CloseableScope()

    assert (yield from _in(owner_scope, rc_map.get("failed")).exit()) == fx.exit.fail("boom")
    assert (yield from _in(borrower_scope, rc_map.get_option("failed")).exit()) == fx.exit.fail(
        "boom"
    )
    assert (yield from lookups.get()) == 1

    yield from owner_scope.close(fx.Success(None))
    yield from borrower_scope.close(fx.Success(None))


@testing.effect
def test_retains_an_idle_entry_and_restarts_its_ttl_on_release():
    """retains an idle entry and restarts its TTL on release"""
    released = yield from fx.Ref.make(0)
    rc_map = yield from fx.RcMap.make(_counting(released), idle_time_to_live=1.0)
    owner_scope = fx.CloseableScope()
    yield from _in(owner_scope, rc_map.get("ttl"))
    yield from owner_scope.close(fx.Success(None))

    yield from testing.adjust(0.5)
    borrower_scope = fx.CloseableScope()
    assert (yield from _in(borrower_scope, rc_map.get_option("ttl"))) == fx.Some("ttl")
    yield from testing.adjust(0.5)
    assert (yield from released.get()) == 0

    yield from borrower_scope.close(fx.Success(None))
    yield from testing.adjust(0.999)
    assert (yield from released.get()) == 0
    yield from testing.adjust(0.001)
    assert (yield from released.get()) == 1
    assert (yield from rc_map.get_option("ttl")) is None


@testing.effect
def test_linearizes_retention_before_invalidation():
    """linearizes retention before invalidation"""
    released = yield from fx.Ref.make(0)
    rc_map = yield from fx.RcMap.make(_counting(released))
    owner_scope = fx.CloseableScope()
    borrower_scope = fx.CloseableScope()
    yield from _in(owner_scope, rc_map.get("key"))
    assert (yield from _in(borrower_scope, rc_map.get_option("key"))) == fx.Some("key")

    yield from rc_map.invalidate("key")
    assert not (yield from rc_map.has("key"))
    yield from owner_scope.close(fx.Success(None))
    assert (yield from released.get()) == 0
    yield from borrower_scope.close(fx.Success(None))
    assert (yield from released.get()) == 1


@testing.effect
def test_returns_none_when_the_map_is_closed():
    """returns None when the map is closed"""
    map_scope = fx.CloseableScope()
    rc_map = yield from _in(map_scope, fx.RcMap.make(_same))
    yield from map_scope.close(fx.Success(None))

    assert (yield from rc_map.get_option("key")) is None


@testing.effect
def test_deallocation():
    """deallocation"""
    acquired: list[str] = []
    released: list[str] = []
    map_scope = fx.CloseableScope()
    rc_map = yield from _in(map_scope, fx.RcMap.make(_lookup(acquired, released)))

    assert acquired == []
    assert (yield from fx.scoped(rc_map.get("foo"))) == "foo"
    assert acquired == ["foo"]
    assert released == ["foo"]

    scope_a = fx.CloseableScope()
    scope_b = fx.CloseableScope()
    yield from _in(scope_a, rc_map.get("bar"))
    yield from fx.scoped(rc_map.get("bar"))
    yield from _in(scope_b, rc_map.get("baz"))
    yield from fx.scoped(rc_map.get("baz"))
    assert acquired == ["foo", "bar", "baz"]
    assert released == ["foo"]
    yield from scope_b.close(fx.Success(None))
    assert acquired == ["foo", "bar", "baz"]
    assert released == ["foo", "baz"]
    yield from scope_a.close(fx.Success(None))
    assert acquired == ["foo", "bar", "baz"]
    assert released == ["foo", "baz", "bar"]

    scope_c = fx.CloseableScope()
    yield from _in(scope_c, rc_map.get("qux"))
    assert acquired == ["foo", "bar", "baz", "qux"]
    assert released == ["foo", "baz", "bar"]

    yield from map_scope.close(fx.Success(None))
    assert acquired == ["foo", "bar", "baz", "qux"]
    assert released == ["foo", "baz", "bar", "qux"]

    assert _interrupted((yield from fx.scoped(rc_map.get("boom")).exit()))


@testing.effect
def test_idle_time_to_live():
    """idleTimeToLive"""
    acquired: list[str] = []
    released: list[str] = []
    rc_map = yield from fx.RcMap.make(_lookup(acquired, released), idle_time_to_live=1.0)

    assert acquired == []
    assert (yield from fx.scoped(rc_map.get("foo"))) == "foo"
    assert acquired == ["foo"]
    assert released == []

    yield from testing.adjust(1.0)
    assert released == ["foo"]

    assert (yield from fx.scoped(rc_map.get("bar"))) == "bar"
    assert acquired == ["foo", "bar"]
    assert released == ["foo"]

    yield from testing.adjust(0.5)
    assert (yield from fx.scoped(rc_map.get("bar"))) == "bar"
    assert acquired == ["foo", "bar"]
    assert released == ["foo"]

    yield from testing.adjust(1.0)
    assert released == ["foo", "bar"]

    yield from fx.scoped(rc_map.get("baz"))
    assert acquired == ["foo", "bar", "baz"]
    yield from rc_map.invalidate("baz")
    assert acquired == ["foo", "bar", "baz"]
    assert released == ["foo", "bar", "baz"]


@testing.effect
def test_touch():
    """.touch"""
    acquired: list[str] = []
    released: list[str] = []
    rc_map = yield from fx.RcMap.make(_lookup(acquired, released), idle_time_to_live=1.0)

    assert acquired == []
    assert (yield from fx.scoped(rc_map.get("foo"))) == "foo"
    assert acquired == ["foo"]
    assert released == []

    yield from testing.adjust(0.5)
    assert released == []

    yield from rc_map.touch("foo")
    yield from testing.adjust(0.5)
    assert released == []
    yield from testing.adjust(0.5)
    assert released == ["foo"]


@testing.effect
def test_capacity():
    """capacity"""
    rc_map = yield from fx.RcMap.make(_same, capacity=2, idle_time_to_live=1.0)

    assert (yield from fx.scoped(rc_map.get("foo"))) == "foo"
    assert (yield from fx.scoped(rc_map.get("foo"))) == "foo"
    assert (yield from fx.scoped(rc_map.get("bar"))) == "bar"

    ex = yield from fx.scoped(rc_map.get("baz")).exit()
    assert ex == fx.exit.fail(fx.ExceededCapacityError("RcMap attempted to exceed capacity of 2"))

    yield from testing.adjust(1.0)
    assert (yield from fx.scoped(rc_map.get("baz"))) == "baz"


@dataclass(frozen=True)
class _Key:
    id: int


@testing.effect
def test_complex_key():
    """complex key"""

    def lookup(key: _Key) -> fx.Effect[int]:
        return fx.succeed(key.id)

    rc_map = yield from fx.RcMap.make(lookup, capacity=1)

    assert (yield from rc_map.get(_Key(1))) == 1
    # no failure means a hit
    assert (yield from rc_map.get(_Key(1))) == 1


@testing.effect
def test_keys_lookup():
    """keys lookup"""
    rc_map = yield from fx.RcMap.make(_same)

    yield from rc_map.get("foo")
    yield from rc_map.get("bar")
    yield from rc_map.get("baz")

    assert (yield from rc_map.keys()) == ["foo", "bar", "baz"]


def _short_or_long(key: str) -> float:
    return 0.5 if key.startswith("short:") else 2.0


@testing.effect
def test_dynamic_idle_time_to_live():
    """dynamic idleTimeToLive"""
    acquired: list[str] = []
    released: list[str] = []
    rc_map = yield from fx.RcMap.make(_lookup(acquired, released), idle_time_to_live=_short_or_long)

    assert acquired == []

    yield from fx.scoped(rc_map.get("short:a"))
    yield from fx.scoped(rc_map.get("long:b"))
    assert acquired == ["short:a", "long:b"]
    assert released == []

    yield from testing.adjust(0.5)
    assert released == ["short:a"]

    yield from testing.adjust(1.5)
    assert released == ["short:a", "long:b"]


@testing.effect
def test_dynamic_idle_time_to_live_with_touch():
    """dynamic idleTimeToLive with touch"""
    acquired: list[str] = []
    released: list[str] = []
    rc_map = yield from fx.RcMap.make(_lookup(acquired, released), idle_time_to_live=_short_or_long)

    yield from fx.scoped(rc_map.get("short:a"))
    assert acquired == ["short:a"]
    assert released == []

    yield from testing.adjust(0.25)
    yield from rc_map.touch("short:a")
    yield from testing.adjust(0.25)
    assert released == []

    yield from testing.adjust(0.25)
    assert released == ["short:a"]


@testing.effect
def test_closing_the_map_while_an_idle_entry_is_being_released_runs_every_finalizer():
    """closing the map while an idle entry is being released runs every finalizer"""
    gate = yield from fx.Deferred[None].make()
    released = 0
    scope = fx.CloseableScope()

    def count() -> None:
        nonlocal released
        released += 1

    @fx.fn
    def lookup(_key: str):
        yield from fx.add_finalizer(lambda _: fx.sync(count))
        yield from fx.add_finalizer(lambda _: gate.wait().and_then(fx.sync(count)))

    rc_map = yield from _in(scope, fx.RcMap.make(lookup, idle_time_to_live=1))
    yield from fx.scoped(rc_map.get("a"))
    yield from testing.adjust(1)
    assert not (yield from rc_map.has("a"))
    closing = yield from scope.close(fx.Success(None)).fork(start_immediately=True)
    yield from gate.succeed(None)
    yield from closing.join()
    assert released == 2


@testing.effect
def test_drops_an_interrupted_lookup_and_closes_its_scope():
    """drops an interrupted lookup and closes its scope"""
    lookups = 0
    started = yield from fx.Deferred[None].make()
    interrupt = yield from fx.Deferred[None].make()
    finalized = yield from fx.Deferred[None].make()

    @fx.fn
    def lookup(_key: str):
        nonlocal lookups
        lookups += 1
        if lookups > 1:
            return lookups
        yield from fx.add_finalizer(lambda _: finalized.succeed(None))
        yield from started.succeed(None)
        yield from interrupt.wait()
        return (yield from fx.interrupt())

    rc_map = yield from fx.RcMap.make(lookup, idle_time_to_live=60)

    # The only borrower leaves, so nothing else releases the entry.
    borrower = yield from fx.scoped(rc_map.get("key")).fork(start_immediately=True)
    yield from started.wait()
    yield from borrower.interrupt()
    yield from interrupt.succeed(None)
    # Effect's resume runs the lookup to its end here; pyfect's is scheduled.
    yield from fx.yield_now()

    assert (yield from fx.scoped(rc_map.get("key"))) == 2
    yield from finalized.wait()


@testing.effect
def test_idle_entry_is_released_exactly_when_its_ttl_ends():
    """Not an Effect title (checked against Effect's millisecond deadline):
    released at 100 ms with a 200 ms TTL, the entry closes at 300 ms. In
    float seconds ``0.1 + 0.2 > 0.3`` left a 0 ns sleep that spun."""
    closed: list[int] = []

    def lookup(key: str) -> fx.Effect[str, Never, fx.Scope]:
        return fx.acquire_release(
            fx.succeed(key), lambda _a, _e: fx.clock.now_nanos().map(closed.append)
        )

    rc_map = yield from fx.RcMap.make(lookup, idle_time_to_live=0.2)
    yield from testing.adjust(0.1)
    scope = fx.CloseableScope()
    yield from _in(scope, rc_map.get("a"))
    yield from scope.close(fx.Success(None))
    with warnings.catch_warnings():
        warnings.simplefilter("error", testing.BusyFiberWarning)
        yield from testing.adjust(1.0)
    assert closed == [300_000_000]
