"""Consistent hashing (Effect's ``HashRing``): nodes named by their
``primary_key()`` placed on a ring of virtual points, ``base_weight`` points
per unit of weight::

    ring = HashRing[Runner]()
    ring.add(runner_a)
    ring.add(runner_b, weight=2)
    ring.get("user-1")        # the node nearest the input's hash
    ring.get_shards(300)      # a balanced node for each of 300 shards

Hashes are Effect's ``Hash.string``, so the same nodes give the same
assignment as Effect's ring.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator

from pyfect._js import js_sort_key
from pyfect._string_hash import string_hash
from pyfect.primary_key import PrimaryKey

_shard_hashes: list[int] = []
"""``Hash.string(f"shard-{i}")`` for each shard index seen so far."""


def _shard_hash(shard: int) -> int:
    while len(_shard_hashes) <= shard:
        _shard_hashes.append(string_hash(f"shard-{len(_shard_hashes)}"))
    return _shard_hashes[shard]


def _js_round(x: float) -> int:
    return math.floor(x + 0.5)


def _normalize_count(n: float) -> int:
    return math.floor(n) if n > 0 else 0


class HashRing[A: PrimaryKey]:
    """A mutable ring of nodes. ``base_weight`` (at least 1) is the number
    of virtual points per unit of weight."""

    __slots__ = ("_base_weight", "_nodes", "_ring", "_total_weight")

    def __init__(self, *, base_weight: int = 128) -> None:
        self._base_weight = max(base_weight, 1)
        self._total_weight = 0.0
        self._nodes: dict[str, tuple[A, float]] = {}
        self._ring: list[tuple[int, str]] = []

    @property
    def base_weight(self) -> int:
        return self._base_weight

    def __iter__(self) -> Iterator[A]:
        return (node for node, _ in self._nodes.values())

    def __len__(self) -> int:
        return len(self._nodes)

    def __repr__(self) -> str:
        return f"HashRing(base_weight={self._base_weight}, nodes={list(self)!r})"

    def add_many(self, nodes: Iterable[A], *, weight: float = 1) -> None:
        """Add ``nodes`` with ``weight`` (at least 0.1). A node whose key is
        already there replaces the stored node and takes the new weight."""
        weight = max(weight, 0.1)
        keys: list[str] = []
        reweighted: set[str] = set()
        for node in nodes:
            key = node.primary_key()
            entry = self._nodes.get(key)
            self._nodes[key] = (node, weight)
            if entry is not None:
                if entry[1] == weight:
                    continue
                reweighted.add(key)
            keys.append(key)
        if reweighted:
            self._ring = [point for point in self._ring if point[1] not in reweighted]
        self._add_points(keys, _js_round(weight * self._base_weight))
        self._update_total_weight()

    def add(self, node: A, *, weight: float = 1) -> None:
        """``add_many([node], weight=weight)``."""
        self.add_many([node], weight=weight)

    def remove(self, node: A) -> None:
        """Remove the node with ``node``'s key, if there is one."""
        key = node.primary_key()
        if self._nodes.pop(key, None) is not None:
            self._ring = [point for point in self._ring if point[1] != key]
            self._update_total_weight()

    def has(self, node: A) -> bool:
        """Whether a node with ``node``'s key is on the ring."""
        return node.primary_key() in self._nodes

    def get(self, input: str) -> A | None:
        """The node nearest ``input``'s hash; ``None`` on an empty ring."""
        if not self._ring:
            return None
        index = self._index_for(string_hash(input), None)[0]
        return self._nodes[self._ring[index][1]][0]

    def get_shards(self, count: float) -> list[A] | None:
        """A node for each of ``count`` shards (floored; at most zero is
        none), no node taking more than its share of the weight while
        another has room; ``None`` on an empty ring."""
        if not self._ring:
            return None
        count = _normalize_count(count)
        shards: list[A | None] = [None] * count
        allocations: dict[str, int] = {}
        remaining: dict[int, None] = {}
        exclude: set[str] = set()

        distances: list[tuple[int, str, int]] = []
        for shard in range(count):
            index, distance = self._index_for(_shard_hash(shard), None)
            distances.append((shard, self._ring[index][1], distance))
            remaining[shard] = None
        distances.sort(key=lambda entry: entry[2])
        for shard, key, _ in distances:
            if key in exclude:
                continue
            value, weight = self._nodes[key]
            shards[shard] = value
            del remaining[shard]
            if self._allocate(allocations, key, weight, count):
                exclude.add(key)

        all_at_max = len(exclude) == len(self._nodes)
        for shard in remaining:
            index = self._index_for(_shard_hash(shard), None if all_at_max else exclude)[0]
            key = self._ring[index][1]
            value, weight = self._nodes[key]
            shards[shard] = value
            if all_at_max:
                continue
            if self._allocate(allocations, key, weight, count):
                exclude.add(key)
                all_at_max = len(exclude) == len(self._nodes)
        return [shard for shard in shards if shard is not None]

    def _allocate(self, allocations: dict[str, int], key: str, weight: float, count: int) -> bool:
        """Count one more shard for ``key``; whether it reached its share."""
        allocations[key] = allocations.get(key, 0) + 1
        max_per_node = max(1, math.floor(count * (weight / self._total_weight)))
        return allocations[key] >= max_per_node

    def _add_points(self, keys: list[str], weight: int) -> None:
        for i in range(weight, 0, -1):
            for key in keys:
                self._ring.append((string_hash(f"{key}:{i}"), key))
        # Ties broken by node key, so the ring does not depend on insertion order.
        self._ring.sort(key=lambda point: (point[0], js_sort_key(point[1])))

    def _update_total_weight(self) -> None:
        # Summed in key order, so the total does not depend on history.
        total = 0.0
        for key in sorted(self._nodes, key=js_sort_key):
            total += self._nodes[key][1]
        self._total_weight = total

    def _index_for(self, hash: int, exclude: set[str] | None) -> tuple[int, int]:
        ring = self._ring
        length = len(ring)
        lo, hi = 0, length - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if ring[mid][0] >= hash:
                hi = mid - 1
            else:
                lo = mid + 1
        a = lo - 1 if lo == length else lo
        dist_a = abs(ring[a][0] - hash)
        if exclude is None:
            b = lo - 1
            if b < 0:
                return a, dist_a
            dist_b = abs(ring[b][0] - hash)
            return (a, dist_a) if dist_a <= dist_b else (b, dist_b)
        if ring[a][1] not in exclude:
            return a, dist_a
        for i in range(1, max(lo, length - lo) + 1):
            for index in (lo - i, lo + i):
                if 0 <= index < length and ring[index][1] not in exclude:
                    return index, abs(ring[index][0] - hash)
        return a, dist_a


__all__ = ["HashRing"]
