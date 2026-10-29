"""Rate limits per key (Effect's ``effect/persistence/RateLimiter``)::

    limiter = yield from RateLimiter()
    result = yield from limiter.consume(key="user:1", limit=100, window=60)
    # fails with RateLimiterError(RateLimitExceeded) once over the limit

``consume`` charges tokens to a key by a ``"fixed-window"`` or
``"token-bucket"`` algorithm and, over the limit, fails or gives the delay
to wait (``on_exceeded="delay"``); ``sleep`` waits that delay, and
``make_with_rate_limiter`` gives a function that limits any effect.
``adaptive_consume`` / ``adaptive_feedback`` learn a server's limit from
its ``429`` responses.

The counters live in a ``RateLimiterStore``: ``layer_store_memory``, or
``layer_store_redis`` (shared by every process using that Redis).
"""

from pyfect.persistence.rate_limiter._errors import (
    RATE_LIMITER_ERROR_REASON,
    RateLimiterError,
    RateLimiterErrorReason,
    RateLimitExceeded,
    RateLimitStoreError,
)
from pyfect.persistence.rate_limiter._limiter import (
    Algorithm,
    ConsumeResult,
    Limit,
    OnExceeded,
    RateLimiter,
    RateLimiterService,
    Sleep,
    WithRateLimiter,
    layer,
    make,
    make_with_rate_limiter,
    sleep,
)
from pyfect.persistence.rate_limiter._memory import layer_store_memory, make_store_memory
from pyfect.persistence.rate_limiter._redis import (
    layer_store_redis,
    layer_store_redis_config,
    make_store_redis,
)
from pyfect.persistence.rate_limiter._store import (
    AdaptiveConsumeResult,
    AdaptivePhase,
    RateLimiterStore,
    RateLimiterStoreService,
)

__all__ = [
    "RATE_LIMITER_ERROR_REASON",
    "AdaptiveConsumeResult",
    "AdaptivePhase",
    "Algorithm",
    "ConsumeResult",
    "Limit",
    "OnExceeded",
    "RateLimitExceeded",
    "RateLimitStoreError",
    "RateLimiter",
    "RateLimiterError",
    "RateLimiterErrorReason",
    "RateLimiterService",
    "RateLimiterStore",
    "RateLimiterStoreService",
    "Sleep",
    "WithRateLimiter",
    "layer",
    "layer_store_memory",
    "layer_store_redis",
    "layer_store_redis_config",
    "make",
    "make_store_memory",
    "make_store_redis",
    "make_with_rate_limiter",
    "sleep",
]
