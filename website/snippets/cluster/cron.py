from dataclasses import replace
from datetime import datetime

import pyfect as fx
from pyfect import cron, reactivity
from pyfect.cluster import cluster_cron, single_runner, singleton
from pyfect.cluster.sharding_config import ShardingConfigService
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient

runs: list[datetime] = []
two_runs = fx.Deferred[None]()


# A singleton runs on exactly one runner, the one holding its shard, and moves
# with the shard when that runner leaves.
leader = singleton.make("leader", fx.sync(lambda: print("leader elected")))


@fx.gen
def tick():
    scheduled = yield from cluster_cron.CurrentScheduledTime()
    runs.append(scheduled)
    if len(runs) == 2:
        yield from two_runs.succeed(None)


# A cron job runs once per instant across the whole cluster: each run is a
# persisted message, delivered at its time, that schedules the next one.
every_second = cluster_cron.make(
    name="tick", cron=cron.parse_unsafe("* * * * * *", "UTC"), execute=tick
)


@fx.gen
def program():
    yield from two_runs.wait()
    yield from fx.sleep("500 millis")  # let the second run schedule the third before shutting down
    print("on whole seconds:", all(run.microsecond == 0 for run in runs))
    print("seconds apart:", (runs[1] - runs[0]).total_seconds())


def settings(config: ShardingConfigService) -> ShardingConfigService:
    # Storage is checked for messages that are due every 10 seconds by default.
    return replace(config, entity_message_poll_interval=fx.duration.Seconds(0.1))


# `single_runner.layer` is one runner with its messages in SQL, here in-memory SQLite.
sql = fx.layer.effect(SqlClient, sqlite.make(sqlite.SqliteClientConfig(filename=":memory:")))
runner = single_runner.layer(sharding_config=settings, runner_storage_kind="memory").pipe(
    fx.layer.provide_merge(sql.pipe(fx.layer.provide(reactivity.layer)))
)
jobs = fx.layer.merge(leader, every_second).pipe(fx.layer.provide_merge(runner))
fx.run_main(program.pipe(fx.provide(jobs)))
