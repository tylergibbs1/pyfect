"""The server half of the runner protocol (Effect's ``RunnerServer``):
handlers for the ``Runners.Rpcs`` that other runners send, handing each
message to ``Sharding`` and answering persisted requests from
``MessageStorage``. ``layer`` serves them over the ``ServerProtocol`` in
the context; ``layer_with_clients`` adds ``Sharding`` and the RPC
``Runners``, and ``layer_client_only`` gives a process that serves
nothing and owns no shards its own ``Sharding`` and ``Runners``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Never, cast

from pyfect import layer as layer_
from pyfect._core import Effect, _WithFiber
from pyfect._fiber import Fiber
from pyfect.cause import Cause
from pyfect.cluster import envelope as envelope_
from pyfect.cluster import reply as reply_
from pyfect.cluster import runner_health, runners
from pyfect.cluster import sharding as sharding_
from pyfect.cluster.cluster_error import (
    AlreadyProcessingMessage,
    EntityNotAssignedToRunner,
    MalformedMessage,
)
from pyfect.cluster.message import Incoming, IncomingEnvelope, IncomingRequest
from pyfect.cluster.message_storage import MessageStorage, MessageStorageService
from pyfect.cluster.reply import ReplyWithContext
from pyfect.cluster.runner_health import RunnerHealth
from pyfect.cluster.runner_storage import RunnerStorage
from pyfect.cluster.runners import (
    EnvelopePayload,
    NotifyPayload,
    RequestPayload,
    RpcClientProtocol,
    Rpcs,
    Runners,
)
from pyfect.cluster.sharding import Sharding, ShardingService
from pyfect.cluster.sharding_config import ShardingConfig, ShardingConfigService
from pyfect.effect import callback, catch_tag, fail_cause, gen, service_option, succeed
from pyfect.errors import Done
from pyfect.exit import Exit, Failure
from pyfect.layer import Layer
from pyfect.queue import Queue
from pyfect.rpc import RpcRequest
from pyfect.rpc.group import HandlersFor
from pyfect.rpc.serialization import CodecFor
from pyfect.rpc.server import ServerOptions, ServerProtocol
from pyfect.rpc.server import layer as server_layer
from pyfect.scope import CloseableScope, Scope, fork_scoped

_VOID: Effect[None] = succeed(None)

type _Encoded = Effect[reply_.Encoded, EntityNotAssignedToRunner]
type _Resume = Callable[[_Encoded], None]


def _respond_nothing(_: ReplyWithContext) -> Effect[None]:
    return _VOID


def _ignore_already_processing(_: AlreadyProcessingMessage) -> Effect[None]:
    return _VOID


_request_scope: Effect[CloseableScope | None] = service_option(Scope).map(
    lambda found: None if found is None else found.value
)
"""The scope of the request being handled (the server gives each one)."""


def _defect_reply(
    reply: ReplyWithContext, defect: BaseException, codec_for: CodecFor
) -> Effect[reply_.Encoded]:
    fallback = ReplyWithContext.from_defect(
        id=reply.reply.id, request_id=reply.reply.request_id, defect=defect
    )
    return reply_.serialize(fallback, codec_for).or_die()


@dataclass(frozen=True, slots=True)
class _Handlers:
    sharding: ShardingService
    storage: MessageStorageService
    codec_for: CodecFor

    def incoming(
        self,
        request: envelope_.PartialRequest,
        caller_scope: CloseableScope | None,
        respond: Callable[[ReplyWithContext], Effect[None, Any]],
    ) -> IncomingRequest:
        return IncomingRequest(
            envelope=request,
            last_sent_reply=None,
            codec_for=self.codec_for,
            caller_scope=caller_scope,
            respond=respond,
        )

    def notify(self, request: RpcRequest[NotifyPayload]) -> Effect[None, Any]:
        envelope = request.payload["envelope"]
        message: Incoming = (
            self.incoming(envelope, None, _respond_nothing)
            if isinstance(envelope, envelope_.Request)
            else IncomingEnvelope(envelope=envelope)
        )
        if request.payload["persisted"]:
            return self.sharding.notify(message)
        return self.sharding.send(message)

    def effect(self, request: RpcRequest[RequestPayload]) -> Effect[reply_.Encoded, Any]:
        sharding = self.sharding

        @gen
        def run():
            caller_scope = yield from _request_scope
            pending: list[_Encoded] = []
            resumes: list[_Resume] = []

            def respond(reply: ReplyWithContext) -> Effect[None]:
                encoded = reply_.serialize_or_defect(reply, self.codec_for)
                if resumes:
                    resumes[0](encoded)
                else:
                    pending.append(encoded)
                return _VOID

            message = self.incoming(request.payload["request"], caller_scope, respond)
            if request.payload["persisted"]:
                return (yield from self.await_persisted(message, resumes))
            yield from sharding.send(message)

            def register(resume: _Resume) -> None:
                if pending:
                    resume(pending[0])
                else:
                    resumes.append(resume)

            return (yield from callback(register))

        return run

    def await_persisted(self, message: IncomingRequest, resumes: list[_Resume]) -> _Encoded:
        """The reply to a persisted request, through a reply handler on
        storage, once sharding has read the request."""

        def body(parent: Fiber[Any, Any]) -> _Encoded:
            def register(resume: _Resume) -> Effect[None]:
                resumes.append(resume)

                def on_exit(exit: Exit[Any, Any]) -> None:
                    if isinstance(exit, Failure):
                        resume(fail_cause(exit.cause))

                handler = parent._fork(
                    self.storage.register_reply_handler(message),
                    daemon=True,
                    start_immediately=True,
                )
                handler.add_observer_unsafe(on_exit)
                notified = self.sharding.notify(message, wait_until_read=True).pipe(
                    catch_tag(AlreadyProcessingMessage, _ignore_already_processing)
                )
                parent._fork(notified, daemon=True, start_immediately=True).add_observer_unsafe(
                    on_exit
                )
                return handler.interrupt()

            return callback(register)

        return _WithFiber(body)

    def stream(
        self, request: RpcRequest[RequestPayload]
    ) -> Effect[Queue[reply_.Encoded, EntityNotAssignedToRunner | Done], Any, Scope]:
        codec_for = self.codec_for

        @gen
        def run():
            caller_scope = yield from _request_scope
            queue = yield from Queue[reply_.Encoded, EntityNotAssignedToRunner | Done].unbounded()

            def offer(encoded: reply_.Encoded, last: bool) -> None:
                queue.offer_unsafe(encoded)
                if last:
                    cast("Queue[reply_.Encoded, Done]", queue).end_unsafe()

            def respond(reply: ReplyWithContext) -> Effect[None]:
                def malformed(error: MalformedMessage) -> Effect[None]:
                    # The fallback defect reply is terminal: end the stream.
                    return _defect_reply(reply, error, codec_for).map(
                        lambda encoded: offer(encoded, True)
                    )

                return (
                    reply_.serialize(reply, codec_for)
                    .map(lambda encoded: offer(encoded, encoded["_tag"] == "WithExit"))
                    .pipe(catch_tag(MalformedMessage, malformed))
                )

            message = self.incoming(request.payload["request"], caller_scope, respond)
            if request.payload["persisted"]:

                def failed(cause: Cause[EntityNotAssignedToRunner]) -> Effect[None]:
                    return queue.fail_cause(cause).as_void()

                handler = self.storage.register_reply_handler(message).on_error(failed)
                yield from fork_scoped(handler)
                yield from self.sharding.notify(message, wait_until_read=True)
            else:
                yield from self.sharding.send(message)
            return queue

        return run

    def envelope(self, request: RpcRequest[EnvelopePayload]) -> Effect[None, Any]:
        return self.sharding.send(IncomingEnvelope(envelope=request.payload["envelope"]))


@gen
def _handlers():
    sharding = yield from Sharding()
    storage = yield from MessageStorage()
    protocol = yield from ServerProtocol()
    handlers = _Handlers(sharding, storage, protocol.codec_for)
    return (
        Rpcs.handlers()
        .handle(Rpcs.ping)(lambda _: _VOID)
        .handle(Rpcs.notify)(handlers.notify)
        .handle(Rpcs.effect)(handlers.effect)
        .handle(Rpcs.stream)(handlers.stream)
        .handle(Rpcs.envelope)(handlers.envelope)
    )


layer_handlers: Layer[HandlersFor[Rpcs], Never, Sharding | MessageStorage | ServerProtocol] = (
    Rpcs.to_layer_effect(_handlers)
)
"""The handlers of the runner protocol (Effect's ``layerHandlers``)."""

layer: Layer[Never, Never, ServerProtocol | Sharding | MessageStorage] = server_layer(
    Rpcs,
    ServerOptions(span_prefix="RunnerServer", disable_tracing=True, disable_fatal_defects=True),
).pipe(layer_.provide(layer_handlers))
"""A runner server over the ``ServerProtocol`` in the context (Effect's
``RunnerServer.layer``): it answers pings and hands the messages of other
runners to ``Sharding``."""


layer_with_clients: Layer[
    Sharding | Runners,
    Never,
    ServerProtocol
    | ShardingConfig
    | RpcClientProtocol
    | MessageStorage
    | RunnerStorage
    | RunnerHealth,
] = layer.pipe(layer_.provide_merge(sharding_.layer)).pipe(layer_.provide_merge(runners.layer_rpc))
"""A runner server with the ``Sharding`` and RPC ``Runners`` it serves
(Effect's ``layerWithClients``)."""


def _client_only(config: ShardingConfigService) -> ShardingConfigService:
    return replace(config, runner_address=None)


layer_client_only: Layer[
    Sharding | Runners,
    Never,
    ShardingConfig | RpcClientProtocol | MessageStorage | RunnerStorage,
] = (
    sharding_.layer.pipe(layer_.provide_merge(runners.layer_rpc))
    .pipe(layer_.provide(runner_health.layer_noop))
    .pipe(layer_.provide(layer_.effect(ShardingConfig, ShardingConfig().map(_client_only))))
)
"""``Sharding`` and ``Runners`` for a process that sends to the cluster
but serves no runner RPCs and owns no shards: its ``runner_address`` is
cleared (Effect's ``layerClientOnly``)."""

__all__ = ["layer", "layer_client_only", "layer_handlers", "layer_with_clients"]
