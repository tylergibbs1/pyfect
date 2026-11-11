"""The harness of platform-node's ``test/cluster-integration`` suite
(Effect's ``harness.ts``): clusters of real socket runners in this process,
talking over localhost through ``socket_runner``, with their messages and
shard locks in SQL under a table prefix of their own.

``make(backend, entities, ...)`` builds a cluster in the current scope:
a client (``socket_runner.layer_client_only`` with a workflow engine) and
none of its runners yet. ``start`` adds runners, ``stop`` closes one
gracefully, ``kill`` closes one without unregistering or releasing its
locks, ``freeze`` stops its heartbeats and lock refreshes while its sockets
stay open, ``fault_lock`` breaks its reserved lock connection (PostgreSQL),
and ``cut_socket`` closes one connection between two members. The
``wait_*`` helpers poll with a deadline and report the cluster's state when
it passes.

pyfect-only: a runner still frozen when the cluster closes is killed
first, so a test failing meanwhile reports its error instead of hanging.
``freeze_client`` stops the client's reads of the runners, and
``wait_for_client_sync`` waits until the client routes by the running
runners: a frozen runner keeps serving the requests the client still
routes to it.

Backends: ``"sqlite"`` (a database file shared by every member; SQLite has
no advisory locks, so its locks are rows) and ``"pg"`` (the throwaway
server of ``_postgres``). Effect runs PostgreSQL and MySQL; MySQL is not
run here (no server). Messages travel as ``SchemaBinary``, as in Effect.
"""

from __future__ import annotations

import copy
import itertools
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, Never, cast

import pytest

import pyfect as fx
from pyfect import duration, reactivity
from pyfect.cluster import (
    cluster_workflow_engine,
    runner_address,
    runner_health,
    runners,
    socket_runner,
    sql_message_storage,
    sql_runner_storage,
)
from pyfect.cluster import sharding_config as sharding_config_
from pyfect.cluster.entity import Entity
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.message_storage import MessageStorage, MessageStorageService
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.runner_storage import RunnerStorage, RunnerStorageService
from pyfect.cluster.runners import RpcClientProtocol, RpcClientProtocolService
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.sharding import Sharding, ShardingService
from pyfect.cluster.sharding_config import DEFAULTS, ShardingConfigService
from pyfect.context import Context
from pyfect.exit import Exit
from pyfect.latch import Latch
from pyfect.layer import Layer
from pyfect.net.net_address import InetAddressV4
from pyfect.rpc import client as rpc_client
from pyfect.rpc import serialization
from pyfect.rpc.serialization import CodecFor, RpcSerialization
from pyfect.scope import CloseableScope, Scope
from pyfect.socket import Socket, make_net
from pyfect.socket import server as socket_server
from pyfect.socket._connection import Connection
from pyfect.socket._errors import read_error
from pyfect.socket._loop import get_loop
from pyfect.socket._net import connecting, from_connection
from pyfect.socket.server import SocketServer
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.connection import Connection as SqlConnection
from pyfect.sql.error import ConnectionError as SqlConnectionError
from pyfect.sql.error import SqlError
from pyfect.workflow import WorkflowEngine

from ._sqlite import make_client

type Backend = Literal["sqlite", "pg"]
type LockMode = Literal["advisory", "row"]
type LockFaultMode = Literal["blackhole", "stuck", "fail", "hangRelease", "clear"]
type RunnerState = Literal["frozen", "killed", "running", "stopped"]
type RunnerEntities = Layer[Never, Never, Any]
type DatabaseMaker = Callable[[], fx.Effect[SqlClientService, Any, Scope]]

S = duration.seconds

CLUSTER_CONFIG: dict[str, Any] = {
    "entity_max_idle_time": S(3),
    "entity_message_poll_interval": S(0.5),
    "refresh_assignments_interval": S(0.15),
    "shard_lock_expiration": S(1.75),
    "shard_lock_refresh_interval": S(0.5),
}

_clusters = itertools.count()


@dataclass(eq=False)
class ClusterRunner:
    address: RunnerAddress
    index: int
    shard_groups: tuple[str, ...]
    sharding: ShardingService
    scope: CloseableScope
    controller: _RunnerStorageController
    lock_fault: _LockFaultController
    _state: RunnerState = "running"

    def state(self) -> RunnerState:
        return self._state


@dataclass(frozen=True)
class MessageCounts:
    failed: int
    replied: int
    unprocessed: int


class _LockSession:
    def __init__(self) -> None:
        self.fault: Literal["blackhole", "fail"] | None = None


