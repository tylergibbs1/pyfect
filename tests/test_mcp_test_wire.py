"""``mcp_test.make_client`` exchanges messages as a transport does: each one is
written as JSON text and read back, both ways, as Effect's ``McpTest`` does
("requests and responses round-trip through the same JSON-RPC encoding as the
stdio and HTTP transports"). So what a test sees is what a wire client sees,
whatever a JSON round trip changes (tuples become lists, ``1.0`` becomes ``1``)."""

from __future__ import annotations

import inspect
from typing import Any, TypedDict, get_type_hints

import pyfect as fx
from pyfect import _json_text, testing
from pyfect import schema as S
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_server as M
from pyfect.ai import mcp_test
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai._mcp import frames
from pyfect.layer import provide


class Words(S.Class, identifier="Words"):
    words: tuple[str, ...] = S.field(S.Array(S.String))


Split = T.make("split", success=S.to_codec_json(Words))


class EchoParams(TypedDict):
    value: object


Echo = T.make("echo", parameters=S.Struct(EchoParams), success=S.String)
KIT = K.make(Split, Echo)
HANDLERS = KIT.to_layer(
    Split.handler(lambda _, __: fx.succeed(Words(words=("a", "b")))),
    Echo.handler(lambda params, _: fx.succeed(type(params["value"]).__name__)),
)
REGISTRATIONS = M.toolkit(KIT).pipe(provide(HANDLERS))


def _wire(value: object) -> Any:
    return _json_text.parse(_json_text.stringify(value))


@testing.effect
def test_a_tool_result_is_what_a_wire_client_reads():
    client = yield from mcp_test.make_client(REGISTRATIONS, protocols=(P.v2025_11_25,))
    result: Any = yield from client.call_tool({"name": "split"})
    assert result["structuredContent"] == {"words": ["a", "b"]}
    assert result == _wire(result)


@testing.effect
def test_a_request_reaches_the_server_as_a_wire_server_reads_it():
    client = yield from mcp_test.make_client(REGISTRATIONS, protocols=(P.v2026_07_28,))
    arguments: Any = {"value": ("a", "b")}
    result = yield from client.call_tool({"name": "echo", "arguments": arguments})
    assert result["content"] == [{"type": "text", "text": '"list"'}]


@testing.effect
def test_a_notification_is_what_a_wire_client_reads():
    greeting = M.resource(uri="test://greeting", name="greeting", content=fx.succeed("hello"))
    client = yield from mcp_test.make_client(greeting, protocols=(P.v2025_11_25,))
    yield from client.subscribe({"uri": "test://greeting"})
    payload: Any = {"uri": "test://greeting", "tags": ("x",)}
    yield from client.server.notify("notifications/resources/updated", payload)
    notification = yield from client.notifications.take()
    assert notification.payload["tags"] == ["x"]


def test_only_the_wire_reaches_the_connection():
    """The guard: in ``mcp_test`` only ``_Wire.send`` hands the server a message,
    after writing it as JSON text, and the client reads only ``Frame`` s, so no
    path skips the JSON round trip a transport makes."""
    source = inspect.getsource(mcp_test)
    assert source.count(".dispatch(") == 1
    assert source.count("frames.read(frames.write(") == 1
    hints = get_type_hints(mcp_test.McpTestClient._receive)  # pyright: ignore[reportPrivateUsage]
    assert hints["frame"] is frames.Frame
