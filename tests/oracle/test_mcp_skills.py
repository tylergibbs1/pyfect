# pyright: basic, reportPrivateUsage=false
"""Ports of Effect's ``ai/McpServer/Skills.test.ts``: the MCP Skills extension
(SEP-2640) on the server.

Each test's docstring is the Effect test title. Effect's ``McpServer.skill``
layers are ``mcp_server.register_skill`` effects run against the server
layer (``server_layer``); a file's bytes are ``bytes`` (a ``bytearray`` for
the one the caller changes afterwards).
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Callable
from typing import Any

import pytest

import pyfect as fx
from pyfect import layer, testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_server as M
from pyfect.ai._mcp.core import ResourceEntry
from pyfect.ai.mcp_schema import McpServerClient, ServerClient
from pyfect.context import Context, Tag
from pyfect.errors import IllegalArgumentError
from pyfect.exit import Exit, Failure, Success
from pyfect.scheduler import CurrentScheduler, EffectScheduler, SchedulerDispatcher

from ._mcp_http import (
    HttpHarness,
    Json,
    http_harness,
    initialize_session,
    read_message,
    server_layer,
)

MODERN = P.v2026_07_28
METADATA: Json = {
    "io.modelcontextprotocol/protocolVersion": MODERN.protocol_version,
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "SkillsClient", "version": "1.0.0"},
}
PNG = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])


def skill_md(frontmatter: str, body: str = "") -> str:
    return f"---\n{frontmatter}\n---\n\n{body}"


REFUNDS_SKILL_MD = skill_md(
    "name: refunds\n"
    "description: Process refunds using the billing tools\n"
    "license: Apache-2.0\n"
    "metadata:\n"
    "  acme-tools: issue_refund",
    "Read references/policy.md before issuing a refund.\n",
)

REFUNDS = M.register_skill(
    "skill://acme/billing/refunds/SKILL.md",
    {
        "SKILL.md": REFUNDS_SKILL_MD,
        "references/policy.md": "Refunds above CHF 500 require manager approval.\n",
        "assets/logo.png": PNG,
        "scripts/check": M.SkillFile("#!/bin/sh\n", "text/x-shellscript"),
    },
)
INVOICES = M.register_skill(
    "skill://acme/billing/invoices/SKILL.md",
    {
        "SKILL.md": skill_md(
            "name: invoices\ndescription: Draft invoices", "Use the invoice tools.\n"
        )
    },
)
SKILLS = REFUNDS.and_then(INVOICES)


def sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def modern_harness(registrations: fx.Effect[None, Any, Any]) -> fx.Effect[HttpHarness, Any, Any]:
    return http_harness(server_layer("SkillsServer", (MODERN,), registrations))


def call(
    harness: HttpHarness,
    method: str,
    params: Json | None = None,
    extra_headers: dict[str, str] | None = None,
) -> fx.Effect[tuple[int, Any]]:
    """A 2026-07-28 request: its HTTP status and JSON-RPC message."""
    params = params or {}
    headers = {"MCP-Protocol-Version": MODERN.protocol_version, "Mcp-Method": method}
    if method == "resources/read":
        headers["Mcp-Name"] = str(params["uri"])
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": {**params, "_meta": METADATA}}

    @fx.gen
    def run():
        response = yield from harness.post(body, {**headers, **(extra_headers or {})})
        message = yield from read_message(response)
        return response.status, message

    return run


def message_of(harness: HttpHarness, method: str, params: Json | None = None) -> fx.Effect[Any]:
    return call(harness, method, params).map(lambda answered: answered[1])


def read_bytes(harness: HttpHarness, uri: str) -> fx.Effect[bytes]:
    def content(message: Any) -> bytes:
        [found] = message["result"]["contents"]
        return found["text"].encode() if "text" in found else base64.b64decode(found["blob"])

    return message_of(harness, "resources/read", {"uri": uri}).map(content)


# --- v2026-07-28 ------------------------------------------------------------------------


@testing.effect
def test_declares_the_extension_and_the_resources_capability_in_discovery():
    """declares the extension and the resources capability in discovery"""
    harness = yield from modern_harness(SKILLS)
    message = yield from message_of(harness, "server/discover")
    capabilities = message["result"]["capabilities"]
    assert capabilities["extensions"] == {"io.modelcontextprotocol/skills": {"directoryRead": True}}
    assert "resources" in capabilities


@testing.effect
def test_lists_every_skill_with_a_manifest_of_the_bytes_resources_read_serves():
    """lists every skill with a manifest of the bytes resources/read serves"""
    harness = yield from modern_harness(SKILLS)
    message = yield from message_of(harness, "skills/list")
    result = message["result"]
    assert result["resultType"] == "complete"
    assert result["ttlMs"] == 0
    assert result["cacheScope"] == "private"

    refunds = next(s for s in result["skills"] if s["frontmatter"]["name"] == "refunds")
    assert refunds["uri"] == "skill://acme/billing/refunds/SKILL.md"
    assert refunds["frontmatter"] == {
        "name": "refunds",
        "description": "Process refunds using the billing tools",
        "license": "Apache-2.0",
        "metadata": {"acme-tools": "issue_refund"},
    }
    assert [r["uri"] for r in refunds["resources"]] == [
        "skill://acme/billing/refunds/SKILL.md",
        "skill://acme/billing/refunds/assets/logo.png",
        "skill://acme/billing/refunds/references/policy.md",
        "skill://acme/billing/refunds/scripts/check",
    ]
    for resource in refunds["resources"]:
        content = yield from read_bytes(harness, resource["uri"])
        assert resource["digest"] == sha256(content)
        assert resource["size"] == len(content)
    served = yield from read_bytes(harness, "skill://acme/billing/refunds/SKILL.md")
    assert served.decode() == REFUNDS_SKILL_MD


@testing.effect
def test_serves_the_bytes_given_at_registration_after_the_caller_changes_them():
    """serves the bytes given at registration after the caller changes them"""
    as_bytes = bytearray(PNG)
    view = memoryview(bytearray(PNG))
    wrapped = bytearray(PNG)
    harness = yield from modern_harness(
        M.register_skill(
            "skill://logo/SKILL.md",
            {
                "SKILL.md": skill_md("name: logo\ndescription: Draw the logo"),
                "bytes.png": as_bytes,
                "buffer.png": view,
                "wrapped.png": M.SkillFile(wrapped, "image/png"),
            },
        )
    )
    for changed in (as_bytes, view, wrapped):
        changed[:] = bytes(len(PNG))

    message = yield from message_of(harness, "skills/get", {"uri": "skill://logo/SKILL.md"})
    for name in ("bytes.png", "buffer.png", "wrapped.png"):
        uri = f"skill://logo/{name}"
        listed = next(r for r in message["result"]["skill"]["resources"] if r["uri"] == uri)
        assert (yield from read_bytes(harness, uri)) == PNG, name
        assert listed["digest"] == sha256(PNG), name


class CurrentUser(Tag[str], key="test/McpSkills/CurrentUser"):
    pass


def visibility_fixture() -> tuple[list[str], fx.Effect[None, Any, Any]]:
    calls: list[str] = []

    def auth(
        effect: fx.Effect[Any, Any, Any], options: M.MiddlewareOptions
    ) -> fx.Effect[Any, Any, Any]:
        calls.append(f"{options.method} {options.target}")
        return effect.pipe(fx.provide_service(CurrentUser, options.headers.get("x-user", "guest")))

    admin_only = M.visibility(lambda _: CurrentUser().map(lambda user: user == "admin"))
    registrations = M.register_skill(
        "skill://acme/public/SKILL.md",
        {"SKILL.md": skill_md("name: public\ndescription: Public skill", "Public.\n")},
    ).and_then(
        M.register_skill(
            "skill://acme/admin/SKILL.md",
            {
                "SKILL.md": skill_md("name: admin\ndescription: Admin skill", "Admin.\n"),
                "notes/secret.md": "Secret.\n",
            },
        ).pipe(fx.provide(admin_only.combine(M.middleware(auth, provides=CurrentUser)).layer))
    )
    return calls, registrations


ADMIN = {"x-user": "admin"}


@testing.effect
def test_hides_a_skill_from_skills_list_skills_get_directory_reads_and_file_reads():
    """hides a skill from skills/list, skills/get, directory reads and file reads"""
    _, registrations = visibility_fixture()
    harness = yield from modern_harness(registrations)

    def uris(message: Any) -> list[str]:
        return sorted(skill["uri"] for skill in message["result"]["skills"])

    assert uris((yield from call(harness, "skills/list"))[1]) == ["skill://acme/public/SKILL.md"]
    assert uris((yield from call(harness, "skills/list", {}, ADMIN))[1]) == [
        "skill://acme/admin/SKILL.md",
        "skill://acme/public/SKILL.md",
    ]

    _, hidden = yield from call(harness, "skills/get", {"uri": "skill://acme/admin/SKILL.md"})
    assert hidden["error"]["code"] == -32602
    _, shown = yield from call(harness, "skills/get", {"uri": "skill://acme/admin/SKILL.md"}, ADMIN)
    assert shown["result"]["skill"]["frontmatter"]["name"] == "admin"

    def names(message: Any) -> list[str]:
        return [child["name"] for child in message["result"]["resources"]]

    _, guest_root = yield from call(harness, "resources/directory/read", {"uri": "skill://acme"})
    assert names(guest_root) == ["public"]
    _, admin_root = yield from call(
        harness, "resources/directory/read", {"uri": "skill://acme"}, ADMIN
    )
    assert names(admin_root) == ["admin", "public"]
    for uri in ("skill://acme/admin", "skill://acme/admin/notes"):
        _, message = yield from call(harness, "resources/directory/read", {"uri": uri})
        assert message["error"]["code"] == -32602, uri

    _, read = yield from call(
        harness, "resources/read", {"uri": "skill://acme/admin/notes/secret.md"}
    )
    assert read["error"]["code"] == -32602


@testing.effect
def test_passes_the_skill_md_uri_as_the_target_checking_only_skills_that_have_the_directory():
    """passes the SKILL.md URI as the target, checking only skills that have the directory"""
    calls, registrations = visibility_fixture()
    harness = yield from modern_harness(registrations)
    yield from call(harness, "skills/list")
    yield from call(harness, "skills/get", {"uri": "skill://acme/admin/SKILL.md"})
    yield from call(harness, "resources/directory/read", {"uri": "skill://acme/public"})
    yield from call(harness, "resources/directory/read", {"uri": "skill://acme/admin/notes"})
    assert calls == [
        "skills/list skill://acme/admin/SKILL.md",
        "skills/get skill://acme/admin/SKILL.md",
        "resources/directory/read skill://acme/admin/SKILL.md",
    ]


@testing.effect
def test_gets_a_skill_by_the_uri_of_its_skill_md():
    """gets a skill by the URI of its SKILL.md"""
    harness = yield from modern_harness(SKILLS)
    listed = yield from message_of(harness, "skills/list")
    message = yield from message_of(
        harness, "skills/get", {"uri": "skill://acme/billing/invoices/SKILL.md"}
    )
    assert message["result"]["resultType"] == "complete"
    assert message["result"]["ttlMs"] == 0
    assert message["result"]["skill"] == next(
        s
        for s in listed["result"]["skills"]
        if s["uri"] == "skill://acme/billing/invoices/SKILL.md"
    )


@testing.effect
def test_reads_every_directory_of_the_skill_namespace_merging_shared_prefixes():
    """reads every directory of the skill namespace, merging shared prefixes"""
    harness = yield from modern_harness(SKILLS)

    def read(uri: str) -> fx.Effect[Any]:
        return message_of(harness, "resources/directory/read", {"uri": uri}).map(
            lambda message: message["result"]
        )

    def directory(uri: str) -> Json:
        return {"uri": uri, "name": uri.rsplit("/", maxsplit=1)[-1], "mimeType": "inode/directory"}

    resources = (yield from message_of(harness, "resources/list"))["result"]["resources"]

    def listed(uri: str) -> Json:
        return next(r for r in resources if r["uri"] == uri)

    assert listed("skill://acme/billing/refunds/SKILL.md") == {
        "uri": "skill://acme/billing/refunds/SKILL.md",
        "name": "refunds",
        "description": "Process refunds using the billing tools",
        "mimeType": "text/markdown",
        "size": len(REFUNDS_SKILL_MD.encode()),
    }

    prefix = yield from read("skill://acme/billing")
    assert prefix["resultType"] == "complete"
    assert prefix["ttlMs"] == 0
    assert prefix["resources"] == [
        directory("skill://acme/billing/invoices"),
        directory("skill://acme/billing/refunds"),
    ]
    assert (yield from read("skill://acme"))["resources"] == [directory("skill://acme/billing")]
    assert (yield from read("skill://acme/billing/refunds"))["resources"] == [
        listed("skill://acme/billing/refunds/SKILL.md"),
        directory("skill://acme/billing/refunds/assets"),
        directory("skill://acme/billing/refunds/references"),
        directory("skill://acme/billing/refunds/scripts"),
    ]
    assert (yield from read("skill://acme/billing/refunds/assets"))["resources"] == [
        listed("skill://acme/billing/refunds/assets/logo.png")
    ]


@testing.effect
def test_rejects_unknown_skills_non_directories_and_foreign_cursors_with_32602():
    """rejects unknown skills, non-directories and foreign cursors with -32602"""
    harness = yield from modern_harness(SKILLS)
    for method, params in [
        ("skills/get", {"uri": "skill://acme/billing/missing/SKILL.md"}),
        ("skills/get", {"uri": "skill://acme/billing/refunds/references/policy.md"}),
        ("resources/directory/read", {"uri": "skill://acme/billing/refunds/SKILL.md"}),
        ("resources/directory/read", {"uri": "skill://acme/missing"}),
        ("resources/directory/read", {"uri": "skill://acme/billing/"}),
        ("skills/list", {"cursor": "next"}),
    ]:
        message = yield from message_of(harness, method, params)
        assert message["error"]["code"] == -32602, f"{method} {params}"


@testing.effect
def test_applies_the_skills_cache_hint_to_every_skills_result():
    """applies the skills cache hint to every skills result"""
    served = M.layer_http(
        name="SkillsServer",
        version="1.0.0",
        path="/mcp",
        protocols=(MODERN,),
        cache_hints={"skills": {"ttl": "1 minute", "cache_scope": "private"}},
    )
    harness = yield from http_harness(
        layer.effect_discard(SKILLS).pipe(layer.provide_merge(served))
    )
    for method, params in [
        ("skills/list", {}),
        ("skills/get", {"uri": "skill://acme/billing/refunds/SKILL.md"}),
        ("resources/directory/read", {"uri": "skill://acme"}),
    ]:
        message = yield from message_of(harness, method, params)
        assert message["result"]["ttlMs"] == 60_000, method
        assert message["result"]["cacheScope"] == "private", method


@testing.effect
def test_answers_the_extension_s_methods_with_32601_and_omits_the_declaration_without_skills():
    """answers the extension's methods with -32601 and omits the declaration without skills"""
    harness = yield from modern_harness(
        M.register_resource(uri="file:///readme", name="Readme", content=fx.succeed("readme"))
    )
    discovered = yield from message_of(harness, "server/discover")
    assert "extensions" not in discovered["result"]["capabilities"]
    for method in ("skills/list", "skills/get", "resources/directory/read"):
        status, message = yield from call(harness, method, {"uri": "skill://acme"})
        assert status == 404, method
        assert message["error"]["code"] == -32601, method


