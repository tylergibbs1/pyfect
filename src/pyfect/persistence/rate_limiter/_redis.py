"""``layer_store_redis``: counters in Redis, updated by Lua scripts."""

from __future__ import annotations

from collections.abc import Callable, Generator, Mapping
from typing import Any, Never, cast

from pyfect._core import Effect
from pyfect.clock import ClockService, clock_with
from pyfect.config import Config, ConfigError
from pyfect.config._config import unwrap
from pyfect.duration import ZERO, Seconds, to_millis
from pyfect.effect import gen, void
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.persistence._seconds import millis
from pyfect.persistence.persistence._service import now_millis
from pyfect.persistence.rate_limiter._errors import RateLimiterError, RateLimitStoreError
from pyfect.persistence.rate_limiter._store import (
    ADAPTIVE_MAX_WINDOW_MILLIS,
    ADAPTIVE_TTL_GRACE_MILLIS,
    AdaptiveConsumeResult,
    AdaptivePhase,
    RateLimiterStore,
    RateLimiterStoreService,
    clamp_adaptive_millis,
)
from pyfect.persistence.redis import Redis, RedisError, RedisReply, RedisService, script


def _items(reply: RedisReply) -> list[RedisReply]:
    if not isinstance(reply, list):
        raise TypeError(f"expected an array reply, got {reply!r}")
    return reply


def _number(reply: RedisReply) -> float:
    return float(cast("str | int", reply))


def _pair(reply: RedisReply) -> tuple[float, float]:
    first, second = _items(reply)
    return _number(first), _number(second)


def _adaptive(reply: RedisReply) -> tuple[float, int, AdaptivePhase]:
    delay, epoch, phase = _items(reply)
    return _number(delay), int(cast("str | int", epoch)), cast("AdaptivePhase", phase)


def _fixed_window_params(
    key: str, tokens: float, refill_millis: float, limit: float | None
) -> list[str | float]:
    return [key, tokens, refill_millis, "" if limit is None else limit]


FIXED_WINDOW = script(
    _fixed_window_params,
    number_of_keys=1,
    decode=_pair,
    lua="""
local key = KEYS[1]
local tokens = tonumber(ARGV[1])
local refillms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local current = tonumber(redis.call("GET", key))
if not current then
  local nextpttl = math.max(1, math.ceil(refillms * tokens))
  redis.call("SET", key, tokens, "PX", nextpttl)
  return { string.format("%.17g", tokens), nextpttl }
end
local currentpttl = tonumber(redis.call("PTTL", key) or "0")
local next = current + tokens
if limit and next > limit then
  return { string.format("%.17g", next), currentpttl }
end
local nextpttl = math.max(1, math.ceil(currentpttl + (refillms * tokens)))
redis.call("SET", key, next, "PX", nextpttl)
-- Use 17 significant digits to round-trip fractional token counts.
return { string.format("%.17g", next), nextpttl }
""",
)


def _token_bucket_params(  # noqa: PLR0917
    key: str,
    last_refill_key: str,
    tokens: float,
    refill_millis: float,
    limit: float,
    now: float,
    overflow: bool,
) -> list[str | float]:
    return [key, last_refill_key, tokens, refill_millis, limit, now, 1 if overflow else 0]


TOKEN_BUCKET = script(
    _token_bucket_params,
    number_of_keys=2,
    decode=_pair,
    lua="""
local key = KEYS[1]
local last_refill_key = KEYS[2]
local tokens = tonumber(ARGV[1])
local refill_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local now = tonumber(ARGV[4])
local overflow = ARGV[5] == "1"
local current = tonumber(redis.call("GET", key))
local last_refill = tonumber(redis.call("GET", last_refill_key))
if not current then current = limit end
if not last_refill then last_refill = now end
local elapsed = now - last_refill
local refill_amount = math.floor(elapsed / refill_ms)
if refill_amount > 0 then
  current = math.min(current + refill_amount, limit)
  last_refill = last_refill + (refill_amount * refill_ms)
end
if current >= limit then
  last_refill = now
end
local next = current - tokens
local stored = current
if next >= 0 or overflow then
  stored = next
end
elapsed = math.max(0, now - last_refill)
local ttl = math.ceil(math.ceil(limit - stored) * refill_ms - elapsed)
if ttl < 1 then ttl = 1 end
redis.call("SET", key, stored, "PX", ttl)
redis.call("SET", last_refill_key, last_refill, "PX", ttl)
-- Use 17 significant digits to round-trip both numbers.
return { string.format("%.17g", next), string.format("%.17g", elapsed) }
""",
)


