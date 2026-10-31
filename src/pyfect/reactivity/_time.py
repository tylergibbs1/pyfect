"""Wall-clock milliseconds, as Effect's ``Date.now()``: the timestamps of
``AsyncResult.success`` and the registry's idle timeouts."""

from __future__ import annotations

import time


def now_millis() -> int:
    """Whole milliseconds since the epoch."""
    return time.time_ns() // 1_000_000
