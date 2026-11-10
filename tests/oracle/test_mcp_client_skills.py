# pyright: basic
"""Ports of the skills and discovery-limit tests of Effect's
``test/ai/McpClient.test.ts``: the MCP Skills extension (SEP-2640) on the
client.

Each test's docstring is the Effect test title (with its ``describe``).
``connect`` reaches an in-memory ``McpServer.layer_http`` serving skills;
``scripted_http`` answers each request with a canned response. A blob is
base64 text, as on the wire.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest

import pyfect as fx
from pyfect import layer, testing
from pyfect.ai import mcp_client as C
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_server as M
from pyfect.ai.mcp_client_error import McpClientError
from pyfect.ai.mcp_schema import Skill
from pyfect.http.client import HttpClient
from pyfect.http.client import make as make_http_client
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.http.response import make as make_response

from ._mcp import MCP_ENDPOINT, in_memory_http

PROTOCOLS = [P.v2025_11_25, P.v2026_07_28]
SERVER_INFO: dict[str, Any] = {"name": "scripted-server", "version": "1.0.0"}
PNG = bytes([0x89, 0x50, 0x4E, 0x47])

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
SLOW_TOOL: dict[str, Any] = {"name": "slow", "inputSchema": {"type": "object"}}


def _protocol_id(protocol: P.AnyProtocolAdapter) -> str:
    return protocol.protocol_version


def _served(registrations: fx.Effect[None, Any, Any]) -> Any:
    return layer.effect_discard(registrations).pipe(
        layer.provide_merge(
            M.layer_http(
                name="skills-server",
                version="1.0.0",
                path="/mcp",
                protocols=(P.v2026_07_28, P.v2025_11_25),
            )
        )
    )


SKILLS_SERVER = _served(
    M.register_skill(
        "skill://acme/refunds/SKILL.md",
        {
            "SKILL.md": "---\nname: refunds\ndescription: Process refunds\n---\n\n"
            "Read references/policy.md.\n",
            "references/policy.md": "Refunds need approval.\n",
            "assets/logo.png": PNG,
        },
    ).and_then(
        M.register_skill(
            "skill://acme/invoices/SKILL.md",
            {
                "SKILL.md": "---\nname: invoices\ndescription: Draft invoices\n---\n\n"
                "Use the invoice tools.\n"
            },
        )
    )
)
PLAIN_SERVER = _served(
    M.register_resource(uri="demo://guide", name="guide", content=fx.succeed("Guide"))
)


def connect(
    protocol: C.ClientProtocol, server: Any, extensions: C.ClientExtensions | None = None
) -> fx.Effect[C.McpClientService, Any, Any]:
    @fx.gen
    def run():
        http = yield from in_memory_http(server)
        transport = yield from C.http(url=MCP_ENDPOINT, protocol=protocol).pipe(
            fx.provide_service(HttpClient, http)
        )
        return (
            yield from C.make(name="test-client", version="1.0.0", extensions=extensions).pipe(
                fx.provide_service(C.Transport, transport)
            )
        )

    return run


# --- scripted HTTP -----------------------------------------------------------------------


@dataclass
class Sent:
    request: HttpClientRequest
    message: dict[str, Any] | None


type Reply = Callable[[dict[str, Any], HttpClientRequest], HttpClientResponse]


def _body_of(request: HttpClientRequest) -> dict[str, Any] | None:
    data = getattr(request.body, "body", None)
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

    def methods(self) -> list[str | None]:
        return [None if s.message is None else s.message.get("method") for s in self.sent]

    def count(self, method: str) -> int:
        return self.methods().count(method)


def scripted_http(
    reply: Reply,
    *,
    protocol: C.ClientProtocol = P.v2026_07_28,
    discovery_limits: Any = None,
    extensions: C.ClientExtensions | None = None,
    sent: list[Sent] | None = None,
) -> fx.Effect[Scripted, McpClientError, Any]:
    """Connects through the public HTTP transport, recording every request
    in ``sent``. Requests are answered by ``reply``; the rest get 202."""
    recorded: list[Sent] = [] if sent is None else sent

    def handle(request: HttpClientRequest) -> fx.Effect[HttpClientResponse]:
        def answer() -> HttpClientResponse:
            message = _body_of(request)
            recorded.append(Sent(request, message))
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
        client = yield from C.make(
            name="test-client",
            version="1.0.0",
            discovery_limits=discovery_limits,
            extensions=extensions,
        ).pipe(fx.provide_service(C.Transport, transport))
        return Scripted(client, recorded)

    return run


def _tag(error: McpClientError) -> str:
    return error.reason._tag


# --- discovery limits --------------------------------------------------------------------


@testing.effect
def test_stops_discovery_when_a_scan_exceeds_inherited_or_overridden_limits():
    """McpClient / discovery limits / should stop discovery when a scan exceeds inherited or overridden limits"""  # noqa: E501

    def reply(message: dict[str, Any], request: HttpClientRequest) -> HttpClientResponse:
        if message["method"] == "tools/list":
            page = {**DISCOVER_RESULT, "tools": [SLOW_TOOL], "nextCursor": str(message["id"])}
            return json_result(request, message, page)
        return scripted_reply(P.v2026_07_28, message, request)

    scripted = yield from scripted_http(reply, discovery_limits={"max_pages": 1})

    page_error = yield from scripted.client.list_tools(limits={"max_items": 5}).flip()
    assert _tag(page_error) == "LimitError"
    assert scripted.count("tools/list") == 1

    item_error = yield from scripted.client.list_tools(
        limits={"max_pages": 3, "max_items": 1}
    ).flip()
    assert _tag(item_error) == "LimitError"
    assert scripted.count("tools/list") == 3


@testing.effect
def test_fails_with_configuration_error_when_client_or_scan_limits_are_invalid():
    """McpClient / discovery limits / should fail with ConfigurationError when client or scan limits are invalid"""  # noqa: E501

    def reply(message: dict[str, Any], request: HttpClientRequest) -> HttpClientResponse:
        return scripted_reply(P.v2026_07_28, message, request)

    client_error = yield from scripted_http(reply, discovery_limits={"max_items": -1}).flip()
    scripted = yield from scripted_http(reply)
    scan_error = yield from scripted.client.list_tools(limits={"max_pages": 0.5}).flip()  # pyright: ignore[reportArgumentType]
    assert _tag(client_error) == "ConfigurationError"
    assert _tag(scan_error) == "ConfigurationError"
    assert scripted.count("tools/list") == 0


# --- skills against an in-memory server ----------------------------------------------------


@pytest.mark.parametrize("protocol", PROTOCOLS, ids=_protocol_id)
@testing.effect
def test_lists_gets_and_browses_skills_and_reads_their_files_verified(protocol: C.ClientProtocol):
    """McpClient skills / <protocol> / should list, get and browse skills and read their files verified"""  # noqa: E501
    client = yield from connect(protocol, SKILLS_SERVER, {"skills": True})
    skills = yield from client.list_skills()
    assert sorted(skill["uri"] for skill in skills) == [
        "skill://acme/invoices/SKILL.md",
        "skill://acme/refunds/SKILL.md",
    ]
    refunds = yield from client.get_skill("skill://acme/refunds/SKILL.md")
    assert refunds == next(skill for skill in skills if skill["uri"] == refunds["uri"])
    assert refunds["frontmatter"] == {"name": "refunds", "description": "Process refunds"}

    children = yield from client.read_resource_directory("skill://acme/refunds")
    assert [child["name"] for child in children] == ["refunds", "assets", "references"]

    resources = refunds["resources"]
    assert resources != "dynamic"
    for resource in resources:
        result = yield from client.read_skill_resource(refunds, resource["uri"])
        assert result["contents"][0]["uri"] == resource["uri"]
    logo = yield from client.read_skill_resource(refunds, "skill://acme/refunds/assets/logo.png")
    content: Any = logo["contents"][0]
    assert base64.b64decode(content["blob"]) == PNG


@pytest.mark.parametrize("protocol", PROTOCOLS, ids=_protocol_id)
@testing.effect
def test_does_not_call_the_extension_s_methods_on_a_server_that_does_not_declare_it(
    protocol: C.ClientProtocol,
):
    """McpClient skills / <protocol> / should not call the extension's methods on a server that does not declare it"""  # noqa: E501
    client = yield from connect(protocol, PLAIN_SERVER, {"skills": True})
    assert (yield from client.list_skills()) == []
    for effect in [
        client.get_skill("skill://acme/refunds/SKILL.md"),
        client.read_resource_directory("skill://acme"),
    ]:
        assert _tag((yield from effect.flip())) == "UnsupportedError"


