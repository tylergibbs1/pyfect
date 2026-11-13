"""A workload that only fails is stalled: errors are not progress.

The first 24-hour soak's HTTP workloads failed every operation (each one's timeout) for
its second hour without being reported stalled, because the check counted a failure
as progress.
"""

from __future__ import annotations

from pathlib import Path

from ._health import LiveFibers, Recorder
from ._sampler import Sampler


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_a_workload_that_only_fails_is_stalled(tmp_path: Path) -> None:
    clock = _Clock()
    failing = Recorder("failing", clock=clock)
    working = Recorder("working", clock=clock)
    sampler = Sampler(
        tmp_path / "run.jsonl",
        interval=60,
        stall_limit=10,
        recorders={"failing": failing, "working": working},
        fibers=LiveFibers(),
        clock=clock,
    )
    try:
        clock.now = 11
        failing.error("timed out")
        working.ok(0.001)
        assert sampler.sample().stalled == ["failing"]
    finally:
        sampler.close()
