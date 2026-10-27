"""Keyed queues served in turn, one item per turn.

The cursor survives additions and removals the way a JavaScript ``Map``
iterator does (Effect's ``PartitionedSemaphore`` relies on it): a key added
later is reached in this round, and a key removed and added again moves to
the end.
"""

from __future__ import annotations

from collections.abc import Hashable


class _Queue[K, V]:
    __slots__ = ("items", "key", "slot")

    def __init__(self, key: K, slot: int) -> None:
        self.key = key
        self.slot = slot
        # A dict as an insertion-ordered set: removal from the middle is O(1).
        self.items: dict[V, None] = {}


class RoundRobin[K: Hashable, V: Hashable]:
    __slots__ = ("_cursor", "_holes", "_queues", "_ring")

    def __init__(self) -> None:
        self._queues: dict[K, _Queue[K, V]] = {}
        self._ring: list[_Queue[K, V] | None] = []
        self._cursor = 0
        self._holes = 0

    def add(self, key: K, item: V) -> None:
        queue = self._queues.get(key)
        if queue is None:
            queue = self._queues[key] = _Queue(key, len(self._ring))
            self._ring.append(queue)
        queue.items[item] = None

    def remove(self, key: K, item: V) -> None:
        queue = self._queues.get(key)
        if queue is None or item not in queue.items:
            return
        del queue.items[item]
        if queue.items:
            return
        del self._queues[key]
        self._ring[queue.slot] = None
        self._holes += 1
        if self._holes * 2 > len(self._ring):
            self._compact()

    def next(self) -> tuple[K, V] | None:
        """The next key and the head of its queue, or ``None`` if all are
        empty. Does not remove it."""
        for _ in range(2):
            while self._cursor < len(self._ring):
                queue = self._ring[self._cursor]
                self._cursor += 1
                if queue is not None:
                    return queue.key, next(iter(queue.items))
            self._cursor = 0
            self._compact()
        return None

    def _compact(self) -> None:
        live_before_cursor = sum(q is not None for q in self._ring[: self._cursor])
        live = [q for q in self._ring if q is not None]
        for slot, queue in enumerate(live):
            queue.slot = slot
        self._ring = list[_Queue[K, V] | None](live)
        self._cursor = live_before_cursor
        self._holes = 0
