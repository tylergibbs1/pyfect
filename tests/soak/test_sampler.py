"""A workload that only fails is stalled: errors are not progress.

The first 24-hour soak's HTTP workloads failed every operation (each one's timeout) for
its second hour without being reported stalled, because the check counted a failure
as progress.
"""

from __future__ import annotations

import time
from pathlib import Path

from ._health import LiveFibers, Recorder
from ._sampler import Sampler


def test_a_workload_that_only_fails_is_stalled(tmp_path: Path) -> None:
    failing, working = Recorder("failing"), Recorder("working")
    sampler = Sampler(
        tmp_path / "run.jsonl",
        interval=60,
        stall_limit=0.05,
        recorders={"failing": failing, "working": working},
        fibers=LiveFibers(),
    )
    time.sleep(0.1)
    failing.error("timed out")
    working.ok(0.001)
    assert sampler.sample().stalled == ["failing"]
    sampler.close()
