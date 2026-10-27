"""``Pool[A, E]``: share scoped resources across fibers.

A pool acquires items with a scoped effect, lends them to fibers, and
releases them all when the scope it was made in closes::

    pool = yield from fx.Pool.make(connect, size=10)
    rows = yield from pool.use(lambda conn: conn.query("..."))

- ``Pool.make(acquire, size=)``: a fixed number of items, acquired at once.
- ``Pool.make_with_ttl(acquire, min=, max=, time_to_live=)``: grows with
  demand up to ``max`` and shrinks back to ``min`` once items have been idle
  (``"usage"``, the default) or alive (``"creation"``) for the time to live.
- ``Pool.make_with_strategy``: a custom ``Strategy`` resizes the pool.

``concurrency`` lets each item serve several borrowers at once; the pool
grows once ``usage / target_utilization`` exceeds what its items serve.
``get`` borrows until the current scope closes, ``use`` for as long as a
function's effect runs; borrowers wait in line for a free item, and a
failed acquisition fails the borrower that reaches it. ``invalidate``
retires an item once its last borrower returns it, ``reserve`` keeps an
item from new borrowers for a scope.
"""

from pyfect.pool._pool import Pool, TimeToLiveStrategy
from pyfect.pool._state import PoolConfig, PoolItem, PoolState, Strategy
from pyfect.pool._waiters import PoolWaiters

__all__ = [
    "Pool",
    "PoolConfig",
    "PoolItem",
    "PoolState",
    "PoolWaiters",
    "Strategy",
    "TimeToLiveStrategy",
]
