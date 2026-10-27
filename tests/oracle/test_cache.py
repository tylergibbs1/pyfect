"""Ports of Effect's ``Cache.test.ts``.

Each test's docstring is the Effect test title. Effect's module functions
are methods (``Cache.get(cache, key)`` is ``cache.get(key)``); ``make`` and
``makeWith`` are one ``Cache.make`` whose ``time_to_live`` is a duration or
a function of the exit and the key. Durations are seconds,
``forkChild({ startImmediately })`` is ``fork(start_immediately=True)``,
``Fiber.await`` is ``await_exit`` and ``Data.Class`` keys are frozen
dataclasses. ``cache.map`` is the private ``_entries`` dict and an entry's
``await()`` is its ``wait()``. ``keys`` / ``values`` / ``entries`` return
lists (Effect: lazy iterables).

Adapted, with the reason:

- "does not retain prior equal object keys on cache hits": the keys are
  frozen dataclasses, collected with ``gc.collect()``.

Omitted, with the reason:

- "make - spans are connected": tracing is M5.
- "PersistedCache > persists synchronous lookup defects": persistence is
  not ported.
"""
# pyright: reportPrivateUsage=false

import gc
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import exit, testing

_HOUR = 3600.0
_MINUTE = 60.0


def _length(key: str) -> fx.Effect[int]:
    return fx.succeed(len(key))


def _length_cache(capacity: int | None = 10, time_to_live: float | None = None):
    return fx.Cache.make(_length, capacity=capacity, time_to_live=time_to_live)


class _TestLookup:
    """Effect's ``makeTestCache``: counts lookups, answering from
    ``results`` or failing with ``Key not found``."""

    def __init__(self) -> None:
        self.count = 0
        self.results: dict[str, fx.Effect[int, str]] = {}

    def __call__(self, key: str) -> fx.Effect[int, str]:
        self.count += 1
        return self.results.get(key, fx.fail(f"Key not found: {key}"))


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

    cache = yield from fx.Cache.make(lookup, capacity=16)
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


# --- constructors ---------------------------------------------------------------


@testing.effect
def test_make_creates_cache_with_fixed_capacity():
    """make - creates cache with fixed capacity"""
    cache = yield from _length_cache(10)
    assert cache.capacity == 10


@testing.effect
def test_make_creates_cache_with_default_infinite_ttl():
    """make - creates cache with default infinite TTL"""
    cache = yield from _length_cache()
    yield from cache.get("test")
    yield from testing.adjust(1000 * _HOUR)
    assert (yield from cache.has("test"))


@testing.effect
def test_make_creates_cache_with_custom_ttl():
    """make - creates cache with custom TTL"""
    cache = yield from _length_cache(time_to_live=_HOUR)
    yield from cache.get("test")
    yield from testing.adjust(30 * _MINUTE)
    assert (yield from cache.has("test"))
    yield from testing.adjust(31 * _MINUTE)
    assert not (yield from cache.has("test"))


@testing.effect
def test_make_uses_a_numeric_zero_ttl():
    """make - uses a numeric zero TTL"""
    cache = yield from _length_cache(time_to_live=0)
    yield from cache.get("test")
    assert not (yield from cache.has("test"))


class _TestService(fx.Tag[int]): ...


@testing.effect
def test_make_lookup_function_context_is_preserved():
    """make - lookup function context is preserved"""

    def program():
        cache = yield from fx.Cache.make(_always(_TestService()), capacity=10)
        return (yield from cache.get("test"))

    result = yield from fx.gen(program).pipe(fx.provide_service(_TestService, 42))
    assert result == 42


def _fail_or_length(key: str) -> fx.Effect[int, str]:
    return fx.fail("error") if key == "fail" else fx.succeed(len(key))


@testing.effect
def test_make_with_creates_cache_with_function_based_ttl():
    """makeWith - creates cache with function-based TTL"""

    def ttl(ex: fx.Exit[int, str], key: str) -> float:
        if isinstance(ex, fx.Failure):
            return 1
        return _MINUTE if key == "short" else _HOUR

    cache = yield from fx.Cache.make(_fail_or_length, capacity=10, time_to_live=ttl)

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
    """makeWith - TTL function receives correct parameters"""
    received: list[tuple[fx.Exit[int, str], str]] = []

    def ttl(ex: fx.Exit[int, str], key: str) -> float:
        received.append((ex, key))
        return float("inf")

    cache = yield from fx.Cache.make(_fail_or_length, capacity=10, time_to_live=ttl)
    yield from cache.get("test")
    yield from cache.get("fail").exit()

    assert received == [(fx.Success(4), "test"), (exit.fail("error"), "fail")]


