"""Whether a schema is exact: a graph of the parts it was built from, since
definitions can be recursive. A cycle is exact unless it reaches
``False``."""

from __future__ import annotations

from collections.abc import Sequence

type Exactness = bool | Sequence[Exactness]


def is_exact(exactness: Exactness, seen: set[int] | None = None) -> bool:
    if isinstance(exactness, bool):
        return exactness
    seen = set() if seen is None else seen
    if id(exactness) in seen:
        return True
    seen.add(id(exactness))
    return all(is_exact(dependency, seen) for dependency in exactness)