# --- skills against a scripted server ----------------------------------------------------


def skills_discovery(directory_read: bool) -> dict[str, Any]:
    return {
        **DISCOVER_RESULT,
        "capabilities": {
            "resources": {},
            "extensions": {"io.modelcontextprotocol/skills": {"directoryRead": directory_read}},
        },
    }


POLICY = b"Refunds need approval.\n"
ENTRY: dict[str, Any] = {
    "uri": "skill://refunds/SKILL.md",
    "frontmatter": {"name": "refunds", "description": "Process refunds"},
    "resources": [
        {"uri": "skill://refunds/SKILL.md", "digest": f"sha256:{'0' * 64}", "size": 10},
        {
            "uri": "skill://refunds/policy.md",
            "digest": f"sha256:{hashlib.sha256(POLICY).hexdigest()}",
            "size": len(POLICY),
        },
    ],
}
CACHEABLE: dict[str, Any] = {"resultType": "complete", "ttlMs": 0, "cacheScope": "private"}


def scripted_skills(
    results: dict[str, Callable[[dict[str, Any]], dict[str, Any]]], directory_read: bool = True
) -> fx.Effect[Scripted, McpClientError, Any]:
    def reply(message: dict[str, Any], request: HttpClientRequest) -> HttpClientResponse:
        if message["method"] == "server/discover":
            return json_result(request, message, skills_discovery(directory_read))
        result = results.get(message["method"])
        if result is None:
            return scripted_reply(P.v2026_07_28, message, request)
        return json_result(request, message, {**CACHEABLE, **result(message)})

    return scripted_http(reply, extensions={"skills": True})


