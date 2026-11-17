"""The sharding tests' shared config (``oracle/_sharding_fixtures.make_config``)
doesn't make the runner sync loop spin.

Effect's tests refresh assignments every 0 ms. Effect's ``TestClock`` returns at
once from a zero sleep, so the sync loop never parks: it re-reads the runners
for as long as a test runs. In JavaScript that costs little. In Python, the
2048 operations it runs on each scheduler turn made a test that moves the
clock 8 s (``test_defects_durable_messages_when_no_entity_ever_registers``)
take 1.4 s of real time on an idle machine and exceed its 5 s timeout in CI.
"""

from typing import Any

import pytest
from oracle._sharding_fixtures import make_config

import pyfect as fx
from pyfect import testing
from pyfect.cluster import message_storage, runner_health, runner_storage, runners, sharding
from pyfect.cluster.sharding import _runners_sync
from pyfect.scope import scoped


@testing.effect
def test_the_sync_loop_parks_between_reads(monkeypatch: pytest.MonkeyPatch):
    reads = [0]
    observe = _runners_sync._Membership.observe  # pyright: ignore[reportPrivateUsage]

    def counted(self: Any, found: Any) -> None:
        reads[0] += 1
        observe(self, found)

    monkeypatch.setattr(_runners_sync._Membership, "observe", counted)  # pyright: ignore[reportPrivateUsage]
    runner = (
        sharding.layer.pipe(fx.layer.provide(runner_storage.layer_memory))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(fx.layer.provide(message_storage.layer_memory))
        .pipe(fx.layer.provide(make_config()))
    )
    fiber = yield from scoped(fx.never.pipe(fx.provide(runner))).fork(start_immediately=True)
    yield from testing.adjust("8 seconds")
    yield from fiber.interrupt()
    # One read per refresh interval, give or take the first.
    assert reads[0] <= 8000 // 50 + 2, reads[0]