# --- get ------------------------------------------------------------------------


@testing.effect
def test_does_not_retain_a_synchronous_zero_ttl_lookup():
    """does not retain a synchronous zero-TTL lookup"""
    cache = yield from fx.Cache.make(
        _always(fx.succeed(42)), capacity=1, time_to_live=lambda _ex, _key: 0
    )
    assert (yield from cache.get("key")) == 42
    assert (yield from cache.size()) == 0


@testing.effect
def test_removes_a_suspended_zero_ttl_lookup_after_completion():
    """removes a suspended zero-TTL lookup after completion"""
    started = yield from fx.Latch.make()
    gate = yield from fx.Deferred[int].make()
    cache = yield from fx.Cache.make(
        _always(started.open().and_then(gate.wait())),
        capacity=1,
        time_to_live=lambda _ex, _key: 0,
    )

    getter = yield from cache.get("key").fork(start_immediately=True)
    yield from started.wait()
    assert (yield from cache.size()) == 1

    yield from gate.succeed(42)
    assert (yield from getter.join()) == 42
    assert (yield from cache.size()) == 0


def _zero_on_failure(ex: fx.Exit[Any, Any], _key: object) -> float:
    return 0 if isinstance(ex, fx.Failure) else _HOUR


@testing.effect
def test_zero_ttl_failure_does_not_evict_a_live_entry_at_capacity():
    """zero-TTL failure does not evict a live entry at capacity"""

    def lookup(key: str) -> fx.Effect[int, str]:
        return fx.fail("error") if key == "bad" else fx.succeed(len(key))

    cache = yield from fx.Cache.make(lookup, capacity=2, time_to_live=_zero_on_failure)

    yield from cache.get("a")
    assert (yield from cache.get("bad").exit()) == exit.fail("error")
    assert (yield from cache.size()) == 1
    yield from cache.get("b")

    assert (yield from cache.get_success("a")) == fx.Some(1)
    assert (yield from cache.get_success("b")) == fx.Some(1)
    assert (yield from cache.size()) == 2


@testing.effect
def test_zero_ttl_lookup_after_expiration_does_not_evict_a_live_entry():
    """zero-TTL lookup after expiration does not evict a live entry"""
    k_lookups = [0]

    def lookup(key: str) -> fx.Effect[int, str]:
        if key == "k":
            k_lookups[0] += 1
            if k_lookups[0] == 2:
                return fx.fail("error")
        return fx.succeed(1)

    def ttl(ex: fx.Exit[int, str], key: str) -> float:
        if isinstance(ex, fx.Failure):
            return 0
        return _MINUTE if key == "k" else _HOUR

    cache = yield from fx.Cache.make(lookup, capacity=2, time_to_live=ttl)

    yield from cache.get("a")
    yield from cache.get("k")
    yield from testing.adjust(2 * _MINUTE)
    assert (yield from cache.get("k").exit()) == exit.fail("error")
    yield from cache.get("b")

    assert (yield from cache.get_success("a")) == fx.Some(1)
    assert (yield from cache.get_success("b")) == fx.Some(1)
    assert (yield from cache.size()) == 2


@testing.effect
def test_zero_ttl_completion_does_not_remove_a_newer_set_value():
    """zero-TTL completion does not remove a newer set value"""
    started = yield from fx.Latch.make()
    gate = yield from fx.Deferred[int, str].make()
    cache = yield from fx.Cache.make(
        _always(started.open().and_then(gate.wait())),
        capacity=1,
        time_to_live=_zero_on_failure,
    )

    getter = yield from cache.get("key").exit().fork(start_immediately=True)
    yield from started.wait()
    yield from cache.set("key", 99)
    yield from gate.fail("error")

    assert (yield from getter.join()) == exit.fail("error")
    assert (yield from cache.get_success("key")) == fx.Some(99)
    assert (yield from cache.size()) == 1


@testing.effect
def test_does_not_retain_synchronously_interrupted_lookups():
    """does not retain synchronously interrupted lookups"""
    calls = [0]

    def lookup(_key: str) -> fx.Effect[int]:
        def run() -> fx.Effect[int]:
            calls[0] += 1
            return fx.succeed(42) if calls[0] > 1 else fx.interrupt()

        return fx.suspend(run)

    cache = yield from fx.Cache.make(lookup, capacity=1)
    yield from cache.get("key").exit()
    assert (yield from cache.get("key").exit()) == fx.Success(42)


