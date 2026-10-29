"""``layer_store_redis``: circuit states in Redis, changed by Lua scripts."""

from __future__ import annotations

from collections.abc import Callable, Generator, Mapping
from typing import Any, Never, cast

from pyfect import _js as js
from pyfect._core import Effect
from pyfect.clock import sleep
from pyfect.config import Config, ConfigError
from pyfect.config._config import unwrap
from pyfect.duration import Duration, Seconds, to_millis
from pyfect.effect import fail, gen
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.persistence._seconds import millis
from pyfect.persistence.circuit_breaker._breaker import recovering
from pyfect.persistence.circuit_breaker._errors import (
    CircuitBreakerError,
    CircuitBreakerStoreError,
    CircuitHalfOpen,
    CircuitOpen,
)
from pyfect.persistence.circuit_breaker._store import (
    CircuitBreakerStore,
    CircuitBreakerStoreService,
)
from pyfect.persistence.circuit_breaker._types import (
    Admission,
    Closed,
    CloseTransition,
    Consecutive,
    HalfOpen,
    HalfOpenTransition,
    Open,
    OpenTransition,
    OutcomeKind,
    State,
    Transition,
    TripPolicy,
)
from pyfect.persistence.redis import Redis, RedisError, RedisReply, RedisService, script
from pyfect.scope import Scope

# Numeric arguments are capped at 2^50 (about 35,000 years in milliseconds),
# so every TTL and timestamp derived from them stays an exact integer, and
# ``int`` writes numbers without an exponent (which PEXPIRE rejects).
# Generations are the larger of the previous one plus one and the Redis
# time in microseconds, so a key that expired and was recreated never
# reissues a generation an old permit holds; they stay integer strings.
_PRELUDE = """
local maxValue = 1125899906842624
local function bounded(value, min)
  local n = tonumber(value)
  if n == nil or n ~= n or n < min or n > maxValue then return nil end
  return n
end
local function positive(value) return bounded(value, 1) end
local function nonNegative(value) return bounded(value, 0) end
local function int(n) return string.format("%.0f", n) end
local time = redis.call("TIME")
local nowMicros = tonumber(time[1]) * 1000000 + tonumber(time[2])
local now = math.floor(nowMicros / 1000)
local function nextGeneration(current)
  return int(math.max((tonumber(current) or 0) + 1, nowMicros))
end
"""


def _items(reply: RedisReply) -> list[RedisReply]:
    if not isinstance(reply, list):
        raise TypeError(f"expected an array reply, got {reply!r}")
    return reply


def _int(reply: RedisReply) -> int:
    return int(cast("str | int", reply))


def _admit_params(key: str, lease_millis: float, idle_millis: float) -> list[str | float]:
    return [key, lease_millis, idle_millis]


# { "ok", generation, probe, consecutiveOpenings, movedToHalfOpen },
# { "open", remainingMillis } or { "halfopen" }.
ADMIT = script(
    _admit_params,
    number_of_keys=1,
    decode=_items,
    lua=_PRELUDE
    + """local key = KEYS[1]
local lease = positive(ARGV[1])
local idle = positive(ARGV[2])
if not lease or not idle then
  return redis.error_reply("CircuitBreaker admit: invalid arguments")
end
local fields = redis.call(
  "HMGET", key, "state", "generation", "openUntil", "openings", "leaseUntil", "resetAt"
)
local state = fields[1]
local generation = fields[2]
local openings = tonumber(fields[4]) or 0
if not state then
  generation = nextGeneration(0)
  redis.call("HSET", key, "state", "Closed", "generation", generation)
  redis.call("PEXPIRE", key, int(idle))
  return { "ok", generation, 0, 0, 0 }
end
if state == "Closed" then
  -- A call admitted before this reset can still trip the circuit. It opens
  -- with the openFor it computed from its older count, and the stored count
  -- restarts at 1.
  if openings > 0 and now >= (tonumber(fields[6]) or 0) then
    openings = 0
    redis.call("HSET", key, "openings", 0)
  end
  redis.call("PEXPIRE", key, int(idle))
  return { "ok", generation, 0, openings, 0 }
end
local moved = 0
if state == "Open" then
  local openUntil = tonumber(fields[3]) or 0
  if now < openUntil then
    return { "open", openUntil - now }
  end
  moved = 1
elseif (tonumber(fields[5]) or 0) > now then
  return { "halfopen" }
end
-- Every probe admission, including a takeover of a lapsed lease, starts a
-- new generation.
generation = nextGeneration(generation)
redis.call(
  "HSET", key, "state", "HalfOpen", "generation", generation, "leaseUntil", int(now + lease)
)
redis.call("PEXPIRE", key, int(lease + idle))
return { "ok", generation, 1, openings, moved }
""",
)


