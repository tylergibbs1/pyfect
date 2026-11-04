"""What a driver's raw result (``Statement.raw``) says about a statement
that changes rows, read the same way whatever the driver."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class RowCount(Protocol):
    """A raw result that counts the rows it changed (the MySQL driver's
    ``ResultSetHeader``)."""

    @property
    def affected_rows(self) -> int: ...


def affected_rows(result: object) -> int:
    """How many rows the statement of ``result`` changed; 0 when its
    driver's result does not count them."""
    return result.affected_rows if isinstance(result, RowCount) else 0


__all__ = ["RowCount", "affected_rows"]
