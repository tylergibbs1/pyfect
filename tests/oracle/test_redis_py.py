"""Ports of Effect's ``platform-node/test/NodeRedis.integration.test.ts``
on ``redis_py`` (Effect's ``NodeRedis``), against the throwaway Redis
server of ``_redis`` (skipped without one), emptied before each test:

- the ``persistence/PersistedCacheTest.ts`` suite on ``persistence.layer_redis``,
- the ``BackingPersistenceTest`` suite on ``persistence.layer_backing_redis``,
- the ``RateLimiterTest`` suite on ``rate_limiter.layer_store_redis``,
- the ``CircuitBreakerTest`` suite on ``circuit_breaker.layer_store_redis``
  (on live time: the store reads Redis ``TIME``),
- the ``persistence/CircuitBreakerRedisTest.ts`` suite,
- the file's own titles.

Each test's docstring is the Effect test title. The
``PersistedQueueTest`` suite and the ``PersistedQueue (NodeRedis)`` titles
about queues are in ``test_redis_py_persisted_queue.py``. Adapted: ``uses
the node-redis protocol default`` checks redis-py's (RESP2, no
``protocol`` option).
"""

from __future__ import annotations

import json
import time
import warnings
from collections.abc import Callable, Generator
from typing import Any, Literal, Never

import pytest

pytest.importorskip("redis")

import pyfect as fx
from pyfect import testing
from pyfect.duration import zero
from pyfect.exit import Failure, Success
from pyfect.persistence import circuit_breaker as cb
from pyfect.persistence import persistence, redis_py
from pyfect.persistence import rate_limiter as rl
from pyfect.persistence.redis import (
    DEFAULT_SUBSCRIBE_CAPACITY,
    Redis,
    RedisConnection,
    RedisError,
    RedisMessage,
    RedisReply,
    RedisService,
    Script,
)
from pyfect.queue import Dequeue
from pyfect.scope import Scope

from . import _backing_persistence_suite as backing_suite
from . import _circuit_breaker_suite as cb_suite
from . import _persisted_cache_suite as cache_suite
from . import _rate_limiter_suite as rl_suite
from . import _redis

# The stores read Redis ``TIME``, so these tests wait on the wall clock,
# while background fibers (the reserve pool's idle timer, lease renewals
# under the suite's TestClock) sleep on the TestClock untouched.
pytestmark = pytest.mark.filterwarnings("ignore::pyfect.testing.ClockNotAdvancedWarning")


@pytest.fixture(autouse=True)
def _flushed() -> None:
    _redis.flush()


def _redis_layer() -> fx.Layer[Redis | redis_py.RedisPy, RedisError]:
    return redis_py.layer(_redis.server().url)


# --- BackingPersistence (NodeRedis) ---------------------------------------------------


@pytest.mark.parametrize(("title", "body"), backing_suite.SUITE, ids=backing_suite.IDS)
def test_backing_persistence_redis(title: str, body: backing_suite.Body) -> None:
    """BackingPersistence (NodeRedis) / ${title}"""
    layer = persistence.layer_backing_redis.pipe(fx.provide(_redis_layer()))
    testing.run_test(fx.scoped(fx.gen(body)).pipe(fx.provide(layer)).or_die())


# --- PersistedCache (NodeRedis) -------------------------------------------------------


def _persistence() -> fx.Layer[Any, Any]:
    return persistence.layer_redis.pipe(fx.provide(_redis_layer()))


def test_persisted_cache_smoke_test() -> None:
    """PersistedCache (NodeRedis) / smoke test"""
    cache_suite.run(_persistence(), cache_suite.smoke_test)


@pytest.mark.parametrize("outcome", ["success", "error"])
def test_persisted_cache_recomputes_and_replaces_entries_with_stale_schemas(
    outcome: Literal["success", "error"],
) -> None:
    """PersistedCache (NodeRedis) / recomputes and replaces entries with stale ${outcome}
    schemas"""
    cache_suite.run(_persistence(), cache_suite.recomputes_stale("NodeRedis", outcome))


