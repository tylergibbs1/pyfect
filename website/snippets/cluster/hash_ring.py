import hashlib
from collections import Counter
from dataclasses import dataclass

from pyfect.hash_ring import HashRing


@dataclass(frozen=True)
class Node:
    name: str

    def primary_key(self) -> str:
        return self.name


ring = HashRing[Node]()
ring.add_many([Node("a"), Node("b")])
jobs = [f"job-{i}" for i in range(600)]

# `get` places each key at the node nearest its hash: only as even as the
# node names hash. Short names like these split 600 keys very unevenly
# (Effect's HashRing gives the same counts).
by_get = Counter(node.name for job in jobs if (node := ring.get(job)))
print("get:", sorted(by_get.items()))

# Balanced: hash each key to one of a fixed number of shards, and let the ring
# place the shards. This is what the cluster does with its entities.
SHARDS = 300
shards = ring.get_shards(SHARDS) or []


def shard_of(key: str) -> int:
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big") % SHARDS


print("shards:", sorted(Counter(node.name for node in shards).items()))
by_shard = Counter(shards[shard_of(job)].name for job in jobs)
print("keys by shard:", sorted(by_shard.items()))
