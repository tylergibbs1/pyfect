"""Ports of Effect's ``test/ai/McpClient.test.ts``.

Each test's docstring is the Effect test title (with its ``describe``).
``connect`` reaches an in-memory ``McpServer.layer_http`` through the
HTTP client; ``scripted_http`` answers each request with a canned
response; ``connect_stdio`` runs the client against a controlled
process. Calls take the tool or prompt and its arguments positionally
(``call_tool(tool, arguments, schema=...)``), and timeouts are seconds.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypedDict, cast

import pytest

import pyfect as fx
from pyfect import layer, sink, stream, testing
from pyfect import schema as S
from pyfect.ai import language_model as lm
from pyfect.ai import mcp_client as C
from pyfect.ai import mcp_client_error as CE
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_server as M
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai.mcp_client_error import McpClientError
from pyfect.ai.mcp_schema import Prompt, Tool
from pyfect.deferred import Deferred
from pyfect.errors import Done
from pyfect.http.client import HttpClient
from pyfect.http.client import make as make_http_client
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.http.response import make as make_response
from pyfect.process import ChildProcessHandle, ChildProcessSpawner, ChildProcessSpawnerService
from pyfect.process import make as make_command
from pyfect.queue import Queue

from ._ai import with_language_model
from ._mcp import MCP_ENDPOINT, in_memory_http

CLIENT_INFO: dict[str, Any] = {"name": "test-client", "version": "1.0.0"}
SERVER_INFO: dict[str, Any] = {"name": "scripted-server", "version": "1.0.0"}
PROTOCOLS = [P.v2025_11_25, P.v2026_07_28]


class AddParams(TypedDict):
    a: float
    b: float


class Total(TypedDict):
    total: float


class ExplainParams(TypedDict):
    total: str


Add = T.make("add", parameters=S.Struct(AddParams), success=S.Struct(Total))
Fail = T.make("fail", success=S.String, failure=S.String)
Slow = T.make("slow", success=S.String)
TestToolkit = K.make(Add, Fail, Slow)

_handlers = TestToolkit.to_layer(
    Add.handler(lambda p, _: fx.succeed(Total(total=p["a"] + p["b"]))),
    Fail.handler(lambda _, __: fx.fail("denied")),
    Slow.handler(lambda _, __: fx.never),
)

SERVER_LAYER: Any = layer.merge(
    M.layer_http(
        name="test-server",
        version="1.0.0",
        path="/mcp",
        protocols=(P.v2026_07_28, P.v2025_11_25),
    ),
    M.toolkit(TestToolkit),
    M.prompt(
        name="explain",
        parameters=S.Struct(ExplainParams),
        content=lambda p: fx.succeed(f"Explain {p['total']}"),
    ),
    M.resource(uri="demo://guide", name="guide", content=fx.succeed("Guide")),
).pipe(layer.provide(_handlers))

SLOW_TOOL: Tool = {"name": "slow", "inputSchema": {"type": "object"}}

INITIALIZE_RESULT: dict[str, Any] = {
    "protocolVersion": "2025-11-25",
    "serverInfo": SERVER_INFO,
    "capabilities": {"tools": {}, "prompts": {}, "resources": {}},
}
DISCOVER_RESULT: dict[str, Any] = {
    "resultType": "complete",
    "_meta": {"io.modelcontextprotocol/serverInfo": SERVER_INFO},
    "supportedVersions": ["2026-07-28"],
    "capabilities": {"tools": {}},
    "ttlMs": 0,
    "cacheScope": "private",
}


def _protocol_id(protocol: P.AnyProtocolAdapter) -> str:
    return protocol.protocol_version


def connect(protocol: C.ClientProtocol) -> fx.Effect[C.McpClientService, Any, Any]:
    @fx.gen
    def run():
        http = yield from in_memory_http(SERVER_LAYER)
        transport = yield from C.http(url=MCP_ENDPOINT, protocol=protocol).pipe(
            fx.provide_service(HttpClient, http)
        )
        return (
            yield from C.make(name="test-client", version="1.0.0").pipe(
                fx.provide_service(C.Transport, transport)
            )
        )

    return run


def find_tool(client: C.McpClientService, name: str) -> fx.Effect[Tool, McpClientError]:
    def pick(tools: list[Tool]) -> Tool:
        found = next((t for t in tools if t["name"] == name), None)
        assert found is not None
        return found

    return client.list_tools().map(pick)


# --- in-memory server --------------------------------------------------------------------


@pytest.mark.parametrize("protocol", PROTOCOLS, ids=_protocol_id)
@testing.effect
def test_discovers_and_calls_tools_prompts_and_resources(protocol: C.ClientProtocol):
    """McpClient / <protocol> / should discover and call tools, prompts and resources"""
    client = yield from connect(protocol)
    assert client.protocol_version == protocol.protocol_version
    assert client.server_info == {"name": "test-server", "version": "1.0.0"}

    tool = yield from find_tool(client, "add")
    raw = yield from client.call_tool(tool, {"a": 20, "b": 22})
    assert raw.get("structuredContent") == {"total": 42}
    decoded = yield from client.call_tool(tool, {"a": 1, "b": 2}, schema=S.Struct(Total))
    assert decoded == {"total": 3}

    [prompt] = yield from client.list_prompts()
    messages = yield from client.get_prompt(prompt, {"total": "42"})
    assert [m["content"] for m in messages["messages"]] == [{"type": "text", "text": "Explain 42"}]

    [resource] = yield from client.list_resources()
    contents = yield from client.read_resource(resource["uri"])
    assert contents["contents"] == [{"uri": "demo://guide", "text": "Guide"}]


@pytest.mark.parametrize("protocol", PROTOCOLS, ids=_protocol_id)
@testing.effect
def test_fails_with_tool_error_when_a_schema_call_reports_is_error(protocol: C.ClientProtocol):
    """McpClient / <protocol> / should fail with ToolError when a schema call reports isError"""
    client = yield from connect(protocol)
    tool = yield from find_tool(client, "fail")
    raw = yield from client.call_tool(tool)
    assert raw.get("isError") is True
    error = yield from client.call_tool(tool, schema=S.String).flip()
    assert isinstance(error.reason, CE.ToolError)
    assert cast("Any", error.reason).result == raw


@pytest.mark.parametrize("protocol", PROTOCOLS, ids=_protocol_id)
@testing.effect
def test_preserves_the_json_rpc_error_code(protocol: C.ClientProtocol):
    """McpClient / <protocol> / should preserve JSON-RPC error code when the server rejects a request"""  # noqa: E501
    client = yield from connect(protocol)
    error = yield from client.read_resource("demo://missing").flip()
    assert isinstance(error.reason, CE.ProtocolError)
    expected = -32002 if protocol.protocol_version == "2025-11-25" else -32602
    assert cast("Any", error.reason).code == expected


@pytest.mark.parametrize("protocol", PROTOCOLS, ids=_protocol_id)
@testing.effect
def test_times_out_when_a_call_exceeds_its_deadline(protocol: C.ClientProtocol):
    """McpClient / <protocol> / should time out when a call exceeds its deadline"""
    client = yield from connect(protocol)
    tool = yield from find_tool(client, "slow")
    call = yield from client.call_tool(tool, timeout=1).flip().fork()
    yield from testing.adjust(1)
    error = yield from call.join()
    assert isinstance(error.reason, CE.TimeoutError)


@pytest.mark.parametrize("protocol", PROTOCOLS, ids=_protocol_id)
@testing.effect
def test_exposes_remote_tools_to_a_language_model(protocol: C.ClientProtocol):
    """McpClient / <protocol> / should expose remote tools to a language model through McpClient.toolkit"""  # noqa: E501
    client = yield from connect(protocol)
    kit = yield from C.toolkit(client, "calc__")
    assert sorted(kit.tools) == ["calc__add", "calc__fail", "calc__slow"]
    call: list[lm.EncodedPart] = [
        {"type": "tool-call", "id": "call-1", "name": "calc__add", "params": {"a": 20, "b": 22}}
    ]
    toolkit: Any = K.make(*kit.tools.values())
    response = yield from (
        lm.generate_text("Add", toolkit=toolkit)
        .pipe(with_language_model(generate_text=call))
        .pipe(fx.provide_context(kit.services))
    )
    assert [part.result for part in response.tool_results] == ['{"total":42}']


# --- scripted HTTP -----------------------------------------------------------------------


@dataclass
class Sent:
    request: HttpClientRequest
    message: dict[str, Any] | None

    @property
    def body(self) -> dict[str, Any]:
        assert self.message is not None
        return self.message


type Reply = Callable[[dict[str, Any], HttpClientRequest], HttpClientResponse]


def _body_of(request: HttpClientRequest) -> dict[str, Any] | None:
    body = cast("Any", request.body)
    data = getattr(body, "body", None)
    return json.loads(data) if isinstance(data, bytes) and data else None


def json_result(
    request: HttpClientRequest,
    message: dict[str, Any],
    result: object,
    headers: dict[str, str] | None = None,
) -> HttpClientResponse:
    return make_response(
        request,
        json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}),
        headers={"content-type": "application/json", **(headers or {})},
    )


def sse_response(request: HttpClientRequest, messages: list[object]) -> HttpClientResponse:
    body = "".join(f"data: {json.dumps(m)}\n\n" for m in messages)
    return make_response(request, body, headers={"content-type": "text/event-stream"})


def scripted_reply(
    protocol: C.ClientProtocol, message: dict[str, Any], request: HttpClientRequest
) -> HttpClientResponse:
    """Answers the handshake and empty discovery for either revision."""
    if message["method"] == "initialize":
        return json_result(request, message, INITIALIZE_RESULT, {"mcp-session-id": "session-1"})
    if message["method"] == "server/discover":
        return json_result(request, message, DISCOVER_RESULT)
    legacy = protocol.protocol_version == "2025-11-25"
    return json_result(
        request, message, {"tools": []} if legacy else {**DISCOVER_RESULT, "tools": []}
    )


@dataclass
class Scripted:
    client: C.McpClientService
    sent: list[Sent] = field(default_factory=list[Sent])


def scripted_http(
    reply: Reply, protocol: C.ClientProtocol = P.v2026_07_28
) -> fx.Effect[Scripted, McpClientError, Any]:
    sent: list[Sent] = []

    def handle(request: HttpClientRequest) -> fx.Effect[HttpClientResponse]:
        def answer() -> HttpClientResponse:
            message = _body_of(request)
            sent.append(Sent(request, message))
            if message is not None and "method" in message and "id" in message:
                return reply(message, request)
            return make_response(request, None, status=202)

        return fx.sync(answer)

    http = make_http_client(lambda request, _url, _signal, _fiber: handle(request))

    @fx.gen
    def run():
        transport = yield from C.http(url=MCP_ENDPOINT, protocol=protocol).pipe(
            fx.provide_service(HttpClient, http)
        )
        client = yield from C.make(name="test-client", version="1.0.0").pipe(
            fx.provide_service(C.Transport, transport)
        )
        return Scripted(client, sent)

    return run


def _method_of(message: dict[str, Any] | None) -> str | None:
    return None if message is None else message.get("method")


@testing.effect
def test_retries_discovery_when_an_unsupported_version_error_omits_its_id():
    """McpClient / should retry discovery when an unsupported-version error omits its ID"""
    requests: list[dict[str, Any]] = []

    def reply(message: dict[str, Any], request: HttpClientRequest) -> HttpClientResponse:
        requests.append(message)
        if len(requests) == 1:
            error = {
                "code": -32022,
                "message": "Unsupported protocol version",
                "data": {"requested": "2026-07-28", "supported": ["2026-07-28"]},
            }
            return make_response(
                request,
                json.dumps({"jsonrpc": "2.0", "error": error}),
                status=400,
                headers={"content-type": "application/json"},
            )
        return json_result(request, message, DISCOVER_RESULT)

    scripted = yield from scripted_http(reply)
    assert scripted.client.server_info == SERVER_INFO
    assert [r["method"] for r in requests] == ["server/discover", "server/discover"]
    assert requests[1]["params"] == {
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientInfo": CLIENT_INFO,
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    }
    assert requests[0]["id"] != requests[1]["id"]


@testing.effect
def test_mirrors_own_annotated_tool_arguments_into_http_headers():
    """McpClient / should mirror own annotated tool arguments into HTTP headers"""
    definition = {
        "name": "routed",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region": {"type": "string", "x-mcp-header": "Region"},
                "constructor": {"type": "string", "x-mcp-header": "Ctor"},
            },
        },
    }
    calls: list[Any] = []

    def reply(message: dict[str, Any], request: HttpClientRequest) -> HttpClientResponse:
        if message["method"] == "tools/call":
            calls.append(request.headers)
        if message["method"] == "server/discover":
            return json_result(request, message, DISCOVER_RESULT)
        if message["method"] == "tools/list":
            return json_result(request, message, {**DISCOVER_RESULT, "tools": [definition]})
        return json_result(request, message, {**DISCOVER_RESULT, "content": []})

    scripted = yield from scripted_http(reply)
    [tool] = yield from scripted.client.list_tools()
    yield from scripted.client.call_tool(tool, {"region": "Hello, 世界"})
    assert calls[0]["mcp-method"] == "tools/call"
    assert calls[0]["mcp-name"] == "routed"
    assert calls[0]["mcp-param-region"] == "=?base64?SGVsbG8sIOS4lueVjA==?="
    assert calls[0].get("mcp-param-ctor") is None


@testing.effect
def test_omits_tools_with_header_annotations_outside_properties_only_paths():
    """McpClient / should omit tools with header annotations outside properties-only paths"""
    annotated = {"type": "string", "x-mcp-header": "Region"}
    tools = [
        {
            "name": "nested",
            "inputSchema": {
                "type": "object",
                "properties": {"scope": {"type": "object", "properties": {"region": annotated}}},
            },
        },
        {
            "name": "items",
            "inputSchema": {
                "type": "object",
                "properties": {"regions": {"type": "array", "items": annotated}},
            },
        },
        {
            "name": "anyOf",
            "inputSchema": {"type": "object", "properties": {"region": {"anyOf": [annotated]}}},
        },
        {
            "name": "defs",
            "inputSchema": {"type": "object", "properties": {}, "$defs": {"region": annotated}},
        },
    ]

    def reply(message: dict[str, Any], request: HttpClientRequest) -> HttpClientResponse:
        if message["method"] == "server/discover":
            return json_result(request, message, DISCOVER_RESULT)
        return json_result(request, message, {**DISCOVER_RESULT, "tools": tools})

    scripted = yield from scripted_http(reply)
    assert [t["name"] for t in (yield from scripted.client.list_tools())] == ["nested"]


@testing.effect
def test_rejects_a_modern_list_result_missing_revision_fields():
    """McpClient / should reject a modern list result that omits revision-required fields"""

    def reply(message: dict[str, Any], request: HttpClientRequest) -> HttpClientResponse:
        if message["method"] == "tools/list":
            return json_result(request, message, {"resultType": "complete", "tools": []})
        return scripted_reply(P.v2026_07_28, message, request)

    scripted = yield from scripted_http(reply)
    error = yield from scripted.client.list_tools().flip()
    assert isinstance(error.reason, CE.ValidationError)


@pytest.mark.parametrize(
    ("ttl", "scope", "valid"),
    [(0, "public", True), (5, "private", True), (-1, "private", False), (0, "shared", False)],
)
@testing.effect
def test_validates_modern_list_cache_fields(ttl: int, scope: str, valid: bool):
    """Not an Effect title: a 2026-07-28 list result's ``ttlMs`` is a
    non-negative integer and its ``cacheScope`` is ``public`` or ``private``
    (Effect's ``CacheableResult``)."""

    def reply(message: dict[str, Any], request: HttpClientRequest) -> HttpClientResponse:
        if message["method"] == "tools/list":
            fields = {"resultType": "complete", "ttlMs": ttl, "cacheScope": scope}
            return json_result(request, message, {**fields, "tools": []})
        return scripted_reply(P.v2026_07_28, message, request)

    scripted = yield from scripted_http(reply)
    if valid:
        assert (yield from scripted.client.list_tools()) == []
    else:
        error = yield from scripted.client.list_tools().flip()
        assert isinstance(error.reason, CE.ValidationError)


@pytest.mark.parametrize("cached", [True, False])
@testing.effect
def test_validates_modern_read_cache_fields(cached: bool):
    """Not an Effect title: a 2026-07-28 ``resources/read`` result is
    cacheable, so it needs ``ttlMs`` and ``cacheScope`` like a list."""
    contents = {"contents": [{"uri": "demo://guide", "text": "Guide"}]}

    def reply(message: dict[str, Any], request: HttpClientRequest) -> HttpClientResponse:
        if message["method"] == "server/discover":
            discover: dict[str, Any] = {**DISCOVER_RESULT, "capabilities": {"resources": {}}}
            return json_result(request, message, discover)
        if message["method"] == "resources/read":
            fields = {"ttlMs": 0, "cacheScope": "private"} if cached else {}
            return json_result(request, message, {"resultType": "complete", **fields, **contents})
        return scripted_reply(P.v2026_07_28, message, request)

    scripted = yield from scripted_http(reply)
    read = scripted.client.read_resource("demo://guide")
    if cached:
        assert (yield from read)["contents"] == contents["contents"]
    else:
        assert isinstance((yield from read.flip()).reason, CE.ValidationError)


@testing.effect
def test_fails_with_limit_error_when_one_page_exceeds_the_item_limit():
    """McpClient / should fail with LimitError when one discovery page exceeds the item limit"""
    prompts = [{"name": "p"}] * 150_000

    def reply(message: dict[str, Any], request: HttpClientRequest) -> HttpClientResponse:
        if message["method"] == "prompts/list":
            return json_result(request, message, {"prompts": prompts})
        return scripted_reply(P.v2025_11_25, message, request)

    scripted = yield from scripted_http(reply, P.v2025_11_25)
    error = yield from scripted.client.list_prompts().flip()
    assert isinstance(error.reason, CE.LimitError)


@pytest.mark.parametrize("protocol", PROTOCOLS, ids=_protocol_id)
@testing.effect
def test_cancels_a_timed_out_http_call(protocol: C.ClientProtocol):
    """McpClient / cancellation / should cancel a timed out <protocol> HTTP call"""
    closed: list[bool] = []

    def reply(message: dict[str, Any], request: HttpClientRequest) -> HttpClientResponse:
        if message["method"] == "tools/call":
            body = stream.never.ensuring(fx.sync(lambda: closed.append(True)))
            return make_response(
                request, cast("Any", body), headers={"content-type": "text/event-stream"}
            )
        return scripted_reply(protocol, message, request)

    scripted = yield from scripted_http(reply, protocol)
    call = yield from scripted.client.call_tool(SLOW_TOOL, timeout=1).flip().fork()
    yield from testing.adjust(1)
    error = yield from call.join()
    assert isinstance(error.reason, CE.TimeoutError)

    call_request = next(s.body for s in scripted.sent if _method_of(s.message) == "tools/call")
    cancellations = [s for s in scripted.sent if _method_of(s.message) == "notifications/cancelled"]
    assert closed == [True]
    if protocol.protocol_version == "2025-11-25":
        assert [c.body["params"] for c in cancellations] == [{"requestId": call_request["id"]}]
        assert cancellations[0].request.headers.get("mcp-session-id") == "session-1"
    else:
        assert cancellations == []


@testing.effect
def test_echoes_the_session_id_and_deletes_the_session_on_close():
    """McpClient / legacy HTTP sessions / should echo the session ID and delete the session when the scope closes"""  # noqa: E501

    @fx.gen
    def session():
        scripted = yield from scripted_http(
            lambda message, request: scripted_reply(P.v2025_11_25, message, request), P.v2025_11_25
        )
        yield from scripted.client.list_tools()
        return scripted.sent

    sent = yield from fx.scoped(session)
    initialize, *rest = sent
    assert initialize.body["method"] == "initialize"
    assert initialize.body["params"]["clientInfo"] == CLIENT_INFO
    assert [s.request.headers.get("mcp-session-id") for s in rest] == ["session-1"] * 3
    assert [_method_of(s.message) or s.request.method for s in rest] == [
        "notifications/initialized",
        "tools/list",
        "DELETE",
    ]


@testing.effect
def test_fails_with_session_expired_when_the_server_forgets_the_session():
    """McpClient / legacy HTTP sessions / should fail with sessionExpired when the server no longer recognizes the session"""  # noqa: E501

    def reply(message: dict[str, Any], request: HttpClientRequest) -> HttpClientResponse:
        if message["method"] == "tools/list":
            return make_response(request, None, status=404)
        return scripted_reply(P.v2025_11_25, message, request)

    scripted = yield from scripted_http(reply, P.v2025_11_25)
    error = yield from scripted.client.list_tools().flip()
    assert isinstance(error.reason, CE.ClosedError)
    assert cast("Any", error.reason).session_expired is True
    count = len(scripted.sent)
    assert (yield from scripted.client.list_tools().flip()) is error
    assert len(scripted.sent) == count


@testing.effect
def test_answers_a_legacy_ping_before_the_final_sse_response():
    """McpClient / HTTP responses / should answer a legacy ping before the final SSE response"""

    def reply(message: dict[str, Any], request: HttpClientRequest) -> HttpClientResponse:
        if message["method"] == "tools/list":
            return sse_response(
                request,
                [
                    {"jsonrpc": "2.0", "id": "ping-1", "method": "ping"},
                    {"jsonrpc": "2.0", "id": message["id"], "result": {"tools": []}},
                ],
            )
        return scripted_reply(P.v2025_11_25, message, request)

    scripted = yield from scripted_http(reply, P.v2025_11_25)
    assert (yield from scripted.client.list_tools()) == []
    assert any(
        s.message is not None and s.message.get("id") == "ping-1" and "result" in s.message
        for s in scripted.sent
    )


@testing.effect
def test_skips_modern_progress_notifications_before_the_final_sse_response():
    """McpClient / HTTP responses / should skip modern progress notifications before the final SSE response"""  # noqa: E501

    def reply(message: dict[str, Any], request: HttpClientRequest) -> HttpClientResponse:
        if message["method"] == "tools/list":
            progress = {
                "jsonrpc": "2.0",
                "method": "notifications/progress",
                "params": {"progressToken": 1, "progress": 1},
            }
            final: dict[str, Any] = {
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {**DISCOVER_RESULT, "tools": []},
            }
            return sse_response(request, [progress, final])
        return scripted_reply(P.v2026_07_28, message, request)

    scripted = yield from scripted_http(reply)
    assert (yield from scripted.client.list_tools()) == []


@testing.effect
def test_preserves_http_status_and_json_rpc_error_details():
    """McpClient / HTTP responses / should preserve HTTP status and JSON-RPC error details when the client filters status codes"""  # noqa: E501

    def reply(message: dict[str, Any], request: HttpClientRequest) -> HttpClientResponse:
        if message["method"] == "tools/list":
            body = {
                "jsonrpc": "2.0",
                "id": message["id"],
                "error": {"code": -32000, "message": "Denied"},
            }
            return make_response(
                request,
                json.dumps(body),
                status=401,
                headers={
                    "content-type": "application/json",
                    "www-authenticate": 'Bearer realm="tools"',
                },
            )
        return scripted_reply(P.v2026_07_28, message, request)

    scripted = yield from scripted_http(reply)
    error = yield from scripted.client.list_tools().flip()
    reason = error.reason
    assert isinstance(reason, CE.HttpError)
    assert reason.status == 401
    assert reason.code == -32000
    assert reason.www_authenticate == 'Bearer realm="tools"'


# --- stdio -------------------------------------------------------------------------------


@dataclass
class StdioServer:
    client: C.McpClientService
    writes: Queue[bytes, Done]
    output: Queue[bytes, Done]
    exit: Deferred[int]

    @property
    def receive(self) -> fx.Effect[Any]:
        return self.writes.take().or_die().map(json.loads)

    def send(self, message: object) -> fx.Effect[None]:
        return self.output.offer((json.dumps(message) + "\n").encode()).as_void()


def connect_stdio(protocol: C.ClientProtocol) -> fx.Effect[StdioServer, Any, Any]:
    """The client of ``layer_stdio`` against a controlled process speaking
    newline-delimited JSON-RPC."""

    @fx.gen
    def run():
        output = Queue[bytes, Done]()
        writes = Queue[bytes, Done]()
        exit = Deferred[int]()

        def kill(**_options: object) -> fx.Effect[None]:
            return exit.succeed(0).as_void()

        handle = ChildProcessHandle(
            pid=cast("Any", 1),
            exit_code=cast("Any", exit.wait()),
            is_running=fx.succeed(True),
            kill=kill,
            stdin=cast(
                "Any",
                sink.for_each(writes.offer).pipe(lambda s: s.ensuring(exit.succeed(0))),
            ),
            stdout=stream.from_queue(output),
            stderr=stream.empty,
            all=stream.empty,
            get_input_fd=lambda _: cast("Any", sink.drain),
            get_output_fd=lambda _: stream.empty,
            unref=cast("Any", fx.succeed(fx.succeed(None))),
        )
        spawner = ChildProcessSpawnerService(lambda _: fx.succeed(handle))
        building = yield from (
            C.layer_stdio(
                name="test-client",
                version="1.0.0",
                command=make_command("test-mcp-server"),
                protocol=protocol,
            )
            .build()
            .pipe(fx.provide_service(ChildProcessSpawner, spawner))
            .fork()
        )
        server = StdioServer(cast("Any", None), writes, output, exit)
        initial = yield from server.receive
        legacy = protocol.protocol_version == "2025-11-25"
        assert initial["method"] == ("initialize" if legacy else "server/discover")
        result = INITIALIZE_RESULT if legacy else DISCOVER_RESULT
        yield from server.send({"jsonrpc": "2.0", "id": initial["id"], "result": result})
        context = yield from building.join()
        server.client = context.unsafe_get(C.McpClient)
        if legacy:
            assert (yield from server.receive) == {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            }
        return server

    return run


@pytest.mark.parametrize("protocol", PROTOCOLS, ids=_protocol_id)
@testing.effect
def test_cancels_a_timed_out_stdio_call(protocol: C.ClientProtocol):
    """McpClient / cancellation / should cancel a timed out <protocol> stdio call"""
    server = yield from connect_stdio(protocol)
    call = yield from server.client.call_tool(SLOW_TOOL, timeout=1).flip().fork()
    request = yield from server.receive
    assert request["method"] == "tools/call"
    yield from testing.adjust(1)
    assert isinstance((yield from call.join()).reason, CE.TimeoutError)
    assert (yield from server.receive) == {
        "jsonrpc": "2.0",
        "method": "notifications/cancelled",
        "params": {"requestId": request["id"]},
    }


@testing.effect
def test_connects_over_stdio_and_closes_the_process_with_the_scope():
    """McpClient / stdio / should connect over stdio and close the process when the layer scope ends"""  # noqa: E501

    @fx.gen
    def session():
        server = yield from connect_stdio(P.v2025_11_25)
        assert server.client.server_info == SERVER_INFO
        listing = yield from server.client.list_tools().fork()
        listed = yield from server.receive
        assert listed["method"] == "tools/list"
        yield from server.send(
            {
                "jsonrpc": "2.0",
                "id": listed["id"],
                "result": {"tools": [{"name": "read", "inputSchema": {"type": "object"}}]},
            }
        )
        assert [t["name"] for t in (yield from listing.join())] == ["read"]
        return server.exit

    exit = yield from fx.scoped(session)
    assert (yield from exit.is_done())


@testing.effect
def test_applies_the_default_deadline_to_discovery():
    """McpClient / stdio / should apply the default deadline to discovery"""
    server = yield from connect_stdio(P.v2025_11_25)
    listing = yield from server.client.list_tools().flip().fork()
    yield from server.receive
    yield from testing.adjust(60)
    assert isinstance((yield from listing.join()).reason, CE.TimeoutError)


@testing.effect
def test_applies_no_default_deadline_to_calls_prompts_or_reads():
    """McpClient / stdio / should not apply a default deadline to tool calls, prompts or resource reads"""  # noqa: E501
    server = yield from connect_stdio(P.v2025_11_25)
    prompt: Prompt = {"name": "slow"}
    fibers = [
        (yield from server.client.call_tool(SLOW_TOOL).fork()),
        (yield from server.client.get_prompt(prompt).fork()),
        (yield from server.client.read_resource("demo://slow").fork()),
    ]
    for _ in fibers:
        yield from server.receive
    yield from testing.adjust(600)
    assert all(fiber.unsafe_poll() is None for fiber in fibers)
    for fiber in fibers:
        yield from fiber.interrupt()


@testing.effect
def test_fails_pending_calls_on_an_error_without_an_id():
    """McpClient / stdio / should fail pending calls when the server sends an error without an ID"""
    server = yield from connect_stdio(P.v2025_11_25)
    call = yield from server.client.call_tool(SLOW_TOOL).flip().fork()
    yield from server.receive
    yield from server.send(
        {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
    )
    assert isinstance((yield from call.join()).reason, CE.ProtocolError)


@testing.effect
def test_fails_pending_calls_when_the_process_exits():
    """McpClient / stdio / should fail pending calls when the process exits"""
    server = yield from connect_stdio(P.v2025_11_25)
    call = yield from server.client.call_tool(SLOW_TOOL).flip().fork()
    yield from server.receive
    yield from server.exit.succeed(1)
    yield from testing.adjust(5)
    assert isinstance((yield from call.join()).reason, CE.TransportError)
