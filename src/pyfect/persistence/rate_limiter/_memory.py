"""``layer_store_memory``: counters in process memory, each dropped once it
expires (its state then the same as a key never seen), by a sweep every
minute for keys left idle."""

from __future__ import annotations

import math
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any, Final, Never

from pyfect import _js as js
from pyfect._core import Effect
from pyfect.clock import ClockService, clock_with
from pyfect.duration import Duration, millis, to_millis, zero
from pyfect.effect import gen, sync
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.persistence._seconds import millis
from pyfect.persistence.persistence._service import now_millis
from pyfect.persistence.rate_limiter._errors import RateLimiterError
from pyfect.persistence.rate_limiter._store import (
    ADAPTIVE_TTL_GRACE_MILLIS,
    AdaptiveConsumeResult,
    AdaptivePhase,
    RateLimiterStore,
    clamp_adaptive_millis,
)
from pyfect.schedule import spaced
from pyfect.scope import Scope

_SWEEP_INTERVAL: Final = millis(60_000)


@dataclass(slots=True)
class _Counter:
    count: float
    expires_at: float


@dataclass(slots=True)
class _Bucket:
    tokens: float
    last_refill: float
    expires_at: float


@dataclass(slots=True)
class _Adaptive:
    phase: AdaptivePhase
    epoch: int
    cooldown_until: float
    learning_started_at: float = 0
    observed_tokens: float = 0
    learned_limit: float = 0
    learned_window_millis: float = 0
    expires_at: float = 0

    def cool_down(self, until: float) -> None:
        self.phase = "cooldown"
        self.cooldown_until = until
        self.learning_started_at = 0
        self.observed_tokens = 0
        self.learned_limit = 0
        self.learned_window_millis = 0
        self.expires_at = until + ADAPTIVE_TTL_GRACE_MILLIS


