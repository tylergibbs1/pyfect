"""A Redis client as a service (Effect's ``effect/persistence/Redis``)::

    redis = yield from Redis()
    yield from redis.send("SET", "greeting", "hello")
    greeting = yield from redis.send("GET", "greeting")       # "hello"

    incr = script(lambda key, by: [key, by], lua="return redis.call('INCRBY', KEYS[1], ARGV[1])",
                  number_of_keys=1, decode=int)
    total = yield from redis.eval(incr)("counter", 5)

``Redis`` sends commands on shared connections, runs ``script``\\ s with
``EVALSHA`` (loading each once), delivers a channel's messages through
``subscribe`` and lends a connection of its own for blocking commands
with ``reserve``. ``make`` builds the service over any client;
``pyfect.persistence.redis_py`` (the ``pyfect[redis]`` extra) provides it
on redis-py.
"""

from pyfect.persistence.redis._error import RedisError
from pyfect.persistence.redis._make import make
from pyfect.persistence.redis._script import RedisReply, Script, script
from pyfect.persistence.redis._service import (
    DEFAULT_SUBSCRIBE_CAPACITY,
    OpenConnection,
    PoolOptions,
    Redis,
    RedisConnection,
    RedisMessage,
    RedisService,
    Send,
    Subscribe,
)

__all__ = [
    "DEFAULT_SUBSCRIBE_CAPACITY",
    "OpenConnection",
    "PoolOptions",
    "Redis",
    "RedisConnection",
    "RedisError",
    "RedisMessage",
    "RedisReply",
    "RedisService",
    "Script",
    "Send",
    "Subscribe",
    "make",
    "script",
]
