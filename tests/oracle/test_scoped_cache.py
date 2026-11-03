"""Ports of Effect's ``ScopedCache.test.ts``.

Each test's docstring is the Effect test title. Effect's module functions
are methods (``ScopedCache.get(cache, key)`` is ``cache.get(key)``);
``make`` and ``makeWith`` are one ``ScopedCache.make`` whose
``time_to_live`` is a duration or a function of the exit and the key.
Durations are seconds, ``forkChild({ startImmediately })`` is
``fork(start_immediately=True)``, ``Fiber.await`` is ``await_exit``,
``Scope.provide(scope)`` is ``fx.scope.provide(scope)``,
``Effect.die(message)`` dies with ``Exception(message)``, ``Data.Class``
keys are frozen dataclasses and ``cache.state._tag === "Closed"`` is
``cache.is_closed``.

Adapted, with the reason:

- "does not retain prior equal object keys on cache hits": the keys are
  frozen dataclasses, collected with ``gc.collect()``.
- "does not cache an asynchronous failure with zero TTL": the lookup
  suspends with ``yield_now`` where Effect awaits a resolved promise.
- "concurrent invalidations don't cause resource leaks": resource ids come
  from a counter, not ``Date.now()`` and ``Math.random()``.
"""

import gc
import itertools
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import clock, exit, testing
from pyfect.cause import Die

_HOUR = 3600.0
_MINUTE = 60.0
_DONE = fx.Success(None)


def _length(key: str) -> fx.Effect[int]:
    return fx.succeed(len(key))


def _length_cache(capacity: int | None = 10, time_to_live: float | None = None):
    return fx.ScopedCache.make(_length, capacity=capacity, time_to_live=time_to_live)


def _fail_or_length(key: str) -> fx.Effect[int, str]:
    return fx.fail("error") if key == "fail" else fx.succeed(len(key))


def _always[A, E, R](lookup: fx.Effect[A, E, R]) -> Callable[[str], fx.Effect[A, E, R]]:
    """A lookup that ignores its key."""
    return lambda _key: lookup


def _counter() -> tuple[list[int], fx.Effect[int]]:
    """A counter and an effect that bumps it and gives the new count."""
    count = [0]

    def bump() -> int:
        count[0] += 1
        return count[0]

    return count, fx.sync(bump)


def _died_with(ex: fx.Exit[Any, Any] | None, message: str) -> bool:
    if not isinstance(ex, fx.Failure):
        return False
    reasons: tuple[object, ...] = ex.cause.reasons
    return [str(r.defect) for r in reasons if isinstance(r, Die)] == [message]


def _in[A, E](scope: fx.CloseableScope, eff: fx.Effect[A, E, fx.Scope]) -> fx.Effect[A, E]:
    return eff.pipe(fx.scope.provide(scope))


class _TestLookup:
    """Effect's ``makeScopedTestCache``: counts lookups, answering from
    ``results`` or failing with ``Key not found``."""

    def __init__(self) -> None:
        self.count = 0
        self.results: dict[str, fx.Effect[int, str]] = {}

    def __call__(self, key: str) -> fx.Effect[int, str]:
        self.count += 1
        return self.results.get(key, fx.fail(f"Key not found: {key}"))


@dataclass
class _Tracker:
    """Effect's ``CleanupTracker``: a lookup acquiring one resource per key."""

    acquired: list[str] = field(default_factory=list[str])
    cleaned_up: list[str] = field(default_factory=list[str])

    def lookup(self, key: str) -> fx.Effect[str, Never, fx.Scope]:
        def acquire() -> None:
            self.acquired.append(key)

        def release(_a: None, _ex: fx.Exit[Any, Any]) -> fx.Effect[None]:
            return fx.sync(lambda: self.cleaned_up.append(key))

        return fx.acquire_release(fx.sync(acquire), release).as_(f"resource-{key}")


def _tracked(log: list[str]) -> Callable[[str], fx.Effect[str, Never, fx.Scope]]:
    """A lookup that logs ``acquired-key`` and ``released-key``."""

    def lookup(key: str) -> fx.Effect[str, Never, fx.Scope]:
        def acquire() -> None:
            log.append(f"acquired-{key}")

        def release(_a: None, _ex: fx.Exit[Any, Any]) -> fx.Effect[None]:
            return fx.sync(lambda: log.append(f"released-{key}"))

        return fx.acquire_release(fx.sync(acquire), release).as_(f"value-{key}")

    return lookup


@dataclass(frozen=True)
class _Region:
    region: str


@testing.effect
def test_does_not_retain_prior_equal_object_keys_on_cache_hits():
    """does not retain prior equal object keys on cache hits"""
    references: list[weakref.ref[_Region]] = []
    lookups = [0]

    def lookup(_key: _Region) -> fx.Effect[int]:
        def bump() -> int:
            lookups[0] += 1
            return lookups[0]

        return fx.sync(bump)

    cache = yield from fx.ScopedCache.make(lookup, capacity=16)
    for _ in range(10):
        key = _Region("us-east-1")
        references.append(weakref.ref(key))
        assert (yield from cache.get(key)) == 1
        del key
    assert lookups[0] == 1
    assert (yield from cache.size()) == 1
    references.pop()  # the last key may still be held by the cache
    gc.collect()
    assert [reference() for reference in references] == [None] * 9
    assert (yield from cache.size()) == 1


# --- make -----------------------------------------------------------------------


@testing.effect
def test_make_creates_cache_with_fixed_capacity():
    """creates cache with fixed capacity"""
    cache = yield from _length_cache(10)
    assert cache.capacity == 10


@testing.effect
def test_make_creates_cache_with_default_infinite_ttl():
    """creates cache with default infinite TTL"""
    cache = yield from _length_cache()
    yield from cache.get("test")
    yield from testing.adjust(1000 * _HOUR)
    assert (yield from cache.has("test"))


@testing.effect
def test_make_creates_cache_with_custom_ttl():
    """creates cache with custom TTL"""
    cache = yield from _length_cache(time_to_live=_HOUR)
    yield from cache.get("test")
    yield from testing.adjust(30 * _MINUTE)
    assert (yield from cache.has("test"))
    yield from testing.adjust(31 * _MINUTE)
    assert not (yield from cache.has("test"))


@testing.effect
def test_make_uses_a_numeric_zero_ttl():
    """uses a numeric zero TTL"""
    cache = yield from _length_cache(time_to_live=0)
    yield from cache.get("test")
    assert not (yield from cache.has("test"))


class _TestService(fx.Tag[int]): ...


@testing.effect
def test_make_lookup_function_context_is_preserved():
    """lookup function context is preserved"""

    def program():
        cache = yield from fx.ScopedCache.make(_always(_TestService()), capacity=10)
        return (yield from cache.get("test"))

    result = yield from fx.scoped(fx.gen(program).pipe(fx.provide_service(_TestService, 42)))
    assert result == 42


@testing.effect
def test_cache_resources_are_released_and_future_gets_interrupt_when_scope_closes():
    """cache resources are released and future gets interrupt when scope closes"""

    def program():
        cache = yield from _length_cache()
        yield from cache.get("test")
        return cache

    cache = yield from fx.scoped(fx.gen(program))
    assert cache.is_closed
    ex = yield from cache.get("test").exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts


# --- makeWith -------------------------------------------------------------------


@testing.effect
def test_make_with_creates_cache_with_function_based_ttl():
    """creates cache with function-based TTL"""

    def ttl(ex: fx.Exit[int, str], key: str) -> float:
        if isinstance(ex, fx.Failure):
            return 1
        return _MINUTE if key == "short" else _HOUR

    cache = yield from fx.ScopedCache.make(_fail_or_length, capacity=10, time_to_live=ttl)

    yield from cache.get("long")
    yield from testing.adjust(30 * _MINUTE)
    assert (yield from cache.has("long"))

    yield from cache.get("short")
    assert (yield from cache.has("short"))
    yield from testing.adjust(_MINUTE + 1)
    assert not (yield from cache.has("short"))
    assert (yield from cache.has("long"))

    yield from cache.get("fail").exit()
    assert (yield from cache.has("fail"))
    yield from testing.adjust(2)
    assert not (yield from cache.has("fail"))


@testing.effect
def test_make_with_ttl_function_receives_correct_parameters():
    """TTL function receives correct parameters"""
    received: list[tuple[fx.Exit[int, str], str]] = []

    def ttl(ex: fx.Exit[int, str], key: str) -> float:
        received.append((ex, key))
        return float("inf")

    cache = yield from fx.ScopedCache.make(_fail_or_length, capacity=10, time_to_live=ttl)
    yield from cache.get("test")
    yield from cache.get("fail").exit()

    assert received == [(fx.Success(4), "test"), (exit.fail("error"), "fail")]


@testing.effect
def test_make_with_different_ttl_for_success_vs_failure():
    """different TTL for success vs failure"""

    def ttl(ex: fx.Exit[int, str], _key: str) -> float:
        return _HOUR if isinstance(ex, fx.Success) else _MINUTE

    cache = yield from fx.ScopedCache.make(_fail_or_length, capacity=10, time_to_live=ttl)
    yield from cache.get("success")
    yield from cache.get("fail").exit()
    yield from testing.adjust(30 * _MINUTE)
    assert (yield from cache.has("success"))
    assert not (yield from cache.has("fail"))


