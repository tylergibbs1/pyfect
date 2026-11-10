"""Ports of Effect's ``test/persistence/RateLimiter.test.ts``: the
``RateLimiterTest`` suite (``_rate_limiter_suite``) on
``layer_store_memory`` (``RateLimiter fixed-window (memory)`` and
``RateLimiter token-bucket timing (memory)``), then the file's own
titles.

Each test's docstring is the Effect test title; titles Effect builds in a
loop are the test's parameters. Durations are seconds, compared in
milliseconds (``to_millis``).
"""

from __future__ import annotations

import math
from collections.abc import Generator
from typing import Any, Literal

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.duration import Duration, millis, to_millis, zero
from pyfect.persistence import rate_limiter as rl

from . import _rate_limiter_suite as suite

_LAYER = rl.layer_store_memory


class TestRateLimiterMemory(suite.RateLimiterSuite):
    """RateLimiter fixed-window (memory) / RateLimiter token-bucket timing (memory)"""

    layer = _LAYER


type OnExceeded = Literal["fail", "delay"]
type Algorithm = Literal["fixed-window", "token-bucket"]


# --- RateLimiter ----------------------------------------------------------------------


def _run(body: suite.Body) -> None:
    suite.run(_LAYER, body)


@pytest.mark.parametrize(
    ("algorithm", "delays"),
    [
        ("fixed-window", [0, 60_000, 180_000, 240_000, 300_000]),
        ("token-bucket", [0, 60_000, 135_000, 210_000, 270_000]),
    ],
)
def test_charges_oversized_delay_mode_requests_behind_the_queue_and_delays_later_requests(
    algorithm: Algorithm, delays: list[int]
) -> None:
    """${algorithm}: oversized requests / charges oversized delay-mode requests behind the queue
    and delays later requests"""

    def body():
        limiter = yield from rl.make
        # A full window, then two oversized requests and a normal one, with
        # no sleeping: every reservation accounts for the earlier ones.
        results = yield from fx.for_each(
            [4, 4, 5, 5, 4],
            lambda tokens: limiter.consume(
                algorithm=algorithm,
                on_exceeded="delay",
                key="oversized",
                limit=4,
                window="1 minute",
                tokens=tokens,
            ),
        )
        assert [to_millis(result.delay) for result in results] == delays
        assert [result.remaining for result in results] == [0, -4, -9, -14, -18]
        assert [to_millis(result.reset_after) for result in results] == [
            60_000,
            120_000,
            195_000,
            270_000,
            330_000,
        ]

    _run(body)


@pytest.mark.parametrize("algorithm", ["fixed-window", "token-bucket"])
def test_rejects_oversized_fail_mode_requests_without_charging_them(algorithm: Algorithm) -> None:
    """${algorithm}: oversized requests / rejects oversized fail-mode requests without charging
    them"""

    def body():
        limiter = yield from rl.make
        opts: dict[str, Any] = {
            "algorithm": algorithm,
            "on_exceeded": "fail",
            "key": "oversized",
            "limit": 4,
            "window": "60 seconds",
        }
        error = yield from suite.exceeded(limiter.consume(**opts, tokens=5))
        assert error.key == "oversized"
        assert error.limit == 4
        assert error.remaining == 0
        assert error.retry_after == 60
        result = yield from limiter.consume(**opts, tokens=4)
        assert result.remaining == 0

    _run(body)


def test_supports_partially_applied_sleep() -> None:
    """supports partially applied sleep"""

    def body():
        limiter = yield from rl.make
        sleep = rl.sleep(limiter)
        result = yield from sleep(
            algorithm="fixed-window", window="1 minute", limit=5, key="partial"
        )
        assert result.remaining == 4

    _run(body)


def test_supports_uncurried_sleep() -> None:
    """supports uncurried sleep"""

    def body():
        limiter = yield from rl.make
        result = yield from rl.sleep(
            limiter, algorithm="fixed-window", window="1 minute", limit=5, key="direct"
        )
        assert result.remaining == 4

    _run(body)


# --- fixed-window ---------------------------------------------------------------------


def _fixed_delay(key: str, tokens: float) -> fx.Effect[rl.ConsumeResult, Any, Any]:
    return rl.make.flat_map(
        lambda limiter: limiter.consume(
            algorithm="fixed-window",
            on_exceeded="delay",
            key=key,
            limit=5,
            window="1 minute",
            tokens=tokens,
        )
    )


