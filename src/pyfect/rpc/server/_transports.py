"""The transports of an RPC server: sockets (TCP, WebSocket) and HTTP
(Effect's ``makeSocketProtocol`` and ``makeProtocolWithHttpEffect``)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Never, cast

from pyfect._core import Effect
from pyfect.effect import fail, gen, succeed, suspend
from pyfect.errors import Done
from pyfect.http.server_request import HttpServerRequest
from pyfect.http.server_response import HttpServerResponse, empty, text
from pyfect.http.server_response import stream as stream_response
from pyfect.queue import Queue
from pyfect.rpc.message import RequestId, response_defect_encoded
from pyfect.rpc.serialization import (
    Frame,
    MaxBufferSizeExceeded,
    Parser,
    RpcSerialization,
    RpcSerializationService,
    encode_text,
)
from pyfect.rpc.server._protocol import (
    Message,
    ProtocolParts,
    ServerProtocolService,
    WriteRequest,
    with_run,
)
from pyfect.rpc.server._serialized import encode_defect_for
from pyfect.scope import Scope, fork_scoped, scoped
from pyfect.socket import CloseEvent, SocketCloseError, SocketError, SocketService, Writer
from pyfect.socket.server import SocketServer
from pyfect.stream import Stream, from_iterable, from_queue

_VOID: Effect[None] = succeed(None)

type BufferSize = int | Literal["unbounded"]
type RequestHeaders = tuple[tuple[str, str], ...]


def _with_headers(message: Message, headers: RequestHeaders) -> Message:
    """A request with the transport's headers before its own."""
    if message.get("_tag") != "Request" or not headers:
        return message
    own = cast("list[Any]", list(message.get("headers") or ()))
    return {**message, "headers": [*headers, *own]}


# --- sockets ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SocketProtocol:
    """A server protocol over sockets: ``on_socket`` serves one connection
    (until it closes); the ``protocol`` is the server's side."""

    protocol: ServerProtocolService
    on_socket: Callable[[SocketService, RequestHeaders], Effect[None, Never, Scope]]


def make_socket_protocol() -> Effect[SocketProtocol, Never, RpcSerialization]:
    @gen
    def make():
        serialization = yield from RpcSerialization()
        encode_defect = encode_defect_for(serialization.codec_for)
        disconnects = yield from Queue[int, Never].unbounded()
        clients: dict[int, Callable[[Message], Effect[None]]] = {}
        ids = iter(range(1 << 62))
        writes: list[WriteRequest] = []

        def on_socket(socket: SocketService, headers: RequestHeaders) -> Effect[None, Never, Scope]:
            @gen
            def serve():
                scope = yield from Scope()
                parser = serialization.make_unsafe()
                client_id = next(ids)

                def leave(_: object) -> Effect[None]:
                    clients.pop(client_id, None)
                    return disconnects.offer(client_id).as_void()

                yield from scope.add_finalizer(leave)
                writer = yield from socket.writer
                clients[client_id] = lambda response: _socket_write(
                    writer, parser, encode_defect, response
                )

                def process(data: Frame) -> Effect[None, SocketError]:
                    try:
                        decoded = parser.decode(data)
                    except MaxBufferSizeExceeded as cause:
                        return writer.write(CloseEvent(1009, str(cause)))
                    except Exception as cause:
                        defect = parser.encode(response_defect_encoded(encode_defect(cause)))
                        return _VOID if defect is None else writer.write(defect)

                    @gen
                    def each():
                        for message in decoded:
                            yield from writes[0](
                                client_id, _with_headers(cast("Message", message), headers)
                            )

                    return each

                @gen
                def read():
                    reader = yield from socket.reader
                    while True:
                        frames = yield from reader.pull
                        for frame in frames:
                            yield from process(frame)

                def closed(error: SocketError) -> Effect[None, SocketError]:
                    return _VOID if isinstance(error.reason, SocketCloseError) else fail(error)

                yield from read.catch_all(closed).or_die()

            return serve

        def send(client_id: int, response: Message) -> Effect[None]:
            write = clients.get(client_id)
            return _VOID if write is None else write(response)

        def parts(write: WriteRequest) -> Effect[ProtocolParts]:
            writes.append(write)
            return succeed(
                ProtocolParts(
                    disconnects=disconnects,
                    send=send,
                    end=lambda _: _VOID,
                    supports_ack=True,
                    supports_span_propagation=True,
                    codec_for=serialization.codec_for,
                )
            )

        protocol = yield from with_run(parts)
        return SocketProtocol(protocol, on_socket)

    return make


