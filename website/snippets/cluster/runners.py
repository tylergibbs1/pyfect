import socket
from dataclasses import replace

import pyfect as fx
from pyfect import reactivity
from pyfect import schema as S
from pyfect.cluster import cluster_socket, runner_address
from pyfect.cluster.entity import CurrentRunnerAddress, Entity
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.sharding import Sharding
from pyfect.cluster.sharding_config import ShardingConfigService
from pyfect.rpc import make as make_rpc
from pyfect.scope import Scope
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient


class Where(Entity, type="Where"):
    port = make_rpc("Port", success=S.Int)


@fx.gen
def where():
    address = yield from CurrentRunnerAddress()  # the runner this entity lives on
    return Where.handlers().handle(Where.port)(lambda _: fx.succeed(address.port))


def free_ports(count: int) -> list[int]:
    # Hold every probe open until all are bound, so the ports differ.
    probes = [socket.socket() for _ in range(count)]
    for probe in probes:
        probe.bind(("127.0.0.1", 0))
    ports = [probe.getsockname()[1] for probe in probes]
    for probe in probes:
        probe.close()
    return ports


def runner(database: fx.Context[SqlClient], port: int):
    # Each runner listens on its own address and shares one database with the others:
    # messages and shard locks live there.
    def settings(config: ShardingConfigService) -> ShardingConfigService:
        return replace(
            config,
            runner_address=runner_address.make("127.0.0.1", port),
            refresh_assignments_interval=fx.duration.millis(200),
            entity_termination_timeout=fx.duration.zero,
            # A stopping runner releases each shard's lock in its own write, so fewer shards
            # stop faster. Every runner of a cluster needs the same count.
            shards_per_group=30,
        )

    return (
        Where.to_layer_effect(where)
        .pipe(fx.layer.provide_merge(cluster_socket.layer(sharding_config=settings)))
        .pipe(fx.layer.provide(fx.layer.succeed_context(database)))
    )


def owns_shards(context: fx.Context[Sharding]) -> bool:
    sharding = context.get_unsafe(Sharding)
    return any(
        sharding.has_shard_id(sharding.get_shard_id(EntityId(f"probe-{i}"), "default"))
        for i in range(100)
    )


@fx.gen
def program():
    ports = free_ports(2)
    scope = yield from Scope()
    # One in-memory database the two runners share. In production, a database every
    # runner reaches (Postgres, MySQL, a SQLite file on a shared host).
    database = yield from (
        fx.layer.effect(SqlClient, sqlite.make(sqlite.SqliteClientConfig(filename=":memory:")))
        .pipe(fx.layer.provide(reactivity.layer))
        .build_with_scope(scope)
    )
    # Two runners in one process here; in production, one per process or machine.
    first = yield from runner(database, ports[0]).build_with_scope(scope)
    second = yield from runner(database, ports[1]).build_with_scope(scope)
    while not (owns_shards(first) and owns_shards(second)):
        yield from fx.sleep("100 millis")

    # A client on the first runner reaches every entity, wherever its shard is.
    make_client = yield from Where.client().pipe(fx.provide(first))
    answers = yield from fx.for_each(
        [make_client(f"user-{i}").port() for i in range(40)], lambda call: call
    )
    by_runner = {"first" if port == ports[0] else "second" for port in answers}
    print("runners that answered:", sorted(by_runner))


# No "Listening on", and no "No healthy runners available" from a runner that syncs
# while the other shuts down.
quiet = fx.provide_service(fx.MinimumLogLevel, fx.LogLevel.ERROR)
fx.run_main(fx.scoped(program).pipe(quiet))
