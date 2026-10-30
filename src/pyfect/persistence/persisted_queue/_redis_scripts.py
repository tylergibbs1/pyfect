"""The Lua scripts of the Redis queue store, as Effect's."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from pyfect.persistence.redis import RedisReply, script

TRIM_FAILED_BATCH_SIZE: Final = 1000

# Every record starts with {"id":"...". Decode only the id, since Redis
# cjson rejects lone UTF-16 surrogates the element may hold.
_RECORD_ID = """
local function record_id(payload)
  assert(string.sub(payload, 1, 7) == '{"id":"', "Invalid queue record id")
  local i = 8
  while i <= #payload do
    local byte = string.byte(payload, i)
    if byte == 92 then
      -- Skip escaped characters, including escaped quotes and backslashes.
      i = i + 2
    elseif byte == 34 then
      return cjson.decode(string.sub(payload, 7, i))
    else
      i = i + 1
    end
  end
  error("Unterminated queue record id")
end
"""


def _taken(reply: RedisReply) -> list[RedisReply] | None:
    if reply is None:
        return None
    if not isinstance(reply, list):
        raise TypeError(f"expected an array reply, got {reply!r}")
    return reply


def _count(reply: RedisReply) -> int:
    if not isinstance(reply, int):
        raise TypeError(f"expected an integer reply, got {reply!r}")
    return reply


def _offer_params(key_queue: str, key_ids: str, id: str, payload: str) -> list[str | float]:
    return [key_queue, key_ids, id, payload]


OFFER = script(
    _offer_params,
    number_of_keys=2,
    lua="""
local key_queue = KEYS[1]
local key_ids = KEYS[2]
local id = ARGV[1]
local payload = ARGV[2]

-- park the dedupe entry outside the timeToLive trim range until the element
-- completes, so unprocessed elements never lose dedupe protection
local result = redis.call("ZADD", key_ids, "NX", "+inf", id)
if result == 1 then
  redis.call("RPUSH", key_queue, payload)
end
""",
)


def _offer_delayed_params(
    key_delayed: str, key_ids: str, id: str, payload: str, visible_at: float
) -> list[str | float]:
    return [key_delayed, key_ids, id, payload, visible_at]


OFFER_DELAYED = script(
    _offer_delayed_params,
    number_of_keys=2,
    lua="""
local key_delayed = KEYS[1]
local key_ids = KEYS[2]
local id = ARGV[1]
local payload = ARGV[2]
local visible_at = ARGV[3]

local result = redis.call("ZADD", key_ids, "NX", "+inf", id)
if result == 1 then
  redis.call("ZADD", key_delayed, visible_at, payload)
end
""",
)


def _reset_queue_params(  # noqa: PLR0917
    key_queue: str,
    key_pending: str,
    key_attempts: str,
    key_failed: str,
    key_ids: str,
    lock_prefix: str,
    max_attempts: int,
    now: float,
) -> list[str | float]:
    return [
        key_queue, key_pending, key_attempts, key_failed, key_ids, lock_prefix, max_attempts, now
    ]  # fmt: skip


RESET_QUEUE = script(
    _reset_queue_params,
    number_of_keys=5,
    lua="""
local key_queue = KEYS[1]
local key_pending = KEYS[2]
local key_attempts = KEYS[3]
local key_failed = KEYS[4]
local key_ids = KEYS[5]
local lock_prefix = ARGV[1]
local max_attempts = tonumber(ARGV[2])
local now = ARGV[3]

local entries = redis.call("HGETALL", key_pending)
for i = 1, #entries, 2 do
  local id = entries[i]
  local payload = entries[i + 1]
  local lock_key = lock_prefix .. id .. ":lock"
  local exists = redis.call("EXISTS", lock_key)
  if exists == 0 then
    local attempts = tonumber(redis.call("HGET", key_attempts, id) or "0")
    if attempts >= max_attempts then
      -- compose the failed record by hand so the element payload does not go
      -- through a lossy cjson round-trip
      local record = string.sub(payload, 1, -2) .. ',"attempts":' .. attempts ..
        ',"lastFailure":"Lock expired after final attempt","failedAt":' .. now .. '}'
      redis.call("RPUSH", key_failed, record)
      redis.call("HDEL", key_attempts, id)
      -- failed ids keep their dedupe entry until failedTimeToLive removes the
      -- dead-letter record, so park them outside the timeToLive trim range
      redis.call("ZADD", key_ids, "XX", "+inf", id)
    else
      redis.call("RPUSH", key_queue, payload)
    end
    redis.call("HDEL", key_pending, id)
  end
end
""",
)


def _requeue_params(  # noqa: PLR0917
    key_queue: str, key_pending: str, key_lock: str, key_attempts: str, id: str, payload: str
) -> list[str | float]:
    return [key_queue, key_pending, key_lock, key_attempts, id, payload]


REQUEUE = script(
    _requeue_params,
    number_of_keys=4,
    lua="""
local key_queue = KEYS[1]
local key_pending = KEYS[2]
local key_lock = KEYS[3]
local key_attempts = KEYS[4]
local id = ARGV[1]
local payload = ARGV[2]

redis.call("DEL", key_lock)
redis.call("HDEL", key_pending, id)
local attempts = redis.call("HINCRBY", key_attempts, id, -1)
if attempts <= 0 then
  redis.call("HDEL", key_attempts, id)
end
redis.call("RPUSH", key_queue, payload)
""",
)


def _complete_params(  # noqa: PLR0917
    key_pending: str, key_lock: str, key_attempts: str, key_ids: str, id: str, now: float
) -> list[str | float]:
    return [key_pending, key_lock, key_attempts, key_ids, id, now]


COMPLETE = script(
    _complete_params,
    number_of_keys=4,
    lua="""
