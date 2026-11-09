"""A cluster cron run scheduled longer than ``skip_if_older_than`` ago is
skipped, and the chain moves on to the next instant (expected value from
Effect's ``ClusterCron`` under Node, with the same deploys)."""

from __future__ import annotations

from oracle.test_cluster_cron import EVERY_SECOND, deploy

import pyfect as fx
from pyfect import testing
from pyfect.cluster import cluster_cron, message_storage
from pyfect.date_time import format_iso


@testing.effect
def test_runs_older_than_skip_if_older_than_are_skipped():
    scheduled: list[str] = []

    @fx.gen
    def execute():
        scheduled.append(format_iso((yield from cluster_cron.CurrentScheduledTime())))

    cron = cluster_cron.make(
        name="test",
        cron=EVERY_SECOND,
        calculate_next_run_from_previous=True,
        skip_if_older_than="1500 millis",
        execute=execute,
    )

    @fx.gen
    def body():
        yield from deploy(cron, 1500)
        # The pending run at 2 s falls behind while no runner is up.
        yield from testing.adjust("5 seconds")
        scheduled.clear()
        yield from deploy(cron, 3000)
        # At 6.5 s the runs at 2, 3 and 4 s are older than 1.5 s.
        assert scheduled == [f"1970-01-01T00:00:0{s}.000Z" for s in range(5, 10)]

    yield from body.pipe(fx.provide(message_storage.memory_driver_layer))
