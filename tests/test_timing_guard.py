"""Tests read the clock only through ``tests/_growth.py`` and ``tests/_timing.py``.

A test that times work with the wall clock fails when the machine is busy:
``tests/test_persistent_collections.py`` compared ``perf_counter`` times of two sizes and
failed up to half its runs under pytest-xdist on a loaded machine, and fixed limits on
pure computation (``test_glob``, ``test_multipart_boundary``, ``test_channel_io``,
``test_find_my_way``) did the same on slow CI runners. ``_growth.assert_near_linear``
measures growth in thread CPU time; ``_timing.wait_until`` waits for another thread as a hang
detector. Timing a test checks goes through the ``TestClock``.

``tests/_timed_io.txt`` lists files that still read the clock themselves, with how many reads each
has: real servers, databases and subprocesses timed against their own timeouts, and growth
checks not yet measured through ``_growth``. A file leaves the list when its reads go; a
count that grows, or a new file, fails here, and so does an entry without a reason.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from _inventory import parse

TESTS = Path(__file__).resolve().parent

_CLOCKS = frozenset(
    f"{name}{suffix}"
    for name in ("perf_counter", "monotonic", "thread_time", "process_time")
    for suffix in ("", "_ns")
)

_HELPERS = frozenset({"_growth.py", "_timing.py"})

TIMED_IO = TESTS / "_timed_io.txt"
"""``path reads  # reason`` per line (``tests/_inventory.py``): a file that still reads the
clock itself, how many reads it has, and what real time it measures."""


def _clock_reads(source: str) -> int:
    reads = 0
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in _CLOCKS
            and isinstance(node.value, ast.Name)
            and node.value.id == "time"
        ):
            reads += 1
        elif isinstance(node, ast.ImportFrom) and node.module == "time":
            reads += sum(alias.name in _CLOCKS for alias in node.names)
    return reads


def _reads_by_file() -> Counter[str]:
    reads: Counter[str] = Counter()
    for path in sorted(TESTS.rglob("*.py")):
        name = path.relative_to(TESTS).as_posix()
        if name not in _HELPERS:
            reads[name] = _clock_reads(path.read_text())
    return +reads


def test_tests_read_the_clock_through_the_timing_helpers() -> None:
    listed = {path: int(entry.value) for path, entry in parse(TIMED_IO.read_text()).items()}
    assert dict(_reads_by_file()) == listed, (
        "time work with _growth.assert_near_linear, wait for threads with _timing.wait_until, "
        "and check timing with the TestClock"
    )


def test_the_guard_sees_every_way_to_read_the_clock() -> None:
    source = (
        "import time\nfrom time import perf_counter, sleep\n"
        "a = time.monotonic()\nb = time.perf_counter_ns()\nc = perf_counter()\n"
        "d = time.thread_time()\ntime.sleep(1)\nclock.monotonic()\n"
    )
    # The import of perf_counter counts once, the call through it not again.
    assert _clock_reads(source) == 4
