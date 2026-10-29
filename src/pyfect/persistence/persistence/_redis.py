"""``layer_backing_redis``: stores in Redis."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Generator, Mapping, Sequence
from typing import Any, Never

from pyfect._core import Effect
from pyfect.duration import Seconds, to_millis
from pyfect.effect import fail, gen, succeed, suspend, void
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.persistence._error import PersistenceError
from pyfect.persistence.persistence._service import (
    BackingEntry,
    BackingPersistence,
    BackingPersistenceService,
    BackingPersistenceStore,
    to_json,
)
from pyfect.persistence.redis import Redis, RedisError, RedisReply, RedisService, script


def _set_many_params(sets: Mapping[str, str], expires: Mapping[str, int]) -> list[str | float]:
    return [*sets, *expires, len(sets), len(expires), *sets.values(), *expires.values()]


def _set_many_keys(sets: Mapping[str, str], expires: Mapping[str, int]) -> int:
    return len(sets) + len(expires)


SET_MANY = script(
    _set_many_params,
    number_of_keys=_set_many_keys,
    lua="""
local num_sets = tonumber(ARGV[1])
local num_expires = tonumber(ARGV[2])
local index = 3

for i = 1, num_sets do
  local key = KEYS[i]
  local value = ARGV[index]
  redis.call("SET", key, value)
  index = index + 1
end

for i = 1, num_expires do
  local key = KEYS[num_sets + i]
  local expire = tonumber(ARGV[index])
  redis.call("PEXPIRE", key, expire)
  index = index + 1
end
""",
)
"""Sets ``sets`` and gives each key of ``expires`` its time to live in
milliseconds, in one step."""


def _ttl_millis(ttl: Seconds) -> int:
    return math.ceil(to_millis(ttl))


def _store(redis: RedisService, prefix: str) -> BackingPersistenceStore:
    set_many_script = redis.eval(SET_MANY)

    def prefixed(key: str) -> str:
        return f"{prefix}:{key}"

    def failed(message: str) -> Callable[[RedisError], PersistenceError]:
        return lambda error: PersistenceError(message=message, cause=error.cause)

    def parse(reply: RedisReply) -> Effect[object | None, PersistenceError]:
        if reply is None:
            return succeed(None)
        try:
            return succeed(json.loads(str(reply)))
        except ValueError as cause:
            return fail(PersistenceError(message="Failed to parse value from Redis", cause=cause))

    def parse_many(keys: Sequence[str], reply: RedisReply) -> list[object | None]:
        values = reply if isinstance(reply, list) else []
        out: list[object | None] = []
        for index in range(len(keys)):
            value = values[index] if index < len(values) else None
            try:
                out.append(None if value is None else json.loads(str(value)))
            except ValueError:
                out.append(None)
        return out

    def get(key: str) -> Effect[object | None, PersistenceError]:
        return (
            redis.send("GET", prefixed(key))
            .map_error(failed(f"Failed to get key {key} from Redis"))
            .flat_map(parse)
        )

    def get_many(keys: Sequence[str]) -> Effect[list[object | None], PersistenceError]:
        return (
            redis.send("mget", *map(prefixed, keys))
            .map_error(failed("Failed to getMany from Redis"))
            .map(lambda reply: parse_many(keys, reply))
        )

    def set_value(key: str, value: object, ttl: Seconds | None) -> Effect[None, PersistenceError]:
        def run() -> Effect[RedisReply, RedisError]:
            text = to_json(value)
            if ttl is None:
                return redis.send("SET", prefixed(key), text)
            return redis.send("SET", prefixed(key), text, "PX", str(_ttl_millis(ttl)))

        return suspend(run).as_void().map_error(failed(f"Failed to set key {key} in Redis"))

    def set_many(entries: Sequence[BackingEntry]) -> Effect[None, PersistenceError]:
        def run() -> Effect[None, RedisError]:
            sets: dict[str, str] = {}
            expires: dict[str, int] = {}
            for key, value, ttl in entries:
                prefixed_key = prefixed(key)
                sets[prefixed_key] = to_json(value)
                if ttl is not None:
                    expires[prefixed_key] = _ttl_millis(ttl)
            return set_many_script(sets, expires).as_void()

        return suspend(run).map_error(failed("Failed to setMany in Redis"))

    def delete_all(keys: RedisReply) -> Effect[object, RedisError]:
        found = [str(key) for key in keys] if isinstance(keys, list) else []
        return void if not found else redis.send("DEL", *found)

    return BackingPersistenceStore(
        get=get,
        get_many=get_many,
        set=set_value,
        set_many=set_many,
        remove=lambda key: (
            redis.send("DEL", prefixed(key))
            .as_void()
            .map_error(failed(f"Failed to remove key {key} from Redis"))
        ),
        clear=redis.send("KEYS", f"{prefix}:*")
        .flat_map(delete_all)
        .as_void()
        .map_error(failed("Failed to clear keys from Redis")),
    )


def _build() -> Generator[Effect[Any, Never, Redis], Any, BackingPersistenceService]:
    redis = yield from Redis()
    return BackingPersistenceService(
        lambda store_id: suspend(lambda: succeed(_store(redis, store_id)))
    )


layer_backing_redis: Layer[BackingPersistence, Never, Redis] = layer_effect(
    BackingPersistence, gen(_build)
)
"""Stores in Redis, each under its id as a key prefix (``id:key``); values
are JSON, and a time to live is a Redis expiry in whole milliseconds,
rounded up."""