@testing.effect
def test_cache_hit_returns_existing_cached_value():
    """cache hit - returns existing cached value"""
    lookup = _TestLookup()
    lookup.results["test"] = fx.succeed(4)
    cache = yield from fx.Cache.make(lookup, capacity=10)

    yield from cache.get("test")
    assert (yield from cache.get("test")) == 4
    assert lookup.count == 1


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
    cache = yield from fx.Cache.make(lookup, capacity=10)

    results = yield from fx.all(cache.get("test"), cache.get("test"), cache.get("test"))
    assert results == (4, 4, 4)
    assert lookup.count == 1


@testing.effect
def test_cache_miss_invokes_lookup_for_non_existent_key():
    """cache miss - invokes lookup for non-existent key"""
    lookup = _TestLookup()
    lookup.results["test"] = fx.succeed(42)
    cache = yield from fx.Cache.make(lookup, capacity=10)

    assert (yield from cache.get("test")) == 42
    assert lookup.count == 1


@testing.effect
def test_cache_miss_invokes_lookup_again_after_ttl_expiration():
    """cache miss - invokes lookup again after TTL expiration"""
    _, bump = _counter()
    cache = yield from fx.Cache.make(_always(bump), capacity=10, time_to_live=_HOUR)

    assert (yield from cache.get("test")) == 1
    yield from testing.adjust(30 * _MINUTE)
    assert (yield from cache.get("test")) == 1
    yield from testing.adjust(31 * _MINUTE)
    assert (yield from cache.get("test")) == 2


@testing.effect
def test_error_handling_lookup_function_fails():
    """error handling - lookup function fails"""
    cache = yield from fx.Cache.make(_always(fx.fail("lookup error")), capacity=10)
    assert (yield from cache.get("test").exit()) == exit.fail("lookup error")


@testing.effect
def test_concurrent_access_multiple_fibers_getting_same_key_only_invoke_lookup_once():
    """concurrent access - multiple fibers getting same key only invoke lookup once"""
    count, bump = _counter()
    cache = yield from fx.Cache.make(_always(bump.delay(0.1)), capacity=10)

    gets = fx.all(cache.get("key"), cache.get("key"), cache.get("key"), concurrency="unbounded")
    results = yield from gets.fork()
    yield from testing.adjust(0.15)
    assert (yield from results.join()) == (1, 1, 1)
    assert count == [1]


@testing.effect
def test_concurrent_access_race_between_get_and_invalidate():
    """concurrent access - race between get and invalidate"""
    count, bump = _counter()
    cache = yield from fx.Cache.make(_always(bump.delay(0.05)), capacity=10)

    fiber1 = yield from cache.get("test").fork()
    yield from testing.adjust(0.025)
    yield from cache.invalidate("test")
    fiber2 = yield from cache.get("test").fork()

    yield from testing.adjust(0.1)
    assert (yield from fiber1.join()) == 1
    assert (yield from fiber2.join()) == 2
    assert count == [2]


@testing.effect
def test_concurrent_access_interrupting_the_first_consumer_does_not_interrupt_the_second():
    """concurrent access - interrupting the first consumer does not interrupt the second"""
    lookup_started = yield from fx.Latch.make()
    lookup_complete = yield from fx.Latch.make()

    @fx.fn
    def lookup(_key: str):
        yield from lookup_started.open()
        yield from lookup_complete.wait()
        return 42

    cache = yield from fx.Cache.make(lookup, capacity=10)

    first = yield from cache.get("K1").fork(start_immediately=True)
    yield from lookup_started.wait()
    second = yield from cache.get("K1").fork(start_immediately=True)
    entry = cache._entries["K1"]
    third = yield from entry.wait().fork(start_immediately=True)

    yield from first.interrupt()
    yield from lookup_complete.open()

    assert (yield from second.await_exit()) == fx.Success(42)
    assert (yield from third.await_exit()) == fx.Success(42)


@testing.effect
def test_interrupting_a_get_option_waiter_keeps_the_shared_lookup_available():
    """interrupting a getOption waiter keeps the shared lookup available"""
    started = yield from fx.Latch.make()
    finish = yield from fx.Latch.make()
    lookups = [0]

    @fx.fn
    def lookup(_key: str):
        lookups[0] += 1
        yield from started.open()
        yield from finish.wait()
        return 42

    cache = yield from fx.Cache.make(lookup, capacity=10)

    first = yield from cache.get("key").fork(start_immediately=True)
    yield from started.wait()
    waiter = yield from cache.get_option("key").fork(start_immediately=True)
    second = yield from cache.get("key").fork(start_immediately=True)
    yield from waiter.interrupt()
    yield from finish.open()

    assert (yield from first.await_exit()) == fx.Success(42)
    assert (yield from second.await_exit()) == fx.Success(42)
    assert (yield from cache.get_option("key")) == fx.Some(42)
    assert lookups == [1]


