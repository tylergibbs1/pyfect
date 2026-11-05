"""Ports of Effect's MCP conformance prompt and completion titles
(test/ai/McpServer/McpConformance/PromptsTest.ts and CompletionTest.ts),
run over stdio for every revision whose test file runs the suite.

Effect runs these over its HTTP conformance harness; the stdio harness
serves the same features server, and the titles check the JSON-RPC
results only. Prompt content takes base64 ``data`` strings, so the
image and audio prompts give ``"AQID"`` / ``"BAUG"`` where Effect's
``ImageContent.make`` encodes a ``Uint8Array``.

Omitted: none.
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai._mcp.core import PromptEntry
from pyfect.context import Context

from ._mcp import Json, StdioHarness, stdio_harness

ALL = [P.v2024_11_05, P.v2025_03_26, P.v2025_06_18, P.v2025_11_25, P.v2026_07_28]
STATEFUL = [p for p in ALL if not p.is_stateless]
COMPLETION = [p for p in ALL if p.protocol_version != "2024-11-05"]


def _id(protocol: P.AnyProtocolAdapter) -> str:
    return protocol.protocol_version


class _TestPromptParams(TypedDict):
    required: str
    optional: NotRequired[str]


class _ContextParams(TypedDict):
    value: str


def _features(invocations: list[str]) -> tuple[fx.Effect[None, Any, Any], ...]:
    """Effect's ``makeFeaturesServerLayer`` prompts and resource template."""

    def test_prompt(params: _TestPromptParams) -> fx.Effect[str]:
        def run() -> str:
            invocations.append("TestPrompt")
            return f"{params['required']}:{params.get('optional', 'omitted')}"

        return fx.sync(run)

    def one(content: MS.ContentBlock) -> fx.Effect[list[MS.PromptMessage]]:
        return fx.succeed([{"role": "user", "content": content}])

    return (
        M.register_resource_template(
            M.uri_template("file:///template/", MS.param("path", S.String)),
            name="TestResourceTemplate",
            description="A test resource template",
            mime_type="text/plain",
            completion={
                "path": lambda value, _: fx.succeed(
                    ["beta", "alpha"] if value == "" else ["alpha", "beta"]
                )
            },
            content=lambda uri, path: fx.succeed(f"{uri}:{path}"),
        ),
        M.register_prompt(
            name="TestPrompt",
            title="Test prompt",
            description="A test prompt",
            parameters=S.Struct(_TestPromptParams),
            completion={
                "required": lambda value, _: fx.succeed(
                    [f"value-{i}" for i in range(101)] if value == "limit" else ["first", "second"]
                )
            },
            content=test_prompt,
        ),
        M.register_prompt(name="NoArgumentPrompt", content=lambda _: fx.succeed("no arguments")),
        M.register_prompt(
            name="ImagePrompt",
            content=lambda _: one({"type": "image", "data": "AQID", "mimeType": "image/png"}),
        ),
        M.register_prompt(
            name="AudioPrompt",
            content=lambda _: one({"type": "audio", "data": "BAUG", "mimeType": "audio/wav"}),
        ),
        M.register_prompt(
            name="EmbeddedResourcePrompt",
            content=lambda _: one(
                {
                    "type": "resource",
                    "resource": {
                        "uri": "file:///embedded",
                        "mimeType": "text/plain",
                        "text": "embedded",
                    },
                }
            ),
        ),
        M.register_prompt(
            name="ContextCompletionPrompt",
            parameters=S.Struct(_ContextParams),
            completion={
                "value": lambda _value, context: fx.succeed(
                    ["context received"]
                    if (context or {}).get("arguments", {}).get("locale") == "en"
                    else ["context missing"]
                )
            },
            content=lambda params: fx.succeed(params["value"]),
        ),
        M.McpServer().flat_map(
            lambda server: server.add_prompt(
                PromptEntry(
                    {"name": "MrtrPrompt"},
                    Context.make(
                        MS.EnabledWhen, lambda client: client.protocol_version == "2026-07-28"
                    ),
                    {},
                    lambda _: fx.succeed(MS.InputRequired(request_state="state")),
                )
            )
        ),
    )


def _server(
    protocol: P.AnyProtocolAdapter, invocations: list[str] | None = None
) -> fx.Effect[StdioHarness, Any, Any]:
    """An initialized client of the features server."""

    @fx.gen
    def run():
        harness = yield from stdio_harness(protocol, None, *_features(invocations or []))
        yield from harness.initialize()
        return harness

    return run


