"""A check that work grows linearly, or stays cheap, measures the work, never the wall clock;
and ``tests/_growth.py`` tells linear from superlinear work whatever else the machine is doing,
and a one-time step in cost per unit (an input outgrowing a CPU cache between the two sizes)
from growth that is superlinear at every size.

Wall-clock time counts every moment the test waited for a CPU, so on a loaded machine a
linear call looks quadratic. ``tests/_growth.py`` measures the thread's CPU time; a test
that counts its work (visits, steps) needs no clock at all.
"""

from __future__ import annotations

import ast
import functools
import gc
import re
import threading
import time
from pathlib import Path

import _source
import pytest
from _growth import MIN_SECONDS, RUNS, Make, Work, assert_near_linear, cpu, cpu_pair

_TESTS = _source.TESTS
_GROWTH_NAME = re.compile(r"linear|quadratic|backtrack|exponential|cheap")
_WALL_CLOCKS = frozenset({"perf_counter", "perf_counter_ns", "monotonic", "monotonic_ns", "time"})
_CPU_CLOCKS = frozenset({"thread_time", "thread_time_ns", "process_time", "process_time_ns"})
_OWNED_ELSEWHERE = frozenset({"test_persistent_collections.py"})
"""Files another change is converting."""


def _time_calls(tree: ast.AST) -> set[str]:
    """The ``time`` module's clocks a module reads (``time.x`` or ``from time import x``).
    ``clock=time.process_time``, handed to ``tests/_growth.py``, is not a read."""
    handed = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword) and node.arg == "clock"
    }
    used: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in handed and isinstance(node, ast.Attribute) and node.attr == "process_time":
            continue
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "time"
        ):
            used.add(node.attr)
        elif isinstance(node, ast.ImportFrom) and node.module == "time":
            used.update(alias.name for alias in node.names)
    return used


def _growth_tests(tree: ast.Module) -> list[str]:
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name.startswith("test_")
        and _GROWTH_NAME.search(node.name)
    ]


@functools.cache
def _modules() -> tuple[tuple[str, ast.Module], ...]:
    """The test modules that mention ``time`` at all, parsed."""
    return tuple(
        (path.relative_to(_TESTS).as_posix(), _source.tree(path))
        for path in _source.files(_TESTS)
        if path.name not in _OWNED_ELSEWHERE and "time" in _source.text(path)
    )


def test_growth_checks_read_no_wall_clock() -> None:
    offenders = {
        name: sorted(_time_calls(tree) & _WALL_CLOCKS)
        for name, tree in _modules()
        if _growth_tests(tree) and _time_calls(tree) & _WALL_CLOCKS
    }
    assert offenders == {}, "measure the work with tests/_growth.py, or count it"


def test_tests_read_cpu_time_only_through_the_growth_helper() -> None:
    readers = [
        name
        for name, tree in _modules()
        if Path(name).name.startswith("test_") and _time_calls(tree) & _CPU_CLOCKS
    ]
    assert readers == [], "use tests/_growth.py (both sizes in turn, the least of each)"


def test_the_guard_sees_a_wall_clock_growth_check() -> None:
    tree = _source.parse(
        "import time\n"
        "def test_parse_is_linear():\n"
        "    start = time.perf_counter()\n"
        "    assert time.perf_counter() - start < 1\n"
    )
    assert _growth_tests(tree) == ["test_parse_is_linear"]
    assert _time_calls(tree) & _WALL_CLOCKS == {"perf_counter"}


def test_the_guard_lets_a_growth_check_hand_the_helper_process_time() -> None:
    tree = _source.parse(
        "import time\n"
        "def test_parse_is_linear():\n"
        "    assert_near_linear(make, 8, clock=time.process_time)\n"
    )
    assert _time_calls(tree) == set()
    assert _time_calls(_source.parse("import time\nstart = time.process_time()\n")) == {
        "process_time"
    }


def _units_for(seconds: float) -> int:
    """About how many ``sum(range(n))`` units take ``seconds`` of CPU here."""
    probe = 1_000_000
    return max(1, int(probe * seconds / max(cpu(lambda: sum(range(probe))), 1e-6)))


def _base() -> int:
    return _units_for(MIN_SECONDS * 1.5)


def _no_doubling(size: int) -> int:
    # growth() doubles the size while it can; a cap one below twice FACTOR keeps it at ``size``.
    return size * 16 - 1


def test_a_cost_step_between_the_two_sizes_is_not_superlinear() -> None:
    base = _base()
    step_at = base * 2  # between the small size and the large one, as a cache size would be

    def make(n: int):
        units = n if n < step_at else 4 * n  # each unit costs 4 times more past the step
        return lambda: sum(range(units))

    assert_near_linear(make, base, _no_doubling(base))