def test_persisted_cache_require_services_at_lookup() -> None:
    """PersistedCache (NodeRedis) / requireServicesAt: 'lookup' requires lookup services at
    get-time"""
    cache_suite.run(_persistence(), cache_suite.require_services_at_lookup("NodeRedis"))


# --- RateLimiter (NodeRedis) ----------------------------------------------------------


class TestRateLimiterRedis(rl_suite.RateLimiterSuite):
    """RateLimiter fixed-window (NodeRedis) / RateLimiter token-bucket timing (NodeRedis)"""

    @property
    def layer(self) -> fx.Layer[rl.RateLimiterStore, Any]:  # pyright: ignore[reportIncompatibleVariableOverride]
        return rl.layer_store_redis().pipe(fx.provide(_redis_layer()))


# --- CircuitBreaker (NodeRedis) -------------------------------------------------------


def _live(seconds: float) -> fx.Effect[None]:
    return testing.with_live(fx.sleep(fx.duration.seconds(seconds)))


def _circuit_breaker_run(
    effect: fx.Effect[Any, Any, Any], store: fx.Layer[cb.CircuitBreakerStore, Any, Any]
) -> None:
    layer = store.pipe(fx.layer.provide_merge(_redis_layer()))
    run: fx.Effect[Any, Any, Any] = fx.scoped(effect).pipe(fx.provide(layer))
    testing.run_test(run)


@pytest.mark.parametrize(("title", "body"), cb_suite.ALL, ids=cb_suite.IDS)
def test_circuit_breaker_redis(title: str, body: cb_suite.Body) -> None:
    """CircuitBreaker (NodeRedis) / ${title}"""
    idle = "400 millis" if body.__name__ in cb_suite.IDLE else "1 hour"
    _circuit_breaker_run(fx.gen(lambda: body(_live)), cb.layer_store_redis(idle_time_to_live=idle))


# --- CircuitBreaker Redis store (NodeRedis) -------------------------------------------


class _Partition:
    """Cuts one "process" off from Redis while another keeps talking to
    it."""

    def __init__(self, redis: RedisService) -> None:
        self.down = False
        self._redis = redis

    def _gate[A](self, effect: fx.Effect[A, RedisError]) -> fx.Effect[A, RedisError]:
        return fx.suspend(
            lambda: fx.fail(RedisError(cause=RuntimeError("partitioned"))) if self.down else effect
        )

    def send(self, command: str, *args: str) -> fx.Effect[RedisReply, RedisError]:
        return self._gate(self._redis.send(command, *args))

    def eval[**P, A](self, script: Script[P, A]) -> Callable[P, fx.Effect[A, RedisError]]:
        run = self._redis.eval(script)
        return lambda *args, **kwargs: self._gate(run(*args, **kwargs))

    def subscribe(
        self, channel: str, *, capacity: int = DEFAULT_SUBSCRIBE_CAPACITY
    ) -> fx.Effect[Dequeue[RedisMessage, RedisError], Never, Scope]:
        return self._redis.subscribe(channel, capacity=capacity)

    @property
    def reserve(self) -> fx.Effect[RedisConnection, RedisError, Scope]:
        return self._redis.reserve


def _store_on(redis: RedisService, **options: Any) -> fx.Effect[cb.CircuitBreakerStoreService]:
    """A separate Redis store, as another process would have."""
    return cb.make_store_redis(**options).pipe(fx.provide_service(Redis, redis))


_OPTIONS: dict[str, Any] = {"trip_policy": cb.consecutive(1), "open_duration": "200 millis"}


def _on(
    store: cb.CircuitBreakerStoreService, **options: Any
) -> fx.Effect[cb.CircuitBreakerService, Never, Scope]:
    return cb.make(**{**_OPTIONS, **options}).pipe(
        fx.provide_service(cb.CircuitBreakerStore, store)
    )


