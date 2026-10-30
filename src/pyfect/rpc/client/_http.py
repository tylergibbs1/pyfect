"""The HTTP transport of an RPC client (Effect's ``makeProtocolHttp``):
each request is POSTed, alone or in a batch with the requests made with
it, and the response body holds the responses."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Never

from pyfect import exit as Exit
from pyfect._core import Effect
from pyfect.clock import sleep
from pyfect.deferred import Deferred
from pyfect.duration import Duration
from pyfect.effect import fail, gen, succeed, suspend
from pyfect.http import body as http_body
from pyfect.http.client import HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.latch import Latch
from pyfect.rpc.client._protocol import (
    ClientProtocolParts,
    ClientProtocolService,
    Message,
    WriteResponse,
    WriteTo,
    with_run_client,
)
from pyfect.rpc.client_error import RpcClientDefect, RpcClientError
from pyfect.rpc.message import ServerMessage, decode_from_server
from pyfect.rpc.serialization import Frame, RpcSerialization, RpcSerializationService
from pyfect.scope import CloseableScope, fork_in

_VOID: Effect[None] = succeed(None)

type _Pending = set[str] | None
"""The ids of an exchange's requests left without an exit, or ``None``
when the server sent no response at all."""


@dataclass(frozen=True, slots=True)
class Batch:
    """Send the requests a client makes within ``window`` of the first in
    one HTTP request, or as soon as there are ``max_size`` of them."""

    window: Duration
    max_size: int | None = None


def _defect(message: str, cause: object) -> RpcClientError:
    return RpcClientError(RpcClientDefect(message, cause))


def _http_error(error: object) -> RpcClientError:
    if isinstance(error, RpcClientError):
        return error
    if isinstance(error, HttpClientError):
        return RpcClientError(error)
    return _defect("HTTP request failed", error)


class _HttpExchange:
    """Sends requests in one HTTP request, writing each response as it is
    decoded."""

    __slots__ = ("_client", "_serialization", "_write")

    def __init__(
        self,
        client: HttpClientService[Any, Any],
        serialization: RpcSerializationService,
        write: WriteTo,
    ) -> None:
        self._client = client
        self._serialization = serialization
        self._write = write

    def send(self, client_id: int, requests: list[Message]) -> Effect[_Pending, RpcClientError]:
        serialization = self._serialization
        parser = serialization.make_unsafe()
        pending = {str(request["id"]) for request in requests}
        seen: list[bool] = []

        def on_response(response: ServerMessage) -> Effect[None]:
            seen.append(True)
            if response["_tag"] == "Exit":
                pending.discard(str(response["requestId"]))
            elif response["_tag"] == "Defect":
                # A defect ends every request of the client.
                pending.clear()
            return self._write(client_id, response)

        def decode(frame: Frame) -> Effect[list[ServerMessage], RpcClientError]:
            try:
                return succeed(decode_from_server(parser.decode(frame)))
            except Exception as cause:
                return fail(_defect("Error decoding HTTP response", cause))

        def each(responses: list[ServerMessage]) -> Effect[None]:
            @gen
            def run():
                for response in responses:
                    yield from on_response(response)

            return run

        @gen
        def exchange():
            encoded = parser.encode(requests[0] if len(requests) == 1 else requests)
            text = encoded if isinstance(encoded, str) else (encoded or b"").decode()
            body = http_body.text(text, serialization.content_type)
            response = yield from self._client.post("", body=body).map_error(_http_error)
            if not serialization.includes_framing:
                data = yield from response.text.map_error(_http_error)
                yield from decode(data).flat_map(each)
            else:
                yield from response.stream.map_error(_http_error).run_for_each(
                    lambda chunk: decode(chunk).flat_map(each)
                )
            return pending if seen else None

        return exchange


def _request_exit(request: Message, pending: _Pending) -> Effect[None, RpcClientError]:
    """How one request of an exchange ends, from what the exchange left."""
    if pending is None:
        return fail(_defect("Received empty HTTP response from RPC server", request))
    if str(request["id"]) in pending:
        return fail(_defect("HTTP response ended before RPC request completed", request))
    return _VOID


def _unbatched(
    exchange: _HttpExchange,
) -> Callable[[int, Message], Effect[None, RpcClientError]]:
    def send(client_id: int, request: Message) -> Effect[None, RpcClientError]:
        return exchange.send(client_id, [request]).flat_map(
            lambda pending: _request_exit(request, pending)
        )

    return send


@dataclass(eq=False)
class _Batch:
    requests: list[Message]
    full: Latch = field(default_factory=lambda: Latch(False))
    done: Deferred[_Pending, RpcClientError] = field(
        default_factory=Deferred[_Pending, RpcClientError]
    )


class _Batcher:
    """The open batch of each client. A batch runs in its client's scope,
    not in a caller, so interrupting one caller does not cancel the HTTP
    request of the others; the scope closes when the client stops."""

    __slots__ = ("_batches", "_exchange", "_options", "_scopes")

    def __init__(self, exchange: _HttpExchange, options: Batch) -> None:
        self._exchange = exchange
        self._options = options
        self._batches: dict[int, _Batch] = {}
        self._scopes: dict[int, CloseableScope] = {}

    def _close_batch(self, client_id: int, batch: _Batch) -> None:
        if self._batches.get(client_id) is batch:
            del self._batches[client_id]

    def _run(self, client_id: int, batch: _Batch) -> Effect[None]:
        def send() -> Effect[_Pending, RpcClientError]:
            self._close_batch(client_id, batch)
            return self._exchange.send(client_id, batch.requests)

        def settle(exit: Exit.Exit[_Pending, RpcClientError]) -> Effect[None]:
            self._close_batch(client_id, batch)
            return batch.done.done(exit).as_void()

        ready = sleep(self._options.window).race_first(batch.full.wait())
        return ready.flat_map(lambda _: suspend(send)).on_exit(settle).ignore()

    def send(self, client_id: int, request: Message) -> Effect[None, RpcClientError]:
        @gen
        def run():
            batch = self._batches.get(client_id)
            if batch is None:
                batch = _Batch([request])
                self._batches[client_id] = batch
                scope = self._scopes.get(client_id)
                if scope is None:
                    scope = self._scopes[client_id] = CloseableScope()
                yield from fork_in(self._run(client_id, batch), scope, start_immediately=True)
            else:
                batch.requests.append(request)
            if len(batch.requests) == self._options.max_size:
                self._close_batch(client_id, batch)
                batch.full.unsafe_open()
            pending = yield from batch.done.wait()
            return (yield from _request_exit(request, pending))

        return run

    def close(self, client_id: int) -> Effect[None]:
        scope = self._scopes.pop(client_id, None)
        return _VOID if scope is None else scope.close(Exit.succeed(None))


def make_protocol_http(
    client: HttpClientService[Any, Any], *, batch: Batch | None = None
) -> Effect[ClientProtocolService, Never, RpcSerialization]:
    """A client protocol POSTing to ``client`` (whose base URL is the
    server's): each request on its own, or with ``batch`` the requests a
    client makes together in one HTTP request."""

    def make() -> Effect[ClientProtocolService, Never, RpcSerialization]:
        batchers: list[_Batcher] = []

        def parts(
            write: WriteTo, _ids: set[int]
        ) -> Effect[ClientProtocolParts, Never, RpcSerialization]:
            def build(serialization: RpcSerializationService) -> ClientProtocolParts:
                exchange = _HttpExchange(client, serialization, write)
                if batch is None:
                    send = _unbatched(exchange)
                else:
                    batcher = _Batcher(exchange, batch)
                    batchers.append(batcher)
                    send = batcher.send

                def send_request(client_id: int, message: Message) -> Effect[None, RpcClientError]:
                    return send(client_id, message) if message.get("_tag") == "Request" else _VOID

                return ClientProtocolParts(send_request, False, serialization.codec_for)

            return RpcSerialization().map(build)

        def with_batches(protocol: ClientProtocolService) -> ClientProtocolService:
            if not batchers:
                return protocol
            batcher = batchers[0]

            def run(client_id: int, f: WriteResponse) -> Effect[Never]:
                return protocol.run(client_id, f).on_exit(lambda _: batcher.close(client_id))

            return ClientProtocolService(run, protocol.send, False, protocol.codec_for)

        return with_run_client(parts).map(with_batches)

    return suspend(make)


__all__ = ["Batch", "make_protocol_http"]