@testing.effect
def test_make_with_ttl_based_on_key_values():
    """TTL based on key values"""
    cache = yield from fx.ScopedCache.make(
        _length, capacity=10, time_to_live=lambda _ex, key: _MINUTE if key == "short" else _HOUR
    )
    yield from cache.get("short")
    yield from cache.get("long")
    yield from testing.adjust(30 * _MINUTE)
    assert not (yield from cache.has("short"))
    assert (yield from cache.has("long"))


@testing.effect
def test_make_with_ttl_based_on_result_values():
    """TTL based on result values"""

    def ttl(ex: fx.Exit[int, Never], _key: str) -> float:
        value = ex.value if isinstance(ex, fx.Success) else 0
        return _HOUR if value > 3 else _MINUTE

    cache = yield from fx.ScopedCache.make(_length, capacity=10, time_to_live=ttl)
    yield from cache.get("ab")
    yield from cache.get("abcd")
    yield from testing.adjust(30 * _MINUTE)
    assert not (yield from cache.has("ab"))
    assert (yield from cache.has("abcd"))


@testing.effect
def test_make_with_infinite_ttl_handling():
    """infinite TTL handling"""
    cache = yield from fx.ScopedCache.make(
        _length, capacity=10, time_to_live=lambda _ex, _key: float("inf")
    )
    yield from cache.get("test")
    yield from testing.adjust(1000 * _HOUR)
    assert (yield from cache.has("test"))


@testing.effect
def test_make_with_zero_duration_ttl():
    """zero duration TTL"""
    cache = yield from fx.ScopedCache.make(_length, capacity=10, time_to_live=lambda _ex, _key: 0)
    yield from cache.get("test")
    assert not (yield from cache.has("test"))


# --- get ------------------------------------------------------------------------


@testing.effect
def test_cache_hit_multiple_different_keys():
    """cache hit - multiple different keys"""
    cache = yield from _length_cache()
    assert (yield from cache.get("a")) == 1
    assert (yield from cache.get("ab")) == 2
    assert (yield from cache.get("abc")) == 3


@testing.effect
def test_cache_hit_same_key_multiple_times_doesnt_invoke_lookup_again():
    """cache hit - same key multiple times doesn't invoke lookup again"""
    lookup = _TestLookup()
    lookup.results["test"] = fx.succeed(4)
    cache = yield from fx.ScopedCache.make(lookup, capacity=10)

    results = yield from fx.all(cache.get("test"), cache.get("test"), cache.get("test"))
    assert results == (4, 4, 4)
    assert lookup.count == 1


@testing.effect
def test_cache_miss_invokes_lookup_for_non_existent_key():
    """cache miss - invokes lookup for non-existent key"""
    lookup = _TestLookup()
    lookup.results["test"] = fx.succeed(42)
    cache = yield from fx.ScopedCache.make(lookup, capacity=10)

    assert (yield from cache.get("test")) == 42
    assert lookup.count == 1


@testing.effect
def test_cache_miss_invokes_lookup_again_after_ttl_expiration():
    """cache miss - invokes lookup again after TTL expiration"""
    _, bump = _counter()
    cache = yield from fx.ScopedCache.make(_always(bump), capacity=10, time_to_live=_HOUR)

    assert (yield from cache.get("test")) == 1
    yield from testing.adjust(30 * _MINUTE)
    assert (yield from cache.get("test")) == 1
    yield from testing.adjust(31 * _MINUTE)
    assert (yield from cache.get("test")) == 2


@testing.effect
def test_get_succeeds_after_an_expired_entrys_finalizer_dies():
    """get succeeds after an expired entry's finalizer dies"""
    _, bump = _counter()

    def release(value: int, _ex: fx.Exit[Any, Any]) -> fx.Effect[None]:
        return fx.die(Exception("cleanup defect")) if value == 1 else fx.void

    cache = yield from fx.ScopedCache.make(
        _always(fx.acquire_release(bump, release)), capacity=2, time_to_live=0
    )

    assert (yield from cache.get("key")) == 1
    for expected in [2, 3]:
        reader = yield from cache.get("key").exit().timeout_option(1).fork()
        yield from testing.adjust(1)
        assert (yield from reader.join()) == fx.Some(fx.Success(expected))


@testing.effect
def test_error_handling_lookup_function_fails():
    """error handling - lookup function fails"""
    cache = yield from fx.ScopedCache.make(_always(fx.fail("lookup error")), capacity=10)
    assert (yield from cache.get("test").exit()) == exit.fail("lookup error")


@testing.effect
def test_concurrent_access_multiple_fibers_getting_same_key_only_invoke_lookup_once():
    """concurrent access - multiple fibers getting same key only invoke lookup once"""
    count, bump = _counter()
    cache = yield from fx.ScopedCache.make(_always(bump.delay(0.1)), capacity=10)

    gets = fx.all(cache.get("key"), cache.get("key"), cache.get("key"), concurrency="unbounded")
    results = yield from gets.fork()
    yield from testing.adjust(0.15)
    assert (yield from results.join()) == (1, 1, 1)
    assert count == [1]


@testing.effect
def test_concurrent_access_race_between_get_and_invalidate():
    """concurrent access - race between get and invalidate"""
    count, bump = _counter()
    cache = yield from fx.ScopedCache.make(_always(bump.delay(0.05)), capacity=10)

    fiber1 = yield from cache.get("test").fork()
    yield from testing.adjust(0.025)
    yield from cache.invalidate("test")
    fiber2 = yield from cache.get("test").fork()

    yield from testing.adjust(0.1)
    assert (yield from fiber1.join()) == 1
    assert (yield from fiber2.join()) == 2
    assert count == [2]


@testing.effect
def test_resource_cleanup_when_entry_is_replaced():
    """resource cleanup when entry is replaced"""
    tracker = _Tracker()
    cache = yield from fx.ScopedCache.make(tracker.lookup, capacity=2)

    yield from cache.get("key1")
    yield from cache.get("key2")
    assert tracker.cleaned_up == []
    yield from cache.get("key3")
    assert tracker.cleaned_up == ["key1"]


@testing.effect
def test_scope_is_properly_provided_to_lookup_function():
    """scope is properly provided to lookup function"""
    log: list[str] = []
    cache = yield from fx.ScopedCache.make(_tracked(log), capacity=10)

    yield from cache.get("test")
    assert log == ["acquired-test"]
    yield from cache.invalidate("test")
    assert log == ["acquired-test", "released-test"]


@testing.effect
def test_cache_closed_state_get_returns_interrupt():
    """cache closed state - get returns interrupt"""
    cache = yield from fx.scoped(_length_cache())
    ex = yield from cache.get("test").exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts


# --- getOption ------------------------------------------------------------------


@testing.effect
def test_get_option_returns_some_for_existing_cached_value():
    """returns Some for existing cached value"""
    cache = yield from _length_cache()
    yield from cache.get("test")
    assert (yield from cache.get_option("test")) == fx.Some(4)


@testing.effect
def test_get_option_returns_none_for_non_existent_key():
    """returns None for non-existent key"""
    cache = yield from _length_cache()
    assert (yield from cache.get_option("test")) is None


@testing.effect
def test_get_option_returns_none_for_expired_value():
    """returns None for expired value"""
    cache = yield from _length_cache(time_to_live=_HOUR)
    yield from cache.get("test")
    yield from testing.adjust(2 * _HOUR)
    assert (yield from cache.get_option("test")) is None


@testing.effect
def test_get_option_waits_for_value_being_computed_and_returns_result():
    """waits for value being computed and returns result"""
    deferred = yield from fx.Deferred[None].make()
    cache = yield from fx.ScopedCache.make(_always(deferred.wait().as_(42)), capacity=10)

    get_fiber = yield from cache.get("test").fork()
    option_fiber = yield from cache.get_option("test").fork()
    yield from deferred.succeed(None)

    assert (yield from get_fiber.join()) == 42
    assert (yield from option_fiber.join()) == fx.Some(42)


@testing.effect
def test_get_option_affects_lru_order():
    """affects LRU order"""
    cache = yield from _length_cache(2)
    yield from cache.get("a")
    yield from cache.get("b")
    yield from cache.get_option("a")
    yield from cache.get("c")

    assert (yield from cache.has("a"))
    assert not (yield from cache.has("b"))
    assert (yield from cache.has("c"))


# --- getSuccess -----------------------------------------------------------------


@testing.effect
def test_get_success_returns_some_for_successfully_cached_value():
    """returns Some for successfully cached value"""
    cache = yield from _length_cache()
    yield from cache.get("test")
    assert (yield from cache.get_success("test")) == fx.Some(4)


@testing.effect
def test_get_success_returns_none_for_failed_cached_value():
    """returns None for failed cached value"""
    cache = yield from fx.ScopedCache.make(_always(fx.fail("error")), capacity=10)
    yield from cache.get("test").exit()
    assert (yield from cache.get_success("test")) is None


@testing.effect
def test_get_success_returns_none_for_non_existent_key():
    """returns None for non-existent key"""
    cache = yield from _length_cache()
    assert (yield from cache.get_success("test")) is None


@testing.effect
def test_get_success_returns_none_for_expired_value():
    """returns None for expired value"""
    cache = yield from _length_cache(time_to_live=_HOUR)
    yield from cache.get("test")
    yield from testing.adjust(2 * _HOUR)
    assert (yield from cache.get_success("test")) is None


# --- set ------------------------------------------------------------------------


@testing.effect
def test_set_sets_new_key_value_pair():
    """sets new key-value pair"""
    lookup = _TestLookup()
    cache = yield from fx.ScopedCache.make(lookup, capacity=10)
    yield from cache.set("test", 42)
    assert (yield from cache.get("test")) == 42
    assert lookup.count == 0