def _capabilities(protocol: P.AnyProtocolAdapter, *, features: bool) -> fx.Effect[Json, Any, Any]:
    """The capabilities the server advertises: ``initialize``'s, or
    ``server/discover``'s on a stateless revision."""

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


def _result(harness: StdioHarness, method: str, params: Json) -> fx.Effect[Json]:
    return harness.send_request(method, params).map(lambda reply: reply["result"])


def _error_code(harness: StdioHarness, method: str, params: Json) -> fx.Effect[int]:
    return harness.send_request(method, params).map(lambda reply: reply["error"]["code"])


def _test_prompt(harness: StdioHarness) -> fx.Effect[Json]:
    return _result(harness, "prompts/list", {}).map(
        lambda result: next(p for p in result["prompts"] if p["name"] == "TestPrompt")
    )


# --- Prompts ------------------------------------------------------------------------------


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_advertise_prompts_when_prompts_are_registered(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Prompts / Capabilities / MUST advertise prompts when prompts are registered"""  # noqa: E501
    assert "prompts" in (yield from _capabilities(protocol, features=True))


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_not_advertise_prompts_when_not_supported(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Prompts / Capabilities / MUST NOT advertise prompts when prompts are not supported"""  # noqa: E501
    assert "prompts" not in (yield from _capabilities(protocol, features=False))


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_list_every_prompt_visible_to_the_initialized_client(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Prompts / Listing Prompts / MUST list every prompt visible to the initialized client"""  # noqa: E501
    harness = yield from _server(protocol)
    result = yield from _result(harness, "prompts/list", {})
    assert sorted(p["name"] for p in result["prompts"]) == [
        "AudioPrompt",
        "ContextCompletionPrompt",
        "EmbeddedResourcePrompt",
        "ImagePrompt",
        *(["MrtrPrompt"] if protocol.is_stateless else []),
        "NoArgumentPrompt",
        "TestPrompt",
    ]


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_schema_preserves_prompt_names_titles_descriptions_and_arguments(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Prompts / Listing Prompts / SCHEMA preserves prompt names, titles, descriptions, and arguments"""  # noqa: E501
    prompt = yield from _test_prompt((yield from _server(protocol)))
    untitled = protocol.protocol_version in ("2024-11-05", "2025-03-26")
    assert prompt.get("title") == (None if untitled else "Test prompt")
    assert prompt["description"] == "A test prompt"
    assert [a["name"] for a in prompt["arguments"]] == ["required", "optional"]


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_mark_required_and_optional_prompt_arguments_correctly(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Prompts / Listing Prompts / MUST mark required and optional prompt arguments correctly"""  # noqa: E501
    prompt = yield from _test_prompt((yield from _server(protocol)))
    assert prompt["arguments"] == [
        {"name": "required", "required": True},
        {"name": "optional", "required": False},
    ]


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_get_a_registered_prompt_without_arguments(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Prompts / Getting Prompts / MUST get a registered prompt without arguments"""  # noqa: E501
    harness = yield from _server(protocol)
    result = yield from _result(harness, "prompts/get", {"name": "NoArgumentPrompt"})
    assert result["messages"] == [
        {"role": "user", "content": {"type": "text", "text": "no arguments"}}
    ]


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_get_a_registered_prompt_with_valid_arguments(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Prompts / Getting Prompts / MUST get a registered prompt with valid arguments"""  # noqa: E501
    harness = yield from _server(protocol)
    params = {"name": "TestPrompt", "arguments": {"required": "required", "optional": "optional"}}
    result = yield from _result(harness, "prompts/get", params)
    assert result["messages"] == [
        {"role": "user", "content": {"type": "text", "text": "required:optional"}}
    ]


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_should_reject_an_unknown_prompt_name_with_invalid_params(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Prompts / Getting Prompts / SHOULD reject an unknown prompt name with Invalid Params"""  # noqa: E501
    harness = yield from _server(protocol)
    params: Json = {"name": "UnknownPrompt", "arguments": {}}
    assert (yield from _error_code(harness, "prompts/get", params)) == MS.INVALID_PARAMS_ERROR_CODE


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_should_reject_missing_required_prompt_arguments(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Prompts / Getting Prompts / SHOULD reject missing required prompt arguments with Invalid Params"""  # noqa: E501
    harness = yield from _server(protocol)
    params: Json = {"name": "TestPrompt", "arguments": {}}
    assert (yield from _error_code(harness, "prompts/get", params)) == MS.INVALID_PARAMS_ERROR_CODE


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_should_reject_prompt_arguments_with_invalid_values(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Prompts / Getting Prompts / SHOULD reject prompt arguments with invalid values"""  # noqa: E501
    harness = yield from _server(protocol)
    params: Json = {"name": "TestPrompt", "arguments": {"required": 123}}
    assert (yield from _error_code(harness, "prompts/get", params)) == MS.INVALID_PARAMS_ERROR_CODE


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_not_invoke_the_prompt_handler_when_validation_fails(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Prompts / Getting Prompts / MUST not invoke the prompt handler when argument validation fails"""  # noqa: E501
    invocations: list[str] = []
    harness = yield from _server(protocol, invocations)
    params: Json = {"name": "TestPrompt", "arguments": {"required": 123}}
    assert (yield from _error_code(harness, "prompts/get", params)) == MS.INVALID_PARAMS_ERROR_CODE
    assert invocations == []


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_schema_preserves_the_prompt_description_and_message_order(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Prompts / Getting Prompts / SCHEMA preserves the prompt description and message order"""  # noqa: E501
    harness = yield from _server(protocol)
    params = {"name": "TestPrompt", "arguments": {"required": "test"}}
    result = yield from _result(harness, "prompts/get", params)
    assert result["description"] == "A test prompt"
    assert [m["role"] for m in result["messages"]] == ["user"]


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_return_text_message_content(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Prompts / Getting Prompts / MUST return text message content"""
    harness = yield from _server(protocol)
    params = {"name": "TestPrompt", "arguments": {"required": "text"}}
    result = yield from _result(harness, "prompts/get", params)
    assert result["messages"][0]["content"] == {"type": "text", "text": "text:omitted"}


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_return_image_message_content(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Prompts / Getting Prompts / MUST return image message content"""
    harness = yield from _server(protocol)
    result = yield from _result(harness, "prompts/get", {"name": "ImagePrompt"})
    assert result["messages"] == [
        {"role": "user", "content": {"type": "image", "data": "AQID", "mimeType": "image/png"}}
    ]


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_return_embedded_resource_message_content(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Prompts / Getting Prompts / MUST return embedded resource message content"""  # noqa: E501
    harness = yield from _server(protocol)
    result = yield from _result(harness, "prompts/get", {"name": "EmbeddedResourcePrompt"})
    assert result["messages"] == [
        {
            "role": "user",
            "content": {
                "type": "resource",
                "resource": {
                    "uri": "file:///embedded",
                    "mimeType": "text/plain",
                    "text": "embedded",
                },
            },
        }
    ]


@pytest.mark.parametrize(
    "protocol", [p for p in ALL if p.protocol_version != "2024-11-05"], ids=_id
)
@testing.effect
def test_should_return_base64_audio_content(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Prompts / Getting Prompts / should return base64 audio content when an audio prompt is requested"""  # noqa: E501
    harness = yield from _server(protocol)
    result = yield from _result(harness, "prompts/get", {"name": "AudioPrompt"})
    assert result["messages"] == [
        {"role": "user", "content": {"type": "audio", "data": "BAUG", "mimeType": "audio/wav"}}
    ]


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_should_advertise_prompt_list_change_notifications(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Prompts > Legacy notifications / should advertise prompt list-change notifications when supported"""  # noqa: E501
    capabilities = yield from _capabilities(protocol, features=True)
    assert capabilities["prompts"]["listChanged"] is True


# --- Completion ---------------------------------------------------------------------------


def _complete(
    protocol: P.AnyProtocolAdapter, ref: Json, argument: Json, context: Json | None = None
) -> fx.Effect[Json, Any, Any]:
    params: Json = {"ref": ref, "argument": argument}
    if context is not None:
        params["context"] = context
    return _server(protocol).flat_map(
        lambda harness: harness.send_request("completion/complete", params)
    )


_TEMPLATE = {"type": "ref/resource", "uri": "file:///template/{path}"}
_PROMPT = {"type": "ref/prompt", "name": "TestPrompt"}


@pytest.mark.parametrize("protocol", COMPLETION, ids=_id)
@testing.effect
def test_must_advertise_completions_when_supported(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Completion / Capabilities / MUST advertise completions when argument completion is supported"""  # noqa: E501
    assert "completions" in (yield from _capabilities(protocol, features=True))


@pytest.mark.parametrize("protocol", COMPLETION, ids=_id)
@testing.effect
def test_must_complete_a_prompt_argument(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Completion / Requesting Completions / MUST complete a prompt argument"""
    reply = yield from _complete(protocol, _PROMPT, {"name": "required", "value": "f"})
    assert reply["result"]["completion"]["values"] == ["first", "second"]


@pytest.mark.parametrize("protocol", COMPLETION, ids=_id)
@testing.effect
def test_must_complete_a_resource_template_argument(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Completion / Requesting Completions / MUST complete a resource template argument"""  # noqa: E501
    reply = yield from _complete(protocol, _TEMPLATE, {"name": "path", "value": "a"})
    assert reply["result"]["completion"]["values"] == ["alpha", "beta"]


@pytest.mark.parametrize("protocol", COMPLETION, ids=_id)
@testing.effect
def test_should_reject_an_unknown_prompt_reference(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Completion / Requesting Completions / SHOULD reject an unknown prompt reference with Invalid Params"""  # noqa: E501
    ref = {"type": "ref/prompt", "name": "UnknownPrompt"}
    reply = yield from _complete(protocol, ref, {"name": "value", "value": ""})
    assert reply["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE


@pytest.mark.parametrize("protocol", COMPLETION, ids=_id)
@testing.effect
def test_must_reject_an_unknown_argument_name(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Completion / Requesting Completions / MUST reject an unknown argument name"""  # noqa: E501
    reply = yield from _complete(protocol, _PROMPT, {"name": "unknown", "value": ""})
    assert reply["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE


@pytest.mark.parametrize("protocol", COMPLETION, ids=_id)
@testing.effect
def test_must_return_completion_values_in_order(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Completion / Requesting Completions / MUST return completion values in order"""  # noqa: E501
    reply = yield from _complete(protocol, _TEMPLATE, {"name": "path", "value": ""})
    assert reply["result"]["completion"]["values"] == ["beta", "alpha"]


@pytest.mark.parametrize("protocol", COMPLETION, ids=_id)
@testing.effect
def test_schema_returns_the_total_and_additional_results_indicator(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Completion / Requesting Completions / SCHEMA returns the total and additional-results indicator"""  # noqa: E501
    reply = yield from _complete(protocol, _TEMPLATE, {"name": "path", "value": ""})
    completion = reply["result"]["completion"]
    assert completion["total"] == 2
    assert completion["hasMore"] is False


@pytest.mark.parametrize("protocol", COMPLETION, ids=_id)
@testing.effect
def test_must_return_at_most_one_hundred_completion_values(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Completion / Requesting Completions / MUST return at most one hundred completion values"""  # noqa: E501
    reply = yield from _complete(protocol, _PROMPT, {"name": "required", "value": "limit"})
    completion = reply["result"]["completion"]
    assert len(completion["values"]) == 100
    assert completion["total"] == 101
    assert completion["hasMore"] is True


@pytest.mark.parametrize(
    "protocol", [p for p in COMPLETION if p.protocol_version != "2025-03-26"], ids=_id
)
@testing.effect
def test_should_pass_previously_resolved_arguments_as_completion_context(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Completion / Requesting Completions / should pass previously resolved arguments when completion context is supplied"""  # noqa: E501
    ref = {"type": "ref/prompt", "name": "ContextCompletionPrompt"}
    context = {"arguments": {"locale": "en"}}
    reply = yield from _complete(protocol, ref, {"name": "value", "value": "c"}, context)
    assert reply["result"]["completion"]["values"] == ["context received"]


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_should_send_a_prompt_list_change_notification_when_the_advertised_list_changes(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Prompts > Legacy notifications / should send a prompt list-change notification when the advertised list changes"""  # noqa: E501
    fixture = yield from stdio_harness(protocol)

    def entry(name: str) -> PromptEntry:
        message: Any = {"role": "user", "content": {"type": "text", "text": name}}
        return PromptEntry(
            {"name": name}, Context.empty(), {}, lambda _: fx.succeed({"messages": [message]})
        )

    yield from fixture.server.add_prompt(entry("baseline-list-changed-prompt"))
    yield from fixture.initialize()
    yield from fixture.server.add_prompt(entry("dynamic-list-changed-prompt"))
    yield from fixture.flush_list_changed
    notification = yield from fixture.await_outbound_method("notifications/prompts/list_changed")
    assert notification["jsonrpc"] == "2.0"
    assert "id" not in notification
    response = yield from fixture.send_request("prompts/list", {})
    assert "dynamic-list-changed-prompt" in [p["name"] for p in response["result"]["prompts"]]
