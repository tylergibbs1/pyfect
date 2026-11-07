"""The RPC client over a protocol (Effect's ``RpcClient.make``): encodes
the requests for the ``ClientProtocol`` and decodes its responses."""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Never, cast, overload

from pyfect import exit as Exit
from pyfect import schema as S
from pyfect._core import Effect, uninterruptible_mask
from pyfect._fiber import Fiber
from pyfect._layer_core import Layer
from pyfect._layer_for_life import with_layer
from pyfect.cause import Cause
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.effect import gen, interrupt, provide_context, succeed, suspend
from pyfect.rpc._rpc import AnyRpc, exit_schema, parse_options
from pyfect.rpc.client._core import ClientCore, ClientOptions, OnFromClient
from pyfect.rpc.client._core import make_no_serialization as make_core
from pyfect.rpc.client._protocol import ClientProtocol, ClientProtocolService, Message
from pyfect.rpc.client_error import RpcClientDefect, RpcClientError
from pyfect.rpc.group import RpcGroup
from pyfect.rpc.message import (
    Ack,
    Eof,
    Interrupt,
    Request,
    RequestId,
    ResponseChunk,
    ResponseDefect,
    ResponseExit,
)
from pyfect.rpc.schema import get_stream_schemas
from pyfect.scope import Scope, fork_scoped

_VOID: Effect[None] = succeed(None)
_client_ids = itertools.count()

type _Parse = Callable[[object], Effect[Any, S.SchemaError, Any]]


@dataclass(frozen=True, slots=True)
class _Schemas:
    decode_chunk: _Parse | None
    encode_payload: _Parse
    decode_exit: _Parse


def _schemas(protocol: ClientProtocolService, rpc: AnyRpc) -> _Schemas:
    codec_for = protocol.codec_for
    streams = get_stream_schemas(rpc.success_schema)
    options = parse_options(rpc)
    chunk = (
        None
        if streams is None
        else S.decode_unknown_effect(codec_for(S.NonEmptyArray(streams.success)), **options)
    )
    return _Schemas(
        chunk,
        S.encode_unknown_effect(codec_for(rpc.payload_schema), **options),
        S.decode_unknown_effect(codec_for(exit_schema(rpc)), **options),
    )


@dataclass(frozen=True, slots=True)
class _Entry:
    rpc: AnyRpc
    context: Context[Any]
    schemas: _Schemas


