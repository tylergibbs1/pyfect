"""``EntityId``: the id of one entity of a type (Effect's ``EntityId``)."""

from __future__ import annotations

from typing import NewType

from pyfect import schema as S
from pyfect.brand import Brand

EntityId = NewType("EntityId", str)

EntityIdSchema = S.String.pipe(S.from_brand(Brand[str, EntityId].nominal()))
"""Entity ids (Effect's ``EntityId`` schema)."""


def make(id: str) -> EntityId:
    return EntityId(id)


__all__ = ["EntityId", "EntityIdSchema", "make"]
