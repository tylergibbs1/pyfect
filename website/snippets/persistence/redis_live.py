import pyfect as fx
from pyfect import layer
from pyfect.persistence import (
    CircuitBreaker,
    Persistence,
    RateLimiter,
    RedisError,
    circuit_breaker,
    persisted_queue,
    persistence,
    rate_limiter,
    redis_py,
)
from pyfect.persistence.persisted_queue import PersistedQueueFactory

# One redis-py client, connected when the layer is built and closed with its scope.
RedisLive = redis_py.layer("redis://localhost:6379")

# The same services as in memory, now shared by every process using this Redis.
Live: fx.Layer[RateLimiter | CircuitBreaker | Persistence | PersistedQueueFactory, RedisError] = (
    layer.merge(
        rate_limiter.layer.pipe(layer.provide(rate_limiter.layer_store_redis())),
        circuit_breaker.layer(trip_policy=circuit_breaker.consecutive(5), open_duration=30).pipe(
            layer.provide(circuit_breaker.layer_store_redis())
        ),
        persistence.layer_redis,
        persisted_queue.layer.pipe(layer.provide(persisted_queue.layer_store_redis())),
    ).pipe(layer.provide(RedisLive))
)
