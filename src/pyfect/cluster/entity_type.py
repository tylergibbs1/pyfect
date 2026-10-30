"""``EntityType``: the name of an entity (Effect's ``EntityType``)."""

from __future__ import annotations

from typing import NewType

from pyfect import schema as S
from pyfect.brand import Brand

EntityType = NewType("EntityType", str)

EntityTypeSchema = S.String.pipe(S.from_brand(Brand[str, EntityType].nominal()))
"""Entity types (Effect's ``EntityType`` schema)."""


def make(value: str) -> EntityType:
    return EntityType(value)


__all__ = ["EntityType", "EntityTypeSchema", "make"]
