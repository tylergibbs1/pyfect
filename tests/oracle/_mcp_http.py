"""The HTTP side of Effect's MCP conformance harness: ``makeHttpHarness``,
``initializeHttpSession``, ``readMcpHttpResponse``, ``makeMcpSseReader``
(test/ai/McpServer/TestUtils) and the ``McpConformance`` service
(McpConformance/McpConformance.ts), over ``router.in_memory_client``, which
streams response bodies so a test reads events as the server writes them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal, cast

import pyfect as fx
from pyfect import layer
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_server as M
from pyfect.exit import Success
from pyfect.http import request as R
from pyfect.http import router
from pyfect.http.client import HttpClientService
from pyfect.http.response import HttpClientResponse
from pyfect.pull import catch_done
from pyfect.scope import CloseableScope, Scope

type Json = dict[str, Any]

MCP_ENDPOINT = "http://localhost/mcp"
ACCEPT = "application/json, text/event-stream"
SERVER_NAME = "McpConformance"
SERVER_VERSION = "1.0.0"
CONFORMANCE_CLIENT = {"name": "McpConformanceClient", "version": "1.0.0"}
ALLOWED_ORIGIN = "https://allowed.example"
INITIALIZED: Json = {"jsonrpc": "2.0", "method": "notifications/initialized"}
type Mode = Literal["server", "request"]


def server_layer(
    name: str,
    protocols: tuple[P.AnyProtocolAdapter, ...],
    registrations: fx.Effect[None, Any, Any] | None = None,
    *,
    allow_session_termination: bool = False,
    mode: Mode = "server",
    instructions: str | None = None,
    extensions: Json | None = None,
) -> layer.Layer[Any, Any, Any]:
    """Effect's ``makeServerLayer`` (``https://allowed.example`` is the one
    allowed origin), with ``registrations`` run against its server."""
    served: layer.Layer[Any, Any, Any]
    if mode == "request":
        served = M.layer_http_request_scoped(
            name=name,
            version=SERVER_VERSION,
            path="/mcp",
            protocols=cast("Any", protocols),
            allowed_origins=(ALLOWED_ORIGIN,),
            instructions=instructions,
            extensions=extensions,
        )
    else:
        served = M.layer_http(
            name=name,
            version=SERVER_VERSION,
            path="/mcp",
            protocols=protocols,
            allowed_origins=(ALLOWED_ORIGIN,),
            allow_session_termination=allow_session_termination,
            instructions=instructions,
            extensions=extensions,
        )
    if registrations is None:
        return served
    return layer.effect_discard(registrations).pipe(layer.provide_merge(served))


@dataclass
class HttpHarness:
    """Requests to an MCP endpoint served in memory."""

    client: HttpClientService[Any, Any]

    def request(
        self, method: str, body: object = None, headers: dict[str, str] | None = None
    ) -> fx.Effect[HttpClientResponse]:
        """Effect's ``jsonRequest``: JSON accept and content-type headers,
        which ``headers`` override (an empty value included)."""
        text = None if body is None else json.dumps(body)
        return self.send(method, text, headers)

    def send(
        self, method: str, text: str | None, headers: dict[str, str] | None = None
    ) -> fx.Effect[HttpClientResponse]:
        request = R.make(method, MCP_ENDPOINT)  # pyright: ignore[reportArgumentType]
        if text is not None:
            request = request.body_text(text, "application/json")
        merged = {"accept": ACCEPT, "content-type": "application/json", **(headers or {})}
        return self.client.execute(request.set_headers(merged)).or_die()

    def post(
        self, body: object, headers: dict[str, str] | None = None
    ) -> fx.Effect[HttpClientResponse]:
        return self.request("POST", body, headers)

    def post_text(self, text: str, headers: dict[str, str] | None = None) -> fx.Effect[Any]:
        return self.send("POST", text, headers)


def http_harness(app: layer.Layer[Any, Any, Any]) -> fx.Effect[HttpHarness, Any, Scope]:
    return router.in_memory_client(app).map(HttpHarness)


def read_message(response: HttpClientResponse) -> fx.Effect[Any]:
    """Effect's ``readMcpHttpResponse``: the JSON body, or an event
    stream's last message."""
    if "text/event-stream" not in (response.headers.get("content-type") or ""):
        return response.text.map(json.loads).or_die()

    def last(text: str) -> Any:
        events = [json.loads(line[6:]) for line in text.split("\n") if line.startswith("data: ")]
        return events[-1] if events else None

    return response.text.map(last).or_die()