@testing.effect
def test_set_overwrites_existing_key():
    """overwrites existing key"""
    cache = yield from _length_cache()
    yield from cache.get("test")
    yield from cache.set("test", 100)
    assert (yield from cache.get("test")) == 100


@testing.effect
def test_set_with_ttl_value_expires():
    """set with TTL - value expires"""
    cache = yield from _length_cache(time_to_live=_HOUR)
    yield from cache.set("test", 42)
    assert (yield from cache.has("test"))
    yield from testing.adjust(2 * _HOUR)
    assert not (yield from cache.has("test"))


@testing.effect
def test_set_doesnt_invoke_lookup_function():
    """set doesn't invoke lookup function"""
    lookup = _TestLookup()
    cache = yield from fx.ScopedCache.make(lookup, capacity=10)
    yield from cache.set("test", 42)
    yield from cache.set("test2", 43)
    yield from cache.set("test3", 44)
    assert lookup.count == 0


@testing.effect
def test_set_enforces_capacity_constraints():
    """set enforces capacity constraints"""
    cache = yield from _length_cache(2)
    yield from cache.set("a", 1)
    yield from cache.set("b", 2)
    assert (yield from cache.size()) == 2
    yield from cache.set("c", 3)
    assert (yield from cache.size()) == 2


@testing.effect
def test_set_resource_cleanup_when_overwriting_existing_entry():
    """resource cleanup when overwriting existing entry"""
    tracker = _Tracker()
    cache = yield from fx.ScopedCache.make(tracker.lookup, capacity=10)
    yield from cache.get("test")
    assert tracker.cleaned_up == []
    yield from cache.set("test", "new-value")
    assert tracker.cleaned_up == ["test"]


# --- has ------------------------------------------------------------------------


@testing.effect
def test_has_returns_true_for_existing_key():
    """returns true for existing key"""
    cache = yield from _length_cache()
    yield from cache.get("test")
    assert (yield from cache.has("test"))


@testing.effect
def test_has_returns_false_for_non_existent_key():
    """returns false for non-existent key"""
    cache = yield from _length_cache()
    assert not (yield from cache.has("test"))


@testing.effect
def test_has_returns_false_for_expired_key():
    """returns false for expired key"""
    cache = yield from _length_cache(time_to_live=_HOUR)
    yield from cache.get("test")
    yield from testing.adjust(2 * _HOUR)
    assert not (yield from cache.has("test"))


@testing.effect
def test_has_does_not_affect_lru_order():
    """does not affect LRU order"""
    cache = yield from _length_cache(2)
    yield from cache.get("a")
    yield from cache.get("b")
    assert (yield from cache.has("a"))
    yield from cache.get("c")

    assert not (yield from cache.has("a"))
    assert (yield from cache.has("b"))
    assert (yield from cache.has("c"))


# --- invalidate -----------------------------------------------------------------


@testing.effect
def test_invalidate_invalidates_existing_key():
    """invalidates existing key"""
    cache = yield from _length_cache()
    yield from cache.get("test")
    yield from cache.invalidate("test")
    assert not (yield from cache.has("test"))


@testing.effect
def test_invalidating_non_existent_key_doesnt_error():
    """invalidating non-existent key doesn't error"""
    cache = yield from _length_cache()
    yield from cache.invalidate("test")
    assert not (yield from cache.has("test"))


@testing.effect
def test_get_after_invalidate_invokes_lookup_again():
    """get after invalidate invokes lookup again"""
    _, bump = _counter()
    cache = yield from fx.ScopedCache.make(_always(bump), capacity=10)
    assert (yield from cache.get("test")) == 1
    yield from cache.invalidate("test")
    assert (yield from cache.get("test")) == 2


@testing.effect
def test_invalidate_resource_cleanup_when_invalidating_entry():
    """resource cleanup when invalidating entry"""
    tracker = _Tracker()
    cache = yield from fx.ScopedCache.make(tracker.lookup, capacity=10)
    yield from cache.get("test")
    assert tracker.cleaned_up == []
    yield from cache.invalidate("test")
    assert tracker.cleaned_up == ["test"]


# --- invalidateWhen -------------------------------------------------------------


@pytest.mark.parametrize("outcome", [fx.Success(1), exit.fail("error")])
@testing.effect
def test_invalidate_when_preserves_a_replacement_resource_after_an_old_lookup_completes(
    outcome: fx.Exit[int, str],
):
    """preserves a replacement resource after an old lookup completes (%#)"""
    acquired = [0]
    released: list[int] = []
    values: list[int] = []
    gate = yield from fx.Deferred[int, str].make()
    owner = fx.CloseableScope()

    def acquire() -> int:
        acquired[0] += 1
        return acquired[0]

    def release(value: int, _ex: fx.Exit[Any, Any]) -> fx.Effect[None]:
        return fx.sync(lambda: released.append(value))

    @fx.fn
    def lookup(_key: str):
        resource_id = yield from fx.acquire_release(fx.sync(acquire), release)
        if resource_id == 1:
            return (yield from gate.wait())
        return resource_id

    cache = yield from _in(owner, fx.ScopedCache.make(lookup, capacity=1))
    first = yield from cache.get("key").exit().fork(start_immediately=True)

    def matches(value: int) -> bool:
        values.append(value)
        return value == 1

    invalidator = yield from cache.invalidate_when("key", matches).fork(start_immediately=True)

    yield from cache.invalidate("key")
    replacement = yield from cache.get("key")
    yield from gate.done(outcome)
    original = yield from first.join()
    invalidated = yield from invalidator.join()
    cached = yield from cache.get_success("key")
    released_before_close = list(released)
    yield from owner.close(_DONE)

    assert released_before_close == [1]
    assert original == outcome
    assert values == ([1] if isinstance(outcome, fx.Success) else [])
    assert (invalidated, replacement, cached, released) == (False, 2, fx.Some(2), [1, 2])


@testing.effect
def test_invalidate_when_invalidates_when_predicate_matches():
    """invalidates when predicate matches"""
    cache = yield from _length_cache()
    yield from cache.get("test")
    assert (yield from cache.invalidate_when("test", lambda value: value == 4))
    assert not (yield from cache.has("test"))


@testing.effect
def test_invalidate_when_doesnt_invalidate_when_predicate_doesnt_match():
    """doesn't invalidate when predicate doesn't match"""
    cache = yield from _length_cache()
    yield from cache.get("test")
    assert not (yield from cache.invalidate_when("test", lambda value: value == 5))
    assert (yield from cache.has("test"))


@testing.effect
def test_invalidate_when_returns_false_for_non_existent_key():
    """returns false for non-existent key"""
    cache = yield from _length_cache()
    assert not (yield from cache.invalidate_when("test", lambda _: True))


@testing.effect
def test_invalidate_when_returns_false_for_failed_cached_value():
    """returns false for failed cached value"""
    cache = yield from fx.ScopedCache.make(_always(fx.fail("error")), capacity=10)
    yield from cache.get("test").exit()
    assert not (yield from cache.invalidate_when("test", lambda _: True))


@testing.effect
def test_invalidate_when_resource_cleanup_when_predicate_matches():
    """resource cleanup when predicate matches"""
    tracker = _Tracker()
    cache = yield from fx.ScopedCache.make(tracker.lookup, capacity=10)
    yield from cache.get("test")
    assert tracker.cleaned_up == []
    assert (yield from cache.invalidate_when("test", lambda value: "resource" in value))
    assert tracker.cleaned_up == ["test"]


# --- refresh --------------------------------------------------------------------


@testing.effect
def test_refresh_caches_a_synchronous_lookup_defect_for_a_missing_key():
    """caches a synchronous lookup defect for a missing key"""
    lookups = [0]

    def lookup(_key: str) -> fx.Effect[int]:
        lookups[0] += 1
        raise Exception("lookup defect")

    cache = yield from fx.ScopedCache.make(lookup, capacity=10)

    assert _died_with((yield from cache.refresh("test").exit()), "lookup defect")
    reader = yield from cache.get("test").exit().timeout_option(1).fork()
    yield from testing.adjust(1)
    read = yield from reader.join()
    assert isinstance(read, fx.Some) and _died_with(read.value, "lookup defect")
    assert lookups == [1]


@testing.effect
def test_refresh_replaces_an_existing_entry_with_a_synchronous_lookup_defect():
    """replaces an existing entry with a synchronous lookup defect"""
    fail = [False]
    released = [0]

    def release(_a: int, _ex: fx.Exit[Any, Any]) -> fx.Effect[None]:
        def bump() -> None:
            released[0] += 1

        return fx.sync(bump)

    def lookup(_key: str) -> fx.Effect[int, Never, fx.Scope]:
        if fail[0]:
            raise Exception("lookup defect")
        return fx.acquire_release(fx.succeed(42), release)

    cache = yield from fx.ScopedCache.make(lookup, capacity=10)
    assert (yield from cache.get("test")) == 42
    fail[0] = True

    assert _died_with((yield from cache.refresh("test").exit()), "lookup defect")
    assert _died_with((yield from cache.get("test").exit()), "lookup defect")
    assert released == [1]


@testing.effect
def test_refresh_existing_key_invokes_lookup_again():
    """refresh existing key invokes lookup again"""
    _, bump = _counter()
    cache = yield from fx.ScopedCache.make(_always(bump), capacity=10)
    yield from cache.get("test")
    assert (yield from cache.refresh("test")) == 2


