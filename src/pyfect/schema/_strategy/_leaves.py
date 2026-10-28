"""Strategies for the leaves: strings, numbers, bigints and JSON, built
within a node's constraint (Effect's primitive constructors in
``Arbitrary.schema``)."""

from __future__ import annotations

from typing import Any

from hypothesis import strategies as st

from pyfect.schema._arbitrary_constraint import ArbitraryConstraint
from pyfect.schema._arbitrary_number import (
    FloatInterval,
    IntInterval,
    big_int_interval,
    float_interval,
    integer_interval,
    integers_within,
)

type Strategy = st.SearchStrategy[Any]

_MAX_SAFE_INTEGER = 2**53 - 1


def string(constraint: ArbitraryConstraint) -> Strategy:
    """Text within the length bounds; with patterns, the matches of any one
    of them (the others, like every check, filter what it draws)."""
    low, high = constraint.min_length or 0, constraint.max_length
    if not constraint.patterns:
        return st.text(min_size=low, max_size=high)
    within = st.one_of([st.from_regex(pattern) for pattern in constraint.patterns])
    if low == 0 and high is None:
        return within
    return within.filter(lambda s: low <= len(s) and (high is None or len(s) <= high))


def _safe_integers(interval: IntInterval | None) -> Strategy | None:
    """The safe integers of ``interval`` (JavaScript's integral ``number``
    values), ``None`` when it holds none."""
    if interval is None:
        return None
    lo = -_MAX_SAFE_INTEGER if interval.low is None else max(interval.low, -_MAX_SAFE_INTEGER)
    hi = _MAX_SAFE_INTEGER if interval.high is None else min(interval.high, _MAX_SAFE_INTEGER)
    return None if lo > hi else st.integers(lo, hi)


def _floats(interval: FloatInterval) -> Strategy:
    bounded = interval.low is not None or interval.high is not None
    return st.floats(
        min_value=interval.low,
        max_value=interval.high,
        allow_nan=not (interval.finite or bounded),
        allow_infinity=False if interval.finite else None,
    )


def number(constraint: ArbitraryConstraint) -> Strategy:
    """Python numbers: ``int`` and ``float`` (JavaScript's ``number``), only
    ``int`` for an integer constraint; ``NaN`` and the infinities only where
    no constraint rules them out."""
    if constraint.number == "integer":
        interval = integer_interval(constraint)
        return st.integers(interval.low, interval.high)
    floats = _floats(float_interval(constraint))
    integers = _safe_integers(integers_within(constraint))
    return floats if integers is None else st.one_of(integers, floats)


def big_int(constraint: ArbitraryConstraint) -> Strategy:
    interval = big_int_interval(constraint)
    return st.integers(interval.low, interval.high)


def _json_leaf() -> Strategy:
    return st.one_of(
        st.none(),
        st.booleans(),
        st.integers(-_MAX_SAFE_INTEGER, _MAX_SAFE_INTEGER),
        st.floats(allow_nan=False, allow_infinity=False),
        st.text(),
    )


def json() -> Strategy:
    """Any JSON value: ``None``, booleans, numbers, strings, lists and
    string-keyed dicts (Effect generates ``Unknown`` and ``Any`` this way)."""
    return st.recursive(
        _json_leaf(),
        lambda children: st.one_of(
            st.lists(children, max_size=4), st.dictionaries(st.text(), children, max_size=4)
        ),
        max_leaves=8,
    )