def _record_params(  # noqa: PLR0917
    key: str,
    generation: str,
    outcome: OutcomeKind,
    trip_policy: TripPolicy,
    open_for_millis: float,
    idle_millis: float,
) -> list[str | float]:
    policy: list[str | float] = (
        ["Consecutive", trip_policy.failure_count, 0, 0]
        if isinstance(trip_policy, Consecutive)
        else ["Rate", trip_policy.threshold, trip_policy.minimum_calls, trip_policy.size]
    )
    return [key, generation, outcome, *policy, open_for_millis, idle_millis]


# { transition, consecutiveOpenings }, the transition "none", "closed-open",
# "halfopen-open" or "halfopen-closed".
RECORD = script(
    _record_params,
    number_of_keys=1,
    decode=_items,
    lua=_PRELUDE
    + """local key = KEYS[1]
local expected = ARGV[1]
local outcome = ARGV[2]
local policy = ARGV[3]
local openFor = nonNegative(ARGV[7])
local idle = positive(ARGV[8])
local valid = openFor ~= nil and idle ~= nil and
  (outcome == "Success" or outcome == "Failure" or outcome == "Ignored")
local failuresNeeded, threshold, minimumCalls, size
if policy == "Consecutive" then
  failuresNeeded = positive(ARGV[4])
  valid = valid and failuresNeeded ~= nil
elseif policy == "Rate" then
  threshold = nonNegative(ARGV[4])
  minimumCalls = positive(ARGV[5])
  size = positive(ARGV[6])
  valid = valid and threshold ~= nil and threshold <= 1 and minimumCalls ~= nil and size ~= nil and
    minimumCalls <= size
else
  valid = false
end
if not valid then
  return redis.error_reply("CircuitBreaker record: invalid arguments")
end
local fields = redis.call(
  "HMGET", key, "state", "generation", "streak", "ring", "failures", "openings", "lastOpenFor"
)
local state = fields[1]
if not state or fields[2] ~= expected then
  return { "none", 0 }
end
local openings = tonumber(fields[6]) or 0
local function open()
  openings = openings + 1
  redis.call(
    "HSET", key,
    "state", "Open",
    "generation", nextGeneration(fields[2]),
    "openUntil", int(now + openFor),
    "openings", openings,
    "lastOpenFor", int(openFor),
    "streak", 0,
    "ring", "",
    "failures", 0,
    "leaseUntil", 0
  )
  redis.call("PEXPIRE", key, int(openFor + idle))
end
if state == "HalfOpen" then
  if outcome == "Ignored" then
    -- A new generation fences a renewal already on its way, so the freed slot
    -- stays free.
    redis.call("HSET", key, "generation", nextGeneration(fields[2]), "leaseUntil", 0)
    redis.call("PEXPIRE", key, int(idle))
    return { "none", openings }
  end
  if outcome == "Failure" then
    open()
    return { "halfopen-open", openings }
  end
  redis.call(
    "HSET", key,
    "state", "Closed",
    "generation", nextGeneration(fields[2]),
    "resetAt", int(now + (tonumber(fields[7]) or 0)),
    "streak", 0,
    "ring", "",
    "failures", 0,
    "leaseUntil", 0
  )
  redis.call("PEXPIRE", key, int(idle))
  return { "halfopen-closed", openings }
end
if state ~= "Closed" then
  return { "none", openings }
end
if outcome == "Ignored" then
  redis.call("PEXPIRE", key, int(idle))
  return { "none", openings }
end
local failed = outcome == "Failure"
local streak = failed and (tonumber(fields[3]) or 0) + 1 or 0
local trips
local ring = fields[4] or ""
local failures = tonumber(fields[5]) or 0
if policy == "Consecutive" then
  trips = streak >= failuresNeeded
else
  ring = ring .. (failed and "1" or "0")
  if failed then failures = failures + 1 end
  if #ring > size then
    local _, dropped = string.gsub(string.sub(ring, 1, #ring - size), "1", "")
    failures = failures - dropped
    ring = string.sub(ring, #ring - size + 1)
  end
  trips = #ring >= minimumCalls and failures > 0 and failures / #ring >= threshold
end
if trips then
  open()
  return { "closed-open", openings }
end
redis.call("HSET", key, "streak", streak, "ring", ring, "failures", failures)
redis.call("PEXPIRE", key, int(idle))
return { "none", openings }
""",
)


