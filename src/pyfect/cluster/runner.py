"""``Runner``: a runner's address, the shard groups it serves and its
weight in shard assignment (Effect's ``Runner``)."""

from __future__ import annotations

from functools import lru_cache

from pyfect import schema as S
from pyfect._string_hash import string_hash
from pyfect.cluster.runner_address import RunnerAddress


class Runner(S.Class, identifier="~effect/cluster/Runner"):
    """Equal when the address and weight are (the groups are not
    compared, as in Effect)."""

    address: RunnerAddress
    groups: tuple[str, ...]
    weight: float = S.field(S.Finite)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Runner):
            return NotImplemented
        return self.address == other.address and self.weight == other.weight

    def __hash__(self) -> int:
        return _key_hash(f"{self.address}:{self.weight}")


# The sharding loops hash every runner on each refresh, as often as every op
# budget: Effect's string hash is too slow in Python to recompute each time.
_key_hash = lru_cache(maxsize=4096)(string_hash)


def make(*, address: RunnerAddress, groups: tuple[str, ...], weight: float) -> Runner:
    return S.new(Runner, disable_checks=True)(address=address, groups=groups, weight=weight)


__all__ = ["Runner", "make"]
