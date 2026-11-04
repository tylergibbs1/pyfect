"""The Streamable HTTP transport: one endpoint taking JSON-RPC POSTs.

A stateful client's ``initialize`` opens a session, named by the
``mcp-session-id`` response header that its later requests send back; a
stateless (2026-07-28) request needs no session. A request's answer is
JSON, or a server-sent event stream when the server sends anything
before it (progress, log messages, requests to the client).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, cast

from pyfect import _json_text, stream
from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect._json_text import parse as parse_json_text
from pyfect.ai._mcp import batch
from pyfect.ai._mcp import sessions as S
from pyfect.ai._mcp.core import McpServer, McpServerService
from pyfect.ai._mcp.dispatch import (
    Connection,
    Request,
    ServerInfo,
    classify,
)
from pyfect.ai._mcp.http_admission import (
    SESSION_HEADER,
    VERSION_HEADER,
    Admitter,
    Rejected,
    Session,
    Unparsable,
)
from pyfect.ai.mcp_protocol import Registry
from pyfect.ai.mcp_schema import JsonObject
from pyfect.byte_size import ByteSize
from pyfect.clock import monotonic
from pyfect.effect import gen, succeed
from pyfect.errors import Done
from pyfect.http import server_response as response
from pyfect.http.incoming_message import MaxBodySize
from pyfect.http.router import HttpRouter
from pyfect.http.server_request import BodyTooLargeError, ServerRequest, read_limited
from pyfect.http.server_response import HttpServerResponse, parse_content_length
from pyfect.logger import CurrentLogLevel, Severity
from pyfect.queue import Queue
from pyfect.result import Ok

_VOID: Effect[None] = succeed(None)


def _media_types(header: str | None) -> list[str]:
    if header is None:
        return []
    types: list[str] = []
    for part in header.split(","):
        media_type, *parameters = part.split(";")
        quality = next(
            (p.strip().lower() for p in parameters if p.strip().lower().startswith("q=")), None
        )
        if quality is not None:
            try:
                value = float(quality[2:])
            except ValueError:
                continue
            if not 0 < value <= 1:
                continue
        types.append(media_type.strip().lower())
    return types


def _json(message: JsonObject | list[JsonObject]) -> str:
    return _json_text.stringify(cast("Any", message))


def _event(message: JsonObject | list[JsonObject]) -> bytes:
    return text_encode(f"data: {_json(message)}\n\n")


class _Sessions:
    def __init__(
        self,
        server: McpServerService,
        info: ServerInfo,
        registry: Registry,
        limits: S.Limits,
        log_level: Severity,
    ) -> None:
        self.server = server
        self.log_level: Severity = log_level
        self.info = info
        self.registry = registry
        self.sessions = S.Table(server, limits)

    def connection(self) -> Connection:
        return Connection(
            self.server,
            self.info,
            self.registry,
            self.server.next_client_id(),
            "http",
            broadcast=lambda _: _VOID,
            default_log_level=self.log_level,
        )


def _empty(status: int, headers: dict[str, str] | None = None) -> HttpServerResponse:
    return response.empty(status=status, headers=headers or {})


def _answer(
    connection: Connection, request: Request, headers: dict[str, str]
) -> Effect[HttpServerResponse]:
    """The answer to one request: JSON when it is the only message, else
    an event stream of what came before it, then it."""
    messages = Queue[JsonObject, Done]()

    def out(message: JsonObject) -> Effect[None]:
        return messages.offer(message).as_void()

    @gen
    def run():
        serving = yield from connection.start(request, out)
        # The stream ends with the request: after its response, or empty
        # when it was cancelled (Effect's empty SSE reply).
        yield from serving.await_exit().ensuring(messages.end().as_void()).fork_daemon()
        first = yield from messages.take().option()
        if first is None:
            return response.stream(stream.empty, content_type="text/event-stream", headers=headers)
        if "method" not in first.value:
            return response.json_unsafe(first.value, headers=headers)
        body = stream.make(first.value).concat(stream.from_queue(messages)).map(_event)
        return response.stream(cast("Any", body), content_type="text/event-stream", headers=headers)

    return run


def _close_all(connections: Sequence[Connection]) -> Effect[None]:
    @gen
    def run():
        for connection in connections:
            yield from connection.close()

    return run


def _read(request: ServerRequest, limit: ByteSize) -> Effect[str | HttpServerResponse | None]:
    """The body as text (``None`` when unreadable), or 413 past ``limit``
    or the app's ``MaxBodySize``, whichever is smaller. Read here, not
    through ``request.text``, so the limit holds for every request type."""

    @gen
    def run():
        app_limit = yield from MaxBodySize()
        bound = limit if app_limit is None else min(limit, app_limit)
        content_length = parse_content_length(request.headers.get("content-length"))
        result = yield from read_limited(request.stream, content_length, bound).result()
        if isinstance(result, Ok):
            return result.value.decode("utf-8-sig", "replace")
        if isinstance(result.error, BodyTooLargeError):
            return _empty(413)
        return None

    return run


def _open_session(
    sessions: _Sessions, initialize: Request, now: float
) -> Effect[HttpServerResponse]:
    """Answer ``initialize`` in a new session: 503 when the table is full
    once the idle sessions are gone."""
    table = sessions.sessions

    @gen
    def run():
        yield from _close_all(table.sweep(now))
        if table.full():
            return _empty(503)
        connection = sessions.connection()
        reply = yield from connection.answer(
            initialize.id, "initialize", initialize.params, lambda _: _VOID
        )
        if reply is None or "error" in reply or connection.protocol is None:
            return response.json_unsafe(reply)
        new_id = uuid.uuid4().hex
        if not table.open(new_id, connection, now):
            yield from connection.close()
            return _empty(503)
        return response.json_unsafe(
            reply,
            headers={SESSION_HEADER: new_id, VERSION_HEADER: connection.protocol.protocol_version},
        )

    return run


def _rejected(rejection: Rejected) -> HttpServerResponse:
    if rejection.error is None:
        return _empty(rejection.status)
    body: JsonObject = {"jsonrpc": "2.0", "id": rejection.id, "error": rejection.error}
    return response.json_unsafe(body, status=rejection.status)


def _batch(
    connection: Connection, messages: list[object], acknowledge: bool, headers: dict[str, str]
) -> Effect[HttpServerResponse]:
    """A batch's responses in one JSON array, or an event stream of the
    server's notifications, then that array; 202 when the batch expects no
    answer, an empty event stream when every request was cancelled."""
    if acknowledge:
        return batch.answer(connection, messages, lambda _: _VOID).as_(_empty(202, headers))
    events = Queue[JsonObject | list[JsonObject], Done]()

    def notify(message: JsonObject) -> Effect[None]:
        return events.offer(message).as_void()

    def finish(replies: list[JsonObject]) -> Effect[None]:
        return events.offer(replies).as_void() if replies else _VOID

    @gen
    def run():
        answered = batch.answer(connection, messages, notify).flat_map(finish)
        yield from answered.ensuring(events.end().as_void()).fork_daemon()
        first = yield from events.take().option()
        if first is None:
            return response.stream(stream.empty, content_type="text/event-stream", headers=headers)
        if isinstance(first.value, list):
            return response.json_unsafe(cast("Any", first.value), headers=headers)
        body = stream.make(first.value).concat(stream.from_queue(events)).map(_event)
        return response.stream(cast("Any", body), content_type="text/event-stream", headers=headers)

    return run


def _post(sessions: _Sessions, request: ServerRequest) -> Effect[HttpServerResponse]:
    table = sessions.sessions
    admitter = Admitter(sessions.registry)

    @gen
    def run():  # noqa: PLR0911
        text = yield from _read(request, table.limits.max_message_bytes)
        if isinstance(text, HttpServerResponse):
            return text
        now = yield from monotonic()
        try:
            message: object = parse_json_text(text) if text is not None else Unparsable()
        except ValueError:
            message = Unparsable()
        session_id = request.headers.get(SESSION_HEADER)
        connection: Connection | None = None
        session: Session = "absent"
        if session_id is not None:
            connection, expired = table.get(session_id, now)
            if expired is not None:
                yield from expired.close()
            session = (
                "unknown"
                if connection is None or connection.protocol is None
                else (connection.protocol)
            )
        admission = admitter.admit(request.headers, message, session)
        if isinstance(admission, Rejected):
            return _rejected(admission)
        headers = {} if isinstance(session, str) else {VERSION_HEADER: session.protocol_version}
        if isinstance(message, list) and connection is not None:  # admitted: names a session
            batch = cast("list[object]", message)
            return (yield from _batch(connection, batch, admission.acknowledge, headers))
        classified = classify(message)
        if classified.request is not None and classified.request.method == "initialize":
            return (yield from _open_session(sessions, classified.request, now))
        if connection is None:
            if classified.request is None:
                # A stateless client's notification or response: nothing to route it to.
                return _empty(202)
            return (yield from _answer(sessions.connection(), classified.request, {}))
        if classified.request is not None:
            return (yield from _answer(connection, classified.request, headers))
        yield from connection.dispatch(message, lambda _: _VOID)
        return _empty(202, headers)

    return run


def _delete(sessions: _Sessions, request: ServerRequest) -> Effect[HttpServerResponse]:
    """End a session; one named with a wrong protocol version stays open."""
    session_id = request.headers.get(SESSION_HEADER)
    if session_id is None:
        return succeed(_empty(400))

    @gen
    def run():
        now = yield from monotonic()
        connection, expired = sessions.sessions.get(session_id, now)
        if expired is not None:
            yield from expired.close()
        if connection is None or connection.protocol is None:
            return _empty(404)
        checked = Admitter(sessions.registry).session(
            request.headers, connection.protocol, initialize=False
        )
        if isinstance(checked, Rejected):
            return _empty(checked.status)
        sessions.sessions.pop(session_id)
        yield from connection.close()
        return _empty(204)

    return run


def serve(
    info: ServerInfo,
    registry: Registry,
    *,
    path: str,
    allowed_origins: Sequence[str] | None,
    allow_session_termination: bool,
    limits: S.Limits,
) -> Effect[None, Any, McpServer | HttpRouter]:
    """Add the MCP endpoint at ``path`` to the router."""

    @gen
    def run():
        server = yield from McpServer()
        router = yield from HttpRouter()
        level = yield from CurrentLogLevel()
        sessions = _Sessions(server, info, registry, limits, level)
        terminate = allow_session_termination and any(
            not p.is_stateless for p in registry.protocols
        )
        allowed = frozenset(allowed_origins or ())

        def admitted(request: ServerRequest) -> bool:
            origin = request.headers.get("origin")
            return origin is None or origin in allowed

        def not_allowed(request: ServerRequest) -> Effect[HttpServerResponse]:
            if not admitted(request):
                return succeed(_empty(403))
            return succeed(_empty(405, {"allow": "POST, DELETE" if terminate else "POST"}))

        def post(request: ServerRequest) -> Effect[HttpServerResponse]:
            if not admitted(request):
                return succeed(_empty(403))
            content_type = _media_types(request.headers.get("content-type"))
            if not content_type or content_type[0] != "application/json":
                return succeed(_empty(415))
            accepted = _media_types(request.headers.get("accept"))
            if "application/json" not in accepted or "text/event-stream" not in accepted:
                return succeed(_empty(406))
            return _post(sessions, request)

        def delete(request: ServerRequest) -> Effect[HttpServerResponse]:
            if not terminate:
                return not_allowed(request)
            if not admitted(request):
                return succeed(_empty(403))
            return _delete(sessions, request)

        for method in ("GET", "PUT", "PATCH", "OPTIONS"):
            yield from router.add(method, path, not_allowed)
        yield from router.add("DELETE", path, delete)
        yield from router.add("POST", path, post)

    return run
