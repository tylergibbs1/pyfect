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
import time
from pathlib import Path

import pytest
from _gc_census import counts_by_type, tracked_count, tracked_of

_ROOT = Path(__file__).resolve().parent.parent
_CENSUS = _ROOT / "tests" / "_gc_census.py"


def test_reading_objects_leaves_tuples_being_built_alone() -> None:
    stop = threading.Event()

    def read() -> None:
        while not stop.is_set():
            counts_by_type()
            tracked_of(threading.Event)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            tuple(x for x in range(200))
    finally:
        stop.set()
        reader.join()


def test_the_census_finds_what_is_tracked() -> None:
    class Tracked:
        pass

    kept = [Tracked(), Tracked()]
    assert tracked_of(Tracked) == kept
    assert counts_by_type()[Tracked] == 2
    assert tracked_count() >= sum(counts_by_type().values()) - 100


def test_a_class_whose_metaclass_checks_instances_in_python_is_refused() -> None:
    from collections.abc import Sized

    with pytest.raises(TypeError, match="metaclass ABCMeta"):
        tracked_of(Sized)


def _reads_gc_objects(path: Path) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(ast.parse(path.read_text())):
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
    sources = [*(_ROOT / "src").rglob("*.py"), *(_ROOT / "tests").rglob("*.py")]
    readers = [
        f"{path.relative_to(_ROOT)}:{line}"
        for path in sorted(sources)
        if path != _CENSUS
        for line in _reads_gc_objects(path)
    ]
    assert readers == []