_UNLOCK_ALL = ("pg_advisory_unlock_all", "RELEASE_ALL_LOCKS")


class _FaultyConnection:
    """A reserved connection whose statements obey the current fault, but
    for the release of every advisory lock (so a closing scope still drops
    the database's locks)."""

    def __init__(
        self, inner: SqlConnection, controller: _LockFaultController, session: _LockSession
    ):
        self._inner = inner
        self._controller = controller
        self._session = session

    def _guard[A](self, sql: str, effect: fx.Effect[A, SqlError]) -> fx.Effect[A, SqlError]:
        def start() -> fx.Effect[A, SqlError]:
            if any(marker in sql for marker in _UNLOCK_ALL):
                return effect
            mode = self._session.fault or self._controller.persistent
            if mode == "fail":
                cause = RuntimeError("lock connection lost")
                return fx.fail(SqlError(reason=SqlConnectionError(cause=cause)))
            if mode is not None:
                return fx.never
            return effect

        return fx.suspend(start)

    def execute(self, sql: str, params: Sequence[object], transform: Any, /) -> Any:
        return self._guard(sql, self._inner.execute(sql, params, transform))

    def execute_raw(self, sql: str, params: Sequence[object], /) -> Any:
        return self._guard(sql, self._inner.execute_raw(sql, params))

    def execute_stream(self, sql: str, params: Sequence[object], transform: Any, /) -> Any:
        return self._inner.execute_stream(sql, params, transform)

    def execute_values(self, sql: str, params: Sequence[object], /) -> Any:
        return self._guard(sql, self._inner.execute_values(sql, params))

    def execute_values_unprepared(self, sql: str, params: Sequence[object], /) -> Any:
        return self._guard(sql, self._inner.execute_values_unprepared(sql, params))

    def execute_unprepared(self, sql: str, params: Sequence[object], transform: Any, /) -> Any:
        return self._guard(sql, self._inner.execute_unprepared(sql, params, transform))


class _LockFaultController:
    """Wraps the ``reserve`` of a client: the runner storage's lock
    connection (PostgreSQL) can be blackholed, stuck, failed, or kept from
    being released (Effect's ``makeLockFaultController``)."""

    def __init__(self, sql: SqlClientService) -> None:
        self.release_gate = Latch(True)
        self.persistent: Literal["stuck", "hangRelease"] | None = None
        self.current: _LockSession | None = None
        client = sql.without_transforms()

        @fx.gen
        def reserve():
            session = _LockSession()
            self.current = session
            scope = yield from Scope()

            def hang(_: Exit[Any, Any]) -> fx.Effect[None]:
                return fx.suspend(
                    lambda: (
                        self.release_gate.wait() if self.persistent == "hangRelease" else fx.void
                    )
                ).uninterruptible()

            yield from scope.add_finalizer(hang)
            connection = yield from sql.reserve
            return _FaultyConnection(connection, self, session)

        fields = client.fields()
        fields["reserve"] = reserve
        self.client: SqlClientService = SqlClientService(**fields)

    def set(self, mode: LockFaultMode) -> fx.Effect[None]:
        def apply() -> None:
            if mode == "clear":
                self.persistent = None
                if self.current is not None:
                    self.current.fault = None
                self.release_gate.open_unsafe()
            elif mode in ("blackhole", "fail"):
                if self.current is None:
                    raise RuntimeError("Runner has no reserved lock connection")
                self.persistent = None
                self.release_gate.open_unsafe()
                self.current.fault = mode
            else:
                self.persistent = mode
                if self.current is not None:
                    self.current.fault = None
                if mode == "hangRelease":
                    self.release_gate.close_unsafe()
                else:
                    self.release_gate.open_unsafe()

        return fx.sync(apply)