def initialize_session(
    harness: HttpHarness, protocol: P.AnyProtocolAdapter, capabilities: Json | None = None
) -> fx.Effect[dict[str, str]]:
    """Effect's ``initializeHttpSession``: the headers of a new session."""

    @fx.gen
    def run():
        response = yield from harness.post(
            {
                "jsonrpc": "2.0",
                "id": "initialize",
                "method": "initialize",
                "params": {
                    "protocolVersion": protocol.protocol_version,
                    "capabilities": capabilities or {},
                    "clientInfo": {"name": "test", "version": "1.0.0"},
                },
            }
        )
        yield from read_message(response)
        session = response.headers.get("mcp-session-id")
        assert session is not None
        headers = {"Mcp-Session-Id": session, "Mcp-Protocol-Version": protocol.protocol_version}
        yield from harness.post(INITIALIZED, headers)
        return headers

    return run


@dataclass
class SseReader:
    """Effect's ``makeMcpSseReader``: the messages of an event stream, read
    as they arrive."""

    _pull: fx.Effect[tuple[bytes, ...], Any]
    _scope: CloseableScope
    _pending: str = ""
    _ended: bool = field(default=False)

    def _take_or_end(self) -> fx.Effect[Json | None]:
        @fx.gen
        def run():
            while True:
                boundary = self._pending.find("\n\n")
                if boundary != -1:
                    event = self._pending[:boundary]
                    self._pending = self._pending[boundary + 2 :]
                    data = "\n".join(
                        line[5:].lstrip() for line in event.split("\n") if line.startswith("data:")
                    )
                    if data:
                        return json.loads(data)
                    continue
                if self._ended:
                    return None
                chunk = yield from catch_done(self._pull, lambda _: fx.succeed(None)).or_die()
                if chunk is None:
                    self._ended = True
                    continue
                text = b"".join(chunk).decode()
                self._pending += text.replace("\r\n", "\n")

        return run

    def take(self) -> fx.Effect[Json]:
        def present(message: Json | None) -> Json:
            assert message is not None, "the event stream ended"
            return message

        return self._take_or_end().map(present)

    def drain(self) -> fx.Effect[list[Json]]:
        @fx.gen
        def run():
            messages: list[Json] = []
            while (message := (yield from self._take_or_end())) is not None:
                messages.append(message)
            return messages

        return run

    @property
    def cancel(self) -> fx.Effect[None]:
        return self._scope.close(Success(None))


def sse_reader(response: HttpClientResponse) -> fx.Effect[SseReader, Any, Scope]:
    """A reader of ``response`` 's events; its body closes with the current
    scope, or earlier with ``cancel``."""
    content_type = response.headers.get("content-type") or ""
    assert content_type.split(";")[0] == "text/event-stream", content_type

    @fx.gen
    def run():
        outer: CloseableScope = yield from Scope()
        scope = yield from outer.fork()
        pull = yield from response.stream.to_pull().pipe(fx.provide_service(Scope, scope))
        return SseReader(pull, scope)

    return run


# --- McpConformance -------------------------------------------------------------------------


@dataclass(frozen=True)
class Session:
    """Effect's ``InitializedSession``."""

    response: HttpClientResponse
    message: Json
    session_id: str | None


def _object(value: object) -> Json:
    return cast("Json", value) if isinstance(value, dict) else {}


def _stateless_body(
    protocol: P.AnyProtocolAdapter, body: object, capabilities: Json | None = None
) -> object:
    message = _object(body)
    if not protocol.is_stateless or "method" not in message:
        return body
    params = _object(message.get("params"))
    default_capabilities: Json = {"elicitation": {"form": {}}, "roots": {}, "sampling": {}}
    meta: Json = {
        **_object(params.get("_meta")),
        "io.modelcontextprotocol/protocolVersion": protocol.protocol_version,
        "io.modelcontextprotocol/clientCapabilities": (
            default_capabilities if capabilities is None else capabilities
        ),
        "io.modelcontextprotocol/clientInfo": CONFORMANCE_CLIENT,
    }
    return {**message, "params": {**params, "_meta": meta}}


def _stateless_headers(protocol: P.AnyProtocolAdapter, body: object) -> dict[str, str]:
    message = _object(body)
    method = message.get("method")
    if not protocol.is_stateless or not isinstance(method, str):
        return {}
    params = _object(message.get("params"))
    key = {"resources/read": "uri", "tools/call": "name", "prompts/get": "name"}.get(method)
    name = None if key is None else params.get(key)
    headers = {"MCP-Protocol-Version": protocol.protocol_version, "Mcp-Method": method}
    if isinstance(name, str):
        headers["Mcp-Name"] = name
    return headers


