"""``MachineId``: the number a runner gets when it registers, which goes
into the snowflakes it makes (Effect's ``MachineId``)."""

from __future__ import annotations

from typing import NewType

from pyfect import schema as S
from pyfect.brand import Brand

MachineId = NewType("MachineId", int)

MachineIdSchema = S.Int.pipe(S.from_brand(Brand[int, MachineId].nominal()))
"""Machine ids (Effect's ``MachineId`` schema)."""


def make(id: int) -> MachineId:
    return MachineId(id)


__all__ = ["MachineId", "MachineIdSchema", "make"]