class _RunnerStorageController:
    """Runner storage that can be frozen (heartbeats and lock refreshes
    wait) or killed (no more writes) (Effect's
    ``makeRunnerStorageController``).

    ``synced_runners`` (pyfect-only) are the healthy runners of the last
    read of the runners that its reader finished with: the sync loop reads
    again only after acting on the previous read."""

    def __init__(self, storage: RunnerStorageService) -> None:
        self.gate = Latch(True)
        self.refresh_paused = Latch(False)
        self.sync_paused = Latch(False)
        self.mode: Literal["frozen", "killed", "running"] = "running"
        self.last_runners: list[Any] = []
        self.synced_runners: frozenset[RunnerAddress] | None = None
        read_once = [False]

        def remember(found: list[Any]) -> None:
            self.last_runners = found
            read_once[0] = True

        def read_started() -> None:
            if read_once[0]:
                self.synced_runners = frozenset(
                    runner.address for runner, healthy in self.last_runners if healthy
                )

        def refresh(address: RunnerAddress, shard_ids: Any) -> fx.Effect[list[ShardId], Any]:
            shards = list(shard_ids)
            return self._while_frozen(
                self.refresh_paused, storage.refresh(address, shards), lambda: shards
            )

        def unless_killed(effect: Callable[[], fx.Effect[None, Any]]) -> fx.Effect[None, Any]:
            return fx.suspend(lambda: fx.void if self.mode == "killed" else effect())

        def release(address: RunnerAddress, shard: ShardId) -> fx.Effect[None, Any]:
            return unless_killed(lambda: storage.release(address, shard))

        def release_all(address: RunnerAddress) -> fx.Effect[None, Any]:
            return unless_killed(lambda: storage.release_all(address))

        def unregister(address: RunnerAddress) -> fx.Effect[None, Any]:
            return unless_killed(lambda: storage.unregister(address))

        self.controlled = copy.replace(
            storage,
            get_runners=fx.sync(read_started).and_then(
                self._while_frozen(
                    self.sync_paused,
                    storage.get_runners.tap(lambda r: fx.sync(lambda: remember(r))),
                    lambda: self.last_runners,
                )
            ),
            refresh=refresh,
            release=release,
            release_all=release_all,
            unregister=unregister,
        )

    def _while_frozen[A](
        self, paused: Latch, effect: fx.Effect[A, Any], on_killed: Callable[[], A]
    ) -> fx.Effect[A, Any]:
        def start() -> fx.Effect[A, Any]:
            if self.mode == "running":
                return effect
            if self.mode == "killed":
                return fx.succeed(on_killed())
            paused.open_unsafe()
            return (
                self.gate.wait()
                .uninterruptible()
                .and_then(
                    fx.suspend(
                        lambda: effect if self.mode == "running" else fx.succeed(on_killed())
                    )
                )
            )

        return fx.suspend(start)

    def freeze(self, *, refreshes: bool = True) -> fx.Effect[None]:
        """Freeze, and wait until a read of the runners (and, with
        ``refreshes``, a lock refresh) is waiting."""

        def apply() -> None:
            self.mode = "frozen"
            self.gate.close_unsafe()

        paused = [self.sync_paused.wait()]
        if refreshes:
            paused.append(self.refresh_paused.wait())
        return fx.sync(apply).and_then(fx.all(*paused, discard=True))

    @property
    def kill(self) -> fx.Effect[None]:
        def apply() -> None:
            self.mode = "killed"
            self.gate.open_unsafe()

        return fx.sync(apply)

    @property
    def resume(self) -> fx.Effect[None]:
        def apply() -> None:
            self.mode = "running"
            self.gate.open_unsafe()

        return fx.sync(apply)

    def release_on_close(self, scope: CloseableScope) -> fx.Effect[None]:
        """Kill this storage if it is still frozen when ``scope`` closes:
        its reader waits uninterruptibly, so closing it frozen would hang,
        and a test failing while a runner is frozen would time out instead
        of reporting its error (pyfect-only). Add this after the layers
        that read the storage, so it runs before their finalizers."""

        def release() -> None:
            if self.mode == "frozen":
                self.mode = "killed"
                self.gate.open_unsafe()

        return scope.add_finalizer(lambda _: fx.sync(release))


def address_key(address: RunnerAddress) -> str:
    return f"{address.host}:{address.port}"


CLIENT_PEER = "client"


def _reads_nothing_once_killed(
    storage: MessageStorageService, controller: _RunnerStorageController
) -> MessageStorageService:
    """A killed runner's process is gone, but here its scope is still closing while a gated
    handler runs, and its read loop lives on. A read after the replacement's ``reset_shards``
    claims a message for ten minutes (``last_read``), and nothing would deliver it."""

    def unprocessed_messages(shard_ids: Any, /, **options: Any) -> fx.Effect[Any, Any]:
        return fx.suspend(
            lambda: (
                fx.succeed([])
                if controller.mode == "killed"
                else storage.unprocessed_messages(shard_ids, **options)
            )
        )

    cls = type(
        "KilledRunnerStorage",
        (MessageStorageService,),
        {"unprocessed_messages": staticmethod(unprocessed_messages)},
    )
    return cls(storage.base, storage._handlers, storage._handlers_by_shard)  # pyright: ignore[reportPrivateUsage]