@testing.effect
def test_refresh_non_existent_key_invokes_lookup_and_enforces_capacity():
    """refresh non-existent key invokes lookup and enforces capacity"""
    _, bump = _counter()
    cache = yield from fx.ScopedCache.make(_always(bump), capacity=1)
    yield from cache.set("other", 99)
    assert (yield from cache.refresh("test")) == 1
    assert (yield from cache.size()) == 1
    assert (yield from cache.keys()) == ["test"]


@testing.effect
def test_refresh_enforces_capacity_when_the_existing_key_is_evicted_during_lookup():
    """refresh enforces capacity when the existing key is evicted during lookup"""
    started = yield from fx.Deferred[None].make()
    result = yield from fx.Deferred[int].make()
    released: list[int] = []

    def release(value: int, _ex: fx.Exit[Any, Any]) -> fx.Effect[None]:
        return fx.sync(lambda: released.append(value))

    @fx.fn
    def lookup(key: str):
        if key == "a":
            value = yield from started.succeed(None).and_then(result.wait())
        else:
            value = 99
        return (yield from fx.acquire_release(fx.succeed(value), release))

    cache = yield from fx.ScopedCache.make(lookup, capacity=1)

    yield from cache.set("a", 1)
    refresh = yield from cache.refresh("a").fork(start_immediately=True)
    yield from started.wait()
    assert (yield from cache.get("b")) == 99
    assert not (yield from cache.has("a"))
    assert released == []

    yield from result.succeed(2)
    assert (yield from refresh.join()) == 2
    assert (yield from cache.size()) == 1
    assert sorted((yield from cache.keys())) == ["a"]
    assert released == [99]
    assert (yield from cache.get_success("a")) == fx.Some(2)

    yield from cache.invalidate_all()
    assert released == [99, 2]


@testing.effect
def test_refresh_updates_ttl():
    """refresh updates TTL"""
    cache = yield from _length_cache(time_to_live=_HOUR)
    yield from cache.get("test")
    yield from testing.adjust(30 * _MINUTE)
    yield from cache.refresh("test")
    yield from testing.adjust(40 * _MINUTE)
    assert (yield from cache.has("test"))


@testing.effect
def test_concurrent_refresh_calls_each_invoke_lookup_independently():
    """concurrent refresh calls each invoke lookup independently"""
    count, bump = _counter()
    cache = yield from fx.ScopedCache.make(_always(bump), capacity=10)
    yield from cache.get("test")
    count[0] = 0

    results = yield from fx.all(
        cache.refresh("test"), cache.refresh("test"), cache.refresh("test"), concurrency="unbounded"
    )
    assert count == [3]
    assert results == (1, 2, 3)


@testing.effect
def test_refresh_resource_cleanup_for_old_entry_after_refresh():
    """resource cleanup for old entry after refresh"""
    tracker = _Tracker()
    cache = yield from fx.ScopedCache.make(tracker.lookup, capacity=10)
    yield from cache.get("test")
    assert tracker.cleaned_up == []
    yield from cache.refresh("test")
    assert tracker.cleaned_up == ["test"]


# --- invalidateAll --------------------------------------------------------------


@pytest.mark.parametrize("operation", ["invalidateAll", "owner scope closure"])
@testing.effect
def test_releases_every_entry_and_propagates_all_release_defects(operation: str):
    """%s releases every entry and propagates all release defects"""
    owner = fx.CloseableScope()
    released: list[str] = []

    def lookup(key: str) -> fx.Effect[str, Never, fx.Scope]:
        def release(_a: str, _ex: fx.Exit[Any, Any]) -> fx.Effect[None]:
            def run() -> fx.Effect[None]:
                released.append(key)
                return fx.void if key == "healthy" else fx.die(Exception(f"release {key}"))

            return fx.suspend(run)

        return fx.acquire_release(fx.succeed(key), release)

    cache = yield from _in(owner, fx.ScopedCache.make(lookup, capacity=10))
    for key in ["a", "b", "healthy"]:
        yield from cache.get(key)

    closing = cache.invalidate_all() if operation == "invalidateAll" else owner.close(_DONE)
    ex = yield from closing.exit()
    assert sorted(released) == ["a", "b", "healthy"]
    assert (yield from cache.size()) == 0
    yield from owner.close(_DONE)
    assert isinstance(ex, fx.Failure)
    reasons: tuple[object, ...] = ex.cause.reasons
    assert sorted(str(r.defect) if isinstance(r, Die) else type(r).__name__ for r in reasons) == [
        "release a",
        "release b",
    ]


@pytest.mark.parametrize("yield_before_refresh", [False, True])
@testing.effect
def test_retains_ownership_of_entries_refreshed_by_finalizers(yield_before_refresh: bool):
    """retains ownership of entries refreshed by finalizers (yield: %s)"""
    acquired = [0]
    released: list[int] = []
    caches: list[fx.ScopedCache[str, int]] = []

    def acquire() -> int:
        acquired[0] += 1
        return acquired[0]

    @fx.fn
    def release(value: int, _ex: fx.Exit[Any, Any]):
        released.append(value)
        if value == 1:
            if yield_before_refresh:
                yield from fx.yield_now()
            yield from caches[0].refresh("key")

    def lookup(_key: str) -> fx.Effect[int, Never, fx.Scope]:
        return fx.acquire_release(fx.sync(acquire), release)

    def program():
        cache = yield from fx.ScopedCache.make(lookup, capacity=10)
        caches.append(cache)
        yield from cache.get("key")
        yield from cache.invalidate_all()
        assert released == [1]
        return (yield from cache.get_success("key"))

    cached = yield from fx.scoped(fx.gen(program))

    assert acquired == [2]
    assert released == [1, 2]
    assert cached == fx.Some(2)


@testing.effect
def test_removes_all_entries_before_running_finalizers():
    """removes all entries before running finalizers"""
    observed: list[list[str]] = []
    caches: list[fx.ScopedCache[str, str]] = []

    def release(_a: str, _ex: fx.Exit[Any, Any]) -> fx.Effect[None]:
        return caches[0].keys().map(observed.append)

    def lookup(key: str) -> fx.Effect[str, Never, fx.Scope]:
        return fx.acquire_release(fx.succeed(key), release)

    cache = yield from fx.ScopedCache.make(lookup, capacity=10)
    caches.append(cache)
    yield from cache.get("first")
    yield from cache.get("second")
    yield from cache.invalidate_all()

    assert observed == [[], []]


@testing.effect
def test_invalidate_all_clears_all_entries():
    """clears all entries"""
    cache = yield from _length_cache()
    for key in ["a", "b", "c"]:
        yield from cache.get(key)
    yield from cache.invalidate_all()
    for key in ["a", "b", "c"]:
        assert not (yield from cache.has(key))


@testing.effect
def test_size_becomes_0_after_invalidate_all():
    """size becomes 0 after invalidateAll"""
    cache = yield from _length_cache()
    for key in ["a", "b", "c"]:
        yield from cache.get(key)
    yield from cache.invalidate_all()
    assert (yield from cache.size()) == 0


@testing.effect
def test_all_keys_return_none_after_invalidate_all():
    """all keys return None after invalidateAll"""
    cache = yield from _length_cache()
    yield from cache.get("a")
    yield from cache.get("b")
    yield from cache.invalidate_all()
    assert (yield from cache.get_option("a")) is None
    assert (yield from cache.get_option("b")) is None


@testing.effect
def test_invalidate_all_resource_cleanup_for_all_entries():
    """resource cleanup for all entries"""
    tracker = _Tracker()
    cache = yield from fx.ScopedCache.make(tracker.lookup, capacity=10)
    for key in ["test1", "test2", "test3"]:
        yield from cache.get(key)
    assert tracker.cleaned_up == []
    assert (yield from cache.invalidate_all()) is None
    assert sorted(tracker.cleaned_up) == ["test1", "test2", "test3"]


# --- size -----------------------------------------------------------------------


@testing.effect
def test_size_empty_cache_returns_0():
    """empty cache returns 0"""
    cache = yield from _length_cache()
    assert (yield from cache.size()) == 0


@testing.effect
def test_size_returns_correct_count_after_adding_entries():
    """returns correct count after adding entries"""
    cache = yield from _length_cache()
    for key in ["a", "b", "c"]:
        yield from cache.get(key)
    assert (yield from cache.size()) == 3


@testing.effect
def test_size_decreases_after_invalidation():
    """decreases after invalidation"""
    cache = yield from _length_cache()
    for key in ["a", "b", "c"]:
        yield from cache.get(key)
    yield from cache.invalidate("b")
    assert (yield from cache.size()) == 2


@testing.effect
def test_size_expired_entries_are_counted_until_accessed():
    """expired entries are counted until accessed"""
    cache = yield from _length_cache(time_to_live=_HOUR)
    yield from cache.get("a")
    yield from cache.get("b")
    yield from testing.adjust(2 * _HOUR)

    assert (yield from cache.size()) == 2
    yield from cache.has("a")
    assert (yield from cache.size()) == 1


# --- keys -----------------------------------------------------------------------


@testing.effect
def test_keys_returns_all_active_keys():
    """returns all active keys"""
    cache = yield from _length_cache()
    for key in ["a", "b", "c"]:
        yield from cache.get(key)
    assert sorted((yield from cache.keys())) == ["a", "b", "c"]


@testing.effect
def test_keys_excludes_keys_for_expired_entries():
    """excludes keys for expired entries"""
    cache = yield from _length_cache(time_to_live=_HOUR)
    yield from cache.get("a")
    yield from cache.get("b")
    yield from testing.adjust(2 * _HOUR)
    assert (yield from cache.keys()) == []