local key_pending = KEYS[1]
local key_lock = KEYS[2]
local key_attempts = KEYS[3]
local key_ids = KEYS[4]
local id = ARGV[1]
local now = ARGV[2]

redis.call("DEL", key_lock)
redis.call("HDEL", key_pending, id)
redis.call("HDEL", key_attempts, id)
redis.call("ZADD", key_ids, "XX", now, id)
""",
)


def _retry_params(  # noqa: PLR0917
    key_pending: str, key_lock: str, key_delayed: str, id: str, payload: str, visible_at: float
) -> list[str | float]:
    return [key_pending, key_lock, key_delayed, id, payload, visible_at]


RETRY = script(
    _retry_params,
    number_of_keys=3,
    lua="""
local key_pending = KEYS[1]
local key_lock = KEYS[2]
local key_delayed = KEYS[3]
local id = ARGV[1]
local payload = ARGV[2]
local visible_at = ARGV[3]

redis.call("DEL", key_lock)
redis.call("HDEL", key_pending, id)
redis.call("ZADD", key_delayed, visible_at, payload)
""",
)


def _failed_params(  # noqa: PLR0917
    key_pending: str,
    key_lock: str,
    key_failed: str,
    key_attempts: str,
    key_ids: str,
    id: str,
    payload: str,
) -> list[str | float]:
    return [key_pending, key_lock, key_failed, key_attempts, key_ids, id, payload]


FAILED = script(
    _failed_params,
    number_of_keys=5,
    lua="""
local key_pending = KEYS[1]
local key_lock = KEYS[2]
local key_failed = KEYS[3]
local key_attempts = KEYS[4]
local key_ids = KEYS[5]
local id = ARGV[1]
local payload = ARGV[2]

redis.call("DEL", key_lock)
redis.call("HDEL", key_pending, id)
redis.call("HDEL", key_attempts, id)
redis.call("RPUSH", key_failed, payload)
-- failed ids keep their dedupe entry until failedTimeToLive removes the
-- dead-letter record, so park them outside the timeToLive trim range
redis.call("ZADD", key_ids, "XX", "+inf", id)
""",
)


def _take_params(  # noqa: PLR0917
    key_queue: str,
    key_pending: str,
    key_delayed: str,
    key_attempts: str,
    lock_prefix: str,
    worker_id: str,
    batch_size: int,
    pttl: float,
    now: float,
) -> list[str | float]:
    return [
        key_queue,
        key_pending,
        key_delayed,
        key_attempts,
        lock_prefix,
        worker_id,
        batch_size,
        pttl,
        now,
    ]


TAKE = script(
    _take_params,
    number_of_keys=4,
    decode=_taken,
    lua="""
local key_queue = KEYS[1]
local key_pending = KEYS[2]
local key_delayed = KEYS[3]
local key_attempts = KEYS[4]
local lock_prefix = ARGV[1]
local worker_id = ARGV[2]
local batch_size = tonumber(ARGV[3])
local pttl = ARGV[4]
local now = ARGV[5]

"""
    + _RECORD_ID
    + """

local due = redis.call("ZRANGEBYSCORE", key_delayed, "-inf", now, "LIMIT", 0, 100)
if #due > 0 then
  for i, payload in ipairs(due) do
    redis.call("RPUSH", key_queue, payload)
  end
  redis.call("ZREM", key_delayed, unpack(due))
end

local payloads = redis.call("LRANGE", key_queue, 0, batch_size - 1)
if #payloads == 0 then
  return nil
end

-- read every id before removing the batch, as script errors do not roll back
local ids = {}
for i, payload in ipairs(payloads) do
  ids[i] = record_id(payload)
end
redis.call("LTRIM", key_queue, #payloads, -1)

local result = {}
for i, id in ipairs(ids) do
  local payload = payloads[i]
  local key_lock = lock_prefix .. id .. ":lock"
  redis.call("SET", key_lock, worker_id, "PX", pttl)
  redis.call("HSET", key_pending, id, payload)
  local attempts = redis.call("HINCRBY", key_attempts, id, 1)
  result[i * 2 - 1] = payload
  result[i * 2] = attempts
end

return result
""",
)


def _trim_failed_params(key_failed: str, key_ids: str, cutoff: float) -> list[str | float]:
    return [key_failed, key_ids, cutoff]


TRIM_FAILED = script(
    _trim_failed_params,
    number_of_keys=2,
    decode=_count,
    lua="""
local key_failed = KEYS[1]
local key_ids = KEYS[2]
local cutoff = tonumber(ARGV[1])
local removed = 0

"""
    + _RECORD_ID
    + """

while removed < """
    + str(TRIM_FAILED_BATCH_SIZE)
    + """ do
  local head = redis.call("LINDEX", key_failed, 0)
  if not head then break end
  local ok, id = pcall(record_id, head)
  if ok then
    -- failedAt is always the last field of a failed record
    local failed_at = tonumber(string.match(head, ',"failedAt":([^,}]+)%}$'))
    if failed_at ~= nil and failed_at >= cutoff then break end
    redis.call("ZREM", key_ids, id)
  end
  -- a corrupt head would otherwise block trimming of the whole list
  redis.call("LPOP", key_failed)
  removed = removed + 1
end

return removed
""",
)


def _expire_all_params(keys: Sequence[str], ttl: float) -> list[str | float]:
    return [*keys, ttl]


EXPIRE_ALL = script(
    _expire_all_params,
    number_of_keys=lambda keys, ttl: len(keys),
    lua="""
local ttl = ARGV[1]
for i, key in ipairs(KEYS) do
  redis.call("PEXPIRE", key, ttl)
end
""",
)
