"""Ports of the 2026-07-28 listing and cache hint titles of Effect's
``test/ai/McpServer/v2026_07_28.test.ts`` (Effect 4.1.2): registrations
given as plain objects or with optional fields left out, and the
``cache_hints`` a server advertises as ``ttlMs``."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

import pyfect as fx
from pyfect import layer, testing
from pyfect import schema as S
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_server as M
from pyfect.ai._mcp.core import PromptEntry, ResourceEntry, ResourceTemplateEntry
from pyfect.context import Context
from pyfect.errors import IllegalArgumentError

from ._mcp import Json
from ._mcp_http import HttpHarness, Mode, http_harness, read_message, server_layer

PROTOCOLS = (P.v2026_07_28,)
META: Json = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "McpConformanceClient", "version": "1.0.0"},
}
MODES: tuple[Mode, ...] = ("server", "request")


def _list(harness: HttpHarness, method: str, params: Json | None = None, name: str | None = None):
    body = {
        "jsonrpc": "2.0",
        "id": method,
        "method": method,
        "params": {**(params or {}), "_meta": META},
    }
    headers = {"mcp-protocol-version": "2026-07-28", "mcp-method": method}
    if name is not None:
        headers["mcp-name"] = name
    return (
        harness.post(body, headers).flat_map(read_message).map(lambda m: cast("Json", m)["result"])
    )


def _served(
    registrations: layer.Layer[Any, Any, Any], name: str, **options: Any
) -> fx.Effect[HttpHarness, Any, Any]:
    return http_harness(
        registrations.pipe(layer.provide_merge(server_layer(name, PROTOCOLS, **options)))
    )


@testing.effect
def test_should_list_resources_and_templates_whose_optional_fields_are_given_as_undefined():
    """Mcp Conformance (2026-07-28) / Result envelopes / should list resources and templates whose optional fields are given as undefined"""  # noqa: E501
    registrations = layer.merge(
        M.resource(
            uri="file:///readme",
            name="Readme",
            description=None,
            mime_type=None,
            audience=None,
            content=fx.succeed("readme"),
        ),
        M.resource_template(
            M.uri_template("file:///notes/", S.String),
            name="Notes",
            description=None,
            mime_type=None,
            content=lambda _uri, _name: fx.succeed("notes"),
        ),
    )
    harness = yield from _served(registrations, "UndefinedFieldsServer")

    resources = yield from _list(harness, "resources/list")
    assert resources["resources"] == [
        {"uri": "file:///readme", "name": "Readme", "annotations": {}}
    ]
    templates = yield from _list(harness, "resources/templates/list")
    assert templates["resourceTemplates"] == [
        {"uriTemplate": "file:///notes/{param0}", "name": "Notes", "annotations": {}}
    ]


@testing.effect
def test_should_list_resources_templates_and_prompts_registered_as_plain_objects():
    """Mcp Conformance (2026-07-28) / Result envelopes / should list resources, templates and prompts registered as plain objects"""  # noqa: E501
    icon: Any = {"src": "https://example.com/icon.png"}

    @fx.gen
    def register():
        server = yield from M.McpServer()
        yield from server.add_resource(
            ResourceEntry(
                {"uri": "file:///plain", "name": "Plain", "icons": [icon]},
                Context.empty(),
                fx.succeed({"contents": []}),
            )
        )
        yield from server.add_resource_template(
            ResourceTemplateEntry(
                {"uriTemplate": "file:///plain/{id}", "name": "PlainTemplate", "icons": [icon]},
                Context.empty(),
                lambda uri: (
                    {"id": uri[len("file:///plain/") :]}
                    if uri.startswith("file:///plain/")
                    else None
                ),
                {},
                lambda _uri, _params: fx.succeed({"contents": []}),
            )
        )
        yield from server.add_prompt(
            PromptEntry(
                {"name": "PlainPrompt", "icons": [icon]},
                Context.empty(),
                {},
                lambda _: fx.succeed({"messages": []}),
            )
        )

    harness = yield from _served(layer.effect_discard(register), "PlainDescriptorsServer")

    resources = yield from _list(harness, "resources/list")
    assert resources["resources"] == [{"uri": "file:///plain", "name": "Plain", "icons": [icon]}]
    templates = yield from _list(harness, "resources/templates/list")
    assert templates["resourceTemplates"] == [
        {"uriTemplate": "file:///plain/{id}", "name": "PlainTemplate", "icons": [icon]}
    ]
    prompts = yield from _list(harness, "prompts/list")
    assert prompts["prompts"] == [{"name": "PlainPrompt", "icons": [icon]}]


def _hint(ttl: Any) -> M.CacheHint:
    return {"ttl": ttl, "cache_scope": "private"}


@testing.effect
def test_should_advertise_configured_cache_hints_and_keep_defaults_for_other_results():
    """Mcp Conformance (2026-07-28) / Result envelopes / should advertise configured cache hints and keep defaults for other results"""  # noqa: E501
    # A hint can carry extra keys that must not reach the wire result.
    tools_hint = cast("M.CacheHint", {**_hint("1 minute"), "internal_only": True})
    registrations = layer.merge(
        M.resource(uri="file:///cached", name="Cached", content=fx.succeed("cached")),
        M.prompt(name="Cached", content=lambda _: fx.succeed("cached")),
    )
    configs: list[tuple[M.CacheHints, dict[str, int]]] = [
        ({"tools": tools_hint}, {"tools/list": 60_000}),
        (
            {
                "discover": _hint(1),
                "tools": _hint("2 millis"),
                "resources": _hint(timedelta(milliseconds=3)),
                "resource_templates": _hint(4),
                # Sub-millisecond remainders round down, so ``ttlMs`` stays whole.
                "prompts": _hint("5999 micros"),
            },
            {
                "server/discover": 1,
                "tools/list": 2,
                "resources/list": 3,
                "resources/templates/list": 4,
                "prompts/list": 5,
            },
        ),
    ]
    cases: list[tuple[str, Json, str | None]] = [
        ("server/discover", {}, None),
        ("tools/list", {}, None),
        ("resources/list", {}, None),
        ("resources/templates/list", {}, None),
        ("prompts/list", {}, None),
        ("resources/read", {"uri": "file:///cached"}, "file:///cached"),
    ]
    for mode in MODES:
        for hints, ttls in configs:
            harness = yield from _served(
                registrations, "CacheHintServer", mode=mode, cache_hints=hints
            )
            for method, params, name in cases:
                result = yield from _list(harness, method, params, name)
                assert "ttl" not in result and "internal_only" not in result, (mode, method)
                cache = (result["ttlMs"], result["cacheScope"])
                assert cache == (ttls.get(method, 0), "private"), (mode, method)


@testing.effect
def test_should_fail_layer_construction_when_a_cache_hint_cannot_be_advertised():
    """Mcp Conformance (2026-07-28) / Result envelopes / should fail layer construction when a cache hint cannot be advertised"""  # noqa: E501
    invalid: list[Any] = [
        {"ttl": "-1 seconds", "cache_scope": "private"},
        {"ttl": "Infinity", "cache_scope": "private"},
        {"ttl": 2**53, "cache_scope": "private"},
        {"ttl": "soon", "cache_scope": "private"},
        {"ttl": 1, "cache_scope": "public"},
    ]
    for mode in MODES:
        for tools in invalid:
            served = server_layer(
                "InvalidCacheHintServer", PROTOCOLS, mode=mode, cache_hints={"tools": tools}
            )
            error = yield from http_harness(served).flip()
            assert isinstance(error, IllegalArgumentError), (mode, tools)
            assert "cache_hints.tools" in str(error), (mode, tools)