@testing.effect
def test_keys_empty_after_invalidate_all():
    """empty after invalidateAll"""
    cache = yield from _length_cache()
    yield from cache.get("a")
    yield from cache.get("b")
    yield from cache.invalidate_all()
    assert (yield from cache.keys()) == []


def _expiring_tracker():
    tracker = _Tracker()
    return tracker, fx.ScopedCache.make(tracker.lookup, capacity=10, time_to_live=_HOUR)


@testing.effect
def test_keys_resource_cleanup_for_expired_entries_as_side_effect():
    """resource cleanup for expired entries as side effect"""
    tracker, make = _expiring_tracker()
    cache = yield from make
    yield from cache.get("a")
    yield from cache.get("b")
    assert tracker.cleaned_up == []
    yield from testing.adjust(2 * _HOUR)

    assert (yield from cache.keys()) == []
    assert sorted(tracker.cleaned_up) == ["a", "b"]


# --- values ---------------------------------------------------------------------


@testing.effect
def test_values_returns_all_successful_cached_values():
    """returns all successful cached values"""
    cache = yield from _length_cache(time_to_live=_HOUR)
    for key in ["a", "ab", "abc"]:
        yield from cache.get(key)
    assert sorted((yield from cache.values())) == [1, 2, 3]


@testing.effect
def test_values_doesnt_include_failed_lookups():
    """doesn't include failed lookups"""
    cache = yield from fx.ScopedCache.make(_fail_or_length, capacity=10, time_to_live=_HOUR)
    yield from cache.get("a")
    yield from cache.get("fail").exit()
    yield from cache.get("ab")
    assert sorted((yield from cache.values())) == [1, 2]


@testing.effect
def test_values_doesnt_include_expired_values():
    """doesn't include expired values"""
    cache = yield from _length_cache(time_to_live=_HOUR)
    yield from cache.get("a")
    yield from cache.get("b")
    yield from testing.adjust(2 * _HOUR)
    assert (yield from cache.values()) == []


@testing.effect
def test_values_resource_cleanup_for_expired_entries_as_side_effect():
    """resource cleanup for expired entries as side effect"""
    tracker, make = _expiring_tracker()
    cache = yield from make
    yield from cache.get("a")
    yield from cache.get("b")
    assert tracker.cleaned_up == []
    yield from testing.adjust(2 * _HOUR)

    assert (yield from cache.values()) == []
    assert sorted(tracker.cleaned_up) == ["a", "b"]


# --- entries --------------------------------------------------------------------


@testing.effect
def test_entries_returns_all_key_value_pairs():
    """returns all key-value pairs"""
    cache = yield from _length_cache(time_to_live=_HOUR)
    for key in ["a", "ab", "abc"]:
        yield from cache.get(key)
    assert sorted((yield from cache.entries())) == [("a", 1), ("ab", 2), ("abc", 3)]


@testing.effect
def test_entries_filters_out_failed_lookups():
    """filters out failed lookups"""
    cache = yield from fx.ScopedCache.make(_fail_or_length, capacity=10, time_to_live=_HOUR)
    yield from cache.get("a")
    yield from cache.get("fail").exit()
    yield from cache.get("ab")
    assert sorted((yield from cache.entries())) == [("a", 1), ("ab", 2)]


@testing.effect
def test_entries_filters_out_expired_entries():
    """filters out expired entries"""
    cache = yield from _length_cache(time_to_live=_HOUR)
    yield from cache.get("a")
    yield from testing.adjust(_HOUR)
    yield from cache.get("b")
    assert (yield from cache.entries()) == [("b", 1)]


@testing.effect
def test_entries_removes_expired_entries_as_side_effect_with_resource_cleanup():
    """removes expired entries as side effect with resource cleanup"""
    tracker, make = _expiring_tracker()
    cache = yield from make
    yield from cache.get("a")
    yield from cache.get("b")
    yield from testing.adjust(2 * _HOUR)

    assert (yield from cache.size()) == 2
    entries = yield from cache.entries()
    assert (yield from cache.size()) == 0
    assert entries == []
    assert sorted(tracker.cleaned_up) == ["a", "b"]


# --- capacity management --------------------------------------------------------


@testing.effect
def test_lru_oldest_entries_removed_when_capacity_exceeded():
    """oldest entries removed when capacity exceeded"""
    cache = yield from _length_cache(3)
    for key in ["first", "second", "third"]:
        yield from cache.get(key)
    for key in ["first", "second", "third"]:
        assert (yield from cache.has(key))
    yield from cache.get("fourth")

    assert not (yield from cache.has("first"))
    for key in ["second", "third", "fourth"]:
        assert (yield from cache.has(key))


@testing.effect
def test_lru_access_order_determines_eviction():
    """access order determines eviction"""
    cache = yield from _length_cache(3)
    for key in ["a", "b", "c", "a", "d"]:
        yield from cache.get(key)
    assert (yield from cache.has("a"))
    assert not (yield from cache.has("b"))
    assert (yield from cache.has("c"))
    assert (yield from cache.has("d"))


@testing.effect
def test_lru_capacity_of_1():
    """capacity of 1"""
    cache = yield from _length_cache(1)
    yield from cache.get("a")
    assert (yield from cache.has("a"))
    yield from cache.get("b")
    assert not (yield from cache.has("a"))
    assert (yield from cache.has("b"))
    yield from cache.get("c")
    assert not (yield from cache.has("b"))
    assert (yield from cache.has("c"))


@testing.effect
def test_lru_very_large_capacity():
    """very large capacity"""
    cache = yield from _length_cache(10000)
    for i in range(100):
        yield from cache.get(f"key-{i}")
    for i in range(100):
        assert (yield from cache.has(f"key-{i}"))
    assert (yield from cache.size()) == 100


@testing.effect
def test_lru_resource_cleanup_for_evicted_entries():
    """resource cleanup for evicted entries"""
    tracker = _Tracker()
    cache = yield from fx.ScopedCache.make(tracker.lookup, capacity=2)
    yield from cache.get("a")
    yield from cache.get("b")
    assert tracker.cleaned_up == []
    yield from cache.get("c")
    assert tracker.cleaned_up == ["a"]
    yield from cache.get("d")
    assert tracker.cleaned_up == ["a", "b"]


# --- fixed TTL ------------------------------------------------------------------


@testing.effect
def test_fixed_ttl_entry_expires_after_specified_duration():
    """entry expires after specified duration"""
    cache = yield from _length_cache(time_to_live=2 * _HOUR)
    yield from cache.get("test")
    yield from testing.adjust(_HOUR)
    assert (yield from cache.has("test"))
    yield from testing.adjust(_HOUR + 1)
    assert not (yield from cache.has("test"))


@testing.effect
def test_fixed_ttl_get_after_expiration_invokes_lookup():
    """get after expiration invokes lookup"""
    count, bump = _counter()
    cache = yield from fx.ScopedCache.make(_always(bump), capacity=10, time_to_live=_HOUR)
    assert (yield from cache.get("test")) == 1
    assert count == [1]
    yield from testing.adjust(2 * _HOUR)
    assert (yield from cache.get("test")) == 2
    assert count == [2]


@testing.effect
def test_fixed_ttl_has_returns_false_for_expired_entries():
    """has returns false for expired entries"""
    cache = yield from _length_cache(time_to_live=_HOUR)
    yield from cache.get("test")
    assert (yield from cache.has("test"))
    yield from testing.adjust(2 * _HOUR)
    assert not (yield from cache.has("test"))


@testing.effect
def test_fixed_ttl_resource_cleanup_for_expired_entries():
    """resource cleanup for expired entries"""
    tracker, make = _expiring_tracker()
    cache = yield from make
    yield from cache.get("test")
    assert tracker.cleaned_up == []
    yield from testing.adjust(2 * _HOUR)
    yield from cache.has("test")
    assert tracker.cleaned_up == ["test"]


# --- function-based TTL ---------------------------------------------------------


@testing.effect
def test_function_ttl_different_ttl_for_success_vs_failure():
    """different TTL for success vs failure"""

    def ttl(ex: fx.Exit[int, str], _key: str) -> float:
        return 2 * _HOUR if isinstance(ex, fx.Success) else 30 * _MINUTE

    cache = yield from fx.ScopedCache.make(_fail_or_length, capacity=10, time_to_live=ttl)
    yield from cache.get("success")
    yield from cache.get("fail").exit()

    yield from testing.adjust(_HOUR)
    assert (yield from cache.has("success"))
    assert not (yield from cache.has("fail"))
    yield from testing.adjust(2 * _HOUR)
    assert not (yield from cache.has("success"))


@testing.effect
def test_function_ttl_ttl_based_on_key():
    """TTL based on key"""

    def ttl(_ex: fx.Exit[int, Never], key: str) -> float:
        if key.startswith("short-"):
            return _MINUTE
        if key.startswith("medium-"):
            return _HOUR
        return 24 * _HOUR

    cache = yield from fx.ScopedCache.make(_length, capacity=10, time_to_live=ttl)
    for key in ["short-item", "medium-item", "long-item"]:
        yield from cache.get(key)

    yield from testing.adjust(2 * _MINUTE)
    assert not (yield from cache.has("short-item"))
    assert (yield from cache.has("medium-item"))
    assert (yield from cache.has("long-item"))

    yield from testing.adjust(2 * _HOUR)
    assert not (yield from cache.has("medium-item"))
    assert (yield from cache.has("long-item"))