def test_quadratic_work_still_fails() -> None:
    base = _base()
    make: Make = lambda n: lambda: sum(range(n * n // base))  # noqa: E731
    with pytest.raises(AssertionError, match="superlinear"):
        assert_near_linear(make, base, _no_doubling(base))


def test_linear_work_passes() -> None:
    base = _base()
    make: Make = lambda n: lambda: sum(range(n))  # noqa: E731
    assert_near_linear(make, base, _no_doubling(base))


def test_time_off_the_cpu_is_not_counted() -> None:
    """A loaded machine takes the CPU from the measuring thread: here each run also waits
    off the CPU, longer the larger the run (quadratically), as a thread descheduled more
    and more would. Its CPU time stays linear; with ``perf_counter`` this fails (25.6x,
    then 3.5x on the recheck)."""
    base = _base()

    def preempted(n: int) -> Work:
        def work() -> None:
            sum(range(n))
            time.sleep(0.2 * (n / (8 * base)) ** 2)

        return work

    assert_near_linear(preempted, base, _no_doubling(base))


def test_measuring_collects_only_the_young_generations(monkeypatch: pytest.MonkeyPatch) -> None:
    """A full collection walks the whole test process's heap: it was 90% of every parser case's
    time, and the collector is off while the work runs anyway."""
    generations: list[int] = []
    monkeypatch.setattr(gc, "collect", lambda generation=2: generations.append(generation) or 0)
    cpu(lambda: None)
    base = _base()
    assert_near_linear(lambda n: lambda: sum(range(n)), base, _no_doubling(base))
    assert generations and max(generations) < 2


def test_process_time_sees_work_on_another_thread() -> None:
    """Work that can move to other threads: ``thread_time`` counts only the calling thread,
    so quadratic work done on another one looks cheap; ``clock=time.process_time`` sees it."""
    base = _base()

    def make(n: int) -> Work:
        def work() -> None:
            thread = threading.Thread(target=lambda: sum(range(n * n // base)))
            thread.start()
            thread.join()

        return work

    assert_near_linear(make, base, _no_doubling(base))
    with pytest.raises(AssertionError, match="superlinear"):
        assert_near_linear(make, base, _no_doubling(base), clock=time.process_time)


class _SlowingClock:
    """A thread clock under which work runs ``factor`` times slower for its first ``reads``."""

    def __init__(self, reads: int, factor: float) -> None:
        self.now, self.reads_left, self.factor = 0.0, reads, factor

    def __call__(self) -> float:
        self.reads_left -= 1
        return self.now

    def work(self, seconds: float):
        def run() -> None:
            self.now += seconds * (self.factor if self.reads_left > 0 else 1)

        return run


def test_a_slow_stretch_falls_on_both_sides_of_a_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Measured one after the other, a slow stretch during the first inflates the ratio; run in
    turn, each side keeps a run outside the stretch."""
    slow = RUNS * 2  # the clock reads of one side's runs
    clock = _SlowingClock(reads=slow, factor=3)
    costly, plain = clock.work(0.0012), clock.work(0.001)
    assert cpu(costly, clock=clock) / cpu(plain, clock=clock) == pytest.approx(3.6)
    clock.reads_left = slow
    first, second = cpu_pair(costly, plain, clock=clock)
    assert first / second == pytest.approx(1.2)


class _StretchClock:
    """A thread clock under which work runs ``factor`` times slower when it starts within
    ``length`` reads from read ``start``: a stretch in which the machine runs slower."""

    def __init__(self, start: int, length: int, factor: float) -> None:
        self.now, self.reads, self.start, self.length = 0.0, 0, start, length
        self.factor = factor

    def __call__(self) -> float:
        self.reads += 1
        return self.now

    def work(self, seconds: float):
        def run() -> None:
            slow = self.start <= self.reads - 1 < self.start + self.length
            self.now += seconds * (self.factor if slow else 1)

        return run


_STRETCH = RUNS * 2  # as many clock reads as one side's runs take
_READS = 40  # more than one assert_near_linear call makes here


@pytest.mark.parametrize("start", range(_READS))
def test_a_slow_stretch_anywhere_does_not_hide_quadratic_work(start: int) -> None:
    clock = _StretchClock(start, _STRETCH, factor=3)
    base = 1000
    make: Make = lambda n: clock.work(0.003 * (n / base) ** 2)  # noqa: E731
    with pytest.raises(AssertionError, match="superlinear"):
        assert_near_linear(make, base, _no_doubling(base), clock=clock)


@pytest.mark.parametrize("start", range(_READS))
def test_a_slow_stretch_anywhere_does_not_fail_linear_work(start: int) -> None:
    clock = _StretchClock(start, _STRETCH, factor=3)
    base = 1000
    make: Make = lambda n: clock.work(0.003 * n / base)  # noqa: E731
    assert_near_linear(make, base, _no_doubling(base), clock=clock)
