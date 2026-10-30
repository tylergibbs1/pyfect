"""``Runner``: a runner's address, the shard groups it serves and its
weight in shard assignment (Effect's ``Runner``)."""

from __future__ import annotations

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
        return string_hash(f"{self.address}:{self.weight}")


def make(*, address: RunnerAddress, groups: tuple[str, ...], weight: float) -> Runner:
    return Runner(address=address, groups=groups, weight=weight)


__all__ = ["Runner", "make"]
