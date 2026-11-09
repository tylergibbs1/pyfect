"""Effect's ``test/persistence/RateLimiterTest.ts``: the suite each
``RateLimiterStore`` runs (its ``suite(name, layer)``), as bodies for the
test modules to run on their stores, plus ``restarts_interval`` and
``consume_fractional_costs``.

Durations are seconds (Effect's ``"5 minutes"`` is ``300``, ``59_000``
milliseconds ``59``); results are compared in milliseconds
(``to_millis``), as Effect's ``Duration.toMillis``. ``Effect.flip`` of an
expected rejection is ``exceeded(...)``.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, Literal

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.duration import ZERO, Seconds, to_millis
from pyfect.persistence import rate_limiter as rl

type Body = Callable[[], Generator[Any, Any]]
type OnExceeded = Literal["fail", "delay"]


def run(layer: fx.Layer[rl.RateLimiterStore, Any, Any], body: Body) -> None:
    testing.run_test(fx.scoped(fx.gen(body)).pipe(fx.provide(layer)))


def options(key: str, on_exceeded: OnExceeded = "fail") -> dict[str, Any]:
    return {
        "algorithm": "token-bucket",
        "window": "300 seconds",
        "limit": 5,
        "key": key,
        "on_exceeded": on_exceeded,
    }


def exceeded(
    effect: fx.Effect[rl.ConsumeResult, rl.RateLimiterError],
) -> fx.Effect[rl.RateLimitExceeded, rl.ConsumeResult]:
    def reason(error: rl.RateLimiterError) -> rl.RateLimitExceeded:
        assert isinstance(error.reason, rl.RateLimitExceeded), "Expected RateLimitExceeded"
        return error.reason

    return effect.flip().map(reason)


def restarts_interval(
    key: str, on_exceeded: OnExceeded, tokens: float, idle: fx.Effect[None, Any, Any]
) -> Body:
    """Consumes ``tokens``, runs ``idle``, and checks the bucket is back at
    capacity with a fresh refill interval."""

    def body():
        limiter = yield from rl.make
        opts = options(key, on_exceeded)
        yield from limiter.consume(**opts, tokens=tokens)
        yield from idle
        result = yield from limiter.consume(**opts, tokens=tokens)
        assert result.remaining == 5 - tokens
        assert result.delay == ZERO
        assert to_millis(result.reset_after) == tokens * 60_000

        excess_opts: dict[str, Any] = {**opts, "tokens": 6 - tokens}
        excess = limiter.consume(**excess_opts)
        if on_exceeded == "fail":
            error = yield from exceeded(excess)
            assert to_millis(error.retry_after) == 60_000
        else:
            delayed = yield from excess
            assert delayed.remaining == -1
            assert to_millis(delayed.delay) == 60_000
            assert to_millis(delayed.reset_after) == 360_000

    return body


def consume_fractional_costs(key: str) -> fx.Effect[list[rl.ConsumeResult], Any, Any]:
    def body():
        limiter = yield from rl.make
        return (
            yield from fx.for_each(
                [0.1, 0.1, 0.4, 0.15, 0.15, 0.1],
                lambda tokens: limiter.consume(**options(key), tokens=tokens),
            )
        )

    return fx.gen(body)


# --- RateLimiter fixed-window (${name}) -----------------------------------------------


def remaining_capacity(tokens: float, expected: list[float | str]) -> Body:
    def body():
        limiter = yield from rl.make
        opts: dict[str, Any] = {
            "algorithm": "fixed-window",
            "key": f"fixed-window-fail-{tokens}",
            "limit": 1,
            "window": "60 seconds",
        }

        def attempt(_: int) -> fx.Effect[float | str]:
            return limiter.consume(**opts, tokens=tokens).match(
                on_success=lambda result: result.remaining,
                on_failure=lambda error: type(error.reason).__name__,
            )

        assert (yield from fx.for_each([0, 1, 2], attempt)) == expected
        available = yield from limiter.consume(**opts, tokens=0)
        assert available.remaining == expected[0]

    return body


def fractional_delay_reservations():
    limiter = yield from rl.make
    results = yield from fx.for_each(
        [0, 1, 2],
        lambda _: limiter.consume(
            algorithm="fixed-window",
            on_exceeded="delay",
            key="fixed-window-fractional-delay",
            limit=1,
            window="1 minute",
            tokens=0.75,
        ),
    )
    assert [to_millis(result.delay) for result in results[:2]] == [0, 0]
    # Redis TTLs use wall time rather than TestClock.
    assert abs(to_millis(results[2].delay) - 60_000) <= 1_000
    assert [result.remaining for result in results] == [0.25, -0.5, -1.25]


# --- RateLimiter token-bucket timing (${name}) ----------------------------------------


def timing(on_exceeded: OnExceeded, elapsed: int, tokens: int, expected: int, reset: int) -> Body:
    def body():
        limiter = yield from rl.make
        opts = options(f"timing-{on_exceeded}-{elapsed}-{tokens}", on_exceeded)
        yield from limiter.consume(**opts, tokens=5)
        yield from testing.adjust(Seconds(elapsed / 1000))
        if on_exceeded == "fail":
            error = yield from exceeded(limiter.consume(**opts, tokens=tokens))
            assert to_millis(error.retry_after) == expected
            assert error.remaining == 0
        else:
            result = yield from limiter.consume(**opts, tokens=tokens)
            assert to_millis(result.delay) == expected
            assert result.remaining == elapsed // 60_000 - tokens
            assert to_millis(result.reset_after) == reset

    return body


def reset_after_accounts_for_elapsed_time(on_exceeded: OnExceeded) -> Body:
    def body():
        limiter = yield from rl.make
        opts = options(f"timing-allowed-{on_exceeded}", on_exceeded)
        initial = yield from limiter.consume(**opts, tokens=4)
        assert to_millis(initial.reset_after) == 240_000
        yield from testing.adjust("59 seconds")
        result = yield from limiter.consume(**opts)
        assert result.delay == ZERO
        assert result.remaining == 0
        assert to_millis(result.reset_after) == 241_000

        yield from testing.adjust("241 seconds")
        full = yield from limiter.consume(**opts, tokens=0)
        assert full.remaining == 5
        assert full.reset_after == ZERO

    return body


def zero_token_call_restarts_the_interval():
    limiter = yield from rl.make
    opts = options("timing-zero-tokens")
    initial = yield from limiter.consume(**opts, tokens=0)
    assert initial.remaining == 5
    assert initial.reset_after == ZERO
    yield from testing.adjust("30 seconds")
    result = yield from limiter.consume(**opts)
    assert result.remaining == 4
    assert result.delay == ZERO
    assert to_millis(result.reset_after) == 60_000


def signed_fractional_token_counts(allow_overflow: bool) -> Body:
    def body():
        store = yield from rl.RateLimiterStore()
        opts: dict[str, Any] = {
            "key": f"fractional-count-{str(allow_overflow).lower()}",
            "limit": 5,
            "refill_rate_millis": 60_000,
            "allow_overflow": allow_overflow,
        }
        initial = yield from store.token_bucket(**opts, tokens=4.5)
        excess = yield from store.token_bucket(**opts, tokens=1)
        stored = yield from store.token_bucket(**opts, tokens=0)
        assert [initial, excess, stored] == [
            (0.5, 0),
            (-0.5, 0),
            (-0.5 if allow_overflow else 0.5, 0),
        ]

    return body


def accumulated_fractional_balances():
    results = yield from consume_fractional_costs("fractional-accumulation")
    assert [
        {
            "remaining": result.remaining,
            "delay": to_millis(result.delay),
            "reset_after": to_millis(result.reset_after),
        }
        for result in results
    ] == [
        {"remaining": 4.9, "delay": 0, "reset_after": 60_000},
        {"remaining": 4.800000000000001, "delay": 0, "reset_after": 60_000},
        {"remaining": 4.4, "delay": 0, "reset_after": 60_000},
        {"remaining": 4.25, "delay": 0, "reset_after": 60_000},
        {"remaining": 4.1, "delay": 0, "reset_after": 60_000},
        {"remaining": 3.9999999999999996, "delay": 0, "reset_after": 120_000},
    ]


def fractional_token_deficit():
    limiter = yield from rl.make
    opts = options("fractional-deficit", "fail")
    yield from limiter.consume(**opts, tokens=4.5)
    error = yield from exceeded(limiter.consume(**opts))
    assert error.remaining == 0
    assert error.limit == 5


def fractional_costs_reset(on_exceeded: OnExceeded) -> Body:
    def body():
        limiter = yield from rl.make
        opts = options(f"fractional-reset-{on_exceeded}", on_exceeded)
        initial = yield from limiter.consume(**opts, tokens=0.5)
        yield from testing.adjust("45 seconds")
        partial = yield from limiter.consume(**opts, tokens=0)
        yield from testing.adjust("15 seconds")
        full = yield from limiter.consume(**opts, tokens=0)
        assert full.remaining == 5
        assert [to_millis(result.reset_after) for result in (initial, partial, full)] == [
            60_000,
            15_000,
            0,
        ]

    return body


def fractional_deficits_remain_rejected():
    limiter = yield from rl.make
    opts = options("fractional-retry-boundary", "fail")
    yield from limiter.consume(**opts, tokens=4.5)
    yield from testing.adjust("45 seconds")
    first = yield from exceeded(limiter.consume(**opts))
    yield from testing.adjust("14999 millis")
    before_refill = yield from exceeded(limiter.consume(**opts))
    yield from testing.adjust("1 millis")
    allowed = yield from limiter.consume(**opts)
    assert [to_millis(error.retry_after) for error in (first, before_refill)] == [15_000, 1]
    assert allowed.remaining == 0.5
    assert allowed.delay == ZERO


def fractional_delay_reservations_wait():
    limiter = yield from rl.make
    opts = options("fractional-reservation-boundary", "delay")
    yield from limiter.consume(**opts, tokens=4.5)
    yield from testing.adjust("45 seconds")
    first = yield from limiter.consume(**opts)
    second = yield from limiter.consume(**opts, tokens=1.25)
    yield from testing.adjust("74999 millis")
    before_refill = yield from limiter.consume(**opts, tokens=0)
    yield from testing.adjust("1 millis")
    available = yield from limiter.consume(**opts, tokens=0)
    assert [
        {
            "remaining": result.remaining,
            "delay": to_millis(result.delay),
            "reset_after": to_millis(result.reset_after),
        }
        for result in (first, second, before_refill, available)
    ] == [
        {"remaining": -0.5, "delay": 15_000, "reset_after": 315_000},
        {"remaining": -1.75, "delay": 75_000, "reset_after": 375_000},
        {"remaining": -0.75, "delay": 1, "reset_after": 300_001},
        {"remaining": 0.25, "delay": 0, "reset_after": 300_000},
    ]


def fractional_elapsed_milliseconds():
    store = yield from rl.RateLimiterStore()
    opts: dict[str, Any] = {
        "key": "timing-fractional",
        "limit": 3,
        "refill_rate_millis": 1_000 / 3,
        "allow_overflow": True,
    }
    initial = yield from store.token_bucket(**opts, tokens=3)
    assert initial == (0, 0)
    yield from testing.adjust("500 millis")
    remaining, elapsed_millis = yield from store.token_bucket(**opts, tokens=1)
    assert remaining == 0
    assert abs(elapsed_millis - 1_000 / 6) <= 0.000_001

    limiter = yield from rl.make
    result = yield from limiter.consume(
        algorithm="token-bucket", on_exceeded="delay", window="1 second", limit=3, key=opts["key"]
    )
    assert result.remaining == -1
    assert abs(to_millis(result.delay) - 1_000 / 6) <= 0.000_01
    assert abs(to_millis(result.reset_after) - 7_000 / 6) <= 0.000_01


def failed_retries_do_not_reserve_tokens():
    limiter = yield from rl.make
    opts = options("timing-fail-boundary", "fail")
    yield from limiter.consume(**opts, tokens=5)
    yield from limiter.consume(**opts).flip()
    yield from testing.adjust("59 seconds")
    yield from limiter.consume(**opts).flip()
    yield from limiter.consume(**opts).flip()
    yield from testing.adjust("1 second")
    result = yield from limiter.consume(**opts)
    assert result.delay == ZERO
    assert result.remaining == 0
    assert to_millis(result.reset_after) == 300_000


def accumulated_delay_reservations():
    limiter = yield from rl.make
    opts = options("timing-delay-reservations", "delay")
    yield from limiter.consume(**opts, tokens=5)
    yield from testing.adjust("59 seconds")
    yield from limiter.consume(**opts)
    result = yield from limiter.consume(**opts)
    assert to_millis(result.delay) == 61_000
    assert result.remaining == -2
    assert to_millis(result.reset_after) == 361_000


_ON_EXCEEDED = pytest.mark.parametrize("on_exceeded", ["fail", "delay"])


class RateLimiterSuite:
    """Effect's ``suite(name, layer)``: a test module subclasses it as
    ``Test...`` with the store's ``layer``."""

    layer: fx.Layer[rl.RateLimiterStore, Any, Any]

    def run(self, body: Body) -> None:
        run(self.layer, body)

    # RateLimiter fixed-window (${name})

    @pytest.mark.parametrize(
        ("tokens", "expected"),
        [
            (1, [0, "RateLimitExceeded", "RateLimitExceeded"]),
            (0.75, [0.25, "RateLimitExceeded", "RateLimitExceeded"]),
        ],
    )
    def test_preserves_remaining_capacity_and_rejects_excess_requests(
        self, tokens: float, expected: list[float | str]
    ) -> None:
        """preserves remaining capacity and rejects excess requests with cost ${tokens}"""
        self.run(remaining_capacity(tokens, expected))

    def test_preserves_fractional_delay_reservations(self) -> None:
        """preserves fractional delay reservations"""
        self.run(fractional_delay_reservations)

    # RateLimiter token-bucket timing (${name})

    @_ON_EXCEEDED
    @pytest.mark.parametrize(
        ("elapsed", "tokens", "expected", "reset"),
        [
            (59_000, 1, 1_000, 301_000),
            (59_500, 1, 500, 300_500),
            (59_000, 2, 61_000, 361_000),
            (119_000, 2, 1_000, 301_000),
        ],
    )
    def test_tokens_after_elapsed_waits(
        self, on_exceeded: OnExceeded, elapsed: int, tokens: int, expected: int, reset: int
    ) -> None:
        """${onExceeded}: ${tokens} tokens after ${elapsed}ms waits ${expected}ms"""
        self.run(timing(on_exceeded, elapsed, tokens, expected, reset))

    @_ON_EXCEEDED
    def test_reset_after_accounts_for_elapsed_time_on_an_allowed_request(
        self,
        on_exceeded: OnExceeded,
    ) -> None:
        """${onExceeded}: resetAfter accounts for elapsed time on an allowed request"""
        self.run(reset_after_accounts_for_elapsed_time(on_exceeded))

    @_ON_EXCEEDED
    @pytest.mark.parametrize(("tokens", "idle"), [(1, 61), (5, 359)])
    def test_restarts_the_refill_interval_after_idle(
        self, on_exceeded: OnExceeded, tokens: int, idle: int
    ) -> None:
        """${onExceeded}: restarts the refill interval after ${idle} idle"""
        key = f"timing-idle-{on_exceeded}-{tokens}"
        self.run(restarts_interval(key, on_exceeded, tokens, testing.adjust(Seconds(idle))))

    def test_restarts_the_interval_after_a_zero_token_call_without_a_whole_token_refill(
        self,
    ) -> None:
        """restarts the interval after a zero-token call without a whole-token refill"""
        self.run(zero_token_call_restarts_the_interval)

    @pytest.mark.parametrize("allow_overflow", [False, True])
    def test_preserves_signed_fractional_token_counts(self, allow_overflow: bool) -> None:
        """preserves signed fractional token counts with allowOverflow=${allowOverflow}"""
        self.run(signed_fractional_token_counts(allow_overflow))

    def test_preserves_accumulated_fractional_balances_and_their_reset_timing(self) -> None:
        """preserves accumulated fractional balances and their reset timing"""
        self.run(accumulated_fractional_balances)

    def test_rejects_a_request_with_a_fractional_token_deficit(self) -> None:
        """rejects a request with a fractional token deficit"""
        self.run(fractional_token_deficit)

    @_ON_EXCEEDED
    def test_fractional_costs_reset_at_the_next_whole_token_refill(
        self, on_exceeded: OnExceeded
    ) -> None:
        """${onExceeded}: fractional costs reset at the next whole-token refill"""
        self.run(fractional_costs_reset(on_exceeded))

    def test_fractional_deficits_remain_rejected_until_the_whole_token_refill(self) -> None:
        """fractional deficits remain rejected until the whole-token refill"""
        self.run(fractional_deficits_remain_rejected)

    def test_fractional_delay_reservations_wait_for_enough_whole_token_refills(self) -> None:
        """fractional delay reservations wait for enough whole-token refills"""
        self.run(fractional_delay_reservations_wait)

    def test_preserves_fractional_elapsed_milliseconds_in_the_store_tuple_and_timing_metadata(
        self,
    ) -> None:
        """preserves fractional elapsed milliseconds in the store tuple and timing metadata"""
        self.run(fractional_elapsed_milliseconds)

    def test_failed_retries_do_not_reserve_tokens_or_move_the_refill_boundary(self) -> None:
        """failed retries do not reserve tokens or move the refill boundary"""
        self.run(failed_retries_do_not_reserve_tokens)

    def test_accumulated_delay_reservations_retain_the_partial_refill_interval(self) -> None:
        """accumulated delay reservations retain the partial refill interval"""
        self.run(accumulated_delay_reservations)