@dataclass
class _SocketController:
    """The open connections between members, by ``source->target``, so a
    test can close one (Effect's ``makeSocketController``)."""

    connections: dict[str, list[Connection]] = field(default_factory=lambda: {})

    def add(self, source: str, target: RunnerAddress, connection: Connection) -> None:
        self.connections.setdefault(f"{source}->{address_key(target)}", []).append(connection)

    def remove(self, source: str, target: RunnerAddress, connection: Connection) -> None:
        key = f"{source}->{address_key(target)}"
        active = self.connections.get(key)
        if active is None:
            return
        if connection in active:
            active.remove(connection)
        if not active:
            del self.connections[key]

    def cut(self, source: str, target: str) -> fx.Effect[None]:
        def apply() -> None:
            active = self.connections.get(f"{source}->{target}")
            if not active:
                raise RuntimeError(f"No active socket from {source} to {target}")
            connection = active[0]
            connection.fail(read_error(ConnectionError(f"Socket cut from {source} to {target}")))
            connection.close(graceful=False)

        return fx.sync(apply)


def tracked_client_protocol(
    controller: _SocketController, source: str
) -> Layer[RpcClientProtocol, Never, RpcSerialization]:
    """Dial runners over TCP, recording each connection under ``source``."""

    @fx.gen
    def make_():
        wire = yield from RpcSerialization()

        def make_protocol(address: RunnerAddress) -> fx.Effect[Any, Never, Scope]:
            async def connect(conn: Connection) -> object:
                return await get_loop().create_connection(lambda: conn, address.host, address.port)

            @fx.gen
            def open_tracked():
                connection = yield from connecting(connect)
                controller.add(source, address, connection)
                scope = yield from Scope()
                yield from scope.add_finalizer(
                    lambda _: fx.sync(lambda: controller.remove(source, address, connection))
                )
                return connection

            socket = from_connection(open_tracked, open_timeout="1 second")
            return (
                rpc_client.make_protocol_socket()
                .pipe(fx.provide_service(Socket, socket))
                .pipe(fx.provide_service(RpcSerialization, wire))
            )

        return RpcClientProtocolService(make=make_protocol, codec_for=wire.codec_for)

    return fx.layer.effect(RpcClientProtocol, make_)


def runner_health_layer(
    client_protocol: Layer[RpcClientProtocol, Never, Any],
) -> Layer[Any, Never, Any]:
    return runner_health.layer_ping.pipe(fx.layer.provide(runners.layer_rpc)).pipe(
        fx.layer.provide(client_protocol)
    )


def socket_runner_layer(
    address: RunnerAddress,
    entities: RunnerEntities,
    server: Any,
    config: ShardingConfigService,
    client_protocol: Layer[RpcClientProtocol, Never, Any],
) -> Layer[Any, Never, Any]:
    """A runner of ``entities`` on ``server`` (Effect's ``socketRunnerLayer``)."""
    return (
        entities.pipe(fx.layer.provide_merge(socket_runner.layer))
        .pipe(fx.layer.provide(runner_health_layer(client_protocol)))
        .pipe(fx.layer.provide(fx.layer.succeed(SocketServer, server)))
        .pipe(fx.layer.provide(client_protocol))
        .pipe(fx.layer.provide(sharding_config_.layer(replace(config, runner_address=address))))
        .pipe(fx.layer.provide(serialization.layer_schema_binary()))
    )


@dataclass
class RawRunnerClient:
    client: runners.Rpcs
    codec_for: CodecFor
    disconnect: fx.Effect[None]


def make_raw_runner_client(runner: ClusterRunner) -> fx.Effect[RawRunnerClient, Never, Scope]:
    """A caller of a runner's RPCs over its own TCP connection, which it
    can close with no retry by ``Sharding`` (Effect's
    ``makeRawRunnerClient``)."""

    @fx.gen
    def make_():
        wire = serialization.make_schema_binary()
        parent = yield from Scope()
        transport = yield from parent.fork()
        yield from parent.add_finalizer(lambda _: transport.close(fx.exit.succeed(None)))
        socket = make_net(runner.address.port, runner.address.host)
        protocol = (
            yield from rpc_client.make_protocol_socket()
            .pipe(fx.provide_service(Socket, socket))
            .pipe(fx.provide_service(RpcSerialization, wire))
            .pipe(fx.provide_service(Scope, transport))
        )
        client = (
            yield from rpc_client.make(runners.Rpcs)
            .pipe(fx.provide_service(rpc_client.ClientProtocol, protocol))
            .pipe(fx.provide_service(Scope, transport))
        )
        return RawRunnerClient(
            client=client,
            codec_for=wire.codec_for,
            disconnect=transport.close(fx.exit.succeed(None)),
        )

    return make_


