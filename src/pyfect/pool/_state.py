"""What a pool keeps: its items, the list of items with free capacity, its
waiters, and the strategy that resizes it.

A pool's state is public, as in Effect, so custom strategies and tests can
read it. Sets of items are dicts used as insertion-ordered sets: the order
in which items are visited is part of the behavior.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pyfect._core import Effect
from pyfect.exit import Exit, Failure
from pyfect.pool._waiters import PoolWaiters

if TYPE_CHECKING:
    from pyfect.pool._pool import Pool
    from pyfect.scope import CloseableScope
    from pyfect.semaphore import Semaphore


class PoolItem[A, E]:
    """One acquisition: its exit, its finalizer, and how it is used.

    ``ref_count`` counts the leases on it, ``reservations`` the ``reserve``
    calls holding it out of circulation. ``idle_since`` is the pool clock's
    wall time, in whole nanoseconds, when its last lease returned (or when
    it was acquired)."""

    __slots__ = (
        "__weakref__",
        "available_next",
        "available_previous",
        "disable_reclaim",
        "exit",
        "finalizer",
        "idle_since",
        "is_available",
        "ref_count",
        "reservations",
    )

    def __init__(self, ex: Exit[A, E], finalizer: Effect[None], idle_since: int) -> None:
        self.exit = ex
        self.finalizer = finalizer
        self.idle_since = idle_since
        self.ref_count = 0
        self.reservations = 0
        self.disable_reclaim = False
        self.is_available = False
        self.available_previous: PoolItem[A, E] | None = None
        self.available_next: PoolItem[A, E] | None = None


class PoolState[A, E]:
    """The mutable state of a pool. The available list is a doubly linked
    list through the items, most recently released first. Runs on other
    threads share a pool: its state is read and changed holding ``lock``,
    which is let go only to resume a fiber."""

    __slots__ = (
        "available_head",
        "available_tail",
        "invalidated",
        "is_shutting_down",
        "items",
        "lock",
        "resize_semaphore",
        "scope",
        "usage",
        "waiters",
    )

    def __init__(self, scope: CloseableScope, resize_semaphore: Semaphore) -> None:
        self.scope = scope
        self.resize_semaphore = resize_semaphore
        self.is_shutting_down = False
        self.usage = 0
        self.items: dict[PoolItem[A, E], None] = {}
        self.invalidated: dict[PoolItem[A, E], None] = {}
        self.lock = threading.Lock()
        self.waiters = PoolWaiters(self.lock)
        self.available_head: PoolItem[A, E] | None = None
        self.available_tail: PoolItem[A, E] | None = None

    def _add_available(self, item: PoolItem[A, E]) -> None:
        if item.is_available or item.reservations:
            return
        item.is_available = True
        item.available_previous = self.available_tail
        item.available_next = None
        if self.available_tail is not None:
            self.available_tail.available_next = item
        else:
            self.available_head = item
        self.available_tail = item

    def _add_available_front(self, item: PoolItem[A, E]) -> None:
        if item.is_available or item.reservations:
            return
        item.is_available = True
        item.available_previous = None
        item.available_next = self.available_head
        if self.available_head is not None:
            self.available_head.available_previous = item
        else:
            self.available_tail = item
        self.available_head = item

    def _remove_available(self, item: PoolItem[A, E]) -> None:
        if not item.is_available:
            return
        item.is_available = False
        if item.available_previous is not None:
            item.available_previous.available_next = item.available_next
        else:
            self.available_head = item.available_next
        if item.available_next is not None:
            item.available_next.available_previous = item.available_previous
        else:
            self.available_tail = item.available_previous
        item.available_previous = None
        item.available_next = None

    def _first_healthy_available(self) -> PoolItem[A, E] | None:
        item = self.available_head
        while item is not None and isinstance(item.exit, Failure):
            item = item.available_next
        return item

    def _remove(self, item: PoolItem[A, E]) -> None:
        """Take ``item`` out of the pool (its finalizer is the caller's)."""
        self.items.pop(item, None)
        self.invalidated.pop(item, None)
        self._remove_available(item)


@dataclass(frozen=True, slots=True)
class Strategy[A, E]:
    """How a pool resizes. ``run`` runs on its own fiber for the pool's
    lifetime, ``on_acquire`` sees each new item, and ``reclaim`` may hand
    back an existing item (an invalidated one, say) instead of acquiring a
    new one."""

    run: Callable[[Pool[A, E]], Effect[None]]
    on_acquire: Callable[[PoolItem[A, E]], Effect[None]]
    reclaim: Callable[[Pool[A, E]], Effect[PoolItem[A, E] | None]]


@dataclass(frozen=True, slots=True, kw_only=True)
class PoolStats:
    """A point-in-time count of a pool's items and waiting borrowers
    (Effect's ``Pool.Stats``). ``idle`` and ``used`` count acquired items,
    not borrowers; ``pending`` counts borrowers waiting for an item; ``min``
    and ``max`` are the configured bounds."""

    idle: int
    used: int
    pending: int
    min: int
    max: int


@dataclass(frozen=True, slots=True)
class PoolConfig[A, E]:
    """A pool's settings. ``acquire`` runs with the services in scope when
    the pool was made; ``target_utilization`` is clamped to [0.1, 1]."""

    acquire: Effect[A, E, Any]
    concurrency: int
    is_fixed: bool
    min_size: int
    max_size: int
    strategy: Strategy[A, E]
    target_utilization: float