class MemoryRateLimiterStore:
    """Counters in dicts, read on the ``Clock``."""

    __slots__ = ("_adaptive", "_buckets", "_counters")

    def __init__(self) -> None:
        self._counters: dict[str, _Counter] = {}
        self._buckets: dict[str, _Bucket] = {}
        self._adaptive: dict[str, _Adaptive] = {}

    def fixed_window(
        self, *, key: str, tokens: float, refill_rate_millis: float, limit: float | None
    ) -> Effect[tuple[float, float], RateLimiterError]:
        def run(clock: ClockService) -> tuple[float, float]:
            now = now_millis(clock)
            counter = self._counters.get(key)
            if counter is None or counter.expires_at <= now:
                counter = _Counter(0, now)
                self._counters[key] = counter
            if limit is not None and counter.count + tokens > limit:
                return counter.count + tokens, counter.expires_at - now
            counter.count += tokens
            counter.expires_at += refill_rate_millis * tokens
            return counter.count, counter.expires_at - now

        return clock_with(lambda clock: sync(lambda: run(clock)))

    def token_bucket(
        self,
        *,
        key: str,
        tokens: float,
        limit: float,
        refill_rate_millis: float,
        allow_overflow: bool,
    ) -> Effect[tuple[float, float], RateLimiterError]:
        def run(clock: ClockService) -> tuple[float, float]:
            now = now_millis(clock)
            bucket = self._buckets.get(key)
            if bucket is None or bucket.expires_at <= now:
                bucket = _Bucket(limit, now, now)
                self._buckets[key] = bucket
            to_add = js.floor(js.divide(now - bucket.last_refill, refill_rate_millis))
            if to_add > 0:
                bucket.tokens = min(limit, bucket.tokens + to_add)
                bucket.last_refill += to_add * refill_rate_millis
            if bucket.tokens >= limit:
                bucket.last_refill = now
            new_count = bucket.tokens - tokens
            if allow_overflow or new_count >= 0:
                bucket.tokens = new_count
            # Once refilled to ``limit`` it is the same as a fresh bucket.
            bucket.expires_at = (
                bucket.last_refill + js.ceil(limit - bucket.tokens) * refill_rate_millis
            )
            return new_count, max(0, now - bucket.last_refill)

        return clock_with(lambda clock: sync(lambda: run(clock)))

    def _state(self, key: str, now: float) -> _Adaptive | None:
        state = self._adaptive.get(key)
        if state is None:
            return None
        if state.expires_at <= now:
            del self._adaptive[key]
            return None
        return state

    def adaptive_consume(
        self, *, key: str, tokens: float, fallback_limit: float, fallback_window: Duration
    ) -> Effect[AdaptiveConsumeResult, RateLimiterError]:
        def run(clock: ClockService) -> AdaptiveConsumeResult:
            now = now_millis(clock)
            state = self._state(key, now)
            if state is None:
                return AdaptiveConsumeResult(zero, 0, "inactive")
            match state.phase:
                case "cooldown":
                    if state.cooldown_until > now:
                        return AdaptiveConsumeResult(
                            millis(state.cooldown_until - now), state.epoch, "cooldown"
                        )
                    state.phase = "learning"
                    state.epoch += 1
                    state.learning_started_at = now
                    state.observed_tokens = tokens
                    state.expires_at = now + to_millis(fallback_window) + ADAPTIVE_TTL_GRACE_MILLIS
                    return AdaptiveConsumeResult(zero, state.epoch, "learning")
                case "learning":
                    state.observed_tokens += tokens
                    return AdaptiveConsumeResult(zero, state.epoch, "learning")
                case "learned":
                    refill_rate_millis = state.learned_window_millis / state.learned_limit
                    if state.cooldown_until <= now:
                        state.observed_tokens = 0
                        state.cooldown_until = now
                    state.observed_tokens += tokens
                    state.cooldown_until += refill_rate_millis * tokens
                    ttl = state.cooldown_until - now
                    elapsed = state.observed_tokens * refill_rate_millis - ttl
                    window = math.floor((state.observed_tokens - 1) / state.learned_limit)
                    remaining = window * state.learned_window_millis - elapsed
                    delay = zero if remaining <= 0 else millis(remaining)
                    return AdaptiveConsumeResult(delay, state.epoch, "learned")
                case "inactive":
                    return AdaptiveConsumeResult(zero, state.epoch, state.phase)

        return clock_with(lambda clock: sync(lambda: run(clock)))

    def adaptive_feedback(
        self, *, key: str, epoch: int, tokens: float, status: int, retry_after: Duration | None
    ) -> Effect[None, RateLimiterError]:
        def run(clock: ClockService) -> None:
            if status != 429 or retry_after is None:
                return
            retry_after_millis = clamp_adaptive_millis(to_millis(retry_after))
            now = now_millis(clock)
            cooldown_until = now + retry_after_millis
            state = self._state(key, now)
            if state is None:
                if epoch == 0:
                    fresh = _Adaptive("cooldown", 0, cooldown_until)
                    fresh.cool_down(cooldown_until)
                    self._adaptive[key] = fresh
                return
            if state.epoch != epoch:
                return
            match state.phase:
                case "cooldown":
                    state.cooldown_until = max(state.cooldown_until, cooldown_until)
                    state.expires_at = state.cooldown_until + ADAPTIVE_TTL_GRACE_MILLIS
                case "learning":
                    accepted = state.observed_tokens - tokens
                    if accepted <= 0:
                        state.cool_down(cooldown_until)
                        return
                    window = clamp_adaptive_millis(
                        (now - state.learning_started_at) + retry_after_millis
                    )
                    state.phase = "learned"
                    state.epoch += 1
                    state.cooldown_until = state.learning_started_at + window
                    state.observed_tokens = accepted
                    state.learned_limit = accepted
                    state.learned_window_millis = window
                    state.expires_at = now + window + ADAPTIVE_TTL_GRACE_MILLIS
                case "learned":
                    state.cool_down(cooldown_until)
                case "inactive":
                    pass

        return clock_with(lambda clock: sync(lambda: run(clock)))

    def sweep(self, now: float) -> None:
        """Drop every entry expired at ``now``."""
        entries: list[dict[str, _Counter] | dict[str, _Bucket] | dict[str, _Adaptive]] = [
            self._counters,
            self._buckets,
            self._adaptive,
        ]
        for entries_by_key in entries:
            for key in [k for k, entry in entries_by_key.items() if entry.expires_at <= now]:
                del entries_by_key[key]

    @property
    def size(self) -> int:
        """How many keys hold state."""
        return len(self._counters) + len(self._buckets) + len(self._adaptive)


def _make() -> Generator[Effect[Any, Never, Scope], Any, MemoryRateLimiterStore]:
    store = MemoryRateLimiterStore()
    sweep = clock_with(lambda clock: sync(lambda: store.sweep(now_millis(clock))))
    yield from sweep.repeat(spaced(_SWEEP_INTERVAL)).fork_scoped()
    return store


make_memory_store: Effect[MemoryRateLimiterStore, Never, Scope] = gen(_make)
"""A store in memory whose expired keys a fiber in the scope sweeps away
every minute; its ``size`` counts the keys holding state."""

layer_store_memory: Layer[RateLimiterStore] = layer_effect(RateLimiterStore, make_memory_store)
"""Counters in memory, fresh each time the layer is built."""