def _adaptive_consume_params(
    key: str, tokens: float, fallback_window_millis: float, ttl_grace_millis: float
) -> list[str | float]:
    return [key, tokens, fallback_window_millis, ttl_grace_millis]


ADAPTIVE_CONSUME = script(
    _adaptive_consume_params,
    number_of_keys=1,
    decode=_adaptive,
    lua="""
local key = KEYS[1]
local tokens = tonumber(ARGV[1])
local fallback_window_ms = tonumber(ARGV[2])
local ttl_grace_ms = tonumber(ARGV[3])
local time = redis.call("TIME")
local now = (tonumber(time[1]) * 1000) + math.floor(tonumber(time[2]) / 1000)
local phase = redis.call("HGET", key, "phase")
if not phase then
  return { 0, 0, "inactive" }
end
local epoch = tonumber(redis.call("HGET", key, "epoch") or "0")
if phase == "cooldown" then
  local cooldown_until = tonumber(redis.call("HGET", key, "cooldownUntil") or "0")
  if cooldown_until > now then
    return { math.ceil(cooldown_until - now), epoch, "cooldown" }
  end
  epoch = epoch + 1
  redis.call(
    "HSET",
    key,
    "phase",
    "learning",
    "epoch",
    epoch,
    "cooldownUntil",
    0,
    "learningStartedAt",
    now,
    "observedTokens",
    tokens,
    "learnedLimit",
    0,
    "learnedWindowMillis",
    0
  )
  redis.call("PEXPIRE", key, math.max(1, math.ceil(fallback_window_ms + ttl_grace_ms)))
  return { 0, epoch, "learning" }
end
if phase == "learning" then
  local observed_tokens = tonumber(redis.call("HGET", key, "observedTokens") or "0") + tokens
  redis.call("HSET", key, "observedTokens", observed_tokens)
  return { 0, epoch, "learning" }
end
if phase == "learned" then
  local cooldown_until = tonumber(redis.call("HGET", key, "cooldownUntil") or "0")
  local observed_tokens = tonumber(redis.call("HGET", key, "observedTokens") or "0")
  local learned_limit = tonumber(redis.call("HGET", key, "learnedLimit") or "0")
  local learned_window_ms = tonumber(redis.call("HGET", key, "learnedWindowMillis") or "0")
  local refill_rate_ms = learned_window_ms / learned_limit
  if cooldown_until <= now then
    observed_tokens = 0
    cooldown_until = now
  end
  observed_tokens = observed_tokens + tokens
  cooldown_until = cooldown_until + (refill_rate_ms * tokens)
  local ttl = cooldown_until - now
  local ttl_total = observed_tokens * refill_rate_ms
  local elapsed = ttl_total - ttl
  local window_number = math.floor((observed_tokens - 1) / learned_limit)
  local remaining = (window_number * learned_window_ms) - elapsed
  redis.call("HSET", key, "observedTokens", observed_tokens, "cooldownUntil", cooldown_until)
  if remaining <= 0 then
    return { 0, epoch, "learned" }
  end
  return { math.ceil(remaining), epoch, "learned" }
end
return { 0, epoch, phase }
""",
)


def _adaptive_feedback_params(  # noqa: PLR0917
    key: str,
    epoch: int,
    tokens: float,
    retry_after_millis: float,
    ttl_grace_millis: float,
    max_window_millis: float,
) -> list[str | float]:
    return [key, epoch, tokens, retry_after_millis, ttl_grace_millis, max_window_millis]


