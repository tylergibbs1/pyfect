"""Effect's ``NonEmptyArray``: a tuple of at least one item, made from its
first item and the rest, so no empty one can be made."""

from __future__ import annotations

from collections.abc import Iterable


def non_empty[A](first: A, rest: Iterable[A]) -> tuple[A, *tuple[A, ...]]:
    return (first, *rest)