def _redis_store_run(body: Callable[[], Generator[Any, Any]], *layers: fx.Layer[Any]) -> None:
    effect: fx.Effect[Any, Any, Any] = testing.with_live(fx.scoped(fx.gen(body)))
    for layer in layers:
        effect = effect.pipe(fx.provide(layer))
    _circuit_breaker_run(effect, cb.layer_store_redis())


def test_a_lapsed_probe_lease_is_taken_over_and_the_old_holders_record_is_discarded() -> None:
    """CircuitBreaker Redis store (NodeRedis) / a lapsed probe lease is taken over and the old
    holder's record is discarded"""

    def body():
        key = "lease-takeover"
        flaky = _Partition((yield from Redis()))
        store_a = yield from _store_on(flaky, probe_lease="300 millis")
        a = yield from _on(store_a)
        b = yield from cb.make(**_OPTIONS)
        transitions_b = yield from b.transitions.take(1).run_collect().fork(start_immediately=True)

        yield from cb_suite.fail(a, key)
        yield from fx.sleep("300 millis")
        stale = yield from cb_suite.held(a, key, fx.fail("boom"))
        # A can no longer renew, so its 300 millis lease lapses.
        flaky.down = True
        yield from fx.sleep("600 millis")
        assert (yield from b.state(key)) == cb.HalfOpen(key, False, 1)

        probe = yield from cb_suite.held(b, key, fx.void)
        flaky.down = False
        assert isinstance((yield from stale.release), Failure)
        assert (yield from b.state(key)) == cb.HalfOpen(key, True, 1)

        assert isinstance((yield from probe.release), Success)
        assert (yield from b.state(key)) == cb.Closed(key)
        # The takeover itself emits nothing.
        assert (yield from transitions_b.join()) == [cb.CloseTransition(key)]

    _redis_store_run(body)


def test_a_failed_lease_renewal_is_reported_and_retried_without_failing_the_probe() -> None:
    """CircuitBreaker Redis store (NodeRedis) / a failed lease renewal is reported and retried
    without failing the probe"""
    reports: list[object] = []

    def record(options: Any) -> None:
        if options.log_level in {fx.LogLevel.WARN, fx.LogLevel.ERROR}:
            reports.append(options.message)

    def body():
        key = "lease-renewal"
        flaky = _Partition((yield from Redis()))
        store_a = yield from _store_on(flaky, probe_lease="600 millis")
        a = yield from _on(store_a)
        b = yield from cb.make(**_OPTIONS)

        yield from cb_suite.fail(a, key)
        yield from fx.sleep("300 millis")
        probe = yield from cb_suite.held(a, key, fx.void)
        # The renewal due after 200 millis fails, the one after 400 millis
        # succeeds.
        flaky.down = True
        yield from fx.sleep("300 millis")
        flaky.down = False
        # Past the original 600 millis lease, so only a renewal keeps it.
        yield from fx.sleep("500 millis")
        rejected = yield from cb_suite.rejection(cb_suite.run_void(b, key))
        assert isinstance(rejected, cb.CircuitHalfOpen)

        assert isinstance((yield from probe.release), Success)
        assert (yield from b.state(key)) == cb.Closed(key)
        assert reports

    _redis_store_run(body, fx.logger.layer([fx.Logger.make(record)]))


def test_a_renewal_after_an_ignored_probe_frees_the_slot_does_not_take_the_lease_back() -> None:
    """CircuitBreaker Redis store (NodeRedis) / a renewal after an Ignored probe frees the slot
    does not take the lease back"""

    def body():
        key = "lease-release"
        redis = yield from Redis()
        store = yield from _store_on(redis, probe_lease="600 millis")
        breaker = yield from _on(store)

        yield from cb_suite.fail(breaker, key)
        yield from fx.sleep("300 millis")

        def admitted():
            admission = yield from store.admit(key)
            assert admission.probe
            yield from store.record(
                key=key,
                generation=admission.generation,
                outcome="Ignored",
                trip_policy=_OPTIONS["trip_policy"],
                open_for=zero,
            )
            # The renewal fiber stays alive until the admit scope closes,
            # as it does while execute is still waiting on record. Its tick
            # after 200 millis lands after the release.
            yield from fx.sleep("350 millis")
            assert (yield from store.state(key)) == cb.HalfOpen(key, False, 1)

        yield from fx.scoped(fx.gen(admitted))

    _redis_store_run(body)