@testing.effect
def test_interrupting_a_get_as_its_lookup_starts_abandons_the_entry():
    """interrupting a get as its lookup starts abandons the entry"""
    started = yield from fx.Deferred[None].make()
    calls = [0]
    interrupted = [False]

    def lookup(_key: str) -> fx.Effect[str]:
        def run() -> fx.Effect[str]:
            calls[0] += 1
            if calls[0] > 1:
                return fx.succeed("ok")

            def mark() -> None:
                interrupted[0] = True

            return started.succeed(None).and_then(fx.never).on_interrupt(fx.sync(mark))

        return fx.suspend(run)

    def ttl(ex: fx.Exit[str, Never], _key: str) -> float:
        return float("inf") if isinstance(ex, fx.Success) else 0

    cache = yield from fx.Cache.make(lookup, capacity=4, time_to_live=ttl)

    getter = yield from cache.get("key").fork()
    yield from started.wait()
    # No yield here: the interrupt must race with the lookup starting.
    yield from getter.interrupt()

    assert (yield from cache.size()) == 0
    assert interrupted == [True]
    assert (yield from cache.get("key")) == "ok"
    assert calls == [2]


@testing.effect
def test_concurrent_access_interrupting_the_last_consumer_interrupts_the_lookup():
    """concurrent access - interrupting the last consumer interrupts the lookup"""
    lookups = [0]
    lookup_started = yield from fx.Latch.make()
    lookup_interrupted = yield from fx.Latch.make()

    def lookup(_key: str) -> fx.Effect[int]:
        lookups[0] += 1
        if lookups[0] == 1:
            return lookup_started.open().and_then(fx.never).on_interrupt(lookup_interrupted.open())
        return fx.succeed(42)

    cache = yield from fx.Cache.make(lookup, capacity=10)

    fiber = yield from cache.get("K1").fork(start_immediately=True)
    yield from lookup_started.wait()
    yield from fiber.interrupt()

    yield from lookup_interrupted.wait()
    assert (yield from cache.get("K1")) == 42


@testing.effect
def test_concurrent_access_interrupted_lookup_does_not_remove_a_newer_set_value():
    """concurrent access - interrupted lookup does not remove a newer set value"""
    lookup_started = yield from fx.Latch.make()
    lookup_interrupted = yield from fx.Latch.make()

    def lookup(_key: str) -> fx.Effect[int]:
        return lookup_started.open().and_then(fx.never).on_interrupt(lookup_interrupted.open())

    cache = yield from fx.Cache.make(lookup, capacity=1)

    getter = yield from cache.get("key").fork(start_immediately=True)
    yield from lookup_started.wait()
    yield from cache.set("key", 99)
    yield from getter.interrupt()
    yield from lookup_interrupted.wait()

    assert (yield from cache.get_success("key")) == fx.Some(99)


@testing.effect
def test_concurrent_access_a_get_made_while_an_abandoned_lookup_is_finalizing_starts_a_new_lookup():
    """concurrent access - a get made while an abandoned lookup is finalizing starts a new lookup"""
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

    cache = yield from fx.Cache.make(lookup, capacity=10)

    getter = yield from cache.get("key").fork(start_immediately=True)
    yield from started.wait()
    interrupt_getter = yield from getter.interrupt().fork(start_immediately=True)
    yield from finalizing.wait()
    fresh = yield from cache.get("key").fork(start_immediately=True)
    yield from finish_finalizer.open()
    yield from interrupt_getter.join()

    assert (yield from fresh.await_exit()) == fx.Success(2)
    assert (yield from cache.get("key")) == 2
    assert lookups == [2]


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
    cache = yield from fx.Cache.make(_always(deferred.wait().as_(42)), capacity=10)

    get_fiber = yield from cache.get("test").fork()
    option_fiber = yield from cache.get_option("test").fork()
    yield from deferred.succeed(None)

    assert (yield from get_fiber.join()) == 42
    assert (yield from option_fiber.join()) == fx.Some(42)


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
    cache = yield from fx.Cache.make(_always(fx.fail("error")), capacity=10)
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
    cache = yield from fx.Cache.make(lookup, capacity=10)
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
    cache = yield from fx.Cache.make(lookup, capacity=10)
    yield from cache.set("test", 42)
    yield from cache.set("test2", 43)
    yield from cache.set("test3", 44)
    assert lookup.count == 0


