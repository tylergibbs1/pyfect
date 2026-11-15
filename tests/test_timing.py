"""``_timing.assert_scales`` tells linear work from quadratic work whatever else the
machine is doing: time the measuring thread spends off the CPU is not counted."""

from __future__ import annotations

import time
from collections.abc import Callable

import pytest
from _timing import assert_scales


def _busy(units: int) -> None:
    total = 0
    for i in range(units):
        total += i
    del total


def _linear(n: int) -> Callable[[], object]:
    return lambda: _busy(n)


def _quadratic(n: int) -> Callable[[], object]:
    return lambda: _busy(n * n // 2000)


def test_linear_work_passes() -> None:
    assert_scales(_linear, 500_000)


def test_quadratic_work_fails() -> None:
    with pytest.raises(AssertionError, match="grows faster than size\\*\\*1"):
        assert_scales(_quadratic, 20_000)


def test_quadratic_work_passes_as_degree_two() -> None:
    assert_scales(_quadratic, 20_000, degree=2)


def test_time_off_the_cpu_is_not_counted() -> None:
    """A loaded machine takes the CPU from the measuring thread: here the larger run
    waits 0.2 s on top of its linear work, as a descheduled thread would."""

    def preempted(n: int) -> Callable[[], object]:
        def work() -> None:
            _busy(n)
            if n > 500_000:
                time.sleep(0.2)

        return work

    assert_scales(preempted, 500_000)