def test_reports_a_full_window_reset_for_an_exact_reservation() -> None:
    """fixed-window / reports a full-window reset for an exact reservation"""

    def body():
        result = yield from _fixed_delay("exact", 5)
        assert result.limit == 5
        assert result.remaining == 0
        assert result.delay == zero
        assert to_millis(result.reset_after) == 60_000

    _run(body)


def test_reports_a_fresh_partial_reset_lifetime_without_rounding() -> None:
    """fixed-window / reports a fresh partial reset lifetime without rounding"""

    def body():
        result = yield from _fixed_delay("partial", 1)
        assert result.limit == 5
        assert result.remaining == 4
        assert result.delay == zero
        assert to_millis(result.reset_after) == 12_000

    _run(body)


def test_subtracts_elapsed_time_from_reset_metadata() -> None:
    """fixed-window / subtracts elapsed time from reset metadata"""

    def body():
        yield from _fixed_delay("elapsed", 4)
        yield from testing.adjust("10 seconds")
        result = yield from _fixed_delay("elapsed", 1)
        assert result.limit == 5
        assert result.remaining == 0
        assert result.delay == zero
        assert to_millis(result.reset_after) == 50_000

    _run(body)


def test_reports_the_exact_reserved_lifetime_without_changing_overflow_delay() -> None:
    """fixed-window / reports the exact reserved lifetime without changing overflow delay"""

    def body():
        consume = _fixed_delay("overflow", 1)
        for _ in range(5):
            yield from consume
        result = yield from consume
        assert result.limit == 5
        assert result.remaining == -1
        assert result.delay == 60
        assert to_millis(result.reset_after) == 72_000

    _run(body)


def _consume_one(
    limiter: rl.RateLimiterService, algorithm: Algorithm, on_exceeded: OnExceeded
) -> fx.Effect[rl.ConsumeResult, rl.RateLimiterError]:
    return limiter.consume(
        algorithm=algorithm, on_exceeded=on_exceeded, window="1 minute", limit=5, tokens=1, key="a"
    )


def test_returns_accumulated_delays_after_the_fixed_window_is_exceeded() -> None:
    """fixed-window / returns accumulated delays after the fixed window is exceeded"""

    def body():
        limiter = yield from rl.make
        consume = _consume_one(limiter, "fixed-window", "delay")
        yield from consume.repeat(times=3)  # 1 + 3
        result = yield from consume  # 5
        assert result.delay == zero
        result = yield from consume  # 6
        assert result.delay == 60
        yield from consume.repeat(times=2)  # 7, 8, 9
        result = yield from consume  # 10
        assert result.delay == 60
        result = yield from consume  # 11
        assert result.delay == 120
        yield from testing.adjust("30 seconds")
        result = yield from consume  # 12
        assert result.delay == 90
        yield from testing.adjust("45 seconds")
        result = yield from consume  # 13
        assert result.delay == 45

    _run(body)


def test_fails_with_retry_after_until_the_fixed_window_resets() -> None:
    """fixed-window / fails with retryAfter until the fixed window resets"""

    def body():
        limiter = yield from rl.make
        consume = _consume_one(limiter, "fixed-window", "fail")
        yield from consume.repeat(times=3)
        result = yield from consume
        assert result.delay == zero
        error = yield from suite.exceeded(consume)
        assert error.retry_after == 60
        assert error.remaining == 0
        yield from testing.adjust("30 seconds")
        error = yield from suite.exceeded(consume)
        assert error.retry_after == 30
        assert error.remaining == 0
        yield from testing.adjust("30 seconds")
        result = yield from consume
        assert result.delay == zero
        assert result.remaining == 4

    _run(body)


# --- token-bucket ---------------------------------------------------------------------


def test_returns_delay_based_on_the_token_refill_rate() -> None:
    """token-bucket / returns delay based on the token refill rate"""

    def body():
        limiter = yield from rl.make
        consume = _consume_one(limiter, "token-bucket", "delay")
        refill_rate = 12
        yield from consume.repeat(times=3)  # 1 + 3
        result = yield from consume  # 5
        assert result.delay == zero
        result = yield from consume  # 6
        assert result.delay == refill_rate
        result = yield from consume  # 7
        assert result.delay == refill_rate * 2
        yield from testing.adjust("1 minute")  # 2
        result = yield from consume  # 3
        assert result.delay == zero
        assert result.remaining == 2

    _run(body)


