"""Two runners built with ``cluster_socket.layer`` over localhost TCP, and
with ``cluster_http.layer`` over HTTP and WebSockets, each with its own
SQLite connection to one shared database file: a message sent from one
runner reaches an entity the other owns, and a durable workflow suspended
on a runner that is stopped resumes on the restarted cluster with its
completed activity replayed, not rerun."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal, TypedDict

import _ports
import pytest

import pyfect as fx
from pyfect import reactivity, testing
from pyfect import schema as S
from pyfect.cluster import cluster_http, cluster_socket, cluster_workflow_engine, runner_address
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity import CurrentRunnerAddress, Entity
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.sharding import Sharding, ShardingService
from pyfect.cluster.sharding_config import ShardingConfigService
from pyfect.context import Context
from pyfect.layer import Layer
from pyfect.rpc import make as make_rpc
from pyfect.scope import CloseableScope, Scope
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient
from pyfect.workflow import Complete, Suspended, activity, durable_deferred, workflow
from pyfect.workflow.workflow_engine import WorkflowEngine

HOST = "127.0.0.1"
SHARDS = 12


class Where(Entity, type="E2EWhere", rpc_annotations=Context.make(Persisted, True)):
    where = make_rpc("Where", success=S.String)


@fx.gen
def _where_handlers():
    address = yield from CurrentRunnerAddress()
    return Where.handlers().handle(Where.where)(
        lambda _: fx.succeed(f"{address.host}:{address.port}")
    )


class IdPayload(TypedDict):
    id: str


Gate = durable_deferred.make("E2EGate", success=S.String)
Resumable = workflow.make(
    "E2EResumable",
    payload=S.Struct(IdPayload),
    success=S.String,
    idempotency_key=lambda payload: payload["id"],
)
activity_runs: dict[str, int] = {}


def _resumable(payload: IdPayload, _execution_id: str) -> Any:
    def count() -> None:
        activity_runs[payload["id"]] = activity_runs.get(payload["id"], 0) + 1

    @fx.gen
    def run():
        yield from activity.make(name="BeforeSuspension", execute=fx.sync(count))
        return (yield from Gate.wait())

    return run


entities: Layer[Any, Any, Any] = fx.layer.merge(
    Where.to_layer_effect(_where_handlers), Resumable.to_layer(_resumable)
).pipe(fx.layer.provide_merge(cluster_workflow_engine.layer))


def _settings(port: int):
    def update(config: ShardingConfigService) -> ShardingConfigService:
        return replace(
            config,
            runner_address=runner_address.make(HOST, port),
            shards_per_group=SHARDS,
            entity_message_poll_interval=fx.duration.seconds(0.5),
            refresh_assignments_interval=fx.duration.seconds(0.15),
            shard_lock_expiration=fx.duration.seconds(1.75),
            shard_lock_refresh_interval=fx.duration.seconds(0.5),
            entity_termination_timeout=fx.duration.seconds(0),
        )

    return update


type Transport = Literal["socket", "http", "websocket"]


def _cluster(transport: Transport, port: int) -> Layer[Any, Any, SqlClient]:
    if transport == "socket":
        return cluster_socket.layer(sharding_config=_settings(port))
    return cluster_http.layer(transport=transport, sharding_config=_settings(port))


def _runner(transport: Transport, database: Path, port: int) -> Layer[Any, Any, Any]:
    sql = fx.layer.effect(
        SqlClient, sqlite.make(sqlite.SqliteClientConfig(filename=str(database)))
    ).pipe(fx.layer.provide(reactivity.layer))
    return entities.pipe(fx.layer.provide_merge(_cluster(transport, port))).pipe(
        fx.layer.provide(sql)
    )


class Runner:
    def __init__(self, port: int, scope: CloseableScope, context: Context[Any]) -> None:
        self.port = port
        self.scope = scope
        self.context = context
        self.sharding: ShardingService = context.get_unsafe(Sharding)

    @property
    def address(self) -> RunnerAddress:
        return runner_address.make(HOST, self.port)


def _start(transport: Transport, database: Path, port: int) -> fx.Effect[Runner, Any, Scope]:
    @fx.gen
    def start():
        parent = yield from Scope()
        scope = yield from parent.fork()
        context = yield from _runner(transport, database, port).build_with_scope(scope)
        return Runner(port, scope, context)

    return start


def _owns_some(runner: Runner) -> bool:
    return any(
        runner.sharding.has_shard_id(
            runner.sharding.get_shard_id(EntityId(f"probe-{i}"), "default")
        )
        for i in range(200)
    )


def _owner(runners: list[Runner], entity_id: str) -> Runner | None:
    for runner in runners:
        shard = runner.sharding.get_shard_id(EntityId(entity_id), "default")
        if runner.sharding.has_shard_id(shard):
            return runner
    return None


def _all_shards_owned(runners: list[Runner]) -> bool:
    return all(_owner(runners, f"probe-{i}") is not None for i in range(200)) and all(
        _owns_some(runner) for runner in runners
    )


def _until(condition: Any, timeout: float = 20) -> fx.Effect[None, Any]:
    @fx.gen
    def wait():
        for _ in range(int(timeout / 0.1)):
            if (yield from condition()):
                return
            yield from fx.sleep("100 millis")
        raise AssertionError("condition not met before the deadline")

    return wait


@pytest.mark.parametrize("transport", ["socket", "http", "websocket"])
@testing.live(timeout="2 minutes")
def test_two_runners_share_sqlite_storage_route_and_resume_workflows(
    tmp_path: Path, transport: Transport
):
    database = tmp_path / "cluster.db"
    ports = [_ports.reserved_port(HOST), _ports.reserved_port(HOST)]

    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        first = yield from _start(transport, database, ports[0])
        second = yield from _start(transport, database, ports[1])
        runners = [first, second]
        yield from _until(lambda: fx.sync(lambda: _all_shards_owned(runners)))

        # A message sent from the first runner reaches an entity on the second.
        entity_id = next(
            f"where-{i}" for i in range(1000) if _owner(runners, f"where-{i}") is second
        )
        make_client = yield from Where.client().pipe(fx.provide(first.context))
        where = yield from make_client(entity_id).where()
        assert where == f"{HOST}:{second.port}"

        # A workflow suspends on its owner.
        engine = first.context.get_unsafe(WorkflowEngine)
        with_engine = fx.provide_service(WorkflowEngine, engine)
        execution_id = yield from Resumable.execute(
            {"id": f"durable-{transport}"}, discard=True
        ).pipe(with_engine)

        def suspended() -> fx.Effect[bool]:
            return (
                Resumable.poll(execution_id)
                .map(lambda result: isinstance(result, Suspended))
                .pipe(with_engine)
            )

        yield from _until(suspended)
        assert activity_runs.get(f"durable-{transport}") == 1

        # Stop the runner that owns it, and restart it on the same address.
        owner = _owner(runners, execution_id)
        assert owner is not None
        other = second if owner is first else first
        yield from owner.scope.close(fx.exit.succeed(None))
        restarted = yield from _start(transport, database, owner.port)
        runners = [other, restarted]
        yield from _until(lambda: fx.sync(lambda: _all_shards_owned(runners)))

        # Completing the deferred from the runner that stayed up resumes it.
        other_engine = fx.provide_service(WorkflowEngine, other.context.get_unsafe(WorkflowEngine))
        token = Gate.token_from_execution_id(workflow=Resumable, execution_id=execution_id)
        yield from Gate.succeed(token=token, value="resumed").pipe(other_engine)

        result: list[Any] = []

        def complete() -> fx.Effect[bool]:
            def check(found: Any) -> bool:
                result[:] = [found]
                return isinstance(found, Complete)

            return Resumable.poll(execution_id).map(check).pipe(other_engine)

        yield from _until(complete)
        assert result[0].exit == fx.exit.succeed("resumed")
        assert activity_runs.get(f"durable-{transport}") == 1

    yield from fx.scoped(fx.gen(body))