def _socket_write(
    writer: Writer, parser: Parser, encode_defect: Callable[[object], object], response: Message
) -> Effect[None]:
    try:
        encoded = parser.encode(response)
    except Exception as cause:
        encoded = parser.encode(response_defect_encoded(encode_defect(cause)))
    if encoded is None:
        return _VOID
    return writer.write(encoded).or_die()


def make_protocol_socket_server() -> Effect[
    ServerProtocolService, Never, RpcSerialization | SocketServer | Scope
]:
    """A server protocol over the connections of the ``SocketServer``."""

    @gen
    def make():
        server = yield from SocketServer()
        made = yield from make_socket_protocol()
        yield from fork_scoped(server.run(lambda socket: scoped(made.on_socket(socket, ()))))
        return made.protocol

    return make


# --- WebSocket and HTTP ----------------------------------------------------------------


type HttpEffect = Effect[HttpServerResponse, Never, Scope | HttpServerRequest]


@dataclass(frozen=True, slots=True)
class HttpProtocol:
    """A server protocol and the HTTP handler feeding it."""

    protocol: ServerProtocolService
    http_effect: HttpEffect


def _request_headers(request: Any) -> RequestHeaders:
    return tuple((k, v) for k, v in request.headers.items())


def make_protocol_with_http_effect_websocket() -> Effect[HttpProtocol, Never, RpcSerialization]:
    """A server protocol over WebSockets, upgraded by its HTTP handler."""

    @gen
    def make():
        made = yield from make_socket_protocol()

        @gen
        def handle():
            request = yield from HttpServerRequest()
            socket = yield from request.upgrade.or_die()
            yield from made.on_socket(socket, _request_headers(request))
            return empty()

        return HttpProtocol(made.protocol, handle)

    return make


@dataclass(slots=True, eq=False)
class _HttpClient:
    write: Callable[[Message], Effect[None]]
    end: Effect[None]


def make_protocol_with_http_effect(
    *, stream_buffer_size: BufferSize = 16
) -> Effect[HttpProtocol, Never, RpcSerialization]:
    """A server protocol over HTTP POSTs: each request body is a client's
    messages; the response holds its responses (streamed as they come for
    a framed serialization)."""

    @gen
    def make():
        serialization = yield from RpcSerialization()
        encode_defect = encode_defect_for(serialization.codec_for)
        disconnects = yield from Queue[int, Never].unbounded()
        clients: dict[int, _HttpClient] = {}
        ids = iter(range(1 << 62))
        writes: list[WriteRequest] = []

        def parts(write: WriteRequest) -> Effect[ProtocolParts]:
            writes.append(write)

            def send(client_id: int, response: Message) -> Effect[None]:
                client = clients.get(client_id)
                return _VOID if client is None else client.write(response)

            def end(client_id: int) -> Effect[None]:
                client = clients.get(client_id)
                return _VOID if client is None else client.end

            return succeed(
                ProtocolParts(
                    disconnects=disconnects,
                    send=send,
                    end=end,
                    supports_ack=False,
                    supports_span_propagation=False,
                    codec_for=serialization.codec_for,
                )
            )

        protocol = yield from with_run(parts)
        handler = _HttpHandler(
            serialization,
            encode_defect=encode_defect,
            disconnects=disconnects,
            clients=clients,
            ids=ids,
            writes=writes,
            buffer=stream_buffer_size,
        )
        return HttpProtocol(protocol, handler.handle())

    return make