def test_fails_until_enough_tokens_are_refilled() -> None:
    """token-bucket / fails until enough tokens are refilled"""

    def body():
        limiter = yield from rl.make
        consume = _consume_one(limiter, "token-bucket", "fail")
        yield from consume.repeat(times=3)  # 1 + 3
        result = yield from consume
        assert result.delay == zero
        error = yield from suite.exceeded(consume)
        assert error.retry_after == 12
        assert error.remaining == 0
        yield from testing.adjust(millis(36_000))
        result = yield from consume
        assert result.delay == zero
        assert result.remaining == 2

    _run(body)


# --- adaptive -------------------------------------------------------------------------


def _adaptive(
    store: rl.RateLimiterStoreService, tokens: float = 1, key: str = "a"
) -> fx.Effect[rl.AdaptiveConsumeResult, rl.RateLimiterError]:
    return store.adaptive_consume(
        key=key, tokens=tokens, fallback_limit=5, fallback_window=millis(60_000)
    )


def _feedback(
    store: rl.RateLimiterStoreService,
    epoch: int,
    retry_after: float | None,
    *,
    tokens: float = 1,
    status: int = 429,
) -> fx.Effect[None, rl.RateLimiterError]:
    return store.adaptive_feedback(
        key="a",
        epoch=epoch,
        tokens=tokens,
        status=status,
        retry_after=None if retry_after is None else Duration(retry_after),
    )


def _learned_after(
    store: rl.RateLimiterStoreService, retry_after: float
) -> Generator[Any, Any, rl.AdaptiveConsumeResult]:
    """The first 429 (one second), one admitted request, then a rejected
    one: the epoch the rejection was sent in."""
    first = yield from _adaptive(store)
    yield from _feedback(store, first.epoch, 1)
    yield from testing.adjust("1 second")
    yield from _adaptive(store)
    rejected = yield from _adaptive(store)
    yield from _feedback(store, rejected.epoch, retry_after)
    return rejected


def test_uses_the_inactive_store_path_until_429_retry_after_feedback() -> None:
    """adaptive / uses the inactive store path until 429 Retry-After feedback"""

    def body():
        store = yield from rl.RateLimiterStore()
        result = yield from _adaptive(store)
        assert (result.delay, result.epoch, result.phase) == (zero, 0, "inactive")
        yield from _feedback(store, result.epoch, 1, status=200)
        result = yield from _adaptive(store)
        assert (result.delay, result.epoch, result.phase) == (zero, 0, "inactive")
        yield from _feedback(store, result.epoch, None)
        result = yield from _adaptive(store)
        assert (result.delay, result.epoch, result.phase) == (zero, 0, "inactive")

    _run(body)


def test_starts_cooldown_on_the_first_429_retry_after_feedback() -> None:
    """adaptive / starts cooldown on the first 429 Retry-After feedback"""

    def body():
        store = yield from rl.RateLimiterStore()
        first = yield from _adaptive(store)
        yield from _feedback(store, first.epoch, 5)
        result = yield from _adaptive(store)
        assert (result.delay, result.epoch, result.phase) == (5, 0, "cooldown")
        other = yield from _adaptive(store, key="b")
        assert (other.delay, other.epoch, other.phase) == (zero, 0, "inactive")

    _run(body)


def test_clamps_zero_retry_after_feedback_to_the_minimum_cooldown() -> None:
    """adaptive / clamps zero Retry-After feedback to the minimum cooldown"""

    def body():
        store = yield from rl.RateLimiterStore()
        first = yield from _adaptive(store)
        yield from _feedback(store, first.epoch, 0)
        result = yield from _adaptive(store)
        assert (to_millis(result.delay), result.epoch, result.phase) == (1, 0, "cooldown")

    _run(body)


def test_bounds_excessive_adaptive_retry_after_cooldowns() -> None:
    """adaptive / bounds excessive adaptive Retry-After cooldowns"""

    def body():
        store = yield from rl.RateLimiterStore()
        first = yield from _adaptive(store)
        yield from _feedback(store, first.epoch, 7200)
        result = yield from _adaptive(store)
        assert (result.delay, result.epoch, result.phase) == (3600, 0, "cooldown")
        yield from testing.adjust("1 hour")
        result = yield from _adaptive(store)
        assert (result.delay, result.epoch, result.phase) == (zero, 1, "learning")

    _run(body)