def _skill(value: dict[str, Any]) -> Skill:
    return value  # pyright: ignore[reportReturnType]


@testing.effect
def test_declares_the_extension_only_when_enabled():
    """McpClient skills / should declare the extension only when enabled"""
    for skills in (True, False):
        scripted = yield from scripted_http(
            lambda message, request: scripted_reply(P.v2025_11_25, message, request),
            protocol=P.v2025_11_25,
            extensions={"skills": skills},
        )
        initialize = next(
            s.message
            for s in scripted.sent
            if s.message is not None and s.message.get("method") == "initialize"
        )
        assert initialize["params"]["capabilities"] == (
            {"extensions": {"io.modelcontextprotocol/skills": {}}} if skills else {}
        )

    def reply(message: dict[str, Any], request: HttpClientRequest) -> HttpClientResponse:
        if message["method"] == "server/discover":
            return json_result(request, message, skills_discovery(True))
        return scripted_reply(P.v2026_07_28, message, request)

    scripted = yield from scripted_http(reply)
    discover = next(
        s.message
        for s in scripted.sent
        if s.message is not None and s.message.get("method") == "server/discover"
    )
    assert discover["params"]["_meta"]["io.modelcontextprotocol/clientCapabilities"] == {}
    client = scripted.client
    skill = _skill(ENTRY)
    for effect in [
        client.list_skills(),
        client.get_skill(ENTRY["uri"]),
        client.read_resource_directory("skill://refunds"),
        client.read_skill_resource(skill, ENTRY["uri"]),
    ]:
        assert _tag((yield from effect.flip())) == "ConfigurationError"
    assert scripted.methods() == ["server/discover"]


@testing.effect
def test_rejects_a_listed_skill_that_breaks_the_extension_s_rules():
    """McpClient skills / should reject a listed skill that breaks the extension's rules"""
    resources = ENTRY["resources"]
    for invalid in [
        {**ENTRY, "frontmatter": {"name": "other", "description": "Process refunds"}},
        {**ENTRY, "resources": resources[1:]},
        {
            **ENTRY,
            "resources": [
                *resources,
                {"uri": "skill://other/file.md", "digest": resources[0]["digest"], "size": 1},
            ],
        },
        {**ENTRY, "resources": [{**resources[0], "digest": "sha256:ABC"}]},
    ]:
        scripted = yield from scripted_skills({"skills/list": lambda _, i=invalid: {"skills": [i]}})
        error = yield from scripted.client.list_skills().flip()
        assert _tag(error) == "ValidationError"


