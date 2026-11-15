"""How tests measure time, so a loaded machine cannot fail them.

A test that times work against the wall clock fails when the machine is busy: other
processes (pytest-xdist workers, other jobs on the runner) take the CPU and the time
counted grows with them. Every clock read in ``tests/`` goes through here
(``tests/test_timing_guard.py``):

- ``assert_scales`` (``scaling_problem``) checks how work grows with its input (linear,
  not quadratic) by the ratio of two sizes' thread CPU time. Time spent waiting for the
  CPU is not counted.
- ``wait_until`` polls for something another thread does, failing only once a hang is
  certain. It is a hang detector, never a speed check.

Timing that is part of what a test checks (a timeout firing, a retry spacing) uses the
``TestClock``.
"""

from __future__ import annotations

import gc
import time
from collections.abc import Callable

HANG_SECONDS = 30.0
"""How long ``wait_until`` polls before it calls a wait a hang, well under the 60 s
per-test alarm (``tests/_timeout.py``)."""

_RUNS = 3
_FLOOR_SECONDS = 0.005
"""Below this a run is too short to measure; work that cheap at the larger size is
cheap enough, whatever its shape."""

type Work = Callable[[int], Callable[[], object]]
"""Given a size, the work to measure at that size (built outside the measurement)."""


def _cpu_seconds(work: Callable[[], object]) -> float:
    """The least thread CPU time of a few runs, with the collector off: a collection's
    cost depends on everything else alive, not on the work."""
    best = float("inf")
    for _ in range(_RUNS):
        enabled = gc.isenabled()
        gc.disable()
        try:
            start = time.thread_time()
            work()
            best = min(best, time.thread_time() - start)
        finally:
            if enabled:
                gc.enable()
    return best


def scaling_problem(make: Work, size: int, *, factor: int = 4, degree: int = 1) -> str | None:
    """Why ``make``'s work grows faster than ``size ** degree``, or ``None``.

    The work at ``factor * size`` may take up to ``factor ** (degree + 0.5)`` times the
    work at ``size``: halfway (geometrically) between the expected growth and the next
    degree's. With the default ``factor`` 4 and ``degree`` 1, linear work takes four
    times as long, the limit is eight, and quadratic work takes sixteen.
    """
    small = _cpu_seconds(make(size))
    large = _cpu_seconds(make(factor * size))
    limit = factor ** (degree + 0.5)
    if large < _FLOOR_SECONDS or large < limit * small:
        return None
    return (
        f"{small * 1000:.1f} ms of CPU at size {size}, {large * 1000:.1f} ms at "
        f"{factor}x: more than {limit:.1f}x, so it grows faster than size**{degree}"
    )


def assert_scales(make: Work, size: int, *, factor: int = 4, degree: int = 1) -> None:
    """Assert ``make``'s work grows like ``size ** degree`` (see ``scaling_problem``)."""
    problem = scaling_problem(make, size, factor=factor, degree=degree)
    assert problem is None, problem


def wait_until(ready: Callable[[], bool], *, what: str, poll: float = 0.001) -> None:
    """Poll ``ready`` until it is true; fail as hung after ``HANG_SECONDS``."""
    deadline = time.monotonic() + HANG_SECONDS
    while not ready():
        assert time.monotonic() < deadline, f"hung: waited {HANG_SECONDS:g}s for {what}"
        time.sleep(poll)