@testing.effect
def test_set_enforces_capacity():
    """set enforces capacity"""
    cache = yield from _length_cache(2)
    yield from cache.set("a", 1)
    yield from cache.set("b", 2)
    assert (yield from cache.size()) == 2
    yield from cache.set("c", 3)
    assert (yield from cache.size()) == 2


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
    cache = yield from fx.Cache.make(_always(bump), capacity=10)
    assert (yield from cache.get("test")) == 1
    yield from cache.invalidate("test")
    assert (yield from cache.get("test")) == 2


# --- invalidateWhen -------------------------------------------------------------


@pytest.mark.parametrize("outcome", [fx.Success(1), exit.fail("error")])
@testing.effect
def test_invalidate_when_preserves_a_newer_set_value_after_an_old_lookup_completes(
    outcome: fx.Exit[int, str],
):
    """preserves a newer set value after an old lookup completes (%#)"""
    gate = yield from fx.Deferred[int, str].make()
    values: list[int] = []
    cache = yield from fx.Cache.make(_always(gate.wait()), capacity=1)

    lookup = yield from cache.get("key").exit().fork(start_immediately=True)

    def matches(value: int) -> bool:
        values.append(value)
        return value == 1

    invalidator = yield from cache.invalidate_when("key", matches).fork(start_immediately=True)

    yield from cache.set("key", 99)
    yield from gate.done(outcome)
    original = yield from lookup.join()
    invalidated = yield from invalidator.join()

    assert original == outcome
    assert values == ([1] if isinstance(outcome, fx.Success) else [])
    assert not invalidated
    assert (yield from cache.get_success("key")) == fx.Some(99)


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
    cache = yield from fx.Cache.make(_always(fx.fail("error")), capacity=10)
    yield from cache.get("test").exit()
    assert not (yield from cache.invalidate_when("test", lambda _: True))


# --- refresh --------------------------------------------------------------------


@testing.effect
def test_refresh_existing_key_invokes_lookup_again():
    """refresh existing key invokes lookup again"""
    _, bump = _counter()
    cache = yield from fx.Cache.make(_always(bump), capacity=10)
    yield from cache.get("test")
    assert (yield from cache.refresh("test")) == 2


@testing.effect
def test_refresh_non_existent_key_invokes_lookup_and_enforces_capacity():
    """refresh non-existent key invokes lookup and enforces capacity"""
    _, bump = _counter()
    cache = yield from fx.Cache.make(_always(bump), capacity=1)
    yield from cache.set("other", 99)
    assert (yield from cache.refresh("test")) == 1
    assert (yield from cache.size()) == 1
    assert (yield from cache.keys()) == ["test"]


@testing.effect
def test_refresh_enforces_capacity_when_the_existing_key_is_evicted_during_lookup():
    """refresh enforces capacity when the existing key is evicted during lookup"""
    started = yield from fx.Deferred[None].make()
    result = yield from fx.Deferred[int].make()
    cache = yield from fx.Cache.make(
        _always(started.succeed(None).and_then(result.wait())), capacity=1
    )

    yield from cache.set("a", 1)
    refresh = yield from cache.refresh("a").fork(start_immediately=True)
    yield from started.wait()
    yield from cache.set("b", 99)
    assert not (yield from cache.has("a"))

    yield from result.succeed(2)
    assert (yield from refresh.join()) == 2
    assert (yield from cache.size()) == 1
    assert sorted((yield from cache.keys())) == ["a"]
    assert (yield from cache.get_success("a")) == fx.Some(2)


@testing.effect
def test_repro_interrupting_a_missing_key_refresh_does_not_remove_a_newer_set_value():
    """repro: interrupting a missing-key refresh does not remove a newer set value"""
    lookup_started = yield from fx.Latch.make()

    def lookup(_key: str) -> fx.Effect[int]:
        return lookup_started.open().and_then(fx.never)

    cache = yield from fx.Cache.make(lookup, capacity=1)

    refresh = yield from cache.refresh("key").fork(start_immediately=True)
    yield from lookup_started.wait()
    yield from cache.set("key", 99)
    assert (yield from cache.get_success("key")) == fx.Some(99)

    yield from refresh.interrupt()
    assert (yield from cache.get_success("key")) == fx.Some(99)