# --- sessionful revisions ---------------------------------------------------------------


@pytest.mark.parametrize(
    "protocol", [P.v2025_11_25, P.v2024_11_05], ids=lambda p: p.protocol_version
)
@testing.effect
def test_serves_the_extension_without_cache_attributes_on(protocol: P.AnyProtocolAdapter):
    """serves the extension without cache attributes on <protocol>"""
    harness = yield from http_harness(
        server_layer("SkillsServer", (protocol,), SKILLS, extensions={"example/other": {}})
    )
    initialize = yield from harness.post(
        {
            "jsonrpc": "2.0",
            "id": "initialize",
            "method": "initialize",
            "params": {
                "protocolVersion": protocol.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0.0"},
            },
        }
    )
    initialized = yield from read_message(initialize)
    assert initialized["result"]["capabilities"]["extensions"] == {
        "example/other": {},
        "io.modelcontextprotocol/skills": {"directoryRead": True},
    }

    headers = yield from initialize_session(harness, protocol)

    def post(method: str, params: Json) -> fx.Effect[Any]:
        return harness.post(
            {"jsonrpc": "2.0", "id": 2, "method": method, "params": params}, headers
        ).flat_map(read_message)

    listed = yield from post("skills/list", {})
    assert list(listed["result"]) == ["skills"]
    assert len(listed["result"]["skills"]) == 2

    got = yield from post("skills/get", {"uri": "skill://acme/billing/refunds/SKILL.md"})
    assert list(got["result"]) == ["skill"]
    assert got["result"]["skill"]["frontmatter"]["name"] == "refunds"

    missing = yield from post("skills/get", {"uri": "skill://acme/missing/SKILL.md"})
    assert missing["error"]["code"] == -32602

    directory = yield from post("resources/directory/read", {"uri": "skill://acme"})
    assert directory["result"] == {
        "resources": [
            {"uri": "skill://acme/billing", "name": "billing", "mimeType": "inode/directory"}
        ]
    }