@testing.effect
def test_accepts_a_skill_whose_other_frontmatter_fields_the_agent_skills_specification_does_not_allow():  # noqa: E501
    """McpClient skills / should accept a skill whose other frontmatter fields the Agent Skills specification does not allow"""  # noqa: E501
    frontmatter = {**ENTRY["frontmatter"], "metadata": {"version": 2}, "future-field": [1]}
    scripted = yield from scripted_skills(
        {"skills/list": lambda _: {"skills": [{**ENTRY, "frontmatter": frontmatter}]}}
    )
    [skill] = yield from scripted.client.list_skills()
    assert skill["frontmatter"] == frontmatter


@testing.effect
def test_skips_invalid_skills_only_when_given_on_invalid_skill_reporting_each():
    """McpClient skills / should skip invalid skills only when given onInvalidSkill, reporting each"""  # noqa: E501
    invalid = {**ENTRY, "uri": "skill://other/SKILL.md"}
    scripted = yield from scripted_skills(
        {"skills/list": lambda _: {"skills": [invalid, ENTRY, {"uri": 1}]}}
    )
    assert _tag((yield from scripted.client.list_skills().flip())) == "ValidationError"

    reported: list[tuple[object, str]] = []

    def report(found: C.InvalidSkill) -> fx.Effect[None]:
        return fx.sync(lambda: reported.append((found.entry, _tag(found.error))))

    skills = yield from scripted.client.list_skills(on_invalid_skill=report)
    assert [skill["uri"] for skill in skills] == [ENTRY["uri"]]
    assert reported == [(invalid, "ValidationError"), ({"uri": 1}, "ValidationError")]


@testing.effect
def test_rejects_skills_get_answering_for_another_skill():
    """McpClient skills / should reject skills/get answering for another skill"""
    scripted = yield from scripted_skills({"skills/get": lambda _: {"skill": ENTRY}})
    error = yield from scripted.client.get_skill("skill://other/SKILL.md").flip()
    assert _tag(error) == "ValidationError"


@testing.effect
def test_rejects_a_directory_child_that_is_not_a_direct_child():
    """McpClient skills / should reject a directory child that is not a direct child"""
    child = {
        "uri": "skill://refunds/nested/file.md",
        "name": "file.md",
        "mimeType": "text/markdown",
    }
    scripted = yield from scripted_skills(
        {"resources/directory/read": lambda _: {"resources": [child]}}
    )
    error = yield from scripted.client.read_resource_directory("skill://refunds").flip()
    assert _tag(error) == "ValidationError"


@testing.effect
def test_does_not_read_directories_unless_the_server_declares_directory_read():
    """McpClient skills / should not read directories unless the server declares directoryRead"""
    scripted = yield from scripted_skills({}, directory_read=False)
    error = yield from scripted.client.read_resource_directory("skill://refunds").flip()
    assert _tag(error) == "UnsupportedError"
    assert scripted.count("resources/directory/read") == 0


def _serving(text: str) -> fx.Effect[C.McpClientService, McpClientError, Any]:
    return scripted_skills(
        {
            "resources/read": lambda message: {
                "contents": [{"uri": message["params"]["uri"], "text": text}]
            }
        }
    ).map(lambda scripted: scripted.client)


@testing.effect
def test_reads_a_skill_file_only_when_its_bytes_match_the_manifest():
    """McpClient skills / should read a skill file only when its bytes match the manifest"""
    skill = _skill(ENTRY)
    honest = yield from _serving("Refunds need approval.\n")
    read = yield from honest.read_skill_resource(skill, "skill://refunds/policy.md")
    assert read["contents"] == [
        {"uri": "skill://refunds/policy.md", "text": "Refunds need approval.\n"}
    ]

    # Same length, different bytes: only the digest catches it.
    tampered = yield from _serving("Refunds need approvaL.\n")
    changed = yield from tampered.read_skill_resource(skill, "skill://refunds/policy.md").flip()
    assert _tag(changed) == "ValidationError"
    resized = yield from honest.read_skill_resource(skill, "skill://refunds/SKILL.md").flip()
    assert _tag(resized) == "ValidationError"