ADAPTIVE_FEEDBACK = script(
    _adaptive_feedback_params,
    number_of_keys=1,
    decode=_number,
    lua="""
local key = KEYS[1]
local feedback_epoch = tonumber(ARGV[1])
local tokens = tonumber(ARGV[2])
local retry_after_ms = tonumber(ARGV[3])
local ttl_grace_ms = tonumber(ARGV[4])
local max_window_ms = tonumber(ARGV[5])
if retry_after_ms <= 0 then
  retry_after_ms = 1
end
if retry_after_ms > max_window_ms then
  retry_after_ms = max_window_ms
end
local time = redis.call("TIME")
local now = (tonumber(time[1]) * 1000) + math.floor(tonumber(time[2]) / 1000)
local cooldown_until = now + retry_after_ms
local phase = redis.call("HGET", key, "phase")
if not phase then
  if feedback_epoch ~= 0 then
    return 0
  end
  redis.call(
    "HSET",
    key,
    "phase",
    "cooldown",
    "epoch",
    0,
    "cooldownUntil",
    cooldown_until,
    "learningStartedAt",
    0,
    "observedTokens",
    0,
    "learnedLimit",
    0,
    "learnedWindowMillis",
    0
  )
  redis.call("PEXPIRE", key, math.max(1, math.ceil(retry_after_ms + ttl_grace_ms)))
  return 1
end
local epoch = tonumber(redis.call("HGET", key, "epoch") or "0")
if epoch ~= feedback_epoch then
  return 0
end
if phase == "cooldown" then
  local current_cooldown_until = tonumber(redis.call("HGET", key, "cooldownUntil") or "0")
  if current_cooldown_until > cooldown_until then
    cooldown_until = current_cooldown_until
  end
  redis.call("HSET", key, "cooldownUntil", cooldown_until)
  redis.call("PEXPIRE", key, math.max(1, math.ceil((cooldown_until - now) + ttl_grace_ms)))
  return 1
end
if phase == "learning" then
  local observed_tokens = tonumber(redis.call("HGET", key, "observedTokens") or "0")
  local accepted_tokens = observed_tokens - tokens
  if accepted_tokens <= 0 then
    redis.call(
      "HSET",
      key,
      "phase",
      "cooldown",
      "cooldownUntil",
      cooldown_until,
      "learningStartedAt",
      0,
      "observedTokens",
      0,
      "learnedLimit",
      0,
      "learnedWindowMillis",
      0
    )
    redis.call("PEXPIRE", key, math.max(1, math.ceil(retry_after_ms + ttl_grace_ms)))
    return 1
  end
  local learning_started_at = tonumber(redis.call("HGET", key, "learningStartedAt") or now)
  local learned_window_ms = (now - learning_started_at) + retry_after_ms
  if learned_window_ms <= 0 then
    learned_window_ms = 1
  end
  if learned_window_ms > max_window_ms then
    learned_window_ms = max_window_ms
  end
  local next_epoch = epoch + 1
  redis.call(
    "HSET",
    key,
    "phase",
    "learned",
    "epoch",
    next_epoch,
    "cooldownUntil",
    learning_started_at + learned_window_ms,
    "observedTokens",
    accepted_tokens,
    "learnedLimit",
    accepted_tokens,
    "learnedWindowMillis",
    learned_window_ms
  )
  redis.call("PEXPIRE", key, math.max(1, math.ceil(learned_window_ms + ttl_grace_ms)))
  return 1
end
if phase == "learned" then
  redis.call(
    "HSET",
    key,
    "phase",
    "cooldown",
    "cooldownUntil",
    cooldown_until,
    "learningStartedAt",
    0,
    "observedTokens",
    0,
    "learnedLimit",
    0,
    "learnedWindowMillis",
    0
  )
  redis.call("PEXPIRE", key, math.max(1, math.ceil(retry_after_ms + ttl_grace_ms)))
  return 1
end
return 0
""",
)


def _store_error(message: str, cause: BaseException) -> RateLimiterError:
    return RateLimiterError(reason=RateLimitStoreError(message=message, cause=cause))


def _failed(command: str) -> Callable[[RedisError], RateLimiterError]:
    message = f"Failed to execute {command} rate limiting command"
    return lambda error: _store_error(message, error.cause)