@testing.effect
def test_interrupting_a_missing_key_refresh_removes_its_pending_entry():
    """interrupting a missing-key refresh removes its pending entry"""
    lookup_started = yield from fx.Latch.make()
    cache = yield from fx.Cache.make(_always(lookup_started.open().and_then(fx.never)), capacity=1)

    refresh = yield from cache.refresh("key").fork(start_immediately=True)
    yield from lookup_started.wait()
    assert (yield from cache.has("key"))

    yield from refresh.interrupt()
    assert not (yield from cache.has("key"))


@pytest.mark.parametrize("existing", [False, True])
@testing.effect
def test_zero_ttl_refresh_with_replacement(existing: bool):
    """zero-TTL refresh with replacement (existing: %s)"""
    gate = yield from fx.Deferred[int, str].make()

    def ttl(ex: fx.Exit[int, str], _key: str) -> float:
        return 0 if isinstance(ex, fx.Failure) else _HOUR

    cache = yield from fx.Cache.make(_always(gate.wait()), capacity=1, time_to_live=ttl)
    if existing:
        yield from cache.set("key", 1)

    refresh = yield from cache.refresh("key").fork(start_immediately=True)
    yield from cache.set("key", 99)
    yield from gate.fail("error")

    assert (yield from refresh.await_exit()) == exit.fail("error")
    assert (yield from cache.get_success("key")) == (None if existing else fx.Some(99))


@testing.effect
def test_zero_ttl_refresh_removes_its_own_entry():
    """zero-TTL refresh removes its own entry"""
    cache = yield from fx.Cache.make(
        _always(fx.fail("error")), capacity=1, time_to_live=lambda _ex, _key: 0
    )
    assert (yield from cache.refresh("key").exit()) == exit.fail("error")
    assert not (yield from cache.has("key"))


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
    cache = yield from fx.Cache.make(_always(bump), capacity=10)
    yield from cache.get("test")
    count[0] = 0

    results = yield from fx.all(
        cache.refresh("test"), cache.refresh("test"), cache.refresh("test"), concurrency="unbounded"
    )
    assert count == [3]
    assert results == (1, 2, 3)


# --- invalidateAll --------------------------------------------------------------


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
    cache = yield from fx.Cache.make(_fail_or_length, capacity=10, time_to_live=_HOUR)
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
    cache = yield from fx.Cache.make(_fail_or_length, capacity=10, time_to_live=_HOUR)
    yield from cache.get("a")
    yield from cache.get("fail").exit()
    yield from cache.get("ab")
    assert sorted((yield from cache.entries())) == [("a", 1), ("ab", 2)]


@testing.effect
def test_entries_filters_out_expired_entries():
    """filters out expired entries"""
    cache = yield from _length_cache(time_to_live=_HOUR)
    yield from cache.get("a")
    yield from cache.get("b")
    yield from testing.adjust(2 * _HOUR)
    assert (yield from cache.entries()) == []


@testing.effect
def test_entries_removes_expired_entries_as_side_effect():
    """removes expired entries as side effect"""
    cache = yield from _length_cache(time_to_live=_HOUR)
    yield from cache.get("a")
    yield from cache.get("b")
    yield from testing.adjust(2 * _HOUR)

    assert (yield from cache.size()) == 2
    entries = yield from cache.entries()
    assert (yield from cache.size()) == 0
    assert entries == []


# --- capacity management --------------------------------------------------------


@testing.effect
def test_lru_eviction_oldest_entries_removed_when_capacity_exceeded():
    """LRU eviction - oldest entries removed when capacity exceeded"""
    cache = yield from _length_cache(3)
    for key in ["a", "b", "c", "d"]:
        yield from cache.get(key)
    assert not (yield from cache.has("a"))
    for key in ["b", "c", "d"]:
        assert (yield from cache.has(key))


@testing.effect
def test_lru_eviction_access_order_determines_eviction():
    """LRU eviction - access order determines eviction"""
    cache = yield from _length_cache(3)
    for key in ["a", "b", "c", "a", "d"]:
        yield from cache.get(key)
    assert (yield from cache.has("a"))
    assert not (yield from cache.has("b"))
    assert (yield from cache.has("c"))
    assert (yield from cache.has("d"))


@testing.effect
def test_capacity_of_1():
    """capacity of 1"""
    cache = yield from _length_cache(1)
    yield from cache.get("a")
    assert (yield from cache.has("a"))
    yield from cache.get("b")
    assert not (yield from cache.has("a"))
    assert (yield from cache.has("b"))