def test_a_leased_half_open_key_outlives_a_shorter_idle_time_to_live() -> None:
    """CircuitBreaker Redis store (NodeRedis) / a leased HalfOpen key outlives a shorter
    idleTimeToLive, and freeing the slot restores it"""

    def body():
        key = "retention-half-open"
        redis = yield from Redis()
        store = yield from _store_on(redis, probe_lease="1 second", idle_time_to_live="300 millis")
        breaker = yield from _on(store, open_duration="100 millis")
        pttl = redis.send("PTTL", f"circuitbreaker:{key}")

        yield from cb_suite.fail(breaker, key)
        yield from fx.sleep("200 millis")
        probe = yield from cb_suite.held(breaker, key, fx.fail("boom"))
        # The remaining lease plus idleTimeToLive.
        leased = yield from pttl
        assert isinstance(leased, int)
        assert 1000 < leased <= 1300

        # Past idleTimeToLive, the first lease and the first expiry: only
        # the renewals keep the key and the probe's slot.
        yield from fx.sleep("1500 millis")
        assert (yield from breaker.state(key)) == cb.HalfOpen(key, True, 1)
        renewed = yield from pttl
        assert isinstance(renewed, int)
        assert renewed > 300

        # The probe's failure still counts as the second opening.
        yield from probe.release
        reopened = yield from breaker.state(key)
        assert isinstance(reopened, cb.Open)
        assert reopened.consecutive_openings == 2

        # An interrupted probe frees the slot, so the key is back on
        # idleTimeToLive.
        yield from fx.sleep("200 millis")
        interrupted = yield from cb_suite.held(breaker, key, fx.void)
        yield from interrupted.fiber.interrupt()
        assert (yield from breaker.state(key)) == cb.HalfOpen(key, False, 2)
        freed = yield from pttl
        assert isinstance(freed, int)
        assert 0 < freed <= 300

    _redis_store_run(body)


def test_a_duration_redis_cannot_represent_is_rejected_before_the_script_writes_anything() -> None:
    """CircuitBreaker Redis store (NodeRedis) / a duration Redis cannot represent is rejected
    before the script writes anything"""

    def body():
        redis = yield from Redis()
        unrepresentable = fx.duration.seconds(1e17)

        # admit never creates the key.
        idle_store = yield from _store_on(redis, idle_time_to_live=unrepresentable)
        idle = yield from _on(idle_store, on_store_error="fail")
        error = yield from fx.void.pipe(idle.execute(key="unrepresentable-idle")).flip()
        assert isinstance(error, cb.CircuitBreakerError)
        assert isinstance(error.reason, cb.CircuitBreakerStoreError)
        assert (yield from redis.send("EXISTS", "circuitbreaker:unrepresentable-idle")) == 0

        # record leaves the hash and its TTL as they were.
        key = "unrepresentable-open"
        breaker = yield from cb.make(trip_policy=cb.consecutive(1), open_duration=unrepresentable)
        yield from fx.void.pipe(breaker.execute(key=key))
        before = yield from redis.send("HGETALL", f"circuitbreaker:{key}")
        yield from cb_suite.fail(breaker, key)

        assert (yield from redis.send("HGETALL", f"circuitbreaker:{key}")) == before
        ttl = yield from redis.send("PTTL", f"circuitbreaker:{key}")
        assert isinstance(ttl, int)
        assert ttl > 0
        assert (yield from breaker.state(key)) == cb.Closed(key)

    _circuit_breaker_run(fx.gen(body), cb.layer_store_redis())


