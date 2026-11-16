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

Two CPU times are compared only as ``_growth.cpu_pair`` measures them (in turn, so a slow
stretch falls on both), the cheaper one floored (``max(plain, 0.001)``), and never added to
or subtracted from each other: ``far - walk < 3 * near``, three separate millisecond
measurements, failed under load whenever ``walk`` came out quicker than the walk inside
``far``. Count the work instead when it can be counted.
"""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Iterable

import _source
from _inventory import parse

TESTS = _source.TESTS

_TIMERS = frozenset({"cpu", "cpu_pair"})
_TESTS_THE_HELPER = frozenset({"test_growth_checks.py"})
"""Checks of ``_growth`` itself, which compare its timings on a fake clock."""

_CLOCKS = frozenset(
    f"{name}{suffix}"
    for name in ("perf_counter", "monotonic", "thread_time", "process_time")
    for suffix in ("", "_ns")
)

_HELPERS = frozenset({"_growth.py", "_timing.py"})

TIMED_IO = TESTS / "_timed_io.txt"
"""``path reads  # reason`` per line (``tests/_inventory.py``): a file that still reads the
clock itself, how many reads it has, and what real time it measures."""


def _clock_reads(nodes: Iterable[ast.AST]) -> int:
    reads = 0
    for node in nodes:
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
    for path in _source.files(TESTS):
        name = path.relative_to(TESTS).as_posix()
        if name not in _HELPERS:
            reads[name] = _clock_reads(_source.walk(path))
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
    assert _clock_reads(ast.walk(_source.parse(source))) == 4


def _timings(scope: ast.AST) -> dict[str, int]:
    """Each name bound to a ``cpu`` or ``cpu_pair`` result, by the call that measured it."""
    found: dict[str, int] = {}
    for node in ast.walk(scope):
        if not (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id in _TIMERS
        ):
            continue
        for target in node.targets:
            names = target.elts if isinstance(target, ast.Tuple) else [target]
            found.update({name.id: id(node) for name in names if isinstance(name, ast.Name)})
    return found


def _measured(node: ast.AST, timings: dict[str, int]) -> list[int]:
    """The measurements an expression reads: named results and inline ``cpu`` calls."""
    return [
        timings[part.id] if isinstance(part, ast.Name) and part.id in timings else id(part)
        for part in ast.walk(node)
        if (isinstance(part, ast.Name) and part.id in timings)
        or (
            isinstance(part, ast.Call)
            and isinstance(part.func, ast.Name)
            and part.func.id in _TIMERS
        )
    ]


def _floored(node: ast.AST, timings: dict[str, int]) -> bool:
    """``max(t, floor)``: a timing too quick to measure counts as ``floor``."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "max"
        and len(node.args) == 2
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id in timings
        and isinstance(node.args[1], ast.Constant)
        and isinstance(node.args[1].value, float | int)
        and node.args[1].value > 0
    )


def _unfloored(node: ast.AST, timings: dict[str, int]) -> bool:
    return any(
        isinstance(part, ast.Name) and part.id in timings for part in ast.walk(node)
    ) and not any(_floored(part, timings) for part in ast.walk(node))


def _timing_comparisons(tree: ast.Module) -> list[str]:
    """Lines that combine CPU times other than as one ``cpu_pair`` with a floored side."""
    timings = _timings(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.BinOp)
            and _measured(node.left, timings)
            and _measured(node.right, timings)
        ):
            found.append(f"{node.lineno}: adds or subtracts timings")
        elif isinstance(node, ast.Compare):
            sides = [side for side in (node.left, *node.comparators) if _measured(side, timings)]
            if len(sides) < 2:
                continue
            calls = {call for side in sides for call in _measured(side, timings)}
            if len(calls) > 1:
                found.append(f"{node.lineno}: compares timings not measured by one cpu_pair")
            elif all(_unfloored(side, timings) for side in sides):
                found.append(f"{node.lineno}: compares timings without flooring one")
    return found


def test_timings_are_compared_only_in_pairs_with_a_floor() -> None:
    found = {
        path.relative_to(TESTS).as_posix(): lines
        for path in _source.files(TESTS, "test_*.py")
        if path.name not in _TESTS_THE_HELPER and (lines := _timing_comparisons(_source.tree(path)))
    }
    assert found == {}, "measure both with cpu_pair, floor the cheaper one, or count the work"


def test_the_guard_sees_a_ratio_of_separate_timings() -> None:
    assert sorted(
        _timing_comparisons(
            _source.parse(
                "near = cpu(a)\nfar = cpu(b)\nwalk = cpu(c)\nassert far - walk < 3 * near\n"
            )
        )
    ) == ["4: adds or subtracts timings", "4: compares timings not measured by one cpu_pair"]
    assert _timing_comparisons(_source.parse("assert cpu(a) < 3 * max(cpu(b), 0.001)\n")) == [
        "1: compares timings not measured by one cpu_pair"
    ]
    assert _timing_comparisons(_source.parse("a, b = cpu_pair(x, y)\nassert a < 3 * b\n")) == [
        "2: compares timings without flooring one"
    ]
    assert (
        _timing_comparisons(_source.parse("a, b = cpu_pair(x, y)\nassert a < 3 * max(b, 0.001)\n"))
        == []
    )
    assert _timing_comparisons(_source.parse("assert cpu(a) < 0.25\n")) == []