@testing.effect
def test_function_ttl_ttl_based_on_value():
    """TTL based on value"""

    def ttl(ex: fx.Exit[int, Never], _key: str) -> float:
        if isinstance(ex, fx.Success):
            return _HOUR if ex.value > 5 else _MINUTE
        return float("inf")

    cache = yield from fx.ScopedCache.make(_length, capacity=10, time_to_live=ttl)
    yield from cache.get("abc")
    yield from cache.get("longkey")
    yield from testing.adjust(2 * _MINUTE)
    assert not (yield from cache.has("abc"))
    assert (yield from cache.has("longkey"))


@testing.effect
def test_function_ttl_infinite_ttl():
    """infinite TTL"""
    cache = yield from fx.ScopedCache.make(
        _length, capacity=10, time_to_live=lambda _ex, _key: float("inf")
    )
    yield from cache.get("test")
    yield from testing.adjust(365 * 24 * _HOUR)
    assert (yield from cache.has("test"))


@testing.effect
def test_function_ttl_zero_duration_ttl():
    """zero duration TTL"""
    cache = yield from fx.ScopedCache.make(_length, capacity=10, time_to_live=lambda _ex, _key: 0)
    yield from cache.get("test")
    assert not (yield from cache.has("test"))


@testing.effect
def test_function_ttl_ttl_updates_on_refresh():
    """TTL updates on refresh"""
    count, bump = _counter()

    def ttl(ex: fx.Exit[int, Never], _key: str) -> float:
        if isinstance(ex, fx.Success):
            return _HOUR if count[0] == 1 else 2 * _HOUR
        return float("inf")

    cache = yield from fx.ScopedCache.make(_always(bump), capacity=10, time_to_live=ttl)
    yield from cache.get("test")
    yield from testing.adjust(30 * _MINUTE)
    assert (yield from cache.has("test"))

    yield from cache.refresh("test")
    yield from testing.adjust(_HOUR)
    assert (yield from cache.has("test"))
    yield from testing.adjust(_HOUR)
    assert not (yield from cache.has("test"))


# --- failed lookups -------------------------------------------------------------


@testing.effect
def test_settles_concurrent_gets_when_ttl_calculation_throws_after_an_asynchronous_lookup():
    """settles concurrent gets when TTL calculation throws after an asynchronous lookup"""
    started = yield from fx.Latch.make()
    finish = yield from fx.Latch.make()

    def ttl(_ex: fx.Exit[int, Never], _key: str) -> float:
        raise Exception("TTL defect")

    cache = yield from fx.ScopedCache.make(
        _always(started.open().and_then(finish.wait().as_(42))), capacity=10, time_to_live=ttl
    )

    first = yield from cache.get("test").exit().timeout_option(1).fork(start_immediately=True)
    yield from started.wait()
    second = yield from cache.get("test").exit().timeout_option(1).fork(start_immediately=True)
    yield from fx.yield_now()
    yield from finish.open()
    yield from testing.adjust(1)

    assert (yield from first.join()) == fx.Some(fx.Success(42))
    assert (yield from second.join()) == fx.Some(fx.Success(42))


@testing.effect
def test_does_not_cache_an_asynchronous_failure_with_zero_ttl():
    """does not cache an asynchronous failure with zero TTL"""
    count, bump = _counter()

    def ttl(ex: fx.Exit[int, str], _key: str) -> float:
        return 0 if isinstance(ex, fx.Failure) else float("inf")

    def fail_first(n: int) -> fx.Effect[int, str]:
        return fx.fail("error") if n == 1 else fx.succeed(n)

    lookup = fx.yield_now().and_then(bump).flat_map(fail_first)
    cache = yield from fx.ScopedCache.make(_always(lookup), capacity=10, time_to_live=ttl)

    assert (yield from cache.get("test").exit()) == exit.fail("error")
    assert (yield from cache.get("test").exit()) == fx.Success(2)
    assert count == [2]


@testing.effect
def test_failed_lookup_caches_the_failure():
    """failed lookup caches the failure"""
    count, bump = _counter()
    cache = yield from fx.ScopedCache.make(_always(bump.and_then(fx.fail("error"))), capacity=10)
    assert (yield from cache.get("test").exit()) == exit.fail("error")
    assert (yield from cache.get("test").exit()) == exit.fail("error")
    assert count == [1]


@testing.effect
def test_subsequent_gets_return_same_failure():
    """subsequent gets return same failure"""
    cache = yield from fx.ScopedCache.make(_always(fx.fail("lookup failed")), capacity=10)
    results = yield from fx.all(
        cache.get("test").exit(), cache.get("test").exit(), cache.get("test").exit()
    )
    assert results == (exit.fail("lookup failed"),) * 3


@testing.effect
def test_can_refresh_after_failure():
    """can refresh after failure"""
    should_fail = [True]

    def lookup(_key: str) -> fx.Effect[int, str]:
        return fx.fail("error") if should_fail[0] else fx.succeed(42)

    cache = yield from fx.ScopedCache.make(lookup, capacity=10)
    assert isinstance((yield from cache.get("test").exit()), fx.Failure)
    should_fail[0] = False
    assert (yield from cache.refresh("test")) == 42


@testing.effect
def test_multiple_fibers_encountering_same_error():
    """multiple fibers encountering same error"""
    count, bump = _counter()
    cache = yield from fx.ScopedCache.make(
        _always(bump.and_then(fx.fail("error")).delay(0.05)), capacity=10
    )
    fibers = yield from fx.all(
        cache.get("test").exit().fork(),
        cache.get("test").exit().fork(),
        cache.get("test").exit().fork(),
    )
    yield from testing.adjust(0.1)
    results = yield from fx.Fiber.join_all(fibers)

    assert count == [1]
    assert results == [exit.fail("error")] * 3


@testing.effect
def test_resource_cleanup_for_failed_entries():
    """resource cleanup for failed entries"""
    log: list[str] = []

    def lookup(key: str) -> fx.Effect[str, str, fx.Scope]:
        return _tracked(log)(key).and_then(fx.fail(f"error-{key}"))

    cache = yield from fx.ScopedCache.make(lookup, capacity=2)
    yield from cache.get("fail1").exit()
    yield from cache.get("fail2").exit()
    assert log == ["acquired-fail1", "acquired-fail2"]

    yield from cache.get("fail3").exit()
    assert log == ["acquired-fail1", "acquired-fail2", "released-fail1", "acquired-fail3"]


# --- scope integration ----------------------------------------------------------


@testing.effect
def test_resources_are_properly_scoped_to_cache_entries():
    """resources are properly scoped to cache entries"""
    log: list[str] = []
    cache = yield from fx.ScopedCache.make(_tracked(log), capacity=10)
    yield from cache.get("test")
    assert log == ["acquired-test"]
    yield from cache.get("test")
    assert log == ["acquired-test"]


@testing.effect
def test_resources_are_cleaned_up_when_entries_are_evicted():
    """resources are cleaned up when entries are evicted"""
    log: list[str] = []
    cache = yield from fx.ScopedCache.make(_tracked(log), capacity=2)
    yield from cache.get("a")
    yield from cache.get("b")
    assert log == ["acquired-a", "acquired-b"]
    yield from cache.get("c")
    assert log == ["acquired-a", "acquired-b", "released-a", "acquired-c"]


@testing.effect
def test_resources_are_cleaned_up_when_cache_is_closed():
    """resources are cleaned up when cache is closed"""
    log: list[str] = []

    def program():
        cache = yield from fx.ScopedCache.make(_tracked(log), capacity=10)
        yield from cache.get("test1")
        yield from cache.get("test2")
        assert log == ["acquired-test1", "acquired-test2"]
        return cache

    cache = yield from fx.scoped(fx.gen(program))
    assert cache.is_closed
    assert sorted(log) == [
        "acquired-test1",
        "acquired-test2",
        "released-test1",
        "released-test2",
    ]


@testing.effect
def test_resources_are_cleaned_up_when_entries_expire():
    """resources are cleaned up when entries expire"""
    log: list[str] = []
    cache = yield from fx.ScopedCache.make(_tracked(log), capacity=10, time_to_live=_HOUR)
    yield from cache.get("test")
    assert log == ["acquired-test"]
    yield from testing.adjust(2 * _HOUR)
    yield from cache.has("test")
    assert log == ["acquired-test", "released-test"]


@testing.effect
def test_resources_are_cleaned_up_when_entries_are_invalidated():
    """resources are cleaned up when entries are invalidated"""
    log: list[str] = []
    cache = yield from fx.ScopedCache.make(_tracked(log), capacity=10)
    yield from cache.get("test")
    assert log == ["acquired-test"]
    yield from cache.invalidate("test")
    assert log == ["acquired-test", "released-test"]


@testing.effect
def test_resource_cleanup_is_atomic_and_doesnt_leak():
    """resource cleanup is atomic and doesn't leak"""
    log: list[str] = []
    cache = yield from fx.ScopedCache.make(_tracked(log), capacity=3)
    for key in ["a", "b", "c"]:
        yield from cache.get(key)

    yield from fx.all(
        cache.invalidate("a"),
        cache.refresh("b"),
        cache.set("c", "new-value"),
        cache.get("d"),
        concurrency="unbounded",
    )

    assert len([entry for entry in log if entry.startswith("acquired")]) == 5
    assert len([entry for entry in log if entry.startswith("released")]) == 3
    assert (yield from cache.size()) == 3


@testing.effect
def test_cache_becomes_closed_when_parent_scope_is_closed():
    """cache becomes closed when parent scope is closed"""

    def program():
        cache = yield from _length_cache()
        assert not cache.is_closed
        yield from cache.get("test")
        return cache

    cache = yield from fx.scoped(fx.gen(program))
    assert cache.is_closed