def _parse_reply(payload: object) -> dict[str, Any] | None:
    if payload is None:
        return None
    if isinstance(payload, str):
        return json.loads(payload)
    return cast("dict[str, Any]", payload)


def _processed(value: object) -> bool:
    return bool(int(value)) if not isinstance(value, bool) else value  # pyright: ignore[reportArgumentType]


@dataclass(eq=False)
class Cluster:
    backend: Backend
    lock_mode: LockMode
    prefix: str
    config: ShardingConfigService
    entities: RunnerEntities
    sql: SqlClientService
    database: Context[Any]
    shared: Context[Any]
    parent: CloseableScope
    client: Context[Any]
    client_sharding: ShardingService
    client_storage: _RunnerStorageController
    workflow_engine: Any
    sockets: _SocketController
    runner_layer: Callable[..., Layer[Any, Never, Any]]
    runners: list[ClusterRunner] = field(default_factory=lambda: [])
    _next_index: itertools.count[int] = field(default_factory=itertools.count)

    # Lifecycle

    def _runner_storage(
        self, scope: CloseableScope, config: ShardingConfigService, database: Context[Any]
    ) -> fx.Effect[Context[RunnerStorage]]:
        return (
            sql_runner_storage.layer_with(prefix=self.prefix)
            .pipe(fx.layer.provide(sharding_config_.layer(config)))
            .build_with_scope(scope)
            .pipe(fx.provide(database))
        )

    def _start_runner(
        self,
        index: int,
        assigned_shard_groups: tuple[str, ...] | None,
        entities: RunnerEntities | None,
        runner_shard_weight: int | None,
    ) -> fx.Effect[ClusterRunner, Any]:
        @fx.gen
        def start():
            scope = yield from self.parent.fork()
            config = self.config
            if assigned_shard_groups is not None:
                config = replace(config, assigned_shard_groups=assigned_shard_groups)
            if runner_shard_weight is not None:
                config = replace(config, runner_shard_weight=runner_shard_weight)
            server_context = yield from fx.layer.effect(
                SocketServer, socket_server.make(0, "127.0.0.1")
            ).build_with_scope(scope)
            server = server_context.get_unsafe(SocketServer)
            assert isinstance(server.address, InetAddressV4)
            address = runner_address.make("127.0.0.1", server.address.port)
            lock_fault = _LockFaultController(self.database.get_unsafe(SqlClient))
            runner_database = self.database.add(SqlClient, lock_fault.client)
            raw_storage = yield from self._runner_storage(scope, config, runner_database)
            yield from scope.add_finalizer(lambda _: lock_fault.set("clear"))
            controller = _RunnerStorageController(raw_storage.get_unsafe(RunnerStorage))
            storage = Context.make(RunnerStorage, controller.controlled)
            messages = _reads_nothing_once_killed(
                self.shared.get_unsafe(MessageStorage), controller
            )
            built = (
                yield from self.runner_layer(
                    address,
                    entities if entities is not None else self.entities,
                    server,
                    config,
                    tracked_client_protocol(self.sockets, address_key(address)),
                )
                .build_with_scope(scope)
                .pipe(fx.provide(self.shared.merge(storage).add(MessageStorage, messages)))
            )
            yield from controller.release_on_close(scope)
            runner = ClusterRunner(
                address=address,
                index=index,
                shard_groups=config.assigned_shard_groups,
                sharding=built.get_unsafe(Sharding),
                scope=scope,
                controller=controller,
                lock_fault=lock_fault,
            )
            self.runners.append(runner)
            return runner

        return start

    def start(
        self,
        count: int,
        *,
        assigned_shard_groups: tuple[str, ...] | None = None,
        entities: RunnerEntities | None = None,
        runner_shard_weight: int | None = None,
    ) -> fx.Effect[list[ClusterRunner], Any]:
        """Starts ``count`` runners, one after another."""

        @fx.gen
        def start_all():
            started: list[ClusterRunner] = []
            for _ in range(count):
                index = next(self._next_index)
                started.append(
                    (
                        yield from self._start_runner(
                            index, assigned_shard_groups, entities, runner_shard_weight
                        )
                    )
                )
            return started

        return start_all

    def stop(self, runner: ClusterRunner) -> fx.Effect[None]:
        """Closes ``runner`` gracefully: it unregisters and hands off its
        shards."""

        @fx.gen
        def stop_():
            if runner.state() in ("stopped", "killed"):
                return
            if runner.state() == "frozen":
                yield from runner.controller.resume
            runner._state = "stopped"  # pyright: ignore[reportPrivateUsage]
            yield from runner.scope.close(fx.exit.succeed(None))

        return stop_

    def kill(self, runner: ClusterRunner) -> fx.Effect[None]:
        """Closes ``runner`` without unregistering it or releasing its
        locks."""

        @fx.gen
        def kill_():
            if runner.state() in ("stopped", "killed"):
                return
            runner._state = "killed"  # pyright: ignore[reportPrivateUsage]
            yield from runner.controller.kill
            yield from runner.scope.close(fx.exit.succeed(None))

        return kill_

    def freeze(self, runner: ClusterRunner) -> fx.Effect[None]:
        """Stops ``runner``'s heartbeats and lock refreshes; its sockets and
        lock connection stay open."""

        @fx.gen
        def freeze_():
            if runner.state() != "running":
                return
            runner._state = "frozen"  # pyright: ignore[reportPrivateUsage]
            yield from runner.controller.freeze()

        return freeze_

    def freeze_client(self) -> fx.Effect[None]:
        """Stops the client's reads of the runners: it keeps routing by
        the runners it last read (pyfect-only)."""
        return self.client_storage.freeze(refreshes=False)

    def resume_client(self) -> fx.Effect[None]:
        return self.client_storage.resume

    def client_in_sync(self) -> bool:
        """Whether the client routes by the running runners: the healthy
        runners of the client's last finished read of the runners are the
        running ones (pyfect-only). A runner sees a shard move up to a
        ``refresh_assignments_interval`` before the client does."""
        running = frozenset(r.address for r in self.runners if r.state() == "running")
        return self.client_storage.synced_runners == running

    def wait_for_client_sync(self, timeout: float = 15) -> fx.Effect[None, Exception]:
        return self.wait_until(
            "The client's view of the runners did not catch up with the running runners",
            fx.sync(self.client_in_sync),
            timeout,
        )

    def fault_lock(self, runner: ClusterRunner, mode: LockFaultMode) -> fx.Effect[None]:
        return runner.lock_fault.set(mode)

    def cut_socket(
        self,
        runner: ClusterRunner,
        *,
        peer: ClusterRunner | Literal["client"],
        direction: Literal["inbound", "outbound"],
    ) -> fx.Effect[None]:
        """Closes one connection between ``runner`` and ``peer``: ``inbound``
        is the one ``peer`` opened to ``runner``."""
        runner_key = address_key(runner.address)
        peer_key = CLIENT_PEER if peer == "client" else address_key(peer.address)
        source, target = (
            (peer_key, runner_key) if direction == "inbound" else (runner_key, peer_key)
        )
        return self.sockets.cut(source, target)

    # Storage

    def table(self, name: str) -> Any:
        return self.sql.identifier(f"{self.prefix}_{name}")

    def insert_message(self, row: dict[str, object]) -> fx.Effect[None, SqlError]:
        return self.sql("INSERT INTO {} {}", self.table("messages"), self.sql.insert(row)).as_void()

    def message_counts(self) -> fx.Effect[MessageCounts, SqlError]:
        @fx.gen
        def counts():
            rows = yield from self.sql(
                "SELECT m.processed, r.payload AS reply_payload FROM {} m "
                "LEFT JOIN {} r ON r.id = m.last_reply_id WHERE m.kind = 0",
                self.table("messages"),
                self.table("replies"),
            )
            failed = replied = unprocessed = 0
            for row in rows:
                if not _processed(row["processed"]):
                    unprocessed += 1
                    continue
                reply = _parse_reply(row["reply_payload"])
                tag = None if reply is None else reply.get("_tag")
                if tag == "Success":
                    replied += 1
                if tag == "Failure":
                    failed += 1
            return MessageCounts(failed=failed, replied=replied, unprocessed=unprocessed)

        return counts

    @property
    def replied_message_count(self) -> fx.Effect[int, SqlError]:
        return self.message_counts().map(lambda c: c.replied)

    @property
    def failed_message_count(self) -> fx.Effect[int, SqlError]:
        return self.message_counts().map(lambda c: c.failed)

    @property
    def unprocessed_message_count(self) -> fx.Effect[int, SqlError]:
        return self.message_counts().map(lambda c: c.unprocessed)

    # Assignments

    def assignment_map(self) -> dict[str, list[str]]:
        assignments: dict[str, list[str]] = {}
        for group in self.config.available_shard_groups:
            for shard in range(1, self.config.shards_per_group + 1):
                shard_id = ShardId(group=group, id=shard)
                assignments[str(shard_id)] = [
                    address_key(r.address)
                    for r in self.runners
                    if r.state() == "running" and r.sharding.has_shard_id(shard_id)
                ]
        return assignments

    def owners_of_shard(
        self, shard: ShardId, include_inactive: bool = False
    ) -> list[ClusterRunner]:
        return [
            r
            for r in self.runners
            if (include_inactive or r.state() == "running") and r.sharding.has_shard_id(shard)
        ]

    def registrations(self) -> fx.Effect[list[dict[str, Any]], SqlError]:
        """The rows of this cluster's runner table, by address."""
        return self.sql(
            "SELECT address, healthy, last_heartbeat FROM {} ORDER BY address",
            self.table("runners"),
        ).map(lambda rows: [dict(row) for row in rows])

    def diagnostics(self) -> fx.Effect[str]:
        @fx.gen
        def report():
            counts = (
                yield from self.message_counts()
                .map(str)
                .catch_all(lambda error: fx.succeed(repr(error)))
            )
            registrations = yield from self.registrations().catch_all(
                lambda error: fx.succeed(repr(error))
            )
            owners = {key: value for key, value in self.assignment_map().items() if len(value) != 1}
            return json.dumps(
                {
                    "unowned_or_shared_shards": owners,
                    "message_counts": counts,
                    "registrations": registrations,
                },
                indent=2,
                default=str,
            )

        return report

    def wait_until(
        self, description: str, condition: fx.Effect[bool, Any, Any], timeout: float = 15
    ) -> fx.Effect[None, Exception]:
        """Polls ``condition`` (with the client's services) every 100 ms
        until it holds; fails with the cluster's state after ``timeout``
        seconds. Each check runs only for the time left, so a condition
        that blocks (``deferred.wait()``) fails at the deadline too."""
        checked = condition.pipe(fx.provide(self.client))

        @fx.gen
        def wait():
            clock = yield from fx.clock.Clock()
            deadline = clock.current_time_millis_unsafe() + timeout * 1000
            while True:
                left = deadline - clock.current_time_millis_unsafe()
                if left <= 0:
                    break
                held = yield from checked.timeout_option(left)
                if held is not None and held.value:
                    return
                if clock.current_time_millis_unsafe() >= deadline:
                    break
                yield from fx.sleep(min(100, max(0, deadline - clock.current_time_millis_unsafe())))
            state = yield from self.diagnostics()
            return (yield from fx.fail(AssertionError(f"{description}\n{state}")))

        return wait

    def wait_for_stable_assignments(
        self, timeout: float = 15
    ) -> fx.Effect[dict[str, list[str]], Exception]:
        """Waits until every shard has one running owner, every running
        runner owns one, and that held for three polls."""
        previous = [""]
        stable = [0]

        def check() -> bool:
            current = self.assignment_map()
            owners = {owner for value in current.values() for owner in value}
            complete = all(len(value) == 1 for value in current.values()) and all(
                r.state() != "running" or address_key(r.address) in owners for r in self.runners
            )
            encoded = json.dumps(current, sort_keys=True) if complete else ""
            stable[0] = stable[0] + 1 if encoded != "" and encoded == previous[0] else 0
            previous[0] = encoded
            return stable[0] >= 3

        return self.wait_until(
            "Shard assignments did not stabilize before the deadline", fx.sync(check), timeout
        ).map(lambda _: self.assignment_map())

    def shard_of_entity(self, entity: type[Entity], entity_id: str) -> fx.Effect[ShardId]:
        return entity.get_shard_id(EntityId(entity_id)).pipe(fx.provide(self.client))

    def owner_of_entity(
        self, entity: type[Entity], entity_id: str
    ) -> fx.Effect[ClusterRunner | None]:
        def find(shard: ShardId) -> ClusterRunner | None:
            for r in self.runners:
                if r.state() == "running" and r.sharding.has_shard_id(shard):
                    return r
            return None

        return self.shard_of_entity(entity, entity_id).map(find)

    def wait_for_entity_owner(
        self, entity: type[Entity], entity_id: str, runner: ClusterRunner, timeout: float = 15
    ) -> fx.Effect[None, Exception]:
        return self.wait_until(
            f"Entity {entity.type}/{entity_id} was not owned by runner {runner.index} "
            "before the deadline",
            self.owner_of_entity(entity, entity_id).map(lambda owner: owner is runner),
            timeout,
        )

    def get_client[T: Entity](self, entity: type[T]) -> fx.Effect[Callable[[str], T]]:
        return entity.client().pipe(fx.provide(self.client))


