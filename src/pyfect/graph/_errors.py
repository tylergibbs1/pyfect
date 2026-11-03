"""``GraphError`` and the messages several modules raise it with."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Never

from pyfect.errors import TaggedError

MAX_SAFE_INDEX = 2**53 - 1
"""Indexes stay JavaScript safe integers, so snapshots round-trip with Effect's."""


@dataclass(eq=False)
class GraphError(TaggedError):
    """An invalid graph operation: a missing node, a kind mismatch, a
    mutation of a finalized or busy graph, a bad weight."""

    message: str

    def __str__(self) -> str:
        return self.message


def fail(message: str) -> Never:
    raise GraphError(message)


def missing_node(node: int) -> GraphError:
    return GraphError(f"Node {node} does not exist")


def is_safe_index(value: object) -> bool:
    """``Number.isSafeInteger(value) && value >= 0``."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return math.isfinite(value) and float(value).is_integer() and 0 <= value <= MAX_SAFE_INDEX


def bound(value: float | None, default: float, message: str) -> float:
    """A radius or limit: a non-negative whole number or ``math.inf``."""
    chosen = default if value is None else value
    if chosen != math.inf and not (
        not isinstance(chosen, bool)
        and math.isfinite(chosen)
        and float(chosen).is_integer()
        and chosen >= 0
    ):
        fail(message)
    return chosen
