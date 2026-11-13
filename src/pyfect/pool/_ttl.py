"""The time-to-live strategies of ``Pool.make_with_ttl``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import weakref
from functools import partial
from typing import TYPE_CHECKING, Any

from pyfect._core import Effect, _Succeed, _Suspend, _WithFiber
from pyfect.clock import Clock, ClockService
from pyfect.duration import Duration, from_nanos_or_infinite, nanos_or_infinite
from pyfect.pool._state import PoolItem, Strategy
from pyfect.queue import Queue

if TYPE_CHECKING:
    from pyfect._fiber import Fiber
    from pyfect.pool._pool import Pool

_VOID: Effect[None] = _Succeed(None)

type _Item = PoolItem[Any, Any]
type _Pool = Pool[Any, Any]


def _clock(fiber: Fiber[Any, Any]) -> ClockService:
    return fiber._context.lookup(Clock)[1]


def creation_ttl(ttl: Duration) -> Effect[Strategy[Any, Any]]:
    """Invalidate each item ``ttl`` after it was acquired, oldest first."""
    ttl_nanos = nanos_or_infinite(ttl)

    def make(fiber: Fiber[Any, Any]) -> Effect[Strategy[Any, Any]]:
        clock = _clock(fiber)
        queue: Queue[_Item] = Queue()
        created: weakref.WeakKeyDictionary[_Item, int] = weakref.WeakKeyDictionary()

        def run(pool: _Pool) -> Effect[None]:
            process = _CreationExpiry(pool, clock, created, ttl_nanos).process
            return queue.take().flat_map(process).forever(disable_yield=True)

        def on_acquire(item: _Item) -> Effect[None]:
            def body() -> Effect[None]:
                created[item] = clock.now_nanos_unsafe()
                return queue.offer(item).as_void()

            return _Suspend(body)

        def reclaim(_: _Pool) -> Effect[_Item | None]:
            return _Succeed(None)

        return _Succeed(Strategy(run, on_acquire, reclaim))

    return _WithFiber(make)


class _CreationExpiry:
    """``creation_ttl``'s run: invalidates each item once its time is up."""

    __slots__ = ("clock", "created", "pool", "ttl_nanos")

    def __init__(
        self,
        pool: _Pool,
        clock: ClockService,
        created: weakref.WeakKeyDictionary[_Item, int],
        ttl_nanos: float,
    ) -> None:
        self.pool = pool
        self.clock = clock
        self.created = created
        self.ttl_nanos = ttl_nanos

    def process(self, item: _Item) -> Effect[None]:
        return _Suspend(partial(self._expire, item))

    def _expire(self, item: _Item) -> Effect[None]:
        pool = self.pool
        with pool.state.lock:
            gone = item not in pool.state.items or item in pool.state.invalidated
        if gone:
            return _VOID
        remaining = self.ttl_nanos - (self.clock.now_nanos_unsafe() - self.created[item])
        if remaining > 0:
            return self.process(item).delay(from_nanos_or_infinite(remaining))
        return pool._invalidate_item(item)


def usage_ttl(ttl: Duration) -> Effect[Strategy[Any, Any]]:
    """Every ``ttl``, while the pool is above its target size, invalidate
    the items idle for at least ``ttl``, longest idle first."""
    ttl_nanos = nanos_or_infinite(ttl)

    def make(fiber: Fiber[Any, Any]) -> Effect[Strategy[Any, Any]]:
        clock = _clock(fiber)

        def run(pool: _Pool) -> Effect[None]:
            retire = _Suspend(_UsageExpiry(pool, clock, ttl_nanos).retire)
            return retire.delay(ttl).forever(disable_yield=True)

        def on_acquire(_: _Item) -> Effect[None]:
            return _VOID

        def reclaim(_: _Pool) -> Effect[_Item | None]:
            return _Succeed(None)

        return _Succeed(Strategy(run, on_acquire, reclaim))

    return _WithFiber(make)


class _UsageExpiry:
    """``usage_ttl``'s run: invalidates the longest idle expired items."""

    __slots__ = ("clock", "pool", "ttl_nanos")

    def __init__(self, pool: _Pool, clock: ClockService, ttl_nanos: float) -> None:
        self.pool = pool
        self.clock = clock
        self.ttl_nanos = ttl_nanos

    def retire(self) -> Effect[None]:
        pool = self.pool
        state = pool.state
        oldest: _Item | None = None
        with state.lock:
            if pool._active_size() <= pool._target_size():
                return _VOID
            expired = self.clock.now_nanos_unsafe() - self.ttl_nanos
            for item in state.items:
                if item.ref_count > 0 or item.idle_since > expired:
                    continue
                if item in state.invalidated or item.reservations:
                    continue
                if oldest is None or item.idle_since < oldest.idle_since:
                    oldest = item
        if oldest is None:
            return _VOID
        return pool._invalidate_item(oldest).and_then(_Suspend(self.retire))