# --- registration -----------------------------------------------------------------------


def register_all(*registrations: fx.Effect[None, Any, Any]) -> fx.Effect[Exit[None, Any]]:
    run_all = fx.void
    for registration in registrations:
        run_all = run_all.and_then(registration)
    return run_all.pipe(fx.provide(M.layer)).exit()


def skill(
    uri: str, frontmatter: str, files: dict[str, str] | None = None
) -> fx.Effect[None, Any, Any]:
    return M.register_skill(
        uri, {"SKILL.md": skill_md(frontmatter, "Refund carefully.\n"), **(files or {})}
    )


def refunds(
    frontmatter: str = "name: refunds\ndescription: Process refunds",
    files: dict[str, str] | None = None,
) -> fx.Effect[None, Any, Any]:
    return skill("skill://refunds/SKILL.md", frontmatter, files)


def assert_rejected(exit: Exit[None, Any], reason: str) -> None:
    assert isinstance(exit, Failure)
    assert re.search(reason, str(exit.cause)) is not None, str(exit.cause)


@testing.effect
def test_accepts_a_valid_skill_keeping_frontmatter_fields_the_agent_skills_specification_does_not_define():  # noqa: E501
    """accepts a valid skill, keeping frontmatter fields the Agent Skills specification does not define"""  # noqa: E501
    exit = yield from register_all(
        refunds("name: refunds\ndescription: Process refunds\nx-team: [billing]")
    )
    assert isinstance(exit, Success)


