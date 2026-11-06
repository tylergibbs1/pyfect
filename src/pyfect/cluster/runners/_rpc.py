"""Runners over RPC (Effect's ``Runners.makeRpc``): one client per runner
address, kept three minutes after its last use, speaking the ``Rpcs``
protocol that ``runner_server`` serves."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never, TypedDict, cast

from pyfect import exit as Exit
from pyfect import layer as layer_
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.cluster import envelope as envelope_
from pyfect.cluster import reply as reply_
from pyfect.cluster import snowflake
from pyfect.cluster.cluster_error import (
    AlreadyProcessingMessage,
    EntityNotAssignedToRunner,
    MailboxFull,
    MalformedMessage,
    RunnerUnavailable,
)
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.message import (
    Outgoing,
    OutgoingEnvelope,
    OutgoingRequest,
    serialize_request,
)
from pyfect.cluster.message_storage import MessageStorage
from pyfect.cluster.reply import Reply, WithExit
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.runners._local import make
from pyfect.cluster.runners._service import (
    RpcClientProtocol,
    RpcClientProtocolService,
    Runners,
    RunnersService,
    RunnersTransport,
    SendError,
)
from pyfect.cluster.sharding_config import ShardingConfig
from pyfect.cluster.snowflake import Generator
from pyfect.effect import catch_tag, fail, gen, provide_context, provide_service, succeed
from pyfect.errors import Done
from pyfect.layer import Layer
from pyfect.queue import Dequeue
from pyfect.rc_map import RcMap
from pyfect.rpc import make as make_rpc
from pyfect.rpc.client import ClientOptions, ClientProtocol
from pyfect.rpc.client import make as make_client
from pyfect.rpc.client_error import RpcClientError
from pyfect.rpc.group import RpcGroup
from pyfect.rpc.serialization import CodecFor
from pyfect.scope import Scope, scoped

_VOID: Effect[None] = succeed(None)

ReplyEncodedSchema = cast("S.Codec[reply_.OnWire, Any, Never, Never]", envelope_.OpaqueHole)
"""A reply already encoded by the protocol's codec (Effect's
``Reply.Encoded``, an opaque hole)."""

_errors = S.Union(EntityNotAssignedToRunner, MailboxFull, AlreadyProcessingMessage)


class NotifyPayload(TypedDict):
    envelope: envelope_.Partial
    persisted: bool


class RequestPayload(TypedDict):
    request: envelope_.PartialRequest
    persisted: bool


class EnvelopePayload(TypedDict):
    envelope: envelope_.AckChunk | envelope_.Interrupt
    persisted: bool


class Rpcs(RpcGroup):
    """The runner-to-runner protocol."""

    ping = make_rpc("Ping")
    notify = make_rpc(
        "Notify",
        payload=S.Struct(NotifyPayload, envelope=envelope_.PartialSchema),
        error=_errors,
    )
    effect = make_rpc(
        "Effect",
        payload=S.Struct(RequestPayload, request=envelope_.PartialRequestSchema),
        success=ReplyEncodedSchema,
        error=_errors,
    )
    stream = make_rpc(
        "Stream",
        payload=S.Struct(RequestPayload, request=envelope_.PartialRequestSchema),
        success=ReplyEncodedSchema,
        error=_errors,
        stream=True,
    )
    envelope = make_rpc(
        "Envelope",
        payload=S.Struct(
            EnvelopePayload,
            envelope=S.Union(envelope_.AckChunkSchema, envelope_.InterruptSchema),
        ),
        error=_errors,
    )


make_rpc_client: Effect[Rpcs, Never, ClientProtocol | Scope] = make_client(
    Rpcs, ClientOptions(span_prefix="Runners", disable_tracing=True)
)
"""A client of ``Rpcs`` over the ``ClientProtocol`` in the context."""


def _unavailable(address: RunnerAddress) -> Effect[Never, RunnerUnavailable]:
    return fail(RunnerUnavailable(address=address))


def _transport_unavailable(address: RunnerAddress) -> Any:
    return catch_tag(RpcClientError, lambda _: _unavailable(address))


def _make_rpc():
    protocol = yield from RpcClientProtocol()
    snowflakes = yield from Generator()

    clients: RcMap[RunnerAddress, tuple[Rpcs, CodecFor]] = yield from RcMap.make(
        _lookup_in(protocol), idle_time_to_live=180.0
    )

    def ping(address: RunnerAddress) -> Effect[None, RunnerUnavailable]:
        return scoped(
            clients.get(address)
            .flat_map(lambda found: found[0].ping())
            .catch_cause(lambda _: clients.invalidate(address).and_then(_unavailable(address)))
        )

    def respond_with_defect(message: OutgoingRequest, defect: BaseException) -> Effect[None]:
        return message.respond(
            WithExit(
                id=snowflakes.next_unsafe(),
                request_id=message.envelope.request_id,
                exit=Exit.die(defect),
            )
        )

    def send(address: RunnerAddress, message: Outgoing) -> Effect[None, SendError]:
        persisted = message.rpc.annotations.get(Persisted)
        if isinstance(message, OutgoingEnvelope):
            sent = clients.get(address).flat_map(
                lambda found: found[0].envelope(
                    {"envelope": message.envelope, "persisted": persisted}
                )
            )
            return scoped(sent).pipe(_transport_unavailable(address))
        request_message = message

        # Persisted requests recover their reply from storage through
        # ``RunnerUnavailable``; volatile ones get the defect as their reply.
        def on_defect(defect: BaseException) -> Effect[None, RunnerUnavailable]:
            if persisted:
                return _unavailable(address)
            return respond_with_defect(request_message, defect)

        def on_malformed(error: MalformedMessage) -> Effect[None]:
            return respond_with_defect(request_message, error)

        def decode(codec_for: CodecFor, encoded: object) -> Effect[Reply]:
            return reply_.decode(
                request_message.rpc, codec_for, encoded, request_message.context
            ).or_die()

        def call(found: tuple[Rpcs, CodecFor]) -> Effect[None, SendError, Scope]:
            client, codec_for = found

            def unary(request: envelope_.PartialRequest) -> Effect[None, SendError]:
                return (
                    client.effect({"request": request, "persisted": persisted})
                    .flat_map(lambda encoded: decode(codec_for, encoded))
                    .flat_map(request_message.respond)
                    .pipe(_transport_unavailable(address))
                    .catch_defect(on_defect)
                )

            def streamed(request: envelope_.PartialRequest) -> Effect[None, SendError, Scope]:
                def drain(queue: Dequeue[object, Any]) -> Effect[None, SendError]:
                    taken: Effect[Never, Any] = (
                        queue.take()
                        .flat_map(lambda encoded: decode(codec_for, encoded))
                        .flat_map(request_message.respond)
                        .forever()
                    )
                    return (
                        taken.pipe(provide_context(request_message.context))
                        .pipe(catch_tag(Done, lambda _: _VOID))
                        .pipe(_transport_unavailable(address))
                        .catch_defect(on_defect)
                    )

                return client.stream(
                    {"request": request, "persisted": persisted}, as_queue=True
                ).flat_map(drain)

            on_success = streamed if request_message.rpc.is_stream else unary
            return serialize_request(request_message, codec_for).match_effect(
                on_failure=on_malformed, on_success=on_success
            )

        return scoped(clients.get(address).flat_map(call))

    def notify(
        address: RunnerAddress | None, message: Outgoing, _discard: bool
    ) -> Effect[None, SendError]:
        if address is None:
            return _VOID
        target = address
        persisted = message.rpc.annotations.get(Persisted)

        def encode(codec_for: CodecFor) -> Effect[envelope_.Partial]:
            if isinstance(message, OutgoingRequest):
                return serialize_request(message, codec_for).or_die()
            return succeed(message.envelope)

        sent = clients.get(target).flat_map(
            lambda found: encode(found[1]).flat_map(
                lambda envelope: found[0].notify({"envelope": envelope, "persisted": persisted})
            )
        )
        notified = scoped(sent).pipe(_transport_unavailable(target))
        return notified.ignore() if persisted else notified

    return (
        yield from make(
            RunnersTransport(
                codec_for=protocol.codec_for,
                ping=ping,
                send=send,
                notify=notify,
                on_runner_unavailable=clients.invalidate,
            )
        )
    )


def _lookup_in(
    protocol: RpcClientProtocolService,
) -> Callable[[RunnerAddress], Effect[tuple[Rpcs, CodecFor], Never, Scope]]:
    return lambda address: _lookup(protocol, address)


def _lookup(
    protocol: RpcClientProtocolService, address: RunnerAddress
) -> Effect[tuple[Rpcs, CodecFor], Never, Scope]:
    @gen
    def run():
        client_protocol = yield from protocol.make(address)
        client = yield from make_rpc_client.pipe(provide_service(ClientProtocol, client_protocol))
        return client, client_protocol.codec_for

    return run


make_rpc_runners: Effect[
    RunnersService,
    Never,
    Scope | RpcClientProtocol | MessageStorage | Generator | ShardingConfig,
] = gen(_make_rpc)
"""Runners over RPC through the ``RpcClientProtocol`` (Effect's
``Runners.makeRpc``)."""

layer_rpc: Layer[Runners, Never, MessageStorage | RpcClientProtocol | ShardingConfig] = (
    layer_.effect(Runners, make_rpc_runners).pipe(layer_.provide(snowflake.layer_generator))
)
"""``make_rpc_runners`` as a layer, with its own snowflake generator."""

__all__ = [
    "EnvelopePayload",
    "NotifyPayload",
    "ReplyEncodedSchema",
    "RequestPayload",
    "Rpcs",
    "layer_rpc",
    "make_rpc_client",
    "make_rpc_runners",
]
