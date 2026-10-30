"""``ShardId``: a shard, numbered within its shard group (Effect's
``ShardId``). Its text form is ``"<group>:<id>"``."""

from __future__ import annotations

from pyfect import schema as S
from pyfect._digits import parse_signed_digits


class ShardId(S.Class, identifier="~effect/cluster/ShardId"):
    """Shard ``id`` of ``group``; equal by both."""

    group: str
    id: int

    def primary_key(self) -> str:
        return str(self)

    def __str__(self) -> str:
        return f"{self.group}:{self.id}"


def make(group: str, id: int) -> ShardId:
    return ShardId(group=group, id=id)


def from_string(text: str) -> ShardId:
    """Parse ``"<group>:<id>"`` (the group may hold ``:``, the id is ASCII
    digits); raises ``ValueError`` for anything else."""
    group, colon, id = text.rpartition(":")
    if not colon:
        raise ValueError("Invalid ShardId format")
    number = parse_signed_digits(id)
    if number is None:
        raise ValueError("ShardId id must be a number")
    return ShardId(group=group, id=number)


__all__ = ["ShardId", "from_string", "make"]
