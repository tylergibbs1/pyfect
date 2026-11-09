import socket
import tempfile
from dataclasses import replace
from pathlib import Path

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


def runner(database: Path, termination_timeout: float, started: Latch, log: list[str]):
    def run(_: object) -> fx.Effect[str]:
        work = fx.sync(started.open_unsafe).and_then(
            fx.sleep("500 millis")
        )  # half a second of work
        return work.and_then(fx.sync(lambda: log.append("job finished"))).as_("done")

    port = free_port()

    def settings(config: ShardingConfigService) -> ShardingConfigService:
        return replace(
            config,
            runner_address=runner_address.make("127.0.0.1", port),
            # How long a stopping runner waits for its entities (15 s by default).
            entity_termination_timeout=fx.duration.Seconds(termination_timeout),
        )

    sql = fx.layer.effect(
        SqlClient, sqlite.make(sqlite.SqliteClientConfig(filename=str(database)))
    ).pipe(fx.layer.provide(reactivity.layer))
    return (
        Job.to_layer(Job.handlers().handle(Job.run)(run))
        .pipe(fx.layer.provide_merge(cluster_socket.layer(sharding_config=settings)))
        .pipe(fx.layer.provide(sql))
    )


@fx.fn
def stop_during_a_job(database: Path, termination_timeout: float):
    log: list[str] = []
    started = Latch()
    scope = yield from fx.scope.make()
    context = yield from runner(database, termination_timeout, started, log).build_with_scope(scope)
    make_client = yield from Job.client().pipe(fx.provide(context))
    yield from make_client("report").run().fork()
    yield from started.wait()

    # Stop the runner while the job runs.
    yield from scope.close(Exit.void)
    log.append("runner stopped")
    return log


@fx.fn
def program(directory: Path):
    # The runner drains: the job finishes here before the shard is handed over.
    drained = yield from stop_during_a_job(directory / "drain.db", 5)
    assert drained == ["job finished", "runner stopped"]
    # With 0 it hands over at once: the job stops here, and its persisted
    # request runs again on the runner that takes the shard.
    handed_over = yield from stop_during_a_job(directory / "handover.db", 0)
    assert handed_over == ["runner stopped"]


with tempfile.TemporaryDirectory() as directory:
    quiet = fx.provide_service(fx.MinimumLogLevel, fx.LogLevel.WARN)  # no "Listening on"
    fx.run_main(program(Path(directory)).pipe(quiet))
