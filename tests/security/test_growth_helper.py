"""``assert_near_linear`` tells a one-time step in cost per unit (an input outgrowing a CPU
cache between the two sizes) from growth that is superlinear at every size."""

from __future__ import annotations

import gc

import pytest

from . import _growth
from ._growth import MIN_SECONDS, Make, assert_near_linear, cpu, cpu_pair


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


def test_measuring_collects_only_the_young_generations(monkeypatch: pytest.MonkeyPatch) -> None:
    """A full collection walks the whole test process's heap: it was 90% of every parser case's
    time, and the collector is off while the work runs anyway."""
    generations: list[int] = []
    monkeypatch.setattr(gc, "collect", lambda generation=2: generations.append(generation) or 0)
    cpu(lambda: None)
    assert generations and max(generations) < 2


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
    slow = _growth.RUNS * 2  # the clock reads of one side's runs
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


_STRETCH = _growth.RUNS * 2  # as many clock reads as one side's runs take
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
