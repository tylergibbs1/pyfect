"""Ports of Effect's MCP conformance resource titles
(test/ai/McpServer/McpConformance/ResourcesTest.ts), run over stdio for
every revision whose test file runs the suite.

Effect runs these over its HTTP conformance harness; the stdio harness
serves the same resources, and the titles check the JSON-RPC results only.
A blob is given as base64 text (``"AQID"``) where Effect's result takes a
``Uint8Array``.

"Resources > Legacy subscriptions" is in test_mcp_conformance_subscriptions.py.

Omitted: none.
"""

from __future__ import annotations

from typing import Any

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai._mcp.core import ResourceEntry
from pyfect.context import Context

from ._mcp import Json, StdioHarness, stdio_harness

ALL = [P.v2024_11_05, P.v2025_03_26, P.v2025_06_18, P.v2025_11_25, P.v2026_07_28]
STATEFUL = [p for p in ALL if not p.is_stateless]


def _id(protocol: P.AnyProtocolAdapter) -> str:
    return protocol.protocol_version


def _features(invocations: list[str]) -> tuple[fx.Effect[None, Any, Any], ...]:
    """The resources of Effect's ``makeFeaturesServerLayer``."""

    def numeric(uri: str, _id: float) -> fx.Effect[str]:
        return fx.sync(lambda: invocations.append("NumericResourceTemplate")).as_(uri)

    return (
        M.register_resource(
            uri="file:///test",
            name="TestResource",
            description="A test resource",
            mime_type="text/plain",
            content=fx.succeed(
                {"contents": [{"uri": "file:///test", "mimeType": "text/plain", "text": "test"}]}
            ),
        ),
        M.register_resource(
            uri="file:///binary",
            name="BinaryResource",
            mime_type="application/octet-stream",
            content=fx.succeed(
                {
                    "contents": [
                        {
                            "uri": "file:///binary",
                            "mimeType": "application/octet-stream",
                            "blob": "AQID",
                        }
                    ]
                }
            ),
        ),
        M.register_resource(
            uri="file:///multiple",
            name="MultipleResource",
            content=fx.succeed(
                {
                    "contents": [
                        {
                            "uri": "file:///multiple#first",
                            "mimeType": "text/plain",
                            "text": "first",
                        },
                        {
                            "uri": "file:///multiple#second",
                            "mimeType": "text/plain",
                            "text": "second",
                        },
                    ]
                }
            ),
        ),
        M.register_resource_template(
            M.uri_template("file:///template/", MS.param("path", S.String)),
            name="TestResourceTemplate",
            description="A test resource template",
            mime_type="text/plain",
            content=lambda uri, path: fx.succeed(f"{uri}:{path}"),
        ),
        M.register_resource_template(
            M.uri_template("file:///numeric/", MS.param("id", S.FiniteFromString)),
            name="NumericResourceTemplate",
            content=numeric,
        ),
    )


def _server(
    protocol: P.AnyProtocolAdapter, invocations: list[str] | None = None
) -> fx.Effect[StdioHarness, Any, Any]:
    @fx.gen
    def run():
        harness = yield from stdio_harness(protocol, None, *_features(invocations or []))
        yield from harness.initialize()
        return harness

    return run


def _capabilities(protocol: P.AnyProtocolAdapter, *, features: bool) -> fx.Effect[Json, Any, Any]:
    @fx.gen
    def run():
        registrations = _features([]) if features else ()
        harness = yield from stdio_harness(protocol, None, *registrations)
        if protocol.is_stateless:
            reply = yield from harness.send_request("server/discover", {})
        else:
            reply = yield from harness.initialize()
        return reply["result"]["capabilities"]

    return run


def _send(protocol: P.AnyProtocolAdapter, method: str, params: Json) -> fx.Effect[Json, Any, Any]:
    return _server(protocol).flat_map(lambda harness: harness.send_request(method, params))


