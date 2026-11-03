"""Effect's ``Equal.equals`` on Python values, and keys that follow it.

Python's ``==`` and ``hash`` call ``True`` equal to ``1`` (and ``False`` to
``0``, also inside tuples and dicts) and a NaN unequal to every other NaN;
Effect's ``Equal.equals`` keeps booleans apart from numbers and calls NaN
equal to NaN. ``1`` and ``1.0`` are one JavaScript number, so they stay
equal. Anything that dedupes, compares or keys values the way Effect's
``Equal`` does (``is_unique``, set and map codecs, cause reasons, unique
strategies) goes through ``equal_key`` / ``equals`` / ``dedupe``, never
through ``set(...)``, ``in`` or a ``dict`` of the values themselves.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence, Set
from contextvars import ContextVar
from typing import cast

from pyfect._stack import stack_nearly_full, with_fresh_stack


def equal_key(value: object) -> Hashable:
    """A key that is ``==`` for two values exactly when ``Equal.equals``
    calls them equal: ``True`` apart from ``1``, NaN equal to NaN, lists,
    tuples, mappings and sets by their items. Raises ``TypeError`` for a
    value holding an unhashable object of another kind, or holding itself
    (compare those with ``equals``)."""
    return _key(value, set())


def _key(value: object, path: set[int]) -> Hashable:
    # ``path``: the ids of the containers being keyed, to stop at a cycle.
    kind = type(value)
    if kind is str or kind is int or value is None:
        return value
    if kind is tuple or kind is list or kind is dict or kind is frozenset or kind is set:
        return _container_key(value, path) if not stack_nearly_full() else _deep(value, path)
    return _other_key(value, path)


def _other_key(value: object, path: set[int]) -> Hashable:
    if isinstance(value, BaseException):
        hash(value)
        return value
    match value:
        case bool():
            return (bool, value)
        case float() if math.isnan(value):
            return (float, "nan")
        case str() | bytes() | int() | float():
            return value
        case list() | tuple() | Mapping() | Set():
            return _deep(cast("object", value), path)
        case Hashable():
            hash(value)  # a frozen dataclass holding a list raises here
            return value
        case _:
            raise TypeError(f"unhashable type: {type(value).__name__!r}")


def _deep(value: object, path: set[int]) -> Hashable:
    return with_fresh_stack(lambda: _container_key(value, path))


def _container_key(value: object, path: set[int]) -> Hashable:
    marker = id(value)
    if marker in path:
        raise TypeError("cyclic value")
    path.add(marker)
    try:
        if isinstance(value, list | tuple):
            items = cast("Sequence[object]", value)
            return (tuple, tuple(_key(item, path) for item in items))
        if isinstance(value, Mapping):
            pairs = cast("Mapping[object, object]", value).items()
            return (dict, frozenset((_key(k, path), _key(v, path)) for k, v in pairs))
        return (frozenset, frozenset(_key(item, path) for item in cast("Set[object]", value)))
    finally:
        path.remove(marker)


_SCALARS = frozenset({str, int, float, bool, bytes, type(None)})

_in_progress: ContextVar[set[tuple[int, int]] | None] = ContextVar(
    "pyfect_equals_in_progress", default=None
)
"""The pairs being compared by the ``equals`` call running in this context.
A fresh stack copies the context, so the set follows a walk across
threads."""


def equals(a: object, b: object) -> bool:
    """Effect's ``Equal.equals``: ``==``, but ``True`` is not ``1`` and NaN
    is NaN, also inside lists, tuples, mappings and sets. A pair of values
    met again while comparing them (a cycle, also through an ``__eq__`` that
    calls ``equals``) is assumed equal, so cyclic values compare as their
    unfoldings do."""
    if a is b:
        return True
    kind = type(a)
    if kind is type(b) and (kind is str or kind is int):
        return a == b
    if kind in _SCALARS and type(b) in _SCALARS:
        return equal_key(a) == equal_key(b)
    pairs = _in_progress.get()
    if pairs is not None:
        return _assuming_equal(a, b, pairs)
    token = _in_progress.set(pairs := set())
    try:
        return _assuming_equal(a, b, pairs)
    finally:
        _in_progress.reset(token)


def _assuming_equal(a: object, b: object, pairs: set[tuple[int, int]]) -> bool:
    pair = (id(a), id(b))
    if pair in pairs:
        return True
    pairs.add(pair)
    try:
        if stack_nearly_full():
            return with_fresh_stack(lambda: _equal_structure(a, b))
        return _equal_structure(a, b)
    finally:
        pairs.remove(pair)


def _equal_structure(a: object, b: object) -> bool:
    # Lists, tuples and mappings part by part, so a value is walked once
    # (keying it whole would key each level again when a part is unhashable).
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, list | tuple) and isinstance(b, list | tuple):
        left, right = cast("Sequence[object]", a), cast("Sequence[object]", b)
        return len(left) == len(right) and all(map(equals, left, right))
    if isinstance(a, Mapping) and isinstance(b, Mapping):
        left_map, right_map = cast("Mapping[object, object]", a), cast("Mapping[object, object]", b)
        if len(left_map) != len(right_map):
            return False
        keys = {equal_key(k): k for k in right_map}
        return all(
            (key := keys.get(equal_key(k), _ABSENT)) is not _ABSENT and equals(v, right_map[key])
            for k, v in left_map.items()
        )
    try:
        return equal_key(cast("object", a)) == equal_key(b)
    except TypeError:
        return bool(a == b)


_ABSENT = object()


def dedupe[A](items: Iterable[A], key: Callable[[A], object] = lambda item: item) -> list[A]:
    """``items`` without the ones ``equals`` calls equal to an earlier one
    (compared through ``key``), in order: Effect's ``Array.dedupe``."""
    kept: list[A] = []
    seen: set[Hashable] = set()
    unkeyed: list[object] = []
    for item in items:
        value = key(item)
        try:
            k = equal_key(value)
        except TypeError:
            if any(equals(value, other) for other in unkeyed):
                continue
            unkeyed.append(value)
        else:
            if k in seen:
                continue
            seen.add(k)
        kept.append(item)
    return kept


def frozenset_of(items: Iterable[object]) -> frozenset[object] | None:
    """The set of ``items``, those ``Equal.equals`` calls equal kept once
    (Effect's ``HashSet``); ``None`` when Python's set would merge items
    Effect keeps apart (``1`` and ``True``)."""
    kept = dedupe(items)
    out = frozenset(kept)
    return out if len(out) == len(kept) else None


def dict_of(pairs: Iterable[tuple[object, object]]) -> dict[object, object] | None:
    """The mapping of ``pairs``, the last value for keys ``Equal.equals``
    calls equal (Effect's ``HashMap``); ``None`` when Python's dict would
    merge keys Effect keeps apart (``1`` and ``True``)."""
    entries: dict[Hashable, tuple[object, object]] = {}
    for key, value in pairs:
        k = equal_key(key)
        entries[k] = (entries[k][0] if k in entries else key, value)
    out = dict(entries.values())
    return out if len(out) == len(entries) else None
