"""RateLimiter and CircuitBreaker edges checked against Effect under Node.

The refill-rate values were printed by Effect's ``RateLimiter`` on the
``TestClock``: Effect divides the window into whole nanoseconds
(``Duration.divideUnsafe``) and every ``Duration.millis`` it gives is whole
nanoseconds too.
"""

from __future__ import annotations

import math
from collections.abc import Generator
from typing import Any, cast

import pytest
from oracle import _redis

import pyfect as fx
from pyfect import testing
from pyfect.duration import Seconds, to_millis
from pyfect.exit import Failure
from pyfect.persistence import circuit_breaker as cb
from pyfect.persistence import rate_limiter as rl
from pyfect.persistence import redis_py


def _consume_twice(
    window_millis: float, limit: float, algorithm: rl.Algorithm, tokens: float
) -> list[float]:
    def body() -> Generator[Any, Any, list[float]]:
        limiter = yield from rl.RateLimiter()
        out: list[float] = []
        for _ in range(2):
            result = yield from limiter.consume(
                key="key",
                window=Seconds(window_millis / 1000),
                limit=limit,
                algorithm=algorithm,
                on_exceeded="delay",
                tokens=tokens,
            )
            out += [to_millis(result.delay), to_millis(result.reset_after), result.remaining]
        return out

    layer = rl.layer.pipe(fx.provide(rl.layer_store_memory))
    return testing.run_test(fx.gen(body).pipe(fx.provide(layer)))


@pytest.mark.parametrize(
    ("window", "limit", "algorithm", "tokens", "expected"),
    [
        (1000, 3, "fixed-window", 2, [0, 666.666666, 1, 1000, 1333.333332, -1]),
        (1000, 3, "token-bucket", 5, [666.666666, 1666.666665, -2, 2333.333331, 3333.33333, -7]),
        (1000.5, 3, "fixed-window", 2, [0, 667, 1, 1000.5, 1334, -1]),
        (1000, 2.5, "token-bucket", 4, [800, 1600, -1.5, 2400, 3200, -5.5]),
        (100, 7, "fixed-window", 9, [100, 128.571426, -2, 200, 257.142852, -11]),
        (1000, 0.3, "fixed-window", 1, [0, 3333.333333, -0.7, 3000, 6666.666666, -1.7]),
    ],
)
def test_refill_rates_are_whole_nanoseconds_as_in_effect(
    window: float, limit: float, algorithm: rl.Algorithm, tokens: float, expected: list[float]
) -> None:
    assert _consume_twice(window, limit, algorithm, tokens) == expected


_INF = math.inf


@pytest.mark.parametrize(
    ("limit", "algorithm", "expected"),
    [
        # A zero limit never refills: Effect's fixed window gives no delay
        # (its arithmetic is NaN) and its token bucket an infinite one.
        (0, "fixed-window", [0, _INF, -1, 0, _INF, -2]),
        (0, "token-bucket", [_INF, _INF, -1, _INF, _INF, -2]),
        # An infinite limit never limits.
        (_INF, "fixed-window", [0, 0, _INF, 0, 0, _INF]),
        (_INF, "token-bucket", [0, 0, _INF, 0, 0, _INF]),
    ],
)
def test_zero_and_infinite_limits_follow_javascript_arithmetic(
    limit: float, algorithm: rl.Algorithm, expected: list[float]
) -> None:
    assert _consume_twice(1000, limit, algorithm, 1) == expected


def test_an_infinite_limit_never_fails_in_fail_mode() -> None:
    def body() -> Generator[Any, Any, list[float]]:
        limiter = yield from rl.RateLimiter()
        result = yield from limiter.consume(
            key="key", window="1 second", limit=_INF, algorithm="token-bucket", tokens=5
        )
        return [to_millis(result.delay), to_millis(result.reset_after), result.remaining]

    layer = rl.layer.pipe(fx.provide(rl.layer_store_memory))
    assert testing.run_test(fx.gen(body).pipe(fx.provide(layer))) == [0, 0, _INF]


