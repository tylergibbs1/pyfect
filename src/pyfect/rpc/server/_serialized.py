"""The RPC server over a protocol (Effect's ``RpcServer.make``): decodes
the requests a ``ServerProtocol`` hands it and encodes the responses."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Never, cast

from pyfect import exit as Exit
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.cause import Cause
from pyfect.context import Context
from pyfect.effect import context, fail_cause, gen, provide_context, succeed, suspend
from pyfect.error_reporter import report
from pyfect.http.headers import Headers
from pyfect.layer import Layer, effect_discard
from pyfect.logger import log_debug
from pyfect.rpc._rpc import AnyRpc, exit_schema, handler_tag, parse_options
from pyfect.rpc.group import HandlersFor, RpcGroup
from pyfect.rpc.message import (
    PONG,
    Ack,
    ClientEnd,
    Eof,
    FromServer,
    Interrupt,
    Request,
    RequestId,
    ResponseChunk,
    ResponseDefect,
    ResponseExit,
    is_request_id,
    response_defect_encoded,
)
from pyfect.rpc.schema import get_stream_schemas
from pyfect.rpc.serialization import CodecFor
from pyfect.rpc.server._core import RpcServer, ServerOptions, make_no_serialization, unknown_tag
from pyfect.rpc.server._protocol import Message, ServerProtocol, ServerProtocolService
from pyfect.scope import Scope, fork_scoped, scoped

_VOID: Effect[None] = succeed(None)


type _Encode = Callable[[object], Effect[Any, S.SchemaError, Any]]


@dataclass(frozen=True, slots=True)
class _Codecs:
    tag: str
    decode: Callable[[object], Effect[Any, S.SchemaError, Any]]
    encode_chunk: Callable[[object], Effect[Any, S.SchemaError, Any]]
    encode_exit: Callable[[object], Effect[Any, S.SchemaError, Any]]
    context: Context[Any]


def _discard_codecs(codec_for: CodecFor, rpc: AnyRpc, codecs: _Codecs) -> _Codecs:
    """The codecs of a discarded call: its only successful exit is the
    acknowledgement, which carries no value, so its exits are encoded with a
    void success."""
    schema = exit_schema(rpc)
    void_exit = S.Exit(S.Void, schema.error, schema.defect)
    return _Codecs(
        codecs.tag,
        codecs.decode,
        codecs.encode_chunk,
        S.encode_unknown_effect(codec_for(void_exit), **parse_options(rpc)),
        codecs.context,
    )


def _drop_notification(reason: str) -> Effect[None]:
    """A notification has no reply to carry the error, so it is only logged."""
    return log_debug(f"Dropped RPC notification: {reason}").annotate_logs(
        {"module": "RpcServer", "method": "dropNotification"}
    )


def _rpc_codecs(codec_for: CodecFor, rpc: AnyRpc, context: Context[Any]) -> _Codecs:
    streams = get_stream_schemas(rpc.success_schema)
    options = parse_options(rpc)
    chunk = S.NonEmptyArray(S.Any if streams is None else streams.success)
    return _Codecs(
        rpc.tag,
        S.decode_unknown_effect(codec_for(rpc.payload_schema), **options),
        S.encode_unknown_effect(codec_for(chunk), **options),
        S.encode_unknown_effect(codec_for(exit_schema(rpc)), **options),
        context,
    )


def _defect_codecs(codec_for: CodecFor) -> tuple[Callable[[object], object], _Encode]:
    encode_defect = S.encode_sync(codec_for(S.Defect()))
    unknown_exit = S.encode_unknown_effect(codec_for(S.Exit(S.Never, S.Never, S.Defect())))
    return encode_defect, unknown_exit


def encode_defect_for(codec_for: CodecFor) -> Callable[[object], object]:
    """How a protocol writes a defect it hit itself."""
    return _defect_codecs(codec_for)[0]


def _headers(encoded: object) -> Headers | None:
    """A request's ``headers``: absent, pairs of strings or an object of
    strings (Effect's ``Headers.fromInput``); ``None`` for any other shape."""
    if encoded is None or isinstance(encoded, Headers):
        return encoded or Headers({})
    if isinstance(encoded, Mapping):
        pairs: list[object] = [
            list(item) for item in cast("Mapping[object, object]", encoded).items()
        ]
    elif isinstance(encoded, list | tuple):
        pairs = list(cast("Sequence[object]", encoded))
    else:
        return None
    out: dict[str, str] = {}
    for pair in pairs:
        if not isinstance(pair, list | tuple):
            return None
        match cast("Sequence[object]", pair):
            case [str() as name, str() as value]:
                out[name.lower()] = value
            case _:
                return None
    return Headers(out)


@dataclass(slots=True, eq=False)
class _Client:
    id: int
    codecs: dict[RequestId, _Codecs] = field(default_factory=dict[RequestId, _Codecs])


class _Serialized:
    __slots__ = (
        "_clients",
        "_codec_cache",
        "_discard_cache",
        "_encode_defect",
        "_group",
        "_notification_count",
        "_protocol",
        "_services",
        "_unknown_exit",
        "server",
    )

    def __init__(
        self, group: type[RpcGroup], protocol: ServerProtocolService, services: Context[Any]
    ) -> None:
        self._group = group
        self._protocol = protocol
        self._services = services
        self._clients: dict[int, _Client] = {}
        self._codec_cache: dict[str, _Codecs] = {}
        self._discard_cache: dict[str, _Codecs] = {}
        self._notification_count = 0
        self._encode_defect, self._unknown_exit = _defect_codecs(protocol.codec_for)
        self.server: RpcServer | None = None

    def _codecs(self, rpc: AnyRpc) -> _Codecs:
        found = self._codec_cache.get(rpc.tag)
        if found is None:
            entry = self._services.get_option(handler_tag(rpc))
            context = Context.empty() if entry is None else entry.value.context
            found = _rpc_codecs(self._protocol.codec_for, rpc, context)
            self._codec_cache[rpc.tag] = found
        return found

    def _reply_codecs(self, rpc: AnyRpc, codecs: _Codecs) -> _Codecs:
        found = self._discard_cache.get(rpc.tag)
        if found is None:
            found = _discard_codecs(self._protocol.codec_for, rpc, codecs)
            self._discard_cache[rpc.tag] = found
        return found

    def _server(self) -> RpcServer:
        server = self.server
        if server is None:
            raise RuntimeError("the RPC server is not running yet")
        return server

    # --- responses ------------------------------------------------------------------

    def on_from_server(self, response: FromServer) -> Effect[None]:
        client = self._clients.get(response.client_id)
        if client is None:
            return _VOID
        match response:
            case ResponseChunk(request_id=request_id, values=values):
                codecs = client.codecs.get(request_id)
                return self._encode_with(client, request_id, codecs, "Chunk", values)
            case ResponseExit(request_id=request_id, exit=exit):
                codecs = client.codecs.pop(request_id, None)
                return self._encode_with(client, request_id, codecs, "Exit", exit)
            case ResponseDefect(defect=defect):
                return self._send_defect(client, defect)
            case ClientEnd():
                self._clients.pop(response.client_id, None)
                return self._protocol.end(response.client_id)

    def _encode_with(
        self,
        client: _Client,
        request_id: RequestId,
        codecs: _Codecs | None,
        tag: str,
        value: object,
    ) -> Effect[None]:
        if codecs is None:
            return _VOID
        encode = codecs.encode_chunk if tag == "Chunk" else codecs.encode_exit
        return self._encode(client, request_id, codecs, encode(value), tag)

    def _encode(
        self,
        client: _Client,
        request_id: RequestId,
        codecs: _Codecs,
        encoded: Effect[Any, S.SchemaError, Any],
        tag: str,
    ) -> Effect[None]:
        failed_encode: list[bool] = []

        def envelope(value: object) -> Message:
            if tag == "Chunk":
                return {"_tag": "Chunk", "requestId": request_id, "values": value}
            return {"_tag": "Exit", "requestId": request_id, "exit": value}

        def encode_failed(error: S.SchemaError) -> Effect[Never]:
            defect = f'Failed to encode response for RPC "{codecs.tag}": {error}'
            failed_encode.append(True)
            cause: Cause[Never] = Exit.die(defect).cause
            return report(cause).flat_map(lambda _: fail_cause(cause))

        write: Effect[None, Any, Any] = (
            encoded.pipe(provide_context(codecs.context))
            .catch_all(encode_failed)
            .flat_map(lambda value: self._protocol.send(client.id, envelope(value)))
        )

        def recover(cause: Cause[Any]) -> Effect[None]:
            client.codecs.pop(request_id, None)
            then: Effect[None] = (
                fail_cause(cause)
                if failed_encode
                else self._server().write(client.id, Interrupt(request_id))
            )
            return self._send_request_defect(
                client, request_id, codecs.encode_exit, cause.squash()
            ).flat_map(lambda _: then)

        return write.catch_cause(recover)

    def _send_request_defect(
        self,
        client: _Client,
        request_id: RequestId,
        encode_exit: Callable[[object], Effect[Any, S.SchemaError, Any]],
        defect: object,
    ) -> Effect[None]:
        sent: Effect[None, Any, Any] = encode_exit(Exit.die(defect)).flat_map(
            lambda exit: self._protocol.send(
                client.id, {"_tag": "Exit", "requestId": request_id, "exit": exit}
            )
        )
        return sent.catch_cause(lambda cause: self._send_defect(client, cause.squash()))

    def _send_defect(self, client: _Client, defect: object) -> Effect[None]:
        def send() -> Effect[None]:
            return self._protocol.send(
                client.id, response_defect_encoded(self._encode_defect(defect))
            )

        return suspend(send).catch_cause(lambda _: _VOID)

    # --- requests -------------------------------------------------------------------

    def on_request(self, client_id: int, message: Message) -> Effect[None]:
        client = self._clients.get(client_id)
        if client is None:
            client = _Client(client_id)
            self._clients[client_id] = client
        server = self._server()
        tag = message.get("_tag")
        if tag == "Request":
            return self._request(client, message)
        if tag == "Ping":
            return self._protocol.send(client.id, PONG).catch_cause(
                lambda cause: self._send_defect(client, cause.squash())
            )
        control = _control_message(message)
        if control is None:
            return self._send_defect(client, unknown_tag(tag))
        return server.write(client_id, control)

    def _request(self, client: _Client, message: Message) -> Effect[None]:
        tag = message.get("tag", "")
        is_notification = message.get("isNotification") is True
        request_id: object
        if is_notification:
            # JSON-RPC notifications share an empty id, and no reply names one.
            request_id = f"@effect/rpc/notification/{self._notification_count}"
            self._notification_count += 1
        else:
            request_id = message.get("id")
            if not is_request_id(request_id):
                return self._send_defect(client, f"Invalid request id: {request_id}")
        rid: RequestId = request_id
        rpc = self._group.rpcs.get(tag) if isinstance(tag, str) else None
        if rpc is None:
            reason = unknown_tag(tag)
            if is_notification:
                return _drop_notification(reason)
            return self._send_request_defect(client, rid, self._unknown_exit, reason)
        codecs = self._codecs(rpc)
        is_discard = not is_notification and message.get("discard") is True
        reply = self._reply_codecs(rpc, codecs) if is_discard else codecs
        headers = _headers(message.get("headers"))
        if headers is None:
            reason = "Invalid request headers"
            if is_notification:
                return _drop_notification(reason)
            return self._send_request_defect(client, rid, reply.encode_exit, reason)

        def decoded(payload: object) -> Effect[None]:
            # Nothing is encoded for a notification, and only a reply would
            # remove its codecs.
            if not is_notification:
                client.codecs[rid] = reply
            request = Request(
                rid,
                rpc.tag,
                payload,
                headers,
                message.get("traceId"),
                message.get("spanId"),
                message.get("sampled"),
                is_notification=is_notification,
                discard=is_discard,
            )
            return self._server().write(client.id, request)

        def invalid(error: S.SchemaError) -> Effect[None]:
            if is_notification:
                return _drop_notification(str(error))
            return self._send_request_defect(client, rid, reply.encode_exit, str(error))

        return (
            codecs.decode(message.get("payload"))
            .pipe(provide_context(codecs.context))
            .match_effect(on_failure=invalid, on_success=decoded)
        )

    def disconnect(self, client_id: int) -> Effect[None]:
        self._clients.pop(client_id, None)
        return self._server().disconnect(client_id)


def _control_message(message: Message) -> Eof | Ack | Interrupt | None:
    match message.get("_tag"):
        case "Eof":
            return Eof()
        case "Ack":
            return Ack(message["requestId"])
        case "Interrupt":
            return Interrupt(message["requestId"])
        case _:
            return None


def make[G: RpcGroup](
    group: type[G], options: ServerOptions | None = None
) -> Effect[Never, Never, Scope | ServerProtocol | HandlersFor[G]]:
    """Run a server of ``group`` over the ``ServerProtocol`` in the
    context, until interrupted (Effect's ``RpcServer.make``)."""
    resolved = options or ServerOptions()

    @gen
    def run():
        protocol = yield from ServerProtocol()
        services = yield from context()
        state = _Serialized(group, protocol, services)
        server_options = ServerOptions(
            disable_tracing=resolved.disable_tracing,
            disable_span_propagation=not protocol.supports_span_propagation,
            span_prefix=resolved.span_prefix,
            span_attributes=resolved.span_attributes,
            concurrency=resolved.concurrency,
            disable_fatal_defects=resolved.disable_fatal_defects,
            disable_client_acks=not protocol.supports_ack,
        )
        state.server = yield from make_no_serialization(group, state.on_from_server, server_options)
        on_disconnect = resolved.on_disconnect

        def handle_disconnect(client_id: int) -> Effect[None, Never, Scope]:
            disconnected = state.disconnect(client_id)
            hook_of = on_disconnect
            if hook_of is None:
                return disconnected
            hook = suspend(lambda: hook_of(client_id)).ignore_cause(
                log="Unhandled", message="RpcServer onDisconnect hook failed"
            )
            # In the server's scope: a slow hook delays no other cleanup, and
            # pending hooks are interrupted when the server stops.
            return disconnected.flat_map(lambda _: fork_scoped(hook).as_void())

        @gen
        def disconnects():
            while True:
                client_id = yield from protocol.disconnects.take()
                yield from handle_disconnect(client_id)

        yield from fork_scoped(disconnects)
        return (yield from protocol.run(state.on_request))

    return run


def layer[G: RpcGroup](
    group: type[G], options: ServerOptions | None = None
) -> Layer[Never, Never, ServerProtocol | HandlersFor[G]]:
    """A server of ``group`` running while the layer is built (Effect's
    ``RpcServer.layer``)."""
    return effect_discard(fork_scoped(scoped(make(group, options))))


__all__ = ["encode_defect_for", "layer", "make"]