def test_returns_the_remaining_cooldown_delay() -> None:
    """adaptive / returns the remaining cooldown delay"""

    def body():
        store = yield from rl.RateLimiterStore()
        first = yield from _adaptive(store)
        yield from _feedback(store, first.epoch, 10)
        yield from testing.adjust("4 seconds")
        result = yield from _adaptive(store)
        assert (result.delay, result.epoch, result.phase) == (6, 0, "cooldown")

    _run(body)


def test_starts_learning_on_the_first_admitted_post_cooldown_request() -> None:
    """adaptive / starts learning on the first admitted post-cooldown request"""

    def body():
        store = yield from rl.RateLimiterStore()
        first = yield from _adaptive(store)
        yield from _feedback(store, first.epoch, 10)
        yield from testing.adjust("10 seconds")
        result = yield from _adaptive(store, tokens=2)
        assert (result.delay, result.epoch, result.phase) == (zero, 1, "learning")

    _run(body)


def test_keeps_learning_requests_at_zero_delay_while_observing_token_counts() -> None:
    """adaptive / keeps learning requests at zero delay while observing token counts"""

    def body():
        store = yield from rl.RateLimiterStore()
        first = yield from _adaptive(store)
        yield from _feedback(store, first.epoch, 1)
        yield from testing.adjust("1 second")
        learning = yield from _adaptive(store, tokens=2)
        assert learning.phase == "learning"
        result = yield from _adaptive(store, tokens=3)
        assert (result.delay, result.epoch, result.phase) == (zero, learning.epoch, "learning")

    _run(body)


def test_learns_the_accepted_token_count_and_inferred_window_from_learning_feedback() -> None:
    """adaptive / learns the accepted token count and inferred window from learning feedback"""

    def body():
        store = yield from rl.RateLimiterStore()
        first = yield from _adaptive(store)
        yield from _feedback(store, first.epoch, 1)
        yield from testing.adjust("1 second")
        learning = yield from _adaptive(store, tokens=2)
        yield from testing.adjust("4 seconds")
        rejected = yield from _adaptive(store, tokens=3)
        yield from _feedback(store, rejected.epoch, 6, tokens=3)
        yield from testing.adjust("6 seconds")
        assert learning.epoch == rejected.epoch
        result = yield from _adaptive(store)
        assert (result.delay, result.phase) == (zero, "learned")
        result = yield from _adaptive(store)
        assert (result.delay, result.phase) == (zero, "learned")
        result = yield from _adaptive(store)
        assert (result.delay, result.phase) == (10, "learned")

    _run(body)


def test_ignores_stale_epoch_feedback() -> None:
    """adaptive / ignores stale epoch feedback"""

    def body():
        store = yield from rl.RateLimiterStore()
        first = yield from _adaptive(store)
        yield from _feedback(store, first.epoch, 1)
        yield from testing.adjust("1 second")
        learning = yield from _adaptive(store)
        yield from _feedback(store, first.epoch, 10)
        result = yield from _adaptive(store)
        assert (result.delay, result.epoch, result.phase) == (zero, learning.epoch, "learning")

    _run(body)


def test_prevents_repeated_learning_429_feedback_from_corrupting_learned_state() -> None:
    """adaptive / prevents repeated learning 429 feedback from corrupting learned state"""

    def body():
        store = yield from rl.RateLimiterStore()
        rejected = yield from _learned_after(store, 5)
        yield from _feedback(store, rejected.epoch, 30)
        learned = yield from _adaptive(store)
        assert (learned.delay, learned.epoch, learned.phase) == (
            5,
            rejected.epoch + 1,
            "learned",
        )

    _run(body)


def test_same_epoch_learned_429_feedback_enters_cooldown_and_can_only_extend_it() -> None:
    """adaptive / same-epoch learned 429 feedback enters cooldown and can only extend it"""

    def body():
        store = yield from rl.RateLimiterStore()
        yield from _learned_after(store, 5)
        learned = yield from _adaptive(store)
        yield from _feedback(store, learned.epoch, 5)
        yield from _feedback(store, learned.epoch, 10)
        result = yield from _adaptive(store)
        assert (result.delay, result.epoch, result.phase) == (10, learned.epoch, "cooldown")

    _run(body)


