"""The time-to-live strategies of ``Pool.make_with_ttl``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import math
import weakref
from typing import TYPE_CHECKING, Any

from pyfect._core import Effect, _Succeed, _Suspend, _WithFiber
from pyfect.clock import Clock, ClockService
from pyfect.duration import Seconds, to_nanos
from pyfect.pool._state import PoolItem, Strategy
from pyfect.queue import Queue

if TYPE_CHECKING:
    from pyfect._fiber import Fiber
    from pyfect.pool._pool import Pool

_VOID: Effect[None] = _Succeed(None)

type _Item = PoolItem[Any, Any]
type _Pool = Pool[Any, Any]


def _nanos(ttl: Seconds) -> float:
    return math.inf if math.isinf(ttl) else to_nanos(ttl)


def _clock(fiber: Fiber[Any, Any]) -> ClockService:
    return fiber._context.lookup(Clock)[1]


def creation_ttl(ttl: Seconds) -> Effect[Strategy[Any, Any]]:
    """Invalidate each item ``ttl`` after it was acquired, oldest first."""
    ttl_nanos = _nanos(ttl)

    def make(fiber: Fiber[Any, Any]) -> Effect[Strategy[Any, Any]]:
        clock = _clock(fiber)
        queue: Queue[_Item] = Queue()
        created: weakref.WeakKeyDictionary[_Item, int] = weakref.WeakKeyDictionary()

        def run(pool: _Pool) -> Effect[None]:
            def process(item: _Item) -> Effect[None]:
                def body() -> Effect[None]:
                    if item not in pool.state.items or item in pool.state.invalidated:
                        return _VOID
                    remaining = ttl_nanos - (clock.now_nanos_unsafe() - created[item])
                    if remaining > 0:
                        return process(item).delay(remaining / 1e9)
                    return pool._invalidate_item(item)

                return _Suspend(body)

            return queue.take().flat_map(process).forever()

        def on_acquire(item: _Item) -> Effect[None]:
            def body() -> Effect[None]:
                created[item] = clock.now_nanos_unsafe()
                return queue.offer(item).as_void()

            return _Suspend(body)

        def reclaim(_: _Pool) -> Effect[_Item | None]:
            return _Succeed(None)

        return _Succeed(Strategy(run, on_acquire, reclaim))

    return _WithFiber(make)


def usage_ttl(ttl: Seconds) -> Effect[Strategy[Any, Any]]:
    """Every ``ttl``, while the pool is above its target size, invalidate
    the items idle for at least ``ttl``, longest idle first."""
    ttl_nanos = _nanos(ttl)

    def make(fiber: Fiber[Any, Any]) -> Effect[Strategy[Any, Any]]:
        clock = _clock(fiber)

        def run(pool: _Pool) -> Effect[None]:
            state = pool.state

            def retire() -> Effect[None]:
                if pool._active_size() <= pool._target_size():
                    return _VOID
                expired = clock.now_nanos_unsafe() - ttl_nanos
                oldest: _Item | None = None
                for item in state.items:
                    if item.ref_count > 0 or item.idle_since > expired:
                        continue
                    if item in state.invalidated or item.reservations:
                        continue
                    if oldest is None or item.idle_since < oldest.idle_since:
                        oldest = item
                if oldest is None:
                    return _VOID
                return pool._invalidate_item(oldest).and_then(process)

            process: Effect[None] = _Suspend(retire)
            return process.delay(ttl).forever()

        def on_acquire(_: _Item) -> Effect[None]:
            return _VOID

        def reclaim(_: _Pool) -> Effect[_Item | None]:
            return _Succeed(None)

        return _Succeed(Strategy(run, on_acquire, reclaim))

    return _WithFiber(make)