def _state_params(key: str) -> list[str | float]:
    return [key]


# Read-only: { state, remainingOpenMillis, consecutiveOpenings, probing }.
STATE = script(
    _state_params,
    number_of_keys=1,
    decode=_items,
    lua=_PRELUDE
    + """local fields = redis.call("HMGET", KEYS[1], "state", "openUntil", "openings", "leaseUntil")
local state = fields[1]
if not state then
  return { "Closed", 0, 0, 0 }
end
local remaining = math.max(0, (tonumber(fields[2]) or 0) - now)
local probing = (tonumber(fields[4]) or 0) > now and 1 or 0
return { state, remaining, tonumber(fields[3]) or 0, probing }
""",
)


def _renew_params(
    key: str, generation: str, lease_millis: float, idle_millis: float
) -> list[str | float]:
    return [key, generation, lease_millis, idle_millis]


# Extends the probe lease while the generation still holds it: 1 when
# renewed, 0 once the lease is gone.
RENEW = script(
    _renew_params,
    number_of_keys=1,
    decode=_int,
    lua=_PRELUDE
    + """local key = KEYS[1]
local lease = positive(ARGV[2])
local idle = positive(ARGV[3])
if not lease or not idle then
  return redis.error_reply("CircuitBreaker renew: invalid arguments")
end
local fields = redis.call("HMGET", key, "state", "generation")
if fields[1] ~= "HalfOpen" or fields[2] ~= ARGV[1] then
  return 0
end
redis.call("HSET", key, "leaseUntil", int(now + lease))
redis.call("PEXPIRE", key, int(lease + idle))
return 1
""",
)


def _redis_millis(duration: Duration) -> float:
    # An infinite duration goes as ``Infinity``, which the scripts reject.
    return max(1, js.ceil(to_millis(duration)))


def _remaining(reply: RedisReply) -> Seconds:
    return millis(max(0, _int(reply)))


