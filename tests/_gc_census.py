"""The objects the collector tracks, read without breaking another thread.

``gc.get_objects()`` holds every tracked object, a tuple another thread is still
building from a generator among them, and Python 3.13 fails that tuple's resize while
it is held (``SystemError: Objects/tupleobject.c:919``). A list returned to Python code
is held at a point where another thread may run, so these call ``get_objects`` from C
and consume its list inside one C call, with the collector off so that no finalizer
runs Python code meanwhile. ``tests/test_gc_census.py`` keeps every other
``gc.get_objects`` out of pyfect and its tests.
"""

from __future__ import annotations

import gc
from collections import _count_elements  # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType]
from itertools import chain, starmap
from typing import cast

from _subclasses import subclasses


def _tracked() -> chain[object]:
    return chain.from_iterable(map(gc.get_objects, (None,)))


def counts_by_type() -> dict[type, int]:
    """How many tracked objects there are of each type."""
    counts: dict[type, int] = {}
    gc.disable()
    try:
        _count_elements(counts, map(type, _tracked()))
    finally:
        gc.enable()
    return counts


def tracked_count() -> int:
    """How many objects the collector tracks."""
    return sum(counts_by_type().values())


def tracked_of[T](kind: type[T]) -> list[T]:
    """The tracked instances of ``kind`` and its subclasses, whose metaclass must be ``type``:
    another metaclass's ``__instancecheck__`` would run Python code while the list is held.

    They are read as the objects that refer to one of those classes (an instance refers to
    its class), so a weak proxy, which refers to nothing, is never asked for its
    ``__class__``: it forwards that to its referent, a ReferenceError once that has died.
    Every object stays inside the one C call, as ``_tracked`` keeps them."""
    if type(kind) is not type:
        raise TypeError(f"{kind.__name__} has metaclass {type(kind).__name__}, not type")
    classes = (kind, *subclasses(kind))
    gc.disable()
    try:
        referrers = starmap(gc.get_referrers, (classes,))
        return cast("list[T]", list(filter(kind.__instancecheck__, chain.from_iterable(referrers))))
    finally:
        gc.enable()