@testing.effect
def test_very_large_capacity():
    """very large capacity"""
    cache = yield from _length_cache(10000)
    for i in range(100):
        yield from cache.get(f"key{i}")
    assert (yield from cache.size()) == 100
    assert (yield from cache.has("key0"))
    assert (yield from cache.has("key99"))


# --- TTL ------------------------------------------------------------------------


@testing.effect
def test_fixed_ttl_entry_expires_after_specified_duration():
    """fixed TTL - entry expires after specified duration"""
    cache = yield from _length_cache(time_to_live=_HOUR)
    yield from cache.get("test")
    yield from testing.adjust(59 * _MINUTE)
    assert (yield from cache.has("test"))
    yield from testing.adjust(2 * _MINUTE)
    assert not (yield from cache.has("test"))


@testing.effect
def test_fixed_ttl_get_after_expiration_invokes_lookup():
    """fixed TTL - get after expiration invokes lookup"""
    _, bump = _counter()
    cache = yield from fx.Cache.make(_always(bump), capacity=10, time_to_live=_HOUR)
    assert (yield from cache.get("test")) == 1
    yield from testing.adjust(2 * _HOUR)
    assert (yield from cache.get("test")) == 2


@testing.effect
def test_fixed_ttl_has_returns_false_for_expired_entries():
    """fixed TTL - has returns false for expired entries"""
    cache = yield from _length_cache(time_to_live=30 * _MINUTE)
    yield from cache.get("test")
    assert (yield from cache.has("test"))
    yield from testing.adjust(31 * _MINUTE)
    assert not (yield from cache.has("test"))


@testing.effect
def test_function_based_ttl_different_ttl_for_success_vs_failure():
    """function-based TTL - different TTL for success vs failure"""

    def ttl(ex: fx.Exit[int, str], _key: str) -> float:
        return _HOUR if isinstance(ex, fx.Success) else _MINUTE

    cache = yield from fx.Cache.make(_fail_or_length, capacity=10, time_to_live=ttl)
    yield from cache.get("success")
    yield from cache.get("fail").exit()
    yield from testing.adjust(30 * _MINUTE)
    assert (yield from cache.has("success"))
    assert not (yield from cache.has("fail"))


@testing.effect
def test_function_based_ttl_ttl_based_on_key():
    """function-based TTL - TTL based on key"""
    cache = yield from fx.Cache.make(
        _length,
        capacity=10,
        time_to_live=lambda _ex, key: _MINUTE if key == "short" else _HOUR,
    )
    yield from cache.get("short")
    yield from cache.get("long")
    yield from testing.adjust(30 * _MINUTE)
    assert not (yield from cache.has("short"))
    assert (yield from cache.has("long"))


@testing.effect
def test_function_based_ttl_ttl_based_on_value():
    """function-based TTL - TTL based on value"""

    def ttl(ex: fx.Exit[int, Never], _key: str) -> float:
        value = ex.value if isinstance(ex, fx.Success) else 0
        return _HOUR if value > 3 else _MINUTE

    cache = yield from fx.Cache.make(_length, capacity=10, time_to_live=ttl)
    yield from cache.get("ab")
    yield from cache.get("abcd")
    yield from testing.adjust(30 * _MINUTE)
    assert not (yield from cache.has("ab"))
    assert (yield from cache.has("abcd"))


@testing.effect
def test_infinite_ttl():
    """infinite TTL"""
    cache = yield from fx.Cache.make(
        _length, capacity=10, time_to_live=lambda _ex, _key: float("inf")
    )
    yield from cache.get("test")
    yield from testing.adjust(1000 * _HOUR)
    assert (yield from cache.has("test"))


@testing.effect
def test_zero_duration_ttl():
    """zero duration TTL"""
    cache = yield from _length_cache(time_to_live=0)
    yield from cache.get("test")
    assert not (yield from cache.has("test"))


@testing.effect
def test_ttl_updates_on_refresh():
    """TTL updates on refresh"""
    cache = yield from _length_cache(time_to_live=_HOUR)
    yield from cache.get("test")
    yield from testing.adjust(45 * _MINUTE)
    yield from cache.refresh("test")
    yield from testing.adjust(30 * _MINUTE)
    assert (yield from cache.has("test"))
    yield from testing.adjust(31 * _MINUTE)
    assert not (yield from cache.has("test"))


# --- error scenarios ------------------------------------------------------------