@testing.effect
def test_resource_cleanup_happens_in_correct_order_during_cache_closure():
    """resource cleanup happens in correct order during cache closure"""
    log: list[str] = []

    def program():
        cache = yield from fx.ScopedCache.make(_tracked(log), capacity=10)
        for key in ["first", "second", "third"]:
            yield from cache.get(key)
        assert log == ["acquired-first", "acquired-second", "acquired-third"]

    yield from fx.scoped(fx.gen(program))
    releases = [entry for entry in log if entry.startswith("released")]
    assert sorted(releases) == ["released-first", "released-second", "released-third"]


# --- service context ------------------------------------------------------------


class _ConfigService(fx.Tag[int]): ...


class _CounterService(fx.Tag[int]): ...


@testing.effect
def test_services_are_available_in_lookup_functions():
    """services are available in lookup functions"""

    @fx.fn
    def lookup(key: str):
        multiplier = yield from _ConfigService()
        return len(key) * multiplier

    cache = yield from fx.ScopedCache.make(lookup, capacity=10).pipe(
        fx.provide_service(_ConfigService, 10)
    )
    assert (yield from cache.get("test")) == 40


@testing.effect
def test_require_services_at_lookup_provides_services_at_lookup_time():
    """requireServicesAt: 'lookup' provides services at lookup time"""
    cache = yield from fx.ScopedCache.make(
        _always(_CounterService()), capacity=10, require_services_at="lookup"
    )

    result1 = yield from cache.get("test").pipe(fx.provide_service(_CounterService, 42))
    result2 = yield from cache.get("another").pipe(fx.provide_service(_CounterService, 100))
    result3 = yield from cache.get("test").pipe(fx.provide_service(_CounterService, 200))

    assert (result1, result2, result3) == (42, 100, 42)


# --- integration ----------------------------------------------------------------


@testing.effect
def test_multiple_time_advances_work_correctly():
    """multiple time advances work correctly"""
    cache = yield from _length_cache(time_to_live=_HOUR)
    yield from cache.get("test")
    for _ in range(10):
        yield from testing.adjust(5 * _MINUTE)
        assert (yield from cache.has("test"))
    yield from testing.adjust(15 * _MINUTE)
    assert not (yield from cache.has("test"))


@testing.effect
def test_resource_cleanup_timing_is_correct():
    """resource cleanup timing is correct"""
    cleanups: list[tuple[str, float]] = []

    def lookup(key: str) -> fx.Effect[int, Never, fx.Scope]:
        def release(_a: None, _ex: fx.Exit[Any, Any]) -> fx.Effect[None]:
            return clock.now().map(lambda time: cleanups.append((key, time)))

        return fx.acquire_release(fx.void, release).as_(len(key))

    cache = yield from fx.ScopedCache.make(lookup, capacity=10, time_to_live=_HOUR)
    start = yield from clock.now()

    yield from cache.get("a")
    yield from testing.adjust(30 * _MINUTE)
    yield from cache.get("b")
    yield from testing.adjust(35 * _MINUTE)  # "a" expires
    yield from cache.has("a")
    yield from testing.adjust(30 * _MINUTE)  # "b" expires
    yield from cache.has("b")

    assert cleanups == [("a", start + 65 * _MINUTE), ("b", start + 95 * _MINUTE)]


@testing.effect
def test_string_keys_work_correctly():
    """string keys work correctly"""

    def shout(key: str) -> fx.Effect[str]:
        return fx.succeed(key.upper())

    cache = yield from fx.ScopedCache.make(shout, capacity=10)
    yield from cache.set("hello", "HELLO!")
    assert (yield from cache.get("hello")) == "HELLO!"
    assert (yield from cache.get("world")) == "WORLD"


@testing.effect
def test_number_keys_work_correctly():
    """number keys work correctly"""

    def square(key: int) -> fx.Effect[int]:
        return fx.succeed(key * key)

    cache = yield from fx.ScopedCache.make(square, capacity=10)
    yield from cache.set(5, 25)
    assert (yield from cache.get(5)) == 25
    assert (yield from cache.get(7)) == 49


@dataclass(frozen=True)
class _CacheKey:
    user_id: str
    product_id: int


@testing.effect
def test_complex_object_keys_work_correctly():
    """complex object keys work correctly"""

    def lookup(key: _CacheKey) -> fx.Effect[str]:
        return fx.succeed(f"{key.user_id}-{key.product_id}")

    cache = yield from fx.ScopedCache.make(lookup, capacity=10)
    assert (yield from cache.get(_CacheKey("user1", 100))) == "user1-100"
    assert (yield from cache.get(_CacheKey("user2", 200))) == "user2-200"
    assert (yield from cache.has(_CacheKey("user1", 100)))


# --- concurrency ----------------------------------------------------------------


@testing.effect
def test_a_get_made_while_an_abandoned_lookup_is_finalizing_starts_a_new_lookup():
    """a get made while an abandoned lookup is finalizing starts a new lookup"""
    lookups = [0]
    started = yield from fx.Latch.make()
    finalizing = yield from fx.Latch.make()
    finish_finalizer = yield from fx.Latch.make()

    def lookup(_key: str) -> fx.Effect[int]:
        def run() -> fx.Effect[int]:
            lookups[0] += 1
            if lookups[0] > 1:
                return fx.succeed(lookups[0])
            return (
                started.open()
                .and_then(fx.never)
                .on_interrupt(finalizing.open().and_then(finish_finalizer.wait()))
            )

        return fx.suspend(run)

    cache = yield from fx.ScopedCache.make(lookup, capacity=10)

    first = yield from cache.get("key").fork(start_immediately=True)
    yield from started.wait()
    interrupt_first = yield from first.interrupt().fork(start_immediately=True)
    yield from finalizing.wait()
    fresh = yield from cache.get("key").fork(start_immediately=True)
    yield from finish_finalizer.open()
    yield from interrupt_first.join()

    assert (yield from fresh.await_exit()) == fx.Success(2)
    assert (yield from cache.get("key")) == 2
    assert lookups == [2]


def _evicting_lookup(
    closing: fx.Latch, close: fx.Latch, then: Callable[[], fx.Effect[int, Never, fx.Scope]]
) -> Callable[[str], fx.Effect[int, Never, fx.Scope]]:
    """Key ``a`` holds a resource whose release opens ``closing`` and waits
    for ``close``; other keys run ``then()``."""

    def release(_a: None, _ex: fx.Exit[Any, Any]) -> fx.Effect[None]:
        return closing.open().and_then(close.wait())

    def lookup(key: str) -> fx.Effect[int, Never, fx.Scope]:
        if key == "a":
            return fx.acquire_release(fx.void, release).as_(1)
        return then()

    return lookup


@testing.effect
def test_get_option_waiter_arriving_during_eviction_keeps_the_lookup_alive():
    """a getOption waiter arriving during eviction keeps the lookup alive when the first caller leaves"""  # noqa: E501
    closing = yield from fx.Latch.make()
    close = yield from fx.Latch.make()
    started = yield from fx.Latch.make()
    finish = yield from fx.Latch.make()

    def then() -> fx.Effect[int, Never, fx.Scope]:
        return started.open().and_then(finish.wait()).as_(42)

    cache = yield from fx.ScopedCache.make(_evicting_lookup(closing, close, then), capacity=1)

    yield from cache.get("a")
    first = yield from cache.get("b").fork(start_immediately=True)
    yield from closing.wait()
    second = yield from cache.get_option("b").fork(start_immediately=True)
    yield from close.open()
    yield from started.wait()
    yield from fx.yield_now()
    yield from first.interrupt()
    yield from finish.open()

    assert (yield from second.await_exit()) == fx.Success(fx.Some(42))
    assert (yield from cache.get("b")) == 42


def _held_forever(
    acquired: fx.Latch, counts: dict[str, int]
) -> Callable[[], fx.Effect[int, Never, fx.Scope]]:
    """A lookup that acquires a counted resource, opens ``acquired`` and
    never ends."""

    def count(name: str) -> fx.Effect[None]:
        def bump() -> None:
            counts[name] += 1

        return fx.sync(bump)

    def then() -> fx.Effect[int, Never, fx.Scope]:
        hold = fx.acquire_release(count("acquisitions"), lambda _a, _e: count("releases"))
        return hold.and_then(acquired.open()).and_then(fx.never)

    return then


@testing.effect
def test_interrupting_the_only_caller_during_eviction_releases_its_lookup():
    """interrupting the only caller during eviction releases its lookup"""
    closing = yield from fx.Latch.make()
    close = yield from fx.Latch.make()
    acquired = yield from fx.Latch.make()
    counts = {"acquisitions": 0, "releases": 0}
    lookup = _evicting_lookup(closing, close, _held_forever(acquired, counts))
    cache = yield from fx.ScopedCache.make(lookup, capacity=1)

    yield from cache.get("a")
    caller = yield from cache.get("b").fork(start_immediately=True)
    yield from closing.wait()
    interrupt = yield from caller.interrupt().fork(start_immediately=True)
    yield from fx.yield_now()
    yield from close.open()
    yield from acquired.wait()
    yield from interrupt.join()

    assert counts == {"acquisitions": 1, "releases": 1}
    assert (yield from cache.size()) == 0