def test_stores_only_cooldown_when_no_tokens_were_accepted_during_learning() -> None:
    """adaptive / stores only cooldown when no tokens were accepted during learning"""

    def body():
        store = yield from rl.RateLimiterStore()
        first = yield from _adaptive(store)
        yield from _feedback(store, first.epoch, 1)
        yield from testing.adjust("1 second")
        learning = yield from _adaptive(store, tokens=2)
        yield from _feedback(store, learning.epoch, 5, tokens=2)
        result = yield from _adaptive(store)
        assert (result.delay, result.epoch, result.phase) == (5, learning.epoch, "cooldown")
        yield from testing.adjust("5 seconds")
        result = yield from _adaptive(store)
        assert (result.delay, result.epoch, result.phase) == (
            zero,
            learning.epoch + 1,
            "learning",
        )

    _run(body)


def test_expires_learned_adaptive_state() -> None:
    """adaptive / expires learned adaptive state"""

    def body():
        store = yield from rl.RateLimiterStore()
        yield from _learned_after(store, 1)
        yield from testing.adjust("61 seconds")
        result = yield from _adaptive(store)
        assert (result.delay, result.epoch, result.phase) == (zero, 0, "inactive")

    _run(body)


def test_bounds_learned_adaptive_windows_and_expires_the_bounded_state() -> None:
    """adaptive / bounds learned adaptive windows and expires the bounded state"""

    def body():
        store = yield from rl.RateLimiterStore()
        first = yield from _adaptive(store)
        yield from _feedback(store, first.epoch, 0.001)
        yield from testing.adjust("1 millis")
        yield from _adaptive(store)
        rejected = yield from _adaptive(store)
        yield from _feedback(store, rejected.epoch, 7200)
        result = yield from _adaptive(store)
        assert (result.delay, result.phase) == (3600, "learned")
        yield from testing.adjust(millis(3_660_000))
        result = yield from _adaptive(store)
        assert (result.delay, result.epoch, result.phase) == (zero, 0, "inactive")

    _run(body)


@pytest.mark.parametrize("algorithm", ["fixed-window", "token-bucket"])
def test_rejects_positive_token_requests_with_a_zero_limit(algorithm: Algorithm) -> None:
    """${algorithm}: oversized requests / rejects positive token requests with a zero limit"""

    def body():
        limiter = yield from rl.make
        options: dict[str, Any] = {
            "algorithm": algorithm,
            "key": "zero-limit",
            "limit": 0,
            "window": "1 minute",
        }
        error = yield from limiter.consume(**options, on_exceeded="fail").flip()
        assert isinstance(error.reason, rl.RateLimitExceeded), "Expected RateLimitExceeded"
        assert error.reason.remaining == 0

        result = yield from limiter.consume(**options, on_exceeded="delay")
        assert result.delay == math.inf
        assert result.reset_after == math.inf

        query = yield from limiter.consume(**options, on_exceeded="delay", tokens=0)
        assert query.delay == zero
        assert query.reset_after == zero

    _run(body)


# --- memory store retention -----------------------------------------------------------


def test_keeps_state_until_it_expires_then_reclaims_it_while_idle() -> None:
    """memory store retention / keeps state until it expires, then reclaims it while idle"""

    def body() -> Generator[Any, Any]:
        memory = yield from rl.make_memory_store
        limiter = yield from rl.make.pipe(fx.provide_service(rl.RateLimiterStore, memory))
        # One token of delay-mode debt: fully refilled after three minutes.
        yield from limiter.consume(
            algorithm="token-bucket",
            on_exceeded="delay",
            key="bucket",
            limit=2,
            window="2 minutes",
            tokens=3,
        )

        yield from testing.adjust("2 minutes")
        assert memory.size == 1

        yield from testing.adjust("2 minutes")
        assert memory.size == 0

    testing.run_test(fx.scoped(fx.gen(body)))


def test_starts_an_expired_token_bucket_fresh_before_the_next_sweep() -> None:
    """memory store retention / starts an expired token bucket fresh before the next sweep"""

    def body():
        limiter = yield from rl.make
        yield from limiter.consume(
            algorithm="token-bucket", key="bucket", limit=1, window="1 second"
        )

        # Past the bucket's expiry, before any sweep: a new configuration starts fresh.
        yield from testing.adjust("2 seconds")
        result = yield from limiter.consume(
            algorithm="token-bucket", key="bucket", limit=1, window="1 hour"
        )
        assert result.remaining == 0

    _run(body)
