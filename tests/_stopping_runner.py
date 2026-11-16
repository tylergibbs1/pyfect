"""A runner that stops while an entity's request runs, with `RunnerStorage sync` running
every 50 ms, so `test_doc_snippets.py`'s delayed drain overlaps several syncs."""

from dataclasses import replace

import pyfect as fx
from pyfect import reactivity
from pyfect import schema as S
from pyfect.cluster import single_runner
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity import Entity
from pyfect.cluster.sharding_config import ShardingConfigService
from pyfect.latch import Latch
from pyfect.rpc import make as make_rpc
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient


class Job(Entity, type="Job", rpc_annotations=fx.Context.make(Persisted, True)):
    run = make_rpc("Run", success=S.String)


started = Latch()


def settings(config: ShardingConfigService) -> ShardingConfigService:
    return replace(
        config,
        refresh_assignments_interval=fx.duration.millis(50),
        entity_termination_timeout=fx.duration.millis(0),
    )


sql = fx.layer.effect(SqlClient, sqlite.make(sqlite.SqliteClientConfig(filename=":memory:")))
runner = single_runner.layer(sharding_config=settings, runner_storage_kind="memory").pipe(
    fx.layer.provide_merge(sql.pipe(fx.layer.provide(reactivity.layer)))
)
jobs = Job.to_layer(
    Job.handlers().handle(Job.run)(lambda _: fx.sync(started.open_unsafe).and_then(fx.never))
).pipe(fx.layer.provide_merge(runner))


@fx.gen
def program():
    make_client = yield from Job.client()
    yield from make_client("job").run().fork()
    yield from started.wait()
    print("stopping")


fx.run_main(program.pipe(fx.provide(jobs)))