# --- RateLimiter token-bucket storage (NodeRedis) -------------------------------------


def _rate_limiter_run(body: Callable[[], Generator[Any, Any]], *, live: bool = False) -> None:
    layer = rl.layer_store_redis().pipe(fx.layer.provide_merge(_redis_layer()))
    effect: fx.Effect[Any, Any, Any] = fx.gen(body)
    if live:
        effect = testing.with_live(effect)
    run: fx.Effect[Any, Any, Any] = fx.scoped(effect).pipe(fx.provide(layer))
    testing.run_test(run)


def test_returns_the_persisted_balance_after_accumulating_fractional_costs() -> None:
    """RateLimiter token-bucket storage (NodeRedis) / returns the persisted balance after
    accumulating fractional costs"""

    def body():
        redis = yield from Redis()
        key = "fractional-persisted-balance"
        results = yield from rl_suite.consume_fractional_costs(key)
        stored = float(str((yield from redis.send("GET", f"ratelimiter:{key}"))))
        assert stored == 3.9999999999999996
        assert results[-1].remaining == stored

    _rate_limiter_run(body)


def test_does_not_restore_capacity_early_after_a_fractional_token_cost() -> None:
    """RateLimiter token-bucket storage (NodeRedis) / does not restore capacity early after a
    fractional token cost"""

    def body():
        redis = yield from Redis()
        store = yield from rl.RateLimiterStore()
        memory = yield from rl.make_memory_store
        opts: dict[str, Any] = {
            "key": "fractional-cost-expiry",
            "limit": 5,
            "refill_rate_millis": 4_000,
            "allow_overflow": False,
        }
        key = f"ratelimiter:{opts['key']}"
        refill_key = f"{key}:refill"
        yield from memory.token_bucket(**opts, tokens=0.5)
        yield from store.token_bucket(**opts, tokens=0.5)
        refill_at = float(str((yield from redis.send("GET", refill_key))))
        ttl = yield from redis.send("PTTL", key)
        assert isinstance(ttl, int)
        assert ttl > 0

        # Wall time: the reported bug expires these keys after 2s, before
        # the 4s refill.
        yield from fx.sleep("2500 millis")
        before_refill = {
            "keys": (yield from redis.send("EXISTS", key, refill_key)),
            "tokens": (yield from redis.send("GET", key)),
            "memory_remaining": (yield from memory.token_bucket(**opts, tokens=0))[0],
            "redis_remaining": (yield from store.token_bucket(**opts, tokens=0))[0],
        }
        elapsed = time.time() * 1000 - refill_at
        assert 2_500 <= elapsed < 4_000

        yield from fx.sleep(fx.duration.seconds((4_100 - elapsed) / 1000))
        assert (yield from memory.token_bucket(**opts, tokens=0))[0] == 5
        assert (yield from store.token_bucket(**opts, tokens=0))[0] == 5
        assert before_refill == {
            "keys": 2,
            "tokens": "4.5",
            "memory_remaining": 4.5,
            "redis_remaining": 4.5,
        }

    _rate_limiter_run(body, live=True)


@pytest.mark.parametrize("on_exceeded", ["fail", "delay"])
def test_restarts_the_refill_interval_after_both_redis_keys_expire(
    on_exceeded: Literal["fail", "delay"],
) -> None:
    """RateLimiter token-bucket storage (NodeRedis) / ${onExceeded}: restarts the refill interval
    after both Redis keys expire"""
    key = f"timing-expired-{on_exceeded}"
    redis_key = f"ratelimiter:{key}"
    refill_key = f"{redis_key}:refill"

    # TestClock does not advance Redis's expiry clock, so expire the keys
    # by hand.
    def idle():
        redis = yield from Redis()
        yield from testing.adjust("359 seconds")
        assert (yield from redis.send("EXISTS", redis_key, refill_key)) == 2
        assert (yield from redis.send("PEXPIRE", redis_key, "0")) == 1
        assert (yield from redis.send("PEXPIRE", refill_key, "0")) == 1
        assert (yield from redis.send("EXISTS", redis_key, refill_key)) == 0

    _rate_limiter_run(rl_suite.restarts_interval(key, on_exceeded, 5, fx.gen(idle)))