class _HttpHandler:
    __slots__ = (
        "_buffer",
        "_clients",
        "_disconnects",
        "_encode_defect",
        "_ids",
        "_serialization",
        "_writes",
    )

    def __init__(
        self,
        serialization: RpcSerializationService,
        *,
        encode_defect: Callable[[object], object],
        disconnects: Queue[int, Never],
        clients: dict[int, _HttpClient],
        ids: Any,
        writes: list[WriteRequest],
        buffer: BufferSize,
    ) -> None:
        self._serialization = serialization
        self._encode_defect = encode_defect
        self._disconnects = disconnects
        self._clients = clients
        self._ids = ids
        self._writes = writes
        self._buffer = buffer

    def handle(self) -> HttpEffect:
        serialization = self._serialization
        framed = serialization.includes_framing

        @gen
        def run():
            request = yield from HttpServerRequest()
            scope = yield from Scope()
            data = yield from request.text.or_die()
            client_id: int = next(self._ids)
            capacity = self._buffer if framed and isinstance(self._buffer, int) else None
            queue = yield from Queue[Any, Done].make(capacity)
            parser = serialization.make_unsafe()
            request_ids: list[RequestId] = []
            client = _HttpClient(self._writer(queue, parser), queue.end().as_void())

            def leave(_: object) -> Effect[None]:
                self._clients.pop(client_id, None)
                self._disconnects.unsafe_offer(client_id)
                if queue.unsafe_is_done():
                    return _VOID
                write = self._writes[0]

                @gen
                def interrupt_all():
                    yield from queue.shutdown()
                    for request_id in request_ids:
                        yield from write(client_id, {"_tag": "Interrupt", "requestId": request_id})

                return interrupt_all

            yield from scope.add_finalizer(leave)
            self._clients[client_id] = client
            headers = _request_headers(request)
            try:
                decoded = [cast("Message", m) for m in parser.decode(data)]
            except Exception as cause:
                decoded = []
                yield from client.write(response_defect_encoded(self._encode_defect(cause)))
            for message in decoded:
                if message.get("_tag") == "Request":
                    request_ids.append(message["id"])
                yield from self._writes[0](client_id, _with_headers(message, headers))
            yield from self._writes[0](client_id, {"_tag": "Eof"})
            content_type = serialization.content_type
            if not framed:
                collected: Effect[list[Any], Never] = queue.collect()
                responses: list[Any] = yield from collected.interruptible()
                encoded = parser.encode(responses) if responses else None
                return text("" if encoded is None else _as_text(encoded), content_type=content_type)
            take_all: Effect[list[Any], Never] = queue.take_all().catch_all(
                lambda _: succeed(list[Any]())
            )
            initial: list[Any] = yield from take_all.interruptible()
            chunks = [encode_text(c) for c in initial]
            if queue.unsafe_is_done():
                return text("".join(c.decode() for c in chunks), content_type=content_type)
            body: Stream[bytes, Never] = from_iterable(chunks).concat(
                from_queue(queue).map(encode_text)
            )
            return stream_response(body, content_type=content_type)

        return run

    def _writer(self, queue: Queue[Any, Done], parser: Parser) -> Callable[[Message], Effect[None]]:
        if not self._serialization.includes_framing:

            def buffered(response: Message) -> Effect[None]:
                if response.get("_tag") == "Request" and response.get("isNotification"):
                    return _VOID
                return queue.offer(response).as_void()

            return buffered

        def framed(response: Message) -> Effect[None]:
            def body() -> Effect[None]:
                try:
                    encoded = parser.encode(response)
                except Exception as cause:
                    encoded = parser.encode(response_defect_encoded(self._encode_defect(cause)))
                return _VOID if encoded is None else queue.offer(encoded).as_void()

            return suspend(body)

        return framed


def _as_text(frame: Frame) -> str:
    return frame if isinstance(frame, str) else frame.decode()


__all__ = [
    "HttpEffect",
    "HttpProtocol",
    "SocketProtocol",
    "make_protocol_socket_server",
    "make_protocol_with_http_effect",
    "make_protocol_with_http_effect_websocket",
    "make_socket_protocol",
]