class _Serialized:
    __slots__ = (
        "_cache",
        "_closing",
        "_decode_defect",
        "_entries",
        "_group",
        "_id",
        "_protocol",
        "core",
    )

    def __init__(self, group: type[RpcGroup], protocol: ClientProtocolService) -> None:
        self._group = group
        self._protocol = protocol
        self._id = next(_client_ids)
        self._entries: dict[RequestId, _Entry] = {}
        self._cache: dict[str, _Schemas] = {}
        self._closing = Deferred[None, Never]()
        self._decode_defect = S.decode_sync(protocol.codec_for(S.Defect()))
        self.core: ClientCore | None = None

    def _core(self) -> ClientCore:
        core = self.core
        if core is None:
            raise RuntimeError("the RPC client is not made yet")
        return core

    def _schemas_of(self, rpc: AnyRpc) -> _Schemas:
        found = self._cache.get(rpc.tag)
        if found is None:
            found = self._cache[rpc.tag] = _schemas(self._protocol, rpc)
        return found

    def close(self) -> Effect[None]:
        """Stop sending requests, and tell the server to interrupt the ones
        still waiting: a call or stream consumed outside the client's scope
        is resumed by the core, not interrupted, so it sends no ``Interrupt``
        itself (Effect leaves them running on the server)."""

        @gen
        def interrupt_all():
            for request_id in list(self._entries):
                yield from self._interrupt_request(request_id).exit()

        return self._closing.succeed(None).flat_map(
            lambda _: interrupt_all.timeout("1 second").exit().as_void()
        )

    def _defect_of(self, encoded: object) -> BaseException:
        """The defect a server sent, or why it could not be decoded: this
        runs in the client's read fiber, which a raise would end."""
        try:
            return cast("BaseException", self._decode_defect(encoded))
        except S.SchemaError as error:
            return RpcClientDefect("Error decoding defect", error)

    def _interrupt_request(self, request_id: RequestId) -> Effect[None, RpcClientError]:
        if self._entries.pop(request_id, None) is None:
            return _VOID
        return self._protocol.send(self._id, {"_tag": "Interrupt", "requestId": request_id})

    # --- requests -----------------------------------------------------------------------

    def on_from_client(self, sent: OnFromClient) -> Effect[None, Any]:
        message = sent.message
        match message:
            case Request():
                return self._send_request(message)
            case Ack(request_id=request_id):
                if request_id not in self._entries:
                    return _VOID
                return self._protocol.send(self._id, {"_tag": "Ack", "requestId": request_id})
            case Interrupt(request_id=request_id):
                return self._interrupt_request(request_id)
            case Eof():
                return _VOID

    def _send_request(self, message: Request) -> Effect[None, Any]:
        rpc = self._group.rpcs[message.tag]
        fiber = Fiber.get_current()
        context = Context.empty() if fiber is None else fiber._context  # pyright: ignore[reportPrivateUsage]
        entry = _Entry(rpc, context, self._schemas_of(rpc))
        self._entries[message.id] = entry

        def send(payload: object) -> Effect[None, Any]:
            if self._closing.is_done_unsafe():
                self._entries.pop(message.id, None)
                return interrupt()
            encoded: dict[str, Any] = {
                "_tag": "Request",
                "id": message.id,
                "tag": message.tag,
                "payload": payload,
                "headers": [[k, v] for k, v in message.headers.items()],
            }
            if message.span_id is not None:
                encoded["traceId"] = message.trace_id
                encoded["spanId"] = message.span_id
                encoded["sampled"] = message.sampled
            return self._protocol.send(self._id, encoded)

        def forget(cause: Cause[Any]) -> Effect[None]:
            if not cause.has_interrupts_only:
                self._entries.pop(message.id, None)
            return _VOID

        encoded = entry.schemas.encode_payload(message.payload).pipe(provide_context(context))
        return encoded.or_die().flat_map(send).on_error(forget)

    # --- responses ----------------------------------------------------------------------

    def on_response(self, message: Message) -> Effect[None]:
        core = self._core()
        match message.get("_tag"):
            case "Chunk":
                return self._chunk(message)
            case "Exit":
                return self._exit(message)
            case "Defect":
                self._entries.clear()
                return suspend(
                    lambda: core.write(ResponseDefect(0, self._defect_of(message.get("defect"))))
                )
            case "ClientProtocolError":
                error = cast("RpcClientError", message["error"])
                ids = list(self._entries)
                self._entries.clear()
                failure = Exit.fail(error)

                @gen
                def deliver():
                    for request_id in ids:
                        yield from core.write(ResponseExit(0, request_id, failure))

                return deliver.uninterruptible()
            case _:
                return _VOID

    def _chunk(self, message: Message) -> Effect[None]:
        request_id: RequestId = message["requestId"]
        entry = self._entries.get(request_id)
        if entry is None or entry.schemas.decode_chunk is None:
            return _VOID
        core = self._core()
        decoded = entry.schemas.decode_chunk(message.get("values")).pipe(
            provide_context(entry.context)
        )

        def failed(cause: Cause[Any]) -> Effect[None]:
            written = core.write(ResponseExit(0, request_id, Exit.Failure(cause)))
            if cause.has_interrupts:
                return written
            stop = self._interrupt_request(request_id).ignore().race_first(self._closing.wait())
            return written.flat_map(lambda _: stop)

        written: Effect[None] = decoded.or_die().flat_map(
            lambda values: core.write(ResponseChunk(0, request_id, tuple(values)))
        )
        # Uninterruptible but for the decode and write: an interrupt during
        # the cleanup lands after the decode failure is recovered.
        return uninterruptible_mask(
            lambda restore: (
                restore(written)
                .on_error(failed)
                .catch_cause_if(lambda cause: not cause.has_interrupts, lambda _: _VOID)
            )
        )

    def _exit(self, message: Message) -> Effect[None]:
        request_id: RequestId = message["requestId"]
        entry = self._entries.pop(request_id, None)
        if entry is None:
            return _VOID
        core = self._core()
        decoded = entry.schemas.decode_exit(message.get("exit")).pipe(
            provide_context(entry.context)
        )
        return (
            decoded.or_die()
            .exit()
            .flat_map(
                lambda result: core.write(
                    ResponseExit(
                        0,
                        request_id,
                        result.value
                        if isinstance(result, Exit.Success)
                        else Exit.Failure(result.cause),
                    )
                )
            )
        )


@overload
def make[G: RpcGroup](
    group: type[G], options: ClientOptions | None = None
) -> Effect[G, Never, Scope | ClientProtocol]: ...
@overload
def make[G: RpcGroup, E, R](
    group: type[G], options: ClientOptions | None = None, *, layer: Layer[ClientProtocol, E, R]
) -> Effect[G, E, R | Scope]: ...
def make(
    group: type[RpcGroup],
    options: ClientOptions | None = None,
    *,
    layer: Layer[ClientProtocol, Any, Any] | None = None,
) -> Effect[Any, Any, Any]:
    """A client of ``group`` over the ``ClientProtocol`` in the context
    (Effect's ``RpcClient.make``), or over ``layer``, built into the
    caller's ``Scope``. The client is valid until that scope closes; a
    protocol provided to ``make(...)`` alone is released once the client
    is made, and its calls then fail with an ``RpcClientError``. Client
    middleware comes from the context too (``middleware.layer_client``)."""
    return with_layer(lambda: _make(group, options), layer)


def _make(
    group: type[RpcGroup], options: ClientOptions | None
) -> Effect[RpcGroup, Never, Scope | ClientProtocol]:
    @gen
    def run():
        protocol = yield from ClientProtocol()
        state = _Serialized(group, protocol)
        resolved = options or ClientOptions()
        core_options = ClientOptions(
            span_prefix=resolved.span_prefix,
            span_attributes=resolved.span_attributes,
            disable_tracing=resolved.disable_tracing,
            supports_ack=protocol.supports_ack,
            generate_request_id=resolved.generate_request_id,
        )
        client, core = yield from make_core(group, state.on_from_client, core_options)
        state.core = core
        listen = protocol.run(state._id, state.on_response)  # pyright: ignore[reportPrivateUsage]
        yield from fork_scoped(listen.catch_cause(lambda _: _VOID).interruptible())
        scope = yield from Scope()
        # Finalizers run in reverse order: this runs while the client still runs.
        yield from scope.add_finalizer(lambda _: state.close())
        return client

    return run


__all__ = ["make"]