# --- NodeRedis ------------------------------------------------------------------------


def test_fails_the_initial_connection_by_default() -> None:
    """fails the initial connection by default"""
    port = _redis.free_port()
    built: fx.Effect[Any, RedisError] = fx.scoped(
        redis_py.layer(f"redis://127.0.0.1:{port}").build()
    )
    error = testing.run_test(built.flip())
    assert isinstance(error, RedisError)


def _with_redis(body: Callable[[], Generator[Any, Any]], *, live: bool = False) -> None:
    effect: fx.Effect[Any, Any, Any] = fx.gen(body)
    if live:
        effect = testing.with_live(effect)
    run: fx.Effect[Any, Any, Any] = fx.scoped(effect).pipe(fx.provide(_redis_layer()))
    testing.run_test(run)


def test_uses_the_redis_py_protocol_default() -> None:
    """PersistedQueue (NodeRedis) / uses the node-redis protocol default"""

    def body():
        client = (yield from redis_py.RedisPy()).client
        assert "protocol" not in client.connection_pool.connection_kwargs

    _with_redis(body)


def test_receives_published_messages() -> None:
    """PersistedQueue (NodeRedis) / receives published messages"""

    def body():
        redis = yield from Redis()
        subscription = yield from redis.subscribe("effect-test")
        yield from redis.send("PUBLISH", "effect-test", "hello")
        assert (yield from subscription.take()) == RedisMessage("effect-test", "hello")

    _with_redis(body)


def test_runs_blocking_reads_on_a_reserved_connection_without_delaying_shared_commands() -> None:
    """PersistedQueue (NodeRedis) / runs blocking reads on a reserved connection without
    delaying shared commands"""

    def body():
        redis = yield from Redis()
        read = yield from fx.scoped(
            redis.reserve.flat_map(
                lambda connection: connection.send(
                    "XREAD", "BLOCK", "5000", "STREAMS", "effect-test-reserve", "$"
                )
            )
        ).fork()
        # XREAD with "$" only sees entries added after it starts blocking.
        yield from redis.send("CLIENT", "LIST").repeat(
            until=lambda clients: "cmd=xread" in str(clients)
        )
        yield from redis.send("XADD", "effect-test-reserve", "*", "key", "value")
        assert "value" in json.dumps((yield from read.join()))

    _with_redis(body, live=True)


def test_an_idle_subscription_does_not_hold_the_test_clock() -> None:
    """A subscription waits for messages that may never come: ``adjust``
    must not wait for it (DOGFOOD beacon #9)."""

    def body():
        redis = yield from Redis()
        yield from redis.subscribe("effect-test")
        started = time.monotonic()
        yield from testing.adjust("10 seconds")
        assert time.monotonic() - started < 0.5

    with warnings.catch_warnings():
        warnings.simplefilter("error", testing.BusyFiberWarning)
        _with_redis(body)


def test_a_blocking_read_does_not_hold_the_test_clock() -> None:
    """A blocking command waits for data that may never come: ``adjust``
    must not wait for it, while plain commands are still waited for
    (DOGFOOD beacon #9)."""

    def body():
        redis = yield from Redis()
        yield from redis.reserve.flat_map(
            lambda connection: connection.send(
                "XREAD", "BLOCK", "0", "STREAMS", "effect-test-idle", "$"
            )
        ).fork()
        yield from redis.send("CLIENT", "LIST").repeat(
            until=lambda clients: "cmd=xread" in str(clients)
        )
        started = time.monotonic()
        yield from testing.adjust("10 seconds")
        assert time.monotonic() - started < 0.5

    with warnings.catch_warnings():
        warnings.simplefilter("error", testing.BusyFiberWarning)
        _with_redis(body)