@dataclass(frozen=True)
class ClusterDatabase:
    backend: Backend
    make: DatabaseMaker


def _pg(server: Any) -> fx.Effect[SqlClientService, Any, Scope]:
    from pyfect.sql import pg

    config = pg.PgPoolConfig(url=server.url, max_connections=10)
    return pg.make(config).pipe(fx.provide(reactivity.layer))


@pytest.fixture(params=["sqlite", "pg"])
def cluster_db(request: pytest.FixtureRequest, tmp_path: Path) -> ClusterDatabase:
    """A database for a cluster: a SQLite file, or the throwaway PostgreSQL
    server (skipped without one)."""
    if request.param == "sqlite":
        return ClusterDatabase("sqlite", lambda: make_client(tmp_path))
    pytest.importorskip("psycopg")
    server = request.getfixturevalue("pg_server")
    return ClusterDatabase("pg", lambda: _pg(server))


def make(
    database: ClusterDatabase,
    *,
    entities: RunnerEntities | Callable[[str], RunnerEntities],
    lock_mode: LockMode = "advisory",
    config: dict[str, Any] | None = None,
    runner_layer: Callable[..., Layer[Any, Never, Any]] | None = None,
) -> fx.Effect[Cluster, Any, Scope]:
    """A cluster in the current scope, with its client and no runners."""

    @fx.gen
    def make_():
        parent = yield from Scope()
        prefix = f"cluster_{os.getpid()}_{next(_clusters)}"
        settings = replace(
            DEFAULTS,
            **{**CLUSTER_CONFIG, **(config or {})},
            shard_lock_disable_advisory=lock_mode == "row",
        )
        client_db = yield from database.make()
        database_context = Context.make(SqlClient, client_db)
        sql = client_db.without_transforms()
        messages = yield from (
            sql_message_storage.layer_with(prefix=prefix)
            .pipe(fx.layer.provide(sharding_config_.layer(settings)))
            .build_with_scope(parent)
            .pipe(fx.provide(database_context))
        )
        shared = database_context.merge(messages)
        resolved = entities(prefix) if callable(entities) else entities
        sockets = _SocketController()
        client_scope = yield from parent.fork()
        client_storage_context = yield from (
            sql_runner_storage.layer_with(prefix=prefix)
            .pipe(fx.layer.provide(sharding_config_.layer(settings)))
            .build_with_scope(client_scope)
            .pipe(fx.provide(database_context))
        )
        client_storage = _RunnerStorageController(client_storage_context.get_unsafe(RunnerStorage))
        client_base = yield from (
            socket_runner.layer_client_only.pipe(
                fx.layer.provide(tracked_client_protocol(sockets, CLIENT_PEER))
            )
            .pipe(fx.layer.provide(sharding_config_.layer(settings)))
            .pipe(fx.layer.provide(serialization.layer_schema_binary()))
            .build_with_scope(client_scope)
            .pipe(fx.provide(shared.merge(Context.make(RunnerStorage, client_storage.controlled))))
        )
        yield from client_storage.release_on_close(client_scope)
        engine = yield from cluster_workflow_engine.make().pipe(
            fx.provide(shared.merge(client_base))
        )
        client = client_base.add(WorkflowEngine, engine)
        return Cluster(
            backend=database.backend,
            lock_mode=lock_mode,
            prefix=prefix,
            config=settings,
            entities=resolved,
            sql=sql,
            database=database_context,
            shared=shared,
            parent=parent,
            client=client,
            client_sharding=client.get_unsafe(Sharding),
            client_storage=client_storage,
            workflow_engine=engine,
            sockets=sockets,
            runner_layer=runner_layer or socket_runner_layer,
        )

    return make_


__all__ = [
    "CLIENT_PEER",
    "Backend",
    "Cluster",
    "ClusterDatabase",
    "ClusterRunner",
    "MessageCounts",
    "RawRunnerClient",
    "cluster_db",
    "make",
    "make_raw_runner_client",
    "socket_runner_layer",
    "tracked_client_protocol",
]
