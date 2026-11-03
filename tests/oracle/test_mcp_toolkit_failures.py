"""``mcp_client.toolkit``'s ``failure_mode`` (DOGFOOD atlas #2). Not an
Effect port: Effect's ``McpClient.toolkit`` always fails the call on a tool
error, which ``failure_mode="error"`` (the default) keeps; with ``"return"``
a tool error goes back to the model, as MCP means it to."""

from __future__ import annotations

from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.ai import language_model as lm
from pyfect.ai import mcp_client as C
from pyfect.ai import mcp_client_error as CE
from pyfect.ai import toolkit as K
from pyfect.ai.mcp_client_error import McpClientError

from ._ai import with_language_model
from .test_mcp_client import PROTOCOLS, connect

ADD: dict[str, Any] = {"a": 1, "b": 2}
USAGE: dict[str, Any] = {"inputTokens": {"total": 1}, "outputTokens": {"total": 1}}


def call(name: str, params: dict[str, Any] | None = None) -> list[lm.EncodedPart]:
    return [
        {"type": "tool-call", "id": "call-1", "name": name, "params": params or {}},
        {"type": "finish", "reason": "tool-calls", "usage": USAGE},
    ]


def ask(
    kit: K.WithHandler[Any, Any, Any, Any], name: str, params: dict[str, Any] | None = None
) -> fx.Effect[Any, Any, Any]:
    toolkit: Any = K.make(*kit.tools.values())
    return (
        lm.generate_text("Go", toolkit=toolkit)
        .pipe(with_language_model(generate_text=call(name, params)))
        .pipe(fx.provide_context(kit.services))
    )


@pytest.mark.parametrize("protocol", PROTOCOLS, ids=lambda p: p.protocol_version)
@testing.effect
def test_a_tool_error_fails_the_call_by_default(protocol: C.ClientProtocol):
    client = yield from connect(protocol)
    kit = yield from C.toolkit(client)
    error = yield from ask(kit, "fail").flip()
    assert isinstance(error, McpClientError)
    assert isinstance(error.reason, CE.ToolError)


@pytest.mark.parametrize("protocol", PROTOCOLS, ids=lambda p: p.protocol_version)
@testing.effect
def test_with_failure_mode_return_a_tool_error_goes_back_to_the_model(
    protocol: C.ClientProtocol,
):
    client = yield from connect(protocol)
    kit = yield from C.toolkit(client, failure_mode="return")
    response = yield from ask(kit, "fail")
    [result] = response.tool_results
    assert result.is_failure
    # The tool error's text, as the server wrote it (the JSON of its failure).
    assert result.result == '"denied"'
    assert result.encoded_result == '"denied"'

    answered = yield from ask(kit, "add", ADD)
    [added] = answered.tool_results
    assert not added.is_failure
    assert added.result == '{"total":3}'


@testing.effect
def test_with_failure_mode_return_a_failed_request_goes_back_to_the_model_too():
    kit = yield from fx.scoped(
        connect(PROTOCOLS[0]).flat_map(lambda c: C.toolkit(c, failure_mode="return"))
    )
    response = yield from ask(kit, "add", ADD)
    [result] = response.tool_results
    assert result.is_failure
    assert result.result == "MCP HTTP transport closed"