@testing.effect
def test_an_interrupt_during_eviction_does_not_strand_a_pending_lookup():
    """an interrupt during eviction does not strand a pending lookup"""
    closing = yield from fx.Latch.make()
    close = yield from fx.Latch.make()
    acquired = yield from fx.Latch.make()
    counts = {"acquisitions": 0, "releases": 0}
    lookup = _evicting_lookup(closing, close, _held_forever(acquired, counts))
    cache = yield from fx.ScopedCache.make(lookup, capacity=1)

    yield from cache.get("a")
    first = yield from cache.get("b").fork(start_immediately=True)
    yield from closing.wait()
    interrupt_first = yield from first.interrupt().fork(start_immediately=True)
    yield from fx.yield_now()
    yield from close.open()
    yield from acquired.wait()
    second = yield from cache.get("b").fork(start_immediately=True)
    yield from fx.yield_now()
    yield from second.interrupt()
    yield from interrupt_first.join()

    assert counts["acquisitions"] > 0
    assert counts["releases"] == counts["acquisitions"]
    assert (yield from cache.size()) == 0


def _started_then_42(started: fx.Latch, finish: fx.Latch) -> Callable[[str], fx.Effect[int]]:
    return _always(started.open().and_then(finish.wait().as_(42)))


@testing.effect
def test_an_interrupted_get_does_not_poison_a_get_option_waiter():
    """an interrupted get does not poison a getOption waiter"""
    started = yield from fx.Latch.make()
    finish = yield from fx.Latch.make()
    cache = yield from fx.ScopedCache.make(_started_then_42(started, finish), capacity=10)

    first = yield from cache.get("key").fork(start_immediately=True)
    yield from started.wait()
    second = yield from cache.get_option("key").fork(start_immediately=True)
    yield from fx.yield_now()
    yield from first.interrupt()
    yield from finish.open()

    assert (yield from second.await_exit()) == fx.Success(fx.Some(42))


@testing.effect
def test_an_interrupted_get_does_not_poison_an_invalidate_when_waiter():
    """an interrupted get does not poison an invalidateWhen waiter"""
    started = yield from fx.Latch.make()
    finish = yield from fx.Latch.make()
    cache = yield from fx.ScopedCache.make(_started_then_42(started, finish), capacity=10)

    first = yield from cache.get("key").fork(start_immediately=True)
    yield from started.wait()
    waiter = yield from cache.invalidate_when("key", lambda _: False).fork(start_immediately=True)
    yield from fx.yield_now()
    yield from first.interrupt()
    yield from finish.open()

    assert (yield from waiter.await_exit()) == fx.Success(False)
    assert (yield from cache.get("key")) == 42


@testing.effect
def test_an_interrupted_refresh_does_not_poison_a_get_joining_its_new_entry():
    """an interrupted refresh does not poison a get joining its new entry"""
    started = yield from fx.Latch.make()
    finish = yield from fx.Latch.make()
    cache = yield from fx.ScopedCache.make(_started_then_42(started, finish), capacity=10)

    refresh = yield from cache.refresh("key").fork(start_immediately=True)
    yield from started.wait()
    get = yield from cache.get("key").fork(start_immediately=True)
    yield from fx.yield_now()
    yield from refresh.interrupt()
    yield from finish.open()

    assert (yield from get.await_exit()) == fx.Success(42)


@testing.effect
def test_an_abandoned_get_reports_defects_from_its_scope_finalizer():
    """an abandoned get reports defects from its scope finalizer"""
    acquired = yield from fx.Latch.make()

    def release(_a: None, _ex: fx.Exit[Any, Any]) -> fx.Effect[None]:
        return fx.die(Exception("finalizer defect"))

    def lookup(_key: str) -> fx.Effect[int, Never, fx.Scope]:
        return fx.acquire_release(fx.void, release).and_then(acquired.open()).and_then(fx.never)

    cache = yield from fx.ScopedCache.make(lookup, capacity=10)
    get = yield from cache.get("key").fork(start_immediately=True)
    yield from acquired.wait()
    yield from get.interrupt()
    ex = yield from get.await_exit()

    assert isinstance(ex, fx.Failure)
    assert any(isinstance(reason, Die) for reason in ex.cause.reasons)


@testing.effect
def test_an_interrupted_first_get_does_not_poison_another_pending_get():
    """an interrupted first get does not poison another pending get"""
    started = yield from fx.Latch.make()
    finish = yield from fx.Latch.make()
    lookups = [0]

    @fx.fn
    def lookup(_key: str):
        lookups[0] += 1
        yield from started.open()
        yield from finish.wait()
        return 42

    cache = yield from fx.ScopedCache.make(lookup, capacity=10)

    first = yield from cache.get("key").fork(start_immediately=True)
    yield from started.wait()
    second = yield from cache.get("key").fork(start_immediately=True)
    yield from first.interrupt()
    yield from finish.open()

    assert (yield from second.await_exit()) == fx.Success(42)
    assert (yield from cache.get("key")) == 42
    assert lookups == [1]


@testing.effect
def test_the_last_interrupted_get_releases_its_resource_and_allows_a_new_lookup():
    """the last interrupted get releases its resource and allows a new lookup"""
    acquired = yield from fx.Latch.make()
    lookups = [0]
    releases = [0]

    def release(_a: None, _ex: fx.Exit[Any, Any]) -> fx.Effect[None]:
        def bump() -> None:
            releases[0] += 1

        return fx.sync(bump)

    def lookup(_key: str) -> fx.Effect[int, Never, fx.Scope]:
        def run() -> fx.Effect[int, Never, fx.Scope]:
            lookups[0] += 1
            if lookups[0] == 1:
                held = fx.acquire_release(fx.void, release).and_then(acquired.open())
                return held.and_then(fx.never)
            return fx.succeed(42)

        return fx.suspend(run)

    cache = yield from fx.ScopedCache.make(lookup, capacity=10)

    first = yield from cache.get("key").fork(start_immediately=True)
    yield from acquired.wait()
    yield from first.interrupt()
    assert releases == [1]
    assert (yield from cache.get("key")) == 42
    assert lookups == [2]


@testing.effect
def test_an_interrupted_refresh_cannot_replace_a_usable_entry_or_leak_its_scope():
    """an interrupted refresh cannot replace a usable entry or leak its scope"""
    acquired = yield from fx.Latch.make()
    lookups = [0]
    released: list[int] = []

    def lookup(_key: str) -> fx.Effect[int, Never, fx.Scope]:
        def run() -> fx.Effect[int, Never, fx.Scope]:
            lookups[0] += 1
            resource_id = lookups[0]
            held = fx.acquire_release(
                fx.void, lambda _a, _e: fx.sync(lambda: released.append(resource_id))
            )
            if resource_id == 2:
                return held.and_then(acquired.open()).and_then(fx.never)
            return held.as_(resource_id)

        return fx.suspend(run)

    cache = yield from fx.ScopedCache.make(lookup, capacity=10)

    assert (yield from cache.get("key")) == 1
    refresh = yield from cache.refresh("key").fork(start_immediately=True)
    yield from acquired.wait()
    yield from refresh.interrupt()

    assert 2 in released
    assert (yield from cache.get("key")) == 1
    assert 1 not in released


@testing.effect
def test_concurrent_gets_share_same_resource():
    """concurrent gets share same resource"""
    count, bump = _counter()

    def lookup(key: str) -> fx.Effect[str]:
        return bump.map(lambda n: f"resource-{key}-{n}").delay(0.1)

    cache = yield from fx.ScopedCache.make(lookup, capacity=10)
    fibers = yield from fx.all(*[cache.get("shared").fork() for _ in range(4)])
    yield from testing.adjust(0.15)
    results = yield from fx.Fiber.join_all(fibers)

    assert count == [1]
    assert results == ["resource-shared-1"] * 4


@testing.effect
def test_concurrent_invalidations_dont_cause_resource_leaks():
    """concurrent invalidations don't cause resource leaks"""
    active: set[str] = set()
    ids = itertools.count()

    def lookup(key: str) -> fx.Effect[str, Never, fx.Scope]:
        def run() -> fx.Effect[str, Never, fx.Scope]:
            resource_id = f"{key}-{next(ids)}"
            return fx.acquire_release(
                fx.sync(lambda: active.add(resource_id)),
                lambda _a, _e: fx.sync(lambda: active.discard(resource_id)),
            ).as_(resource_id)

        return fx.suspend(run)

    cache = yield from fx.ScopedCache.make(lookup, capacity=10)
    for key in ["key1", "key2", "key3"]:
        yield from cache.get(key)
    assert len(active) == 3

    yield from fx.all(
        cache.invalidate("key1"),
        cache.invalidate("key2"),
        cache.invalidate("key3"),
        cache.invalidate("key1"),
        cache.invalidate("key2"),
        concurrency="unbounded",
    )
    assert active == set()


@testing.effect
def test_concurrent_refresh_operations_dont_interfere():
    """concurrent refresh operations don't interfere"""
    count, bump = _counter()

    def lookup(key: str) -> fx.Effect[str]:
        return bump.map(lambda n: f"{key}-{n}").delay(0.05)

    cache = yield from fx.ScopedCache.make(lookup, capacity=10)
    yield from cache.get("a").fork()
    yield from cache.get("b").fork()
    yield from testing.adjust(0.05)
    count[0] = 0

    fibers = yield from fx.all(
        cache.refresh("a").fork(),
        cache.refresh("b").fork(),
        cache.refresh("a").fork(),
        cache.refresh("b").fork(),
    )
    yield from testing.adjust(0.1)
    results = yield from fx.Fiber.join_all(fibers)

    assert results == ["a-1", "b-2", "a-3", "b-4"]
    assert count == [4]