@dataclass
class Conformance:
    """Effect's ``McpConformance`` service, for one protocol revision (the
    default server only: these suites never initialize the features one)."""

    protocol: P.AnyProtocolAdapter
    harness: HttpHarness

    def initialize_request(self, id: int = 1, protocol_version: str | None = None) -> Json:
        return {
            "jsonrpc": "2.0",
            "id": id,
            "method": "initialize",
            "params": {
                "protocolVersion": protocol_version or self.protocol.protocol_version,
                "capabilities": {},
                "clientInfo": CONFORMANCE_CLIENT,
            },
        }

    @staticmethod
    def ping_request(id: int = 2) -> Json:
        return {"jsonrpc": "2.0", "id": id, "method": "ping", "params": {}}

    def post(self, body: object, headers: dict[str, str] | None = None) -> fx.Effect[Any]:
        return self.harness.post(body, headers)

    def request(
        self, method: str, body: object = None, headers: dict[str, str] | None = None
    ) -> fx.Effect[HttpClientResponse]:
        return self.harness.request(method, body, headers)

    def initialize(self, id: int = 1) -> fx.Effect[Session]:
        protocol = self.protocol

        @fx.gen
        def run():
            if protocol.is_stateless:
                discover = _stateless_body(
                    protocol,
                    {"jsonrpc": "2.0", "id": id, "method": "server/discover", "params": {}},
                )
                response = yield from self.post(discover, _stateless_headers(protocol, discover))
                decoded = yield from read_message(response)
                result = decoded["result"]
                message = {
                    "jsonrpc": "2.0",
                    "id": id,
                    "result": {
                        "protocolVersion": protocol.protocol_version,
                        "capabilities": result["capabilities"],
                        "instructions": result.get("instructions"),
                        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    },
                }
                return Session(response, message, None)
            response = yield from self.post(self.initialize_request(id))
            message = yield from read_message(response)
            assert message["id"] == id and "result" in message, message
            return Session(response, message, response.headers.get("mcp-session-id"))

        return run

    def _session_headers(
        self,
        session: Session,
        include_protocol_version: bool,
        protocol_version: str | None,
        headers: dict[str, str] | None,
    ) -> dict[str, str]:
        out: dict[str, str] = {}
        if session.session_id is not None:
            out["Mcp-Session-Id"] = session.session_id
        if include_protocol_version:
            negotiated = session.message["result"]["protocolVersion"]
            out["Mcp-Protocol-Version"] = protocol_version or negotiated
        return {**out, **(headers or {})}

    def send(
        self,
        session: Session,
        body: object,
        *,
        include_protocol_version: bool = True,
        protocol_version: str | None = None,
        client_capabilities: Json | None = None,
        headers: dict[str, str] | None = None,
    ) -> fx.Effect[HttpClientResponse]:
        protocol = self.protocol
        if not protocol.is_stateless:
            merged = self._session_headers(
                session, include_protocol_version, protocol_version, headers
            )
            return self.post(body, merged)
        request = _stateless_body(protocol, body, client_capabilities)
        return self.post(request, {**_stateless_headers(protocol, request), **(headers or {})})

    def send_text(self, session: Session, text: str) -> fx.Effect[HttpClientResponse]:
        return self.harness.post_text(text, self._session_headers(session, True, None, None))

    def notify_initialized(self, session: Session) -> fx.Effect[HttpClientResponse]:
        return self.send(session, INITIALIZED)

    def ping(
        self,
        session: Session,
        id: int = 2,
        *,
        include_protocol_version: bool = True,
        protocol_version: str | None = None,
    ) -> fx.Effect[HttpClientResponse]:
        return self.send(
            session,
            self.ping_request(id),
            include_protocol_version=include_protocol_version,
            protocol_version=protocol_version,
        )

    @staticmethod
    def decode_error(response: HttpClientResponse) -> fx.Effect[Json]:
        def check(message: Any) -> Json:
            assert message["jsonrpc"] == "2.0" and "error" in message, message
            assert isinstance(message["error"]["code"], int), message
            return message

        return read_message(response).map(check)

    @staticmethod
    def decode_result(response: HttpClientResponse) -> fx.Effect[Json]:
        def check(message: Any) -> Json:
            assert message["jsonrpc"] == "2.0" and isinstance(message.get("result"), dict), message
            assert isinstance(message["id"], (str, int)), message
            return message

        return read_message(response).map(check)


def conformance(protocol: P.AnyProtocolAdapter) -> fx.Effect[Conformance, Any, Scope]:
    """Effect's ``McpConformance.layer(protocol)``."""
    app = server_layer(SERVER_NAME, (protocol,))
    return http_harness(app).map(lambda harness: Conformance(protocol, harness))