@testing.effect
def test_rejects_a_name_that_differs_from_the_last_path_segment():
    """rejects a name that differs from the last path segment"""
    exit = yield from register_all(
        skill("skill://other/SKILL.md", "name: refunds\ndescription: Process refunds")
    )
    assert_rejected(exit, 'frontmatter name "refunds" must equal "other"')


@testing.effect
def test_rejects_a_uri_that_does_not_address_a_skill_md():
    """rejects a URI that does not address a SKILL.md"""
    exit = yield from register_all(
        skill("skill://refunds/README.md", "name: refunds\ndescription: Process refunds")
    )
    assert_rejected(exit, r"<skill-path>/SKILL\.md")


@testing.effect
def test_rejects_frontmatter_that_breaks_the_agent_skills_specification():
    """rejects frontmatter that breaks the Agent Skills specification"""
    exit = yield from register_all(
        skill("skill://Refunds/SKILL.md", "name: Refunds\ndescription: Process refunds")
    )
    assert_rejected(exit, r'not valid Agent Skills frontmatter[\s\S]*\["name"\]')
    for frontmatter, reason in [
        ('name: refunds\ndescription: ""', r'\["description"\]'),
        # `metadata` is a map of strings.
        (
            "name: refunds\ndescription: Process refunds\nmetadata:\n  version: 2",
            r'\["metadata"\]\["version"\]',
        ),
        (
            f"name: refunds\ndescription: Process refunds\ncompatibility: {'x' * 501}",
            r'\["compatibility"\]',
        ),
    ]:
        assert_rejected((yield from register_all(refunds(frontmatter))), reason)