class RedisRateLimiterStore:
    """Counters in Redis under ``prefix``; each operation is one script,
    so concurrent limiters share them safely."""

    __slots__ = (
        "_adaptive_consume",
        "_adaptive_feedback",
        "_fixed_window",
        "_prefix",
        "_token_bucket",
    )

    def __init__(self, redis: RedisService, prefix: str) -> None:
        self._prefix = prefix
        self._fixed_window = redis.eval(FIXED_WINDOW)
        self._token_bucket = redis.eval(TOKEN_BUCKET)
        self._adaptive_consume = redis.eval(ADAPTIVE_CONSUME)
        self._adaptive_feedback = redis.eval(ADAPTIVE_FEEDBACK)

    def fixed_window(
        self, *, key: str, tokens: float, refill_rate_millis: float, limit: float | None
    ) -> Effect[tuple[float, float], RateLimiterError]:
        return self._fixed_window(
            f"{self._prefix}{key}", tokens, refill_rate_millis, limit
        ).map_error(_failed("fixedWindow"))

    def token_bucket(
        self,
        *,
        key: str,
        tokens: float,
        limit: float,
        refill_rate_millis: float,
        allow_overflow: bool,
    ) -> Effect[tuple[float, float], RateLimiterError]:
        redis_key = f"{self._prefix}{key}"
        refill_key = f"{redis_key}:refill"

        def run(clock: ClockService) -> Effect[tuple[float, float], RedisError]:
            now = now_millis(clock)
            return self._token_bucket(
                redis_key, refill_key, tokens, refill_rate_millis, limit, now, allow_overflow
            )

        # As Effect: this command's error keeps the whole ``RedisError``.
        return clock_with(run).map_error(
            lambda error: _store_error("Failed to execute tokenBucket rate limiting command", error)
        )

    def adaptive_consume(
        self, *, key: str, tokens: float, fallback_limit: float, fallback_window: Seconds
    ) -> Effect[AdaptiveConsumeResult, RateLimiterError]:
        def result(reply: tuple[float, int, AdaptivePhase]) -> AdaptiveConsumeResult:
            delay, epoch, phase = reply
            return AdaptiveConsumeResult(ZERO if delay <= 0 else millis(delay), epoch, phase)

        return (
            self._adaptive_consume(
                f"{self._prefix}{key}:adaptive",
                tokens,
                to_millis(fallback_window),
                ADAPTIVE_TTL_GRACE_MILLIS,
            )
            .map_error(_failed("adaptiveConsume"))
            .map(result)
        )

    def adaptive_feedback(
        self, *, key: str, epoch: int, tokens: float, status: int, retry_after: Seconds | None
    ) -> Effect[None, RateLimiterError]:
        if status != 429 or retry_after is None:
            return void
        return (
            self._adaptive_feedback(
                f"{self._prefix}{key}:adaptive",
                epoch,
                tokens,
                clamp_adaptive_millis(to_millis(retry_after)),
                ADAPTIVE_TTL_GRACE_MILLIS,
                ADAPTIVE_MAX_WINDOW_MILLIS,
            )
            .as_void()
            .map_error(_failed("adaptiveFeedback"))
        )


def make_store_redis(
    *, prefix: str = "ratelimiter:"
) -> Effect[RateLimiterStoreService, Never, Redis]:
    """A store in the ``Redis`` service, its keys under ``prefix``."""

    def build() -> Generator[Effect[Any, Never, Any], Any, RateLimiterStoreService]:
        redis = yield from Redis()
        return RedisRateLimiterStore(redis, prefix)

    return gen(build)


def layer_store_redis(*, prefix: str = "ratelimiter:") -> Layer[RateLimiterStore, Never, Redis]:
    """Counters in Redis, under ``prefix``."""
    return layer_effect(RateLimiterStore, make_store_redis(prefix=prefix))


def layer_store_redis_config(
    options: Config[Mapping[str, Any]] | Mapping[str, Any],
) -> Layer[RateLimiterStore, ConfigError, Redis]:
    """``layer_store_redis`` with its options read from the
    ``ConfigProvider``: a ``Config`` of them, or a mapping from option names
    to their ``Config`` (Effect's ``Config.Wrap``)."""
    read: Effect[Mapping[str, Any], ConfigError] = unwrap(options)
    return layer_effect(RateLimiterStore, read.flat_map(lambda fields: make_store_redis(**fields)))
