"""Ports of Effect's ``test/HashRing.test.ts``.

Each test's docstring is the Effect test title. A node is anything with a
``primary_key()`` method; the ring is mutated in place.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pyfect._string_hash import string_hash
from pyfect.hash_ring import HashRing


@dataclass(frozen=True)
class Node:
    key: str
    name: str = ""

    def primary_key(self) -> str:
        return self.key


def test_updates_stored_node_on_same_key() -> None:
    """updates the stored node when adding the same primary key"""
    first, updated = Node("node", "first"), Node("node", "updated")
    ring = HashRing[Node]()
    ring.add(first)
    ring.add(updated)
    assert ring.get("request") is updated


def test_updates_stored_node_on_weight_change() -> None:
    """updates the stored node when changing its weight"""
    first, updated = Node("node", "first"), Node("node", "updated")
    ring = HashRing[Node]()
    ring.add(first)
    ring.add(updated, weight=2)
    assert ring.get("request") is updated


def test_get_shards_normalizes_count() -> None:
    """getShards normalizes the shard count"""
    node = Node("node")
    ring = HashRing[Node]()
    ring.add(node)
    shards = [ring.get_shards(count) for count in (math.nan, -1, 0, 0.5, 1.9, 2.9)]
    assert shards == [[], [], [], [], [node], [node, node]]


def test_get_shards_considers_first_ring_entry() -> None:
    """getShards considers the first ring entry when excluding allocated nodes"""
    ring = HashRing[Node](base_weight=1)
    ring.add(Node("node-10"))
    ring.add(Node("node-29"))
    shards = ring.get_shards(3)
    assert shards is not None
    assert [node.primary_key() for node in shards] == ["node-10", "node-29", "node-29"]


def test_get_shards_unchanged_after_fractional_churn() -> None:
    """getShards is unchanged after adding and removing a fractional-weight node"""
    a, b, c, d = (Node(f"runner-{x}:34431") for x in "abcd")
    churned = HashRing[Node]()
    churned.add_many([a, b, c], weight=0.1)
    churned.add(d, weight=0.3)
    churned.remove(d)
    fresh = HashRing[Node]()
    fresh.add_many([a, b, c], weight=0.1)
    assert churned.get_shards(300) == fresh.get_shards(300)


def test_get_shards_breaks_ties_independently_of_order() -> None:
    """getShards breaks ring hash ties independently of insertion order"""
    first, second = Node("runner-27:34431"), Node("runner-1176:34431")
    assert string_hash("runner-27:34431:13") == string_hash("runner-1176:34431:71")
    ring = HashRing[Node]()
    ring.add(first)
    ring.add(second)
    swapped = HashRing[Node]()
    swapped.add(second)
    swapped.add(first)
    assert swapped.get_shards(300) == ring.get_shards(300)


def test_get_shards_keeps_integer_weight_assignment() -> None:
    """getShards keeps the assignment for integer weights"""
    ring = HashRing[Node]()
    nodes = [Node(f"runner-{i}:34431") for i in range(5)]
    for node, weight in zip(nodes, [1, 1, 2, 1, 3], strict=True):
        ring.add(node, weight=weight)
    expected = [4, 3, 0, 2, 2, 4, 3, 4, 1, 2, 2, 4, 1, 4, 4, 0]
    assert ring.get_shards(16) == [nodes[i] for i in expected]


def test_get_shards_independent_of_insertion_order_for_fractional_weights() -> None:
    """(pyfect) getShards sums fractional weights in key order, so the
    assignment does not depend on the order nodes were added"""
    weights = [("a", 0.1), ("b", 0.2), ("c", 0.3)]
    # 0.1 + 0.2 + 0.3 != 0.3 + 0.2 + 0.1 in floating point.
    forward, backward = HashRing[Node](), HashRing[Node]()
    for key, weight in weights:
        forward.add(Node(key), weight=weight)
    for key, weight in reversed(weights):
        backward.add(Node(key), weight=weight)
    for count in (2, 10, 60, 300):
        assert backward.get_shards(count) == forward.get_shards(count)