class RedisCircuitBreakerStore:
    """States in Redis hashes under ``prefix``; each change is one script,
    so every process sharing the Redis sees one circuit per key. A probe
    holds a lease renewed every third of it while it runs."""

    __slots__ = ("_admit", "_idle", "_lease", "_prefix", "_record", "_renew", "_state")

    def __init__(
        self, redis: RedisService, *, prefix: str, lease_millis: float, idle_millis: float
    ) -> None:
        self._prefix = prefix
        self._lease = lease_millis
        self._idle = idle_millis
        self._admit = redis.eval(ADMIT)
        self._record = redis.eval(RECORD)
        self._state = redis.eval(STATE)
        self._renew = redis.eval(RENEW)

    def _renewing(self, redis_key: str, generation: str) -> Effect[None]:
        # Stops once the lease is gone: a renewal can never win it back.
        renew = self._renew(redis_key, generation, self._lease, self._idle).catch_cause(
            lambda cause: recovering("CircuitBreaker failed to renew a probe lease, retrying")(
                cause
            ).as_(1)
        )
        interval = millis(self._lease / 3)

        def body() -> Generator[Effect[Any], Any]:
            while True:
                yield from sleep(interval)
                if (yield from renew) != 1:
                    return

        return gen(body)

    def admit(self, key: str) -> Effect[Admission, CircuitBreakerError, Scope]:
        redis_key = f"{self._prefix}{key}"

        def body() -> Generator[Effect[Any, CircuitBreakerError, Scope], Any, Admission]:
            reply = yield from self._admit(redis_key, self._lease, self._idle).map_error(
                _failed("Failed to admit a call through the circuit")
            )
            match reply[0]:
                case "open":
                    retry_after = _remaining(reply[1])
                    return (
                        yield from fail(
                            CircuitBreakerError(
                                reason=CircuitOpen(key=key, retry_after=retry_after)
                            )
                        )
                    )
                case "halfopen":
                    return (yield from fail(CircuitBreakerError(reason=CircuitHalfOpen(key=key))))
                case _:
                    _, generation, probe, openings, moved = reply
                    if probe == 1:
                        yield from (
                            self._renewing(redis_key, str(generation)).interruptible().fork_scoped()
                        )
                    return Admission(
                        _int(generation),
                        probe == 1,
                        _int(openings),
                        HalfOpenTransition(key) if moved == 1 else None,
                    )

        return gen(body)

    def record(
        self,
        *,
        key: str,
        generation: int,
        outcome: OutcomeKind,
        trip_policy: TripPolicy,
        open_for: Seconds,
    ) -> Effect[Transition | None, CircuitBreakerError]:
        def transition(reply: list[RedisReply]) -> Transition | None:
            moved, openings = reply
            match moved:
                case "closed-open":
                    return OpenTransition(key, "Closed", open_for, _int(openings))
                case "halfopen-open":
                    return OpenTransition(key, "HalfOpen", open_for, _int(openings))
                case "halfopen-closed":
                    return CloseTransition(key)
                case _:
                    return None

        return (
            self._record(
                f"{self._prefix}{key}",
                str(generation),
                outcome,
                trip_policy,
                max(0, js.ceil(to_millis(open_for))),
                self._idle,
            )
            .map_error(_failed("Failed to record an outcome"))
            .map(transition)
        )

    def state(self, key: str) -> Effect[State, CircuitBreakerError]:
        def decode(reply: list[RedisReply]) -> State:
            state, remaining, openings, probing = reply
            match state:
                case "Open":
                    return Open(key, _remaining(remaining), _int(openings))
                case "HalfOpen":
                    return HalfOpen(key, probing == 1, _int(openings))
                case _:
                    return Closed(key)

        return (
            self._state(f"{self._prefix}{key}")
            .map_error(_failed("Failed to read the circuit state"))
            .map(decode)
        )


def _failed(message: str) -> Callable[[RedisError], CircuitBreakerError]:
    return lambda error: CircuitBreakerError(
        reason=CircuitBreakerStoreError(message=message, cause=error.cause)
    )


def make_store_redis(
    *,
    prefix: str = "circuitbreaker:",
    probe_lease: Duration = 10,
    idle_time_to_live: Duration = 3600,
) -> Effect[CircuitBreakerStoreService, Never, Redis]:
    """A store in the ``Redis`` service, its keys under ``prefix``. A
    probe's lease lasts ``probe_lease`` (renewed while it runs, so a probe
    whose process died frees its slot), and a key idle for
    ``idle_time_to_live`` expires (an open one only after its open time)."""
    lease_millis = _redis_millis(probe_lease)
    idle_millis = _redis_millis(idle_time_to_live)

    def build() -> Generator[Effect[Any, Never, Any], Any, CircuitBreakerStoreService]:
        redis = yield from Redis()
        store = RedisCircuitBreakerStore(
            redis, prefix=prefix, lease_millis=lease_millis, idle_millis=idle_millis
        )
        return CircuitBreakerStoreService(admit=store.admit, record=store.record, state=store.state)

    return gen(build)


def layer_store_redis(
    *,
    prefix: str = "circuitbreaker:",
    probe_lease: Duration = 10,
    idle_time_to_live: Duration = 3600,
) -> Layer[CircuitBreakerStore, Never, Redis]:
    """Circuit states in Redis (see ``make_store_redis``)."""
    return layer_effect(
        CircuitBreakerStore,
        make_store_redis(
            prefix=prefix, probe_lease=probe_lease, idle_time_to_live=idle_time_to_live
        ),
    )


def layer_store_redis_config(
    options: Config[Mapping[str, Any]] | Mapping[str, Any],
) -> Layer[CircuitBreakerStore, ConfigError, Redis]:
    """``layer_store_redis`` with its options read from the
    ``ConfigProvider``: a ``Config`` of them, or a mapping from option names
    to their ``Config`` (Effect's ``Config.Wrap``)."""
    read: Effect[Mapping[str, Any], ConfigError] = unwrap(options)
    return layer_effect(
        CircuitBreakerStore, read.flat_map(lambda fields: make_store_redis(**fields))
    )
