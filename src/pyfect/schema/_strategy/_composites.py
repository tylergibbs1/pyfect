"""Strategies for sequences and mappings, given their parts' strategies
(``None`` for a part the recursion budget leaves out)."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass
from typing import Any

from hypothesis import strategies as st

from pyfect._equal import equal_key
from pyfect.schema._arbitrary_constraint import ArbitraryConstraint

type Strategy = st.SearchStrategy[Any]


@dataclass(frozen=True, slots=True)
class ArraysPlan:
    required: Sequence[Strategy]
    optional: Sequence[Strategy | None]
    rest: Strategy | None
    post: Sequence[Strategy]
    mutable: bool
    unique: bool
    """Distinct rest items (Effect's ``Equal.equals``, ``unique_key``)."""


def unique_key(value: object) -> Hashable:
    """A key equal for values ``Equal.equals`` calls equal
    (``pyfect._equal.equal_key``); a value with no key is only itself."""
    try:
        return equal_key(value)
    except TypeError:
        return (id, id(value))


def arrays(plan: ArraysPlan, constraint: ArbitraryConstraint) -> Strategy:
    """A tuple (a list when ``mutable``): the required elements, a prefix of
    the optional ones, then (once every optional one is there) rest items
    and the post-rest elements, within the length bounds."""
    low, high = constraint.min_length or 0, constraint.max_length

    @st.composite
    def draw_arrays(draw: st.DrawFn) -> Any:
        items = [draw(s) for s in plan.required]
        complete = True
        for strategy in plan.optional:
            needed = len(items) + len(plan.post) < low
            if strategy is None or not (needed or draw(st.booleans())):
                complete = False
                break
            items.append(draw(strategy))
        if complete and plan.rest is not None:
            count = len(items) + len(plan.post)
            rest = draw(
                st.lists(
                    plan.rest,
                    min_size=max(0, low - count),
                    max_size=None if high is None else max(0, high - count),
                    unique_by=unique_key if plan.unique else None,
                )
            )
            items.extend(rest)
        items.extend(draw(s) for s in plan.post)
        return items if plan.mutable else tuple(items)

    return draw_arrays()


@dataclass(frozen=True, slots=True)
class Index:
    key: Strategy
    value: Strategy


@dataclass(frozen=True, slots=True)
class ObjectsPlan:
    required: Sequence[tuple[Hashable, Strategy]]
    optional: Sequence[tuple[Hashable, Strategy]]
    indexes: Sequence[Index]
    fits_indexes: Callable[[Hashable, Any], bool]
    """Whether an entry's value fits every index signature taking its key."""


def objects(plan: ObjectsPlan, constraint: ArbitraryConstraint) -> Strategy:
    """A dict: the required keys, any of the optional ones, then entries of
    the index signatures (never a declared key), within the property
    bounds."""
    declared = {name for name, _ in (*plan.required, *plan.optional)}
    low, high = constraint.min_properties or 0, constraint.max_properties
    entries = (
        st.one_of([st.tuples(i.key, i.value) for i in plan.indexes]).filter(
            lambda entry: entry[0] not in declared and plan.fits_indexes(*entry)
        )
        if plan.indexes
        else None
    )

    @st.composite
    def draw_objects(draw: st.DrawFn) -> dict[Hashable, Any]:
        out: dict[Hashable, Any] = {name: draw(s) for name, s in plan.required}
        for name, strategy in plan.optional:
            if draw(st.booleans()):
                out[name] = draw(strategy)
        if entries is not None:
            count = len(out)
            pairs = draw(
                st.lists(
                    entries,
                    min_size=max(0, low - count),
                    max_size=None if high is None else max(0, high - count),
                    unique_by=lambda entry: entry[0],
                )
            )
            out.update(pairs)
        return out

    return draw_objects()
