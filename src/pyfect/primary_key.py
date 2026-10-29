"""Values that name themselves with a string (Effect's ``PrimaryKey``).

A persisted request is stored under its primary key, so two requests with
the same key share one stored result::

    @dataclass(frozen=True)
    class GetUser(persistable.Class(success=User)):
        id: int

        def primary_key(self) -> str:
            return f"GetUser:{self.id}"
"""

from __future__ import annotations

from typing import Protocol, TypeIs, runtime_checkable


@runtime_checkable
class PrimaryKey(Protocol):
    """Anything with a ``primary_key()`` method."""

    def primary_key(self) -> str: ...


def is_primary_key(u: object) -> TypeIs[PrimaryKey]:
    return isinstance(u, PrimaryKey)


def value(key: PrimaryKey) -> str:
    """``key.primary_key()``."""
    return key.primary_key()


__all__ = ["PrimaryKey", "is_primary_key", "value"]