def test_a_shorter_same_epoch_retry_after_does_not_shorten_a_cooldown() -> None:
    def adaptive(store: rl.RateLimiterStoreService) -> fx.Effect[rl.AdaptiveConsumeResult, Any]:
        return store.adaptive_consume(
            key="a", tokens=1, fallback_limit=5, fallback_window=Seconds(60)
        )

    def feedback(
        store: rl.RateLimiterStoreService, epoch: int, retry_after: float
    ) -> fx.Effect[None, Any]:
        return store.adaptive_feedback(
            key="a", epoch=epoch, tokens=1, status=429, retry_after=Seconds(retry_after)
        )

    def body() -> Generator[Any, Any, rl.AdaptiveConsumeResult]:
        store = yield from rl.RateLimiterStore()
        first = yield from adaptive(store)
        yield from feedback(store, first.epoch, 10)
        yield from feedback(store, first.epoch, 5)
        return (yield from adaptive(store))

    effect = fx.gen(body).pipe(fx.provide(rl.layer_store_memory))
    result = testing.run_test(effect)
    assert (to_millis(result.delay), result.phase) == (10_000, "cooldown")


# --- durations Redis cannot hold ------------------------------------------------------

pytestmark = pytest.mark.filterwarnings("ignore::pyfect.testing.ClockNotAdvancedWarning")


def _on_redis(
    effect: fx.Effect[Any, Any, Any], store: fx.Layer[cb.CircuitBreakerStore, Any, Any]
) -> Any:
    _redis.flush()
    layer = store.pipe(fx.layer.provide_merge(redis_py.layer(_redis.server().url)))
    run: fx.Effect[Any, Any, Any] = fx.scoped(effect).pipe(fx.provide(layer))
    return testing.run_test(run)


def _rate_at_threshold() -> Generator[Any, Any, list[str]]:
    # One failure in two calls is exactly the threshold, which trips.
    breaker = yield from cb.make(
        trip_policy=cb.rate(threshold=0.5, size=2, minimum_calls=2), open_duration="1 minute"
    )
    states: list[str] = []
    for call in (fx.void, fx.fail("boom")):
        yield from call.pipe(breaker.execute(key="rate")).ignore()
        states.append(type((yield from breaker.state("rate"))).__name__)
    return states


def test_a_failure_rate_equal_to_the_threshold_trips_in_memory() -> None:
    effect = fx.scoped(fx.gen(_rate_at_threshold)).pipe(fx.provide(cb.layer_store_memory()))
    assert testing.run_test(effect) == ["Closed", "Open"]


def test_a_failure_rate_equal_to_the_threshold_trips_on_redis() -> None:
    assert _on_redis(fx.gen(_rate_at_threshold), cb.layer_store_redis()) == ["Closed", "Open"]


def test_an_infinite_open_duration_on_redis_is_a_store_error_not_a_defect() -> None:
    # Effect sends ``Infinity`` and the record script rejects it, so the
    # failed record is reported and the call's own result stands.
    def body() -> Generator[Any, Any, object]:
        breaker = yield from cb.make(trip_policy=cb.consecutive(1), open_duration=math.inf)
        exit = yield from fx.fail("boom").pipe(breaker.execute(key="inf")).exit()
        state = yield from breaker.state("inf")
        return exit, state

    exit, state = _on_redis(fx.gen(body), cb.layer_store_redis())
    assert isinstance(exit, Failure)
    exit = cast("Failure[str]", exit)
    assert exit.cause.find_error() == fx.Ok("boom")
    assert state == cb.Closed("inf")


def test_an_infinite_probe_lease_on_redis_fails_admission_with_a_store_error() -> None:
    def body() -> Generator[Any, Any, object]:
        breaker = yield from cb.make(
            trip_policy=cb.consecutive(1), open_duration="1 second", on_store_error="fail"
        )
        return (yield from fx.void.pipe(breaker.execute(key="lease")).flip())

    error = _on_redis(fx.gen(body), cb.layer_store_redis(probe_lease=math.inf))
    assert isinstance(error, cb.CircuitBreakerError)
    assert isinstance(error.reason, cb.CircuitBreakerStoreError)
