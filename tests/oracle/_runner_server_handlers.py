"""The runner-server setup of Effect's ``RunnerServer.test.ts`` and of the
RunnerServer cases of ``Runners.test.ts``: ``RunnerServer.layerHandlers``
over ``Sharding.layer`` with memory storage, and requests addressed the way
a sending runner would."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Never, cast

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.cluster import (
    envelope,
    message_storage,
    runner_health,
    runner_server,
    runner_storage,
    runners,
    sharding,
    sharding_config,
    snowflake,
)
from pyfect.cluster.entity import Entity
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.cluster.message import IncomingRequest
from pyfect.cluster.runners import Rpcs
from pyfect.cluster.sharding import Sharding
from pyfect.cluster.snowflake import Generator
from pyfect.duration import millis
from pyfect.layer import Layer
from pyfect.queue import Queue
from pyfect.rpc.message import Request as RpcRequest
from pyfect.rpc.serialization import CodecFor
from pyfect.rpc.server import (
    RpcServer,
    ServerProtocol,
    ServerProtocolService,
    make_no_serialization,
)
from pyfect.scope import CloseableScope


def codec_for_json_string(schema: S.Top) -> S.Codec[Any, Any, Any, Any]:
    """A hole codec observably different from ``S.to_codec_json``: the entity
    payload and the replies become JSON strings on the wire."""
    return S.from_json_string(S.to_codec_json(schema))


def layer_protocol(codec_for: CodecFor) -> Layer[ServerProtocol]:
    def make(disconnects: Queue[int, Any]) -> ServerProtocolService:
        return ServerProtocolService(
            run=lambda _: fx.never,
            disconnects=cast("Queue[int]", disconnects),
            send=lambda _client, _message: fx.void,
            end=lambda _client: fx.void,
            supports_ack=False,
            supports_span_propagation=False,
            codec_for=codec_for,
        )

    return fx.layer.effect(ServerProtocol, Queue[int, Any].unbounded().map(make))


config = sharding_config.layer(
    replace(
        sharding_config.DEFAULTS,
        entity_mailbox_capacity=10,
        entity_termination_timeout=millis(0),
        entity_message_poll_interval=millis(5000),
        send_retry_interval=millis(100),
        refresh_assignments_interval=millis(0),
    )
)


def make_handlers(
    entities: Layer[Never, Never, Any], codec_for: CodecFor = S.to_codec_json
) -> Layer[Any]:
    return (
        runner_server.layer_handlers.pipe(fx.layer.provide(layer_protocol(codec_for)))
        .pipe(fx.layer.provide_merge(entities))
        .pipe(fx.layer.provide_merge(sharding.layer))
        .pipe(fx.layer.provide_merge(snowflake.layer_generator))
        .pipe(fx.layer.provide(runner_storage.layer_memory))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(fx.layer.provide_merge(message_storage.layer_memory))
        .pipe(fx.layer.provide(config))
    )


def make_request(
    entity: type[Entity], entity_id: str, *, tag: str = "ReproStream", payload: object = None
) -> fx.Effect[envelope.PartialRequest, Never, Sharding | Generator]:
    """A request for ``entity``'s single RPC, addressed the way a sending
    runner would."""

    @fx.gen
    def make():
        service = yield from Sharding()
        ids = yield from Generator()
        id_ = EntityId(entity_id)
        return envelope.make_request(
            request_id=ids.next_unsafe(),
            address=EntityAddress(
                shard_id=service.get_shard_id(id_, entity.get_shard_group(id_)),
                entity_type=EntityType(entity.type),
                entity_id=id_,
            ),
            tag=tag,
            payload=cast("object", {"id": 1} if payload is None else payload),
        )

    return make


def make_server() -> fx.Effect[RpcServer, Never, Any]:
    """A runner RPC server whose replies are discarded."""
    return make_no_serialization(Rpcs, lambda _: fx.void)


def write_request(
    server: RpcServer,
    tag: str,
    request: envelope.PartialRequest,
    *,
    persisted: bool = False,
    client_id: int = 0,
) -> fx.Effect[None]:
    return server.write(
        client_id,
        RpcRequest(
            id=str(request.request_id),
            tag=tag,
            payload={"request": request, "persisted": persisted},
        ),
    )


def incoming(
    request: envelope.PartialRequest, caller_scope: CloseableScope | None = None
) -> IncomingRequest:
    return IncomingRequest(
        envelope=request,
        last_sent_reply=None,
        respond=lambda _: fx.void,
        codec_for=S.to_codec_json,
        caller_scope=caller_scope,
    )


def live_timeout[A, E, R](effect: fx.Effect[A, E, R]) -> fx.Effect[A, Any, R]:
    return testing.with_live(effect.timeout("1 second"))
