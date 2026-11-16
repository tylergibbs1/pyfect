"""Reading the collector's objects never breaks another thread's ``tuple(generator)``.

The long soak on Python 3.13 died with ``SystemError: Objects/tupleobject.c:919: bad
argument to internal function``: ``tuple`` of a generator makes the tuple, then resizes
it, which fails if anything else holds it, and the sampler thread's
``gc.get_objects()`` list held it while the program's thread ran on. (Python 3.14
builds the tuple differently.) ``_gc_census`` reads the objects safely, and is the only
reader: tests that counted objects the same way, while pyfect's threads ran, could
break them as the soak did.
"""

from __future__ import annotations

import ast
import threading
import weakref
from pathlib import Path

import _source
import pytest
from _gc_census import counts_by_type, tracked_count, tracked_of

_ROOT = _source.ROOT
_CENSUS = _ROOT / "tests" / "_gc_census.py"


_TUPLES = 200_000
"""How many tuples are built while the objects are read (about a second here)."""


def test_reading_objects_leaves_tuples_being_built_alone() -> None:
    stop = threading.Event()
    reads = 0

    def read() -> None:
        nonlocal reads
        while not stop.is_set():
            counts_by_type()
            tracked_of(threading.Event)
            reads += 1

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        for _ in range(_TUPLES):
            tuple(x for x in range(200))
    finally:
        stop.set()
        reader.join()
    assert reads > 0


def test_the_census_finds_what_is_tracked() -> None:
    class Tracked:
        pass

    kept = [Tracked(), Tracked()]
    assert tracked_of(Tracked) == kept
    assert counts_by_type()[Tracked] == 2
    assert tracked_count() >= sum(counts_by_type().values()) - 100


def test_the_census_reads_past_a_proxy_whose_referent_has_died() -> None:
    # A proxy forwards __class__ to its referent, so isinstance() on one whose referent is gone
    # raises ReferenceError. Another test can leave such a proxy behind for the collector.
    class Referent:
        pass

    referent = Referent()
    dead = weakref.proxy(referent, lambda _: None)  # a callback makes the proxy tracked
    del referent
    kept = [Referent()]
    assert tracked_of(Referent) == kept
    assert type(dead) in counts_by_type()


def test_a_class_whose_metaclass_checks_instances_in_python_is_refused() -> None:
    from collections.abc import Sized

    with pytest.raises(TypeError, match="metaclass ABCMeta"):
        tracked_of(Sized)


def _reads_gc_objects(path: Path) -> list[int]:
    lines: list[int] = []
    for node in _source.walk(path):
        match node:
            case ast.Attribute(attr="get_objects", value=ast.Name(id="gc")):
                lines.append(node.lineno)
            case ast.ImportFrom(module="gc", names=names) if any(
                alias.name == "get_objects" for alias in names
            ):
                lines.append(node.lineno)
            case _:
                pass
    return lines


def test_only_the_census_reads_the_collectors_objects() -> None:
    sources = [*_source.files(_ROOT / "src"), *_source.files(_source.TESTS)]
    readers = [
        f"{path.relative_to(_ROOT)}:{line}"
        for path in sorted(sources)
        if path != _CENSUS
        for line in _reads_gc_objects(path)
    ]
    assert readers == []