@testing.effect
def test_rejects_a_skill_md_without_frontmatter():
    """rejects a SKILL.md without frontmatter"""
    exit = yield from register_all(
        M.register_skill("skill://refunds/SKILL.md", {"SKILL.md": "Refund carefully.\n"})
    )
    assert_rejected(exit, "must begin with YAML frontmatter")


@testing.effect
def test_rejects_a_file_path_that_escapes_the_skill():
    """rejects a file path that escapes the skill"""
    for path in [
        "../secrets.md",
        "references/../../secrets.md",
        "/etc/passwd",
        "references\\..\\x",
    ]:
        assert_rejected(
            (yield from register_all(refunds(files={path: "secret"}))), "escapes the skill"
        )


@testing.effect
def test_rejects_a_skill_whose_directory_overlaps_another_skill_s_in_either_order():
    """rejects a skill whose directory overlaps another skill's, in either order"""
    outer = refunds()
    inner = skill("skill://refunds/nested/SKILL.md", "name: nested\ndescription: Nested")
    assert_rejected((yield from register_all(outer, inner)), "overlaps")
    assert_rejected((yield from register_all(inner, outer)), "overlaps")

    # Sharing a prefix is not overlapping.
    sibling = skill("skill://refunds-v2/SKILL.md", "name: refunds-v2\ndescription: Process refunds")
    assert isinstance((yield from register_all(outer, sibling)), Success)