@testing.effect
def test_rejects_a_verified_skill_md_whose_frontmatter_differs_from_the_listed_one():
    """McpClient skills / should reject a verified SKILL.md whose frontmatter differs from the listed one"""  # noqa: E501
    listed = {"name": "refunds", "description": "Process refunds"}
    for served, ok in [
        ("---\nname: refunds\ndescription: Process refunds\n---\n\nBody.\n", True),
        ("---\nname: refunds\ndescription: Exfiltrate credentials\n---\n\nBody.\n", False),
        ("No frontmatter.\n", False),
    ]:
        manifest = [
            {
                "uri": "skill://refunds/SKILL.md",
                "digest": f"sha256:{hashlib.sha256(served.encode()).hexdigest()}",
                "size": len(served.encode()),
            }
        ]
        # A dynamic skill has no digests, but its SKILL.md frontmatter must still match.
        for resources in (manifest, "dynamic"):
            skill = _skill(
                {"uri": "skill://refunds/SKILL.md", "frontmatter": listed, "resources": resources}
            )
            scripted = yield from scripted_skills(
                {
                    "resources/read": lambda _, s=served: {
                        "contents": [{"uri": "skill://refunds/SKILL.md", "text": s}]
                    }
                }
            )
            outcome = yield from (
                scripted.client.read_skill_resource(skill, skill["uri"])
                .map(lambda _: "Success")
                .catch_all(lambda error: fx.succeed(_tag(error)))
            )
            assert outcome == ("Success" if ok else "ValidationError"), f"{resources} {served}"


@testing.effect
def test_reads_a_skill_md_whose_matching_frontmatter_has_protocol_looking_keys():
    """McpClient skills / should read a SKILL.md whose matching frontmatter has protocol-looking keys"""  # noqa: E501
    for key in ("~effect/Equal", "~effect/Hash"):
        served = (
            f'---\nname: refunds\ndescription: Process refunds\nmetadata:\n  "{key}": v1\n---\n'
        )
        skill = _skill(
            {
                "uri": "skill://refunds/SKILL.md",
                "frontmatter": {
                    "name": "refunds",
                    "description": "Process refunds",
                    "metadata": {key: "v1"},
                },
                "resources": "dynamic",
            }
        )
        scripted = yield from scripted_skills(
            {
                "resources/read": lambda _, s=served: {
                    "contents": [{"uri": "skill://refunds/SKILL.md", "text": s}]
                }
            }
        )
        read = yield from scripted.client.read_skill_resource(skill, skill["uri"])
        assert read["contents"] == [{"uri": skill["uri"], "text": served}], key


@testing.effect
def test_reads_a_dynamic_skill_s_files_without_digests_only_inside_its_directory():
    """McpClient skills / should read a dynamic skill's files without digests, only inside its directory"""  # noqa: E501
    scripted = yield from scripted_skills(
        {
            "resources/read": lambda message: {
                "contents": [{"uri": message["params"]["uri"], "text": "Anything.\n"}]
            }
        }
    )
    dynamic = _skill({**ENTRY, "resources": "dynamic"})
    read = yield from scripted.client.read_skill_resource(
        dynamic, "skill://refunds/references/new.md"
    )
    assert read["contents"] == [{"uri": "skill://refunds/references/new.md", "text": "Anything.\n"}]
    assert scripted.count("resources/read") == 1

    for uri in (
        "skill://other/file.md",
        "skill://refunds-v2/file.md",
        "skill://refunds/../other/file.md",
    ):
        error = yield from scripted.client.read_skill_resource(dynamic, uri).flip()
        assert _tag(error) == "ValidationError", uri
    assert scripted.count("resources/read") == 1


@testing.effect
def test_does_not_read_files_missing_from_the_manifest():
    """McpClient skills / should not read files missing from the manifest"""
    scripted = yield from scripted_skills({})
    unlisted = yield from scripted.client.read_skill_resource(
        _skill(ENTRY), "skill://refunds/extra.md"
    ).flip()
    assert _tag(unlisted) == "ValidationError"
    assert scripted.count("resources/read") == 0