def _read(protocol: P.AnyProtocolAdapter, uri: str) -> fx.Effect[list[Json], Any, Any]:
    return _send(protocol, "resources/read", {"uri": uri}).map(
        lambda reply: reply["result"]["contents"]
    )


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_advertise_resources_when_resources_are_registered(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Resources / Capabilities / MUST advertise resources when resources are registered"""  # noqa: E501
    assert "resources" in (yield from _capabilities(protocol, features=True))


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_not_advertise_resources_when_not_supported(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Resources / Capabilities / MUST NOT advertise resources when resources are not supported"""  # noqa: E501
    assert "resources" not in (yield from _capabilities(protocol, features=False))


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_list_every_resource_visible_to_the_initialized_client(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Resources / Listing Resources / MUST list every resource visible to the initialized client"""  # noqa: E501
    reply = yield from _send(protocol, "resources/list", {})
    assert sorted(r["uri"] for r in reply["result"]["resources"]) == [
        "file:///binary",
        "file:///multiple",
        "file:///test",
    ]


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_schema_preserves_resource_uri_name_description_and_mime_type(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Resources / Listing Resources / SCHEMA preserves resource URI, name, description, and MIME type"""  # noqa: E501
    reply = yield from _send(protocol, "resources/list", {})
    resource = next(r for r in reply["result"]["resources"] if r["uri"] == "file:///test")
    assert (
        resource
        | {
            "uri": "file:///test",
            "name": "TestResource",
            "description": "A test resource",
            "mimeType": "text/plain",
        }
        == resource
    )


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_read_text_resource_contents(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Resources / Reading Resources / MUST read text resource contents"""
    assert (yield from _read(protocol, "file:///test")) == [
        {"uri": "file:///test", "mimeType": "text/plain", "text": "test"}
    ]


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_read_binary_resource_contents_as_base64(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Resources / Reading Resources / MUST read binary resource contents as base64"""  # noqa: E501
    assert (yield from _read(protocol, "file:///binary")) == [
        {"uri": "file:///binary", "mimeType": "application/octet-stream", "blob": "AQID"}
    ]


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_schema_preserves_the_resource_uri_and_mime_type_in_contents(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Resources / Reading Resources / SCHEMA preserves the resource URI and MIME type in returned contents"""  # noqa: E501
    contents = yield from _read(protocol, "file:///test")
    assert contents[0]["uri"] == "file:///test"
    assert contents[0]["mimeType"] == "text/plain"


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_return_multiple_resource_contents_in_order(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Resources / Reading Resources / MUST return multiple resource contents in order"""  # noqa: E501
    contents = yield from _read(protocol, "file:///multiple")
    assert [c["uri"] for c in contents] == ["file:///multiple#first", "file:///multiple#second"]


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_should_return_the_revision_specific_error_for_an_unknown_uri(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Resources / Reading Resources / should return the revision-specific error when the resource URI is unknown"""  # noqa: E501
    reply = yield from _send(protocol, "resources/read", {"uri": "file:///missing"})
    expected = -32602 if protocol.protocol_version == "2026-07-28" else -32002
    assert reply["error"]["code"] == expected


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_list_every_registered_resource_template(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Resources / Resource Templates / MUST list every registered resource template"""  # noqa: E501
    reply = yield from _send(protocol, "resources/templates/list", {})
    template = next(
        t for t in reply["result"]["resourceTemplates"] if t["name"] == "TestResourceTemplate"
    )
    assert {k: template.get(k) for k in ("uriTemplate", "name", "description", "mimeType")} == {
        "uriTemplate": "file:///template/{path}",
        "name": "TestResourceTemplate",
        "description": "A test resource template",
        "mimeType": "text/plain",
    }


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_match_and_decode_a_concrete_resource_template_uri(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Resources / Resource Templates / MUST match and decode a concrete resource-template URI"""  # noqa: E501
    contents = yield from _read(protocol, "file:///template/encoded%20path")
    assert contents[0]["text"] == "file:///template/encoded%20path:encoded path"


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_not_invoke_the_handler_when_template_decoding_fails(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Resources / Resource Templates / MUST not invoke the handler when template parameter decoding fails"""  # noqa: E501
    invocations: list[str] = []
    harness = yield from _server(protocol, invocations)
    reply = yield from harness.send_request(
        "resources/read", {"uri": "file:///numeric/not-a-number"}
    )
    assert reply["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE
    assert invocations == []


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_should_advertise_resource_list_change_notifications(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Resources > Legacy notifications / should advertise resource list-change notifications when supported"""  # noqa: E501
    capabilities = yield from _capabilities(protocol, features=True)
    assert capabilities["resources"]["listChanged"] is True


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_should_send_a_resource_list_change_notification_when_the_advertised_list_changes(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Resources > Legacy notifications / should send a resource list-change notification when the advertised list changes"""  # noqa: E501
    fixture = yield from stdio_harness(protocol)

    def entry(uri: str) -> ResourceEntry:
        return ResourceEntry(
            {"uri": uri, "name": uri}, Context.empty(), fx.succeed({"contents": []})
        )

    yield from fixture.server.add_resource(entry("file:///baseline-list-changed"))
    yield from fixture.initialize()
    yield from fixture.server.add_resource(entry("file:///dynamic-list-changed"))
    yield from fixture.flush_list_changed
    notification = yield from fixture.await_outbound_method("notifications/resources/list_changed")
    assert notification["jsonrpc"] == "2.0"
    assert "id" not in notification
    response = yield from fixture.send_request("resources/list", {})
    uris = [r["uri"] for r in response["result"]["resources"]]
    assert "file:///dynamic-list-changed" in uris