@testing.effect
def test_rejects_a_plain_resource_sharing_a_uri_with_a_skill_file_in_either_order():
    """rejects a plain resource sharing a URI with a skill file, in either order"""
    policy = M.register_resource(
        uri="skill://refunds/references/policy.md", name="Policy", content=fx.succeed("Replaced.\n")
    )
    with_policy = refunds(files={"references/policy.md": "Approve first.\n"})
    assert_rejected(
        (yield from register_all(with_policy, policy)), r"skill://refunds/references/policy\.md"
    )
    assert_rejected(
        (yield from register_all(policy, with_policy)), r"skill://refunds/references/policy\.md"
    )


class _Held:
    def __init__(self, tasks: list[Callable[[], None]]) -> None:
        self._tasks = tasks

    def schedule_task(self, task: Callable[[], None], priority: int) -> None:
        self._tasks.append(task)

    def flush(self) -> None:
        pass


class _Gated(EffectScheduler):
    """Runs a fiber a few steps at a time, holding its tasks for the test."""

    def __init__(self, tasks: list[Callable[[], None]]) -> None:
        self._tasks = tasks

    def should_yield(self, fiber: Any) -> bool:
        return fiber.current_op_count > 2

    def make_dispatcher(self) -> SchedulerDispatcher:
        return _Held(self._tasks)


def _client() -> ServerClient:
    initialize: Any = {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1.0.0"},
    }
    return ServerClient(
        1, "2025-06-18", {}, {"name": "test", "version": "1.0.0"}, initialize, fx.die("not used")
    )


@testing.effect
def test_keeps_a_skill_file_and_a_concurrently_registered_resource_from_both_succeeding():
    """keeps a skill file and a concurrently registered resource from both succeeding"""

    @fx.gen
    def run():
        uri = "skill://refunds/SKILL.md"
        tasks: list[Callable[[], None]] = []

        def registered() -> bool:
            return any(entry.resource["uri"] == uri for entry in server.resources)

        server = yield from M.McpServer()
        resource_fiber = yield from (
            M.register_resource(uri=uri, name="Replacement", content=fx.succeed("Replaced.\n"))
            .pipe(fx.provide_service(CurrentScheduler, _Gated(tasks)))
            .exit()
            .fork()
        )

        # One task of the gated fiber; a resumed fiber runs after the current
        # step (pyfect's synchronous resume), so give it a turn.
        @fx.gen
        def step():
            if tasks:
                tasks.pop(0)()
            yield from fx.yield_now()

        while not tasks:
            yield from fx.yield_now()
        # Step until the resource passed the ownership check, or its registration finished.
        while resource_fiber.poll_unsafe() is None and not registered():
            yield from step

        skill_exit = yield from refunds().exit()
        while resource_fiber.poll_unsafe() is None:
            yield from step
        resource_exit = yield from resource_fiber.join()

        assert isinstance(resource_exit, Success) != isinstance(skill_exit, Success)
        listed = [entry for entry in server.resources if entry.resource["uri"] == uri]
        assert len(listed) == 1
        assert listed[0].resource["name"] == (
            "refunds" if isinstance(skill_exit, Success) else "Replacement"
        )
        served = yield from server.find_resource(uri).pipe(
            fx.provide_service(McpServerClient, _client())
        )
        [content] = served["contents"]
        assert content.get("text") == (
            skill_md("name: refunds\ndescription: Process refunds", "Refund carefully.\n")
            if isinstance(skill_exit, Success)
            else "Replaced.\n"
        )

    yield from run.pipe(fx.provide(M.layer))


@testing.effect
def test_rejects_an_add_resource_effect_built_before_a_skill_claims_its_uri():
    """rejects an addResource Effect built before a skill claims its URI"""

    @fx.gen
    def run():
        server = yield from M.McpServer()
        pending = server.add_resource(
            ResourceEntry(
                {"uri": "skill://refunds/SKILL.md", "name": "Replacement"},
                Context.empty(),
                fx.succeed(
                    {"contents": [{"uri": "skill://refunds/SKILL.md", "text": "Replaced.\n"}]}
                ),
            )
        )
        yield from refunds()
        yield from pending

    exit = yield from run.pipe(fx.provide(M.layer)).exit()
    assert_rejected(exit, r"skill://refunds/SKILL\.md is a file of a registered skill")
    assert isinstance(exit, Failure)
    assert any(isinstance(d, IllegalArgumentError) for d in exit.cause.defects)
