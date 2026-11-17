import socket
from dataclasses import replace

import pyfect as fx
from pyfect import exit as Exit
from pyfect import reactivity
from pyfect import schema as S
from pyfect.cluster import cluster_socket, runner_address
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity import Entity
from pyfect.cluster.sharding_config import ShardingConfigService
from pyfect.latch import Latch
from pyfect.rpc import make as make_rpc
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient


class Job(Entity, type="Job", rpc_annotations=fx.Context.make(Persisted, True)):
    run = make_rpc("Run", success=S.String)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def runner(
    termination_timeout: fx.duration.Input,
    work: fx.Effect[None],
    started: Latch,
    log: list[str],
):
    def run(_: object) -> fx.Effect[str]:
        job = fx.sync(started.open_unsafe).and_then(work)
        return job.and_then(fx.sync(lambda: log.append("job finished"))).as_("done")

    port = free_port()

    def settings(config: ShardingConfigService) -> ShardingConfigService:
        return replace(
            config,
            runner_address=runner_address.make("127.0.0.1", port),
            # How long a stopping runner waits for its entities (15 s by default).
            entity_termination_timeout=fx.duration.from_input_unsafe(termination_timeout),
        )

    # Each runner gets its own in-memory database for its messages and shard locks.
    sql = fx.layer.effect(
        SqlClient, sqlite.make(sqlite.SqliteClientConfig(filename=":memory:"))
    ).pipe(fx.layer.provide(reactivity.layer))
    return (
        Job.to_layer(Job.handlers().handle(Job.run)(run))
        .pipe(fx.layer.provide_merge(cluster_socket.layer(sharding_config=settings)))
        .pipe(fx.layer.provide(sql))
    )


@fx.fn
def stop_during_a_job(termination_timeout: fx.duration.Input, work: fx.Effect[None]):
    log: list[str] = []
    started = Latch()
    scope = yield from fx.scope.make()
    context = yield from runner(termination_timeout, work, started, log).build_with_scope(scope)
    make_client = yield from Job.client().pipe(fx.provide(context))
    yield from make_client("report").run().fork()
    yield from started.wait()

    # Stop the runner while the job runs.
    yield from scope.close(Exit.void)
    log.append("runner stopped")
    return log


@fx.fn
def program():
    # The runner drains: half a second of work finishes here before the shard is handed over.
    half_a_second = fx.sleep("500 millis")
    drained = yield from stop_during_a_job("5 seconds", half_a_second)
    assert drained == ["job finished", "runner stopped"]
    # With 0 it hands over at once: a job still running stops here, and its persisted
    # request runs again on the runner that takes the shard.
    handed_over = yield from stop_during_a_job(0, fx.never)
    assert handed_over == ["runner stopped"]


quiet = fx.provide_service(fx.MinimumLogLevel, fx.LogLevel.WARN)  # no "Listening on"
fx.run_main(program().pipe(quiet))