@testing.effect
def test_failed_lookup_caches_the_failure():
    """failed lookup caches the failure"""
    cache = yield from fx.Cache.make(_always(fx.fail("lookup error")), capacity=10)
    result1 = yield from cache.get("test").exit()
    result2 = yield from cache.get("test").exit()
    assert isinstance(result1, fx.Failure)
    assert result1 == result2


@testing.effect
def test_subsequent_gets_return_same_failure():
    """subsequent gets return same failure"""
    count, bump = _counter()
    cache = yield from fx.Cache.make(_always(bump.and_then(fx.fail("error"))), capacity=10)
    for _ in range(3):
        yield from cache.get("test").exit()
    assert count == [1]


@testing.effect
def test_can_refresh_after_failure():
    """can refresh after failure"""
    should_fail = [True]

    def _maybe_failing(_key: str) -> fx.Effect[int, str]:
        return fx.fail("error") if should_fail[0] else fx.succeed(42)

    cache = yield from fx.Cache.make(_maybe_failing, capacity=10)
    assert isinstance((yield from cache.get("test").exit()), fx.Failure)
    should_fail[0] = False
    assert (yield from cache.refresh("test")) == 42


@testing.effect
def test_multiple_fibers_encountering_same_error():
    """multiple fibers encountering same error"""
    count, bump = _counter()
    cache = yield from fx.Cache.make(
        _always(bump.and_then(fx.fail("error")).delay(0.1)), capacity=10
    )
    gets = fx.all(
        cache.get("key").exit(),
        cache.get("key").exit(),
        cache.get("key").exit(),
        concurrency="unbounded",
    )
    fiber = yield from gets.fork()
    yield from testing.adjust(0.15)
    results = yield from fiber.join()

    assert count == [1]
    assert all(isinstance(result, fx.Failure) for result in results)
    assert results[0] == results[1] == results[2]


# --- integration ----------------------------------------------------------------


@testing.effect
def test_with_test_clock_multiple_time_advances():
    """with TestClock - multiple time advances"""
    cache = yield from _length_cache(time_to_live=_HOUR)
    yield from cache.get("a")
    yield from testing.adjust(30 * _MINUTE)
    yield from cache.get("b")
    yield from testing.adjust(30 * _MINUTE)
    yield from cache.get("c")
    yield from testing.adjust(30 * _MINUTE)

    assert not (yield from cache.has("a"))  # expired at 60 min, now at 90 min
    assert not (yield from cache.has("b"))  # expired at 90 min, now at 90 min
    assert (yield from cache.has("c"))  # expires at 120 min


@testing.effect
def test_with_test_clock_set_specific_time():
    """with TestClock - set specific time"""
    cache = yield from _length_cache(time_to_live=1.0)
    yield from cache.get("test")
    yield from testing.set_time(0.5)
    assert (yield from cache.has("test"))
    yield from testing.set_time(1.5)
    assert not (yield from cache.has("test"))


@testing.effect
def test_with_different_key_types_string_keys():
    """with different key types - string keys"""
    cache = yield from _length_cache()
    yield from cache.get("hello")
    yield from cache.get("world")
    assert (yield from cache.get("hello")) == 5
    assert (yield from cache.get("world")) == 5


@testing.effect
def test_with_different_key_types_number_keys():
    """with different key types - number keys"""

    def lookup(key: int) -> fx.Effect[str]:
        return fx.succeed(f"number: {key}")

    cache = yield from fx.Cache.make(lookup, capacity=10)
    for key in [1, 2, 3]:
        yield from cache.get(key)
    for key in [1, 2, 3]:
        assert (yield from cache.get(key)) == f"number: {key}"


@dataclass(frozen=True)
class _CacheKey:
    id: int
    name: str


@testing.effect
def test_with_different_key_types_complex_object_keys():
    """with different key types - complex object keys"""
    lookups: list[_CacheKey] = []

    def lookup(key: _CacheKey) -> fx.Effect[str]:
        lookups.append(key)
        return fx.succeed(f"{key.name}-{key.id}")

    cache = yield from fx.Cache.make(lookup, capacity=10)
    key1 = _CacheKey(1, "test")
    key2 = _CacheKey(2, "test")
    key3 = _CacheKey(1, "test")  # equal to key1

    yield from cache.get(key1)
    yield from cache.get(key2)
    assert (yield from cache.get(key1)) == "test-1"
    assert (yield from cache.get(key2)) == "test-2"
    assert (yield from cache.get(key3)) == "test-1"
    assert len(lookups) == 2
