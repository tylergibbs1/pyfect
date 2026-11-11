"""The MCP client's transports: a child process on stdio, or Streamable
HTTP. A transport sends a request and waits for its response, sends a
notification, and says which tools it can call."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Literal, Never, Self, cast, final

from pyfect import stream
from pyfect._core import Effect
from pyfect._service_copy import replaced
from pyfect.ai._mcp.client_wire import (
    cancelled,
    encode_message,
    failure,
    header_parameters,
    is_request,
    is_response,
    limit_error,
    media_type,
    parse_message,
    reply_to_server,
    routing_headers,
)
from pyfect.ai.mcp_client_error import (
    ClosedError,
    ConfigurationError,
    HttpError,
    McpClientError,
    ProtocolError,
    TransportError,
)
from pyfect.ai.mcp_protocol import ProtocolAdapter
from pyfect.ai.mcp_schema import JsonObject, RequestId, Tool, parse_request_id
from pyfect.byte_size import ByteSize
from pyfect.channel import LineTooLongError, split_lines_within
from pyfect.deferred import Deferred
from pyfect.duration import millis
from pyfect.effect import fail, gen, succeed, suspend, sync
from pyfect.encoding import sse
from pyfect.errors import Done
from pyfect.http import request as http_request
from pyfect.http.client import HttpClient
from pyfect.http.error import HttpClientError
from pyfect.http.response import HttpClientResponse, is_too_large, with_body_limit
from pyfect.process import ChildProcessSpawner, Command
from pyfect.queue import Queue
from pyfect.scope import Scope, add_finalizer

type ClientProtocolVersion = Literal["2025-11-25", "2026-07-28"]
type ClientProtocol = ProtocolAdapter[ClientProtocolVersion]

CLOSE_TIMEOUT = millis(5000)
DEFAULT_MAX_MESSAGE_BYTES = 16 * 1024 * 1024

_VOID: Effect[None] = succeed(None)


@final
class TransportService:
    """How a client reaches its server (Effect's ``McpClient.Transport``):
    ``stdio`` and ``http`` build one, and ``TransportService(protocol,
    request, notify, is_callable)`` makes one of three functions (a test
    double, say)."""

    __slots__ = ("_is_callable", "_notify", "_request", "protocol")

    protocol: ClientProtocol
    """The protocol adapter of the version the client speaks."""

    def __replace__(self, **changes: Any) -> Self:
        """A copy with ``changes`` to the constructor's arguments (``copy.replace``)."""
        return replaced(self, changes)

    def __init__(
        self,
        protocol: ClientProtocol,
        request: Callable[[JsonObject, Tool | None], Effect[JsonObject, McpClientError]],
        notify: Callable[[JsonObject], Effect[None, McpClientError]],
        is_callable: Callable[[Tool], bool],
    ) -> None:
        self.protocol = protocol
        self._request = request
        self._notify = notify
        self._is_callable = is_callable

    def request(self, message: JsonObject, tool: Tool | None) -> Effect[JsonObject, McpClientError]:
        """Send the JSON-RPC request ``message`` and wait for its response
        (a JSON-RPC error response included); ``tool`` supplies a tool
        call's routing headers. Fails with an ``McpClientError`` when the
        message cannot be sent or read, a message exceeds the size limit,
        the server answers an HTTP error status or no or a mismatched
        response, or the transport has closed. Interrupting it
        tells the server the request was cancelled (except ``initialize``,
        and on 2026-07-28 HTTP)."""
        return self._request(message, tool)

    def notify(self, message: JsonObject) -> Effect[None, McpClientError]:
        """Send the JSON-RPC notification ``message`` without waiting for a
        reply. Fails with an ``McpClientError`` when it cannot be sent, the
        server answers an HTTP error status, or the transport has closed."""
        return self._notify(message)

    def is_callable(self, tool: Tool) -> bool:
        """Whether this transport can route a call to ``tool``: always on
        stdio; on 2026-07-28 HTTP only when its header parameters are
        valid."""
        return self._is_callable(tool)


def message_limit(max_message_bytes: int | None) -> Effect[ByteSize, McpClientError]:
    limit = DEFAULT_MAX_MESSAGE_BYTES if max_message_bytes is None else max_message_bytes
    if limit <= 0:
        return fail(failure(ConfigurationError("maxMessageBytes must be a positive safe integer")))
    return succeed(ByteSize(limit))


class _Closing:
    """The first error a transport closed with, failing every later call."""

    def __init__(self) -> None:
        self.failed: McpClientError | None = None
        self.signal = Deferred[Never, McpClientError]()

    def close(self, error: McpClientError) -> Effect[None]:
        def run() -> Effect[None]:
            if self.failed is None:
                self.failed = error
            return self.signal.fail(self.failed).as_void()

        return suspend(run)

    def check(self) -> Effect[None, McpClientError]:
        return _VOID if self.failed is None else fail(self.failed)


def stdio(
    *, command: Command, protocol: ClientProtocol, max_message_bytes: int | None = None
) -> Effect[TransportService, McpClientError, ChildProcessSpawner | Scope]:
    """A transport to ``command``'s process, on its standard input and
    output. Closing the scope closes its input, then terminates it if it
    has not exited within five seconds."""

    @gen
    def run():
        max_bytes = yield from message_limit(max_message_bytes)
        spawner = yield from ChildProcessSpawner()
        process = yield from spawner.spawn(command).map_error(
            lambda cause: failure(TransportError("Cannot spawn MCP server", cause))
        )
        pending: dict[RequestId, Deferred[JsonObject]] = {}
        closing = _Closing()
        lines = Queue[str, Done]()

        def write(message: JsonObject) -> Effect[None, McpClientError]:
            return closing.check().and_then(
                encode_message(message, max_bytes).flat_map(
                    lambda text: lines.offer(text + "\n").as_void()
                )
            )

        def receive(message: JsonObject) -> Effect[None, McpClientError]:
            if is_request(message):
                return write(reply_to_server(message))
            if not is_response(message):
                return _VOID
            id = parse_request_id(message.get("id"))
            if id is None:
                return fail(
                    failure(
                        ProtocolError(description="Server returned an uncorrelated JSON-RPC error")
                    )
                )
            response = pending.get(id)
            return _VOID if response is None else response.succeed(message).as_void()

        def line(text: str) -> Effect[None, McpClientError]:
            if not text.strip():
                return _VOID
            return parse_message(text, max_bytes).flat_map(receive)

        def as_client_error(cause: object) -> McpClientError:
            if isinstance(cause, McpClientError):
                return cause
            if isinstance(cause, LineTooLongError):
                return limit_error("MCP message exceeds maxMessageBytes")
            return failure(TransportError("MCP stdout failed", cause))

        yield from (
            stream.from_queue(lines)
            .encode_text()
            .run(process.stdin)
            .catch_all(
                lambda cause: closing.close(failure(TransportError("MCP stdin failed", cause)))
            )
            .fork_scoped()
        )
        yield from process.stderr.run_drain().ignore().fork_scoped()
        drained = Deferred[None]()
        yield from (
            process.stdout.decode_text()
            .pipe_through_channel(split_lines_within(max_bytes))
            .run_for_each(line)
            .map_error(as_client_error)
            .and_then(fail(failure(TransportError("MCP server closed stdout"))))
            .catch_all(closing.close)
            .ensuring(drained.succeed(None))
            .fork_scoped()
        )
        yield from (
            process.exit_code.map(lambda code: f"MCP process exited ({code})")
            .or_else_succeed(lambda _: "MCP process exited")
            .tap(lambda _: drained.wait().timeout_option(CLOSE_TIMEOUT))
            .flat_map(lambda description: closing.close(failure(TransportError(description))))
            .fork_scoped()
        )

        @gen
        def finalize():
            yield from closing.close(failure(ClosedError(description="MCP transport closed")))
            yield from lines.end()
            exited = yield from process.exit_code.timeout_option(CLOSE_TIMEOUT).option()
            if exited is None or exited.value is None:
                yield from process.kill(force_kill_after=CLOSE_TIMEOUT).ignore()

        yield from add_finalizer(lambda _: finalize)

        def request(message: JsonObject, _tool: Tool | None) -> Effect[JsonObject, McpClientError]:
            id = cast("RequestId", message["id"])
            response = Deferred[JsonObject]()

            def cancel() -> Effect[None]:
                if message.get("method") == "initialize":
                    return _VOID
                return response.is_done().flat_map(
                    lambda done: _VOID if done else write(cancelled(id)).ignore()
                )

            return (
                sync(lambda: pending.__setitem__(id, response))
                .and_then(write(message))
                .and_then(response.wait())
                .race_first(closing.signal.wait())
                .on_interrupt(cancel())
                .ensuring(sync(lambda: pending.pop(id, None)))
            )

        return TransportService(protocol, request, write, lambda _: True)

    return run


def _read_failed(cause: HttpClientError) -> McpClientError:
    if is_too_large(cause):
        return limit_error("MCP message exceeds maxMessageBytes")
    return failure(TransportError("Cannot read MCP response", cause))


def http(  # noqa: PLR0915
    *,
    url: str,
    protocol: ClientProtocol,
    headers: Mapping[str, str] | None = None,
    max_message_bytes: int | None = None,
) -> Effect[TransportService, McpClientError, HttpClient | Scope]:
    """A Streamable HTTP transport to ``url``. A 2025-11-25 session is
    deleted when the scope closes; a server forgetting it fails every
    later call with a ``ClosedError`` whose ``session_expired`` is set."""

    @gen
    def run():  # noqa: PLR0915
        max_bytes = yield from message_limit(max_message_bytes)
        client = yield from HttpClient()
        modern = protocol.protocol_version == "2026-07-28"
        closing = _Closing()
        session: list[str] = []
        base_headers = {
            **(headers or {}),
            "accept": "application/json, text/event-stream",
            "mcp-protocol-version": protocol.protocol_version,
        }

        def current_headers() -> dict[str, str]:
            return {**base_headers, "mcp-session-id": session[0]} if session else dict(base_headers)

        def http_error(response: HttpClientResponse) -> Effect[Never, McpClientError]:
            def with_remote(remote: Mapping[str, Any] | None) -> Effect[Never, McpClientError]:
                return fail(
                    failure(
                        HttpError(
                            response.status,
                            code=None if remote is None else remote.get("code"),
                            data=None if remote is None else remote.get("data"),
                            description=None if remote is None else remote.get("message"),
                            www_authenticate=response.headers.get("www-authenticate"),
                            retry_after=response.headers.get("retry-after"),
                        )
                    )
                )

            if media_type(response.headers) != "application/json":
                return with_remote(None)
            remote = (
                with_body_limit(response, max_bytes)
                .text.map_error(lambda _: None)
                .flat_map(lambda text: parse_message(text, max_bytes))
                .map(lambda message: cast("Mapping[str, Any] | None", message.get("error")))
                .or_else_succeed(lambda _: None)
            )
            return remote.flat_map(with_remote)

        def send(
            message: JsonObject, tool: Tool | None
        ) -> Effect[HttpClientResponse, McpClientError]:
            @gen
            def go():
                yield from closing.check()
                body = yield from encode_message(message, max_bytes)
                routing = (yield from routing_headers(message, tool)) if modern else {}
                request = (
                    http_request.post(url)
                    .set_headers({**current_headers(), **routing})
                    .body_text(body, "application/json")
                )
                response = yield from client.execute(request).map_error(
                    lambda cause: failure(TransportError("MCP HTTP request failed", cause))
                )
                if session and response.status == 404:
                    if closing.failed is None:
                        closing.failed = failure(ClosedError(session_expired=True))
                    return (yield from fail(closing.failed))
                if not 200 <= response.status < 300:
                    return (yield from http_error(response))
                assigned = response.headers.get("mcp-session-id")
                if not modern and assigned is not None:
                    session[:] = [assigned]
                return response

            return go

        def exchange[A](effect: Effect[A, McpClientError]) -> Effect[A, McpClientError]:
            return effect.race_first(closing.signal.wait())

        def notify(message: JsonObject) -> Effect[None, McpClientError]:
            return exchange(send(message, None).as_void())

        def match(
            message: JsonObject, request: JsonObject
        ) -> Effect[JsonObject | None, McpClientError]:
            if is_request(message):
                return notify(reply_to_server(message)).as_(None)
            if not is_response(message):
                return succeed(None)
            if message.get("id") != request["id"] and not (
                "error" in message and message.get("id") is None
            ):
                return fail(
                    failure(
                        ProtocolError(description="HTTP MCP response id does not match its request")
                    )
                )
            return succeed(message)

        def read_response(
            response: HttpClientResponse, request: JsonObject
        ) -> Effect[JsonObject, McpClientError]:
            ended = failure(TransportError("MCP response ended before the terminal response"))
            kind = media_type(response.headers)
            if kind == "application/json":
                return (
                    with_body_limit(response, max_bytes)
                    .text.map_error(_read_failed)
                    .flat_map(lambda text: parse_message(text, max_bytes))
                    .flat_map(lambda message: match(message, request))
                    .flat_map(lambda found: fail(ended) if found is None else succeed(found))
                )
            if kind == "text/event-stream":
                events: list[str] = []

                def on_event(event: object) -> None:
                    if isinstance(event, sse.Event) and event.data:
                        events.append(event.data)

                parser = sse.make_parser(on_event, max_event_size=max_bytes)

                def feed(chunk: str) -> stream.Stream[str, McpClientError]:
                    error = parser.feed(chunk)
                    parsed = stream.from_iterable(events[:])
                    events.clear()
                    if error is None:
                        return parsed
                    return parsed.concat(
                        stream.fail(limit_error("MCP SSE event exceeds maxMessageBytes"))
                    )

                found = (
                    response.stream.map_error(_read_failed)
                    .decode_text()
                    .flat_map(feed)
                    .map_effect(
                        lambda data: parse_message(data, max_bytes).flat_map(
                            lambda message: match(message, request)
                        )
                    )
                    .filter(lambda message: message is not None)
                    .run_head()
                )
                return found.flat_map(
                    lambda head: (
                        fail(ended) if head is None else succeed(cast("JsonObject", head.value))
                    )
                )
            return fail(failure(ProtocolError(description="Unsupported MCP response Content-Type")))

        @gen
        def finalize():
            if closing.failed is None:
                closing.failed = failure(ClosedError(description="MCP HTTP transport closed"))
            yield from closing.signal.fail(closing.failed)
            reason = closing.failed.reason
            if not session or not isinstance(reason, ClosedError) or reason.session_expired:
                return None
            delete = http_request.delete(url).set_headers(current_headers())
            yield from client.execute(delete).timeout_option(CLOSE_TIMEOUT).ignore()
            return None

        yield from add_finalizer(lambda _: finalize)

        def request(message: JsonObject, tool: Tool | None) -> Effect[JsonObject, McpClientError]:
            def received(response: HttpClientResponse) -> Effect[JsonObject, McpClientError]:
                if response.status in (202, 204):
                    return fail(
                        failure(ProtocolError(description="MCP request received no response"))
                    )
                return read_response(response, message)

            def cancel() -> Effect[None]:
                if modern or message.get("method") == "initialize":
                    return _VOID
                return (
                    notify(cancelled(cast("RequestId", message["id"])))
                    .timeout_option(CLOSE_TIMEOUT)
                    .ignore()
                )

            return exchange(send(message, tool).flat_map(received)).on_interrupt(cancel())

        def is_callable(tool: Tool) -> bool:
            return not modern or header_parameters(tool) is not None

        return TransportService(protocol, request, notify, is_callable)

    return run
