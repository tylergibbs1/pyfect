"""The memory and Redis rate-limiter stores give the same results, down to
the Python type (dogfood apps #8: Redis gave ``remaining=1.0`` where memory
gave ``1``; Effect's stores both give the JavaScript number 1). "Swap the
memory stores for these and nothing else changes" (rate-limiting.mdx).
"""

from __future__ import annotations

from typing import Any

import pytest
from oracle import _redis

import pyfect as fx
from pyfect import testing
from pyfect.persistence import rate_limiter as rl
from pyfect.persistence import redis_py

# The Redis store reads Redis TIME, so these runs wait on the wall clock.
pytestmark = pytest.mark.filterwarnings("ignore::pyfect.testing.ClockNotAdvancedWarning")

_CASES: list[dict[str, Any]] = [
    {"algorithm": "fixed-window", "limit": 2, "tokens": 1},
    {"algorithm": "fixed-window", "limit": 1, "tokens": 0.75},
    {"algorithm": "fixed-window", "limit": 2, "tokens": 1, "on_exceeded": "delay"},
    {"algorithm": "token-bucket", "limit": 5, "tokens": 1},
    {"algorithm": "token-bucket", "limit": 5, "tokens": 0.5},
    {"algorithm": "token-bucket", "limit": 2, "tokens": 1, "on_exceeded": "delay"},
]


def _results(store: fx.Layer[rl.RateLimiterStore, Any, Any]) -> list[str]:
    def body():
        limiter = yield from rl.make
        out: list[str] = []
        for index, case in enumerate(_CASES):
            for _ in range(3):
                result = yield from limiter.consume(
                    key=f"agree-{index}", window="60 seconds", **case
                ).result()
                out.append(repr(result.map(lambda r: (r.remaining, r.limit)).map_error(type)))
        return out

    return testing.run_test(fx.scoped(fx.gen(body)).pipe(fx.provide(store)))


def test_memory_and_redis_stores_give_the_same_results():
    _redis.flush()
    redis = rl.layer_store_redis(prefix="agree:").pipe(
        fx.provide(redis_py.layer(_redis.server().url))
    )
    assert _results(redis) == _results(rl.layer_store_memory)
