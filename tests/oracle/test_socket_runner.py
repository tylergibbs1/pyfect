"""Ports of platform-node's ``test/cluster/SocketRunner.test.ts``: a runner
built with ``socket_runner.layer`` on a real ``SocketServer`` over
localhost, and a client built with ``socket_runner.layer_client_only`` or
``cluster_socket.layer(client_only=True, storage="byo")``, sharing memory
storage. Each test's docstring is the Effect test title.

Adapted, with the reason:
- "discarded persisted requests serialize circular values and volatile
  requests do not wait for replies": the circular value is a JavaScript
  ``BigDecimal`` (its ``normalized`` self-reference); the payload's amount
  is a decimal string here, and the rest of the test is Effect's.
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import replace
from typing import Any, Literal, Never, TypedDict

import pyfect as fx
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect import testing
from pyfect.cluster import (
    cluster_socket,
    message_storage,
    runner_address,
    runner_health,
    runner_storage,
    sharding_config,
    socket_runner,
)
from pyfect.cluster.cluster_schema import Persisted, Uninterruptible
from pyfect.cluster.entity import Entity, Request
from pyfect.cluster.sharding import Sharding
from pyfect.cluster.sharding_config import DEFAULTS, ShardingConfigService
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.layer import Layer
from pyfect.net.net_address import InetAddressV4
from pyfect.rpc import make as make_rpc
from pyfect.rpc import serialization
from pyfect.schema import ErrorInstance
from pyfect.socket import server as socket_server
from pyfect.socket.server import SocketServer

HOST = "127.0.0.1"


class ProcessPayload(S.Class, identifier="TestPayload"):
    id: str
    amount: str

    def primary_key(self) -> str:
        return self.id


class ProcessEntity(Entity, type="TestEntity", rpc_annotations=Context.make(Uninterruptible, True)):
    process = make_rpc("Process", payload=ProcessPayload).annotate(Persisted, True)
    process_volatile = make_rpc("ProcessVolatile", payload=ProcessPayload).annotate(
        Persisted, False
    )


class SerializationEntity(
    Entity, type="SerializationEntity", rpc_annotations=Context.make(Persisted, False)
):
    ping = make_rpc("Ping", success=S.String)


class IdPayload(TypedDict):
    id: float


class IsolationEntity(
    Entity, type="IsolationEntity", rpc_annotations=Context.make(Persisted, False)
):
    bad_reply = make_rpc("BadReply", success=S.Int, payload=S.Struct(IdPayload))
    slow = make_rpc("Slow", success=S.String)


shared_storage = fx.layer.merge(runner_storage.layer_memory, message_storage.layer_memory).pipe(
    fx.layer.provide(sharding_config.layer_defaults)
)


def _config(port: int, **overrides: Any) -> ShardingConfigService:
    return replace(
        DEFAULTS,
        runner_address=runner_address.make(HOST, port),
        entity_termination_timeout=fx.duration.Seconds(0),
        entity_message_poll_interval=fx.duration.Seconds(5),
        send_retry_interval=fx.duration.Seconds(0.1),
        **overrides,
    )


def start_runner(
    entities: Layer[Never, Never, Sharding],
    wire: Layer[serialization.RpcSerialization] | None = None,
) -> fx.Effect[int, Any, Any]:
    wire_ = serialization.layer_schema_binary() if wire is None else wire

    @fx.gen
    def start():
        server = yield from socket_server.make(0, HOST)
        address = server.address
        assert isinstance(address, InetAddressV4)
        port = address.port
        runner = (
            entities.pipe(fx.layer.provide_merge(socket_runner.layer))
            .pipe(fx.layer.provide(runner_health.layer_noop))
            .pipe(fx.layer.provide(fx.layer.succeed(SocketServer, server)))
            .pipe(fx.layer.provide(cluster_socket.layer_client_protocol))
            .pipe(fx.layer.provide(sharding_config.layer(_config(port))))
            .pipe(fx.layer.provide(wire_))
        )
        yield from runner.build()
        return port

    return start


def client_layer(port: int) -> Layer[Any, Never, Any]:
    return (
        socket_runner.layer_client_only.pipe(fx.layer.provide(cluster_socket.layer_client_protocol))
        .pipe(
            fx.layer.provide(
                sharding_config.layer(
                    _config(port, runner_listen_address=runner_address.make(HOST, port))
                )
            )
        )
        .pipe(fx.layer.provide(serialization.layer_schema_binary()))
    )


def configured_client_layer(
    port: int,
    kind: Literal["binary", "ndjson"] | None = None,
    max_buffer_size: int | None = None,
) -> Layer[Any, Any, Any]:
    def settings(config: ShardingConfigService) -> ShardingConfigService:
        return _config(port, runner_listen_address=runner_address.make(HOST, port))

    options: dict[str, Any] = {}
    if kind is not None:
        options["serialization"] = kind
    if max_buffer_size is not None:
        options["serialization_max_buffer_size"] = max_buffer_size
    return cluster_socket.layer(
        client_only=True, storage="byo", sharding_config=settings, **options
    )


serialization_entity_layer = SerializationEntity.to_layer(
    SerializationEntity.handlers().handle(SerializationEntity.ping)(lambda _: fx.succeed("pong"))
)


@fx.fn
def _ping(entity_id: str):
    make_client = yield from SerializationEntity.client()
    return (yield from make_client(entity_id).ping())


def _assert_serialization(
    wire: Layer[serialization.RpcSerialization], kind: Literal["binary", "ndjson"] | None
) -> Any:
    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        port = yield from start_runner(serialization_entity_layer, wire)
        result = yield from fx.scoped(
            _ping("serialization-entity").pipe(fx.provide(configured_client_layer(port, kind)))
        )
        assert result == "pong"

    return fx.gen(body).pipe(fx.provide(shared_storage))


@testing.live(timeout="15 seconds")
def test_uses_the_default_serialization_for_tcp_connections():
    """uses SchemaBinary by default for TCP connections"""
    yield from _assert_serialization(serialization.layer_schema_binary(), None)


@testing.live(timeout="15 seconds")
def test_preserves_an_explicit_ndjson_selection():
    """(not an Effect title) an explicit ndjson selection reaches a runner on ndjson"""
    yield from _assert_serialization(serialization.layer_ndjson, "ndjson")


@testing.live(timeout="15 seconds")
def test_preserves_an_explicit_binary_selection():
    """preserves an explicit binary selection"""
    yield from _assert_serialization(serialization.layer_schema_binary(), "binary")


@testing.live(timeout="15 seconds")
def test_applies_serialization_max_buffer_size_to_the_default_parser():
    """applies serializationMaxBufferSize to the default SchemaBinary parser"""

    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        port = yield from start_runner(serialization_entity_layer)
        pong = yield from fx.scoped(
            _ping("serialization-limit-entity").pipe(fx.provide(configured_client_layer(port)))
        )
        assert pong == "pong"
        exit = yield from fx.scoped(
            _ping("serialization-limit-entity")
            .timeout("1 second")
            .pipe(fx.provide(configured_client_layer(port, None, 1)))
        ).exit()
        assert isinstance(exit, Exit.Failure), "the configured frame limit must reject the response"

    yield from fx.gen(body).pipe(fx.provide(shared_storage))


@testing.live(timeout="30 seconds")
def test_discarded_persisted_requests_and_volatile_requests_do_not_wait_for_replies():
    """discarded persisted requests serialize circular values and volatile requests do not wait for replies"""  # noqa: E501

    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        volatile_started = yield from Deferred[None, Never].make()
        release_volatile = yield from Deferred[None, Never].make()

        def process_volatile(_: Request[ProcessPayload]) -> fx.Effect[None]:
            return volatile_started.succeed(None).and_then(release_volatile.wait())

        entities = ProcessEntity.to_layer(
            ProcessEntity.handlers()
            .handle(ProcessEntity.process)(lambda _: fx.void)
            .handle(ProcessEntity.process_volatile)(process_volatile)
        )
        port = yield from start_runner(entities)

        @fx.gen
        def client_side():
            make_client = yield from ProcessEntity.client()
            client = make_client("entity-1")
            amount = "123.45"
            yield from client.process.discard(ProcessPayload(id="req-1", amount=amount))
            volatile = yield from client.process_volatile.discard(
                ProcessPayload(id="req-2", amount=amount)
            ).fork()
            yield from volatile_started.wait().timeout_or_else(
                "5 seconds",
                lambda: fx.die(AssertionError("the volatile request never reached its handler")),
            )
            yield from volatile.join().timeout_or_else(
                "1 second",
                lambda: fx.die(AssertionError("volatile discard waited for the entity reply")),
            )
            yield from release_volatile.succeed(None)

        yield from fx.scoped(client_side.pipe(fx.provide(client_layer(port))))

    yield from fx.gen(body).pipe(fx.provide(shared_storage))


@testing.live(timeout="30 seconds")
def test_a_reply_serialization_failure_fails_only_its_own_request():
    """a reply serialization failure fails only its own request"""

    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        slow_started = yield from Deferred[None, Never].make()
        release_slow = yield from Deferred[None, Never].make()
        entities = IsolationEntity.to_layer(
            IsolationEntity.handlers()
            .handle(IsolationEntity.bad_reply)(lambda _: fx.succeed(cast_any(1.5)))
            .handle(IsolationEntity.slow)(
                lambda _: slow_started.succeed(None).and_then(release_slow.wait()).as_("done")
            )
        )
        port = yield from start_runner(entities)

        @fx.gen
        def client_side():
            make_client = yield from IsolationEntity.client()
            slow = yield from make_client("slow-entity").slow().fork()
            yield from slow_started.wait().timeout_or_else(
                "5 seconds",
                lambda: fx.die(AssertionError("the Slow request never reached its handler")),
            )
            bad = yield from (
                make_client("bad-entity")
                .bad_reply({"id": 1})
                .exit()
                .ensuring(release_slow.succeed(None))
            )
            assert isinstance(bad, Exit.Failure), "the unencodable reply must fail the request"
            # The defect crosses the wire as an error instance; Effect reads its
            # name through ``String(error)``.
            failure = bad.cause.squash()
            assert isinstance(failure, ErrorInstance)
            assert failure.name == "MalformedMessage", "the caller must get the encode error"
            slow_exit = yield from slow.await_exit()
            assert slow_exit == Exit.succeed("done")

        yield from fx.scoped(client_side.pipe(fx.provide(client_layer(port))))

    yield from fx.gen(body).pipe(fx.provide(shared_storage))


def cast_any(value: object) -> Any:
    return value
