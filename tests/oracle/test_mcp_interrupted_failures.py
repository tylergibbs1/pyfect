"""Requests whose failure also holds an interruption: Effect's ``RpcServer``
answers with the serialized ``Cause`` in the error's ``data``.

Effect's JSON-RPC encoding of a failed exit writes ``{"_tag": "Cause", code,
message, data}``, ``code`` and ``message`` from the cause's first ``Fail``
and ``data`` the cause itself; the MCP serialization strips that down to the
bare error only when the cause is one ``Fail``. Middleware that adds an
interruption to a failure leaves the cause whole (``runMiddleware`` passes
interruption through), so the answer carries it. Every expected value here
was read from Effect 4.1.2 under Node, over the same stdio transport.
"""

from __future__ import annotations

from typing import Any, Never, TypedDict

import pytest

import pyfect as fx
from pyfect import cause as C
from pyfect import layer, testing
from pyfect import schema as S
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.cause import Cause
from pyfect.layer import provide

from ._mcp import Json, stdio_harness
from .test_mcp_visibility import Unauthorized

DeleteUser = T.make("DeleteUser", success=S.String)
TOOLS = K.make(DeleteUser)
HANDLERS = TOOLS.to_layer(DeleteUser.handler(lambda _, __: fx.succeed("deleted")))


class _Topic(TypedDict):
    topic: str


META = {
    "io.modelcontextprotocol/protocolVersion": P.v2026_07_28.protocol_version,
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "client", "version": "1"},
}

LISTS = ["tools/list", "prompts/list", "resources/list", "resources/templates/list"]
CALLS: dict[str, dict[str, Any]] = {
    "tools/call": {"name": "DeleteUser", "arguments": {}},
    "prompts/get": {"name": "secret", "arguments": {"topic": "a"}},
    "resources/read": {"uri": "test://secret"},
    "completion/complete": {
        "ref": {"type": "ref/prompt", "name": "secret"},
        "argument": {"name": "topic", "value": ""},
    },
}

CAUSES: dict[str, Any] = {
    "mcp error": lambda: C.fail(Unauthorized("no", data={"x": 1})) + C.interrupt(7),
    "other error": lambda: C.fail("plain") + C.interrupt(7),
    "interruption only": lambda: C.interrupt(7),
    "invalid params": lambda: C.fail(MS.InvalidParams("Not found")) + C.interrupt(),
}

INTERNAL = {"code": -32603, "message": "Internal error"}
CAUSE_OF_MCP_ERROR = {
    "_tag": "Cause",
    "code": -32001,
    "message": "no",
    "data": [
        {"_tag": "Fail", "error": {"code": -32001, "message": "no", "data": {"x": 1}}},
        {"_tag": "Interrupt", "fiberId": 7},
    ],
}
CAUSE_OF_OTHER_ERROR = {
    "_tag": "Cause",
    "code": -32603,
    "message": "MCP feature handler failed",
    "data": [
        {"_tag": "Fail", "error": {"code": -32603, "message": "MCP feature handler failed"}},
        {"_tag": "Interrupt", "fiberId": 7},
    ],
}
CAUSE_OF_INVALID_PARAMS = {
    "_tag": "Cause",
    "code": -32602,
    "message": "Not found",
    "data": [
        {"_tag": "Fail", "error": {"code": -32602, "message": "Not found"}},
        {"_tag": "Interrupt", "fiberId": None},
    ],
}
EXPECTED = {
    "mcp error": CAUSE_OF_MCP_ERROR,
    "other error": CAUSE_OF_OTHER_ERROR,
    "invalid params": CAUSE_OF_INVALID_PARAMS,
}
# A tool's own ``InvalidParams`` / ``InternalError`` is its ``isError`` result,
# interrupted or not (Effect's ``catchTags`` in ``addTool``).
TOOL_ERROR_RESULT = {"content": [{"type": "text", "text": "Not found"}], "isError": True}


def _check(name: str, method: str, response: Json, *, legacy: bool) -> None:
    if method == "tools/call" and name == "invalid params":
        result = response["result"]
        assert {k: result[k] for k in TOOL_ERROR_RESULT} == TOOL_ERROR_RESULT, method
    elif method == "tools/call" and legacy:
        assert response["error"] == INTERNAL, method
    else:
        assert response["error"] == EXPECTED.get(name, INTERNAL), method


def _registrations(middleware: M.Middleware) -> layer.Layer[Any, Any, Any]:
    return layer.merge(
        M.toolkit(TOOLS).pipe(provide(HANDLERS)),
        M.resource(uri="test://secret", name="secret", content=fx.succeed("secret")),
        M.resource_template(
            M.uri_template("secret://", S.String),
            name="secret-docs",
            content=lambda _uri, _name: fx.succeed("secret"),
        ),
        M.prompt(
            name="secret",
            parameters=S.Struct(_Topic),
            completion={"topic": lambda _, __: fx.succeed(["a"])},
            content=lambda _: fx.succeed("secret"),
        ),
    ).pipe(provide(middleware.layer))


def _failing(make: Any) -> M.Middleware:
    def fn(_effect: Any, _options: M.MiddlewareOptions) -> Any:
        return fx.fail_cause(make())

    return M.middleware(fn)


def _outside_hidden(make: Any) -> M.Middleware:
    def fn(effect: Any, _options: M.MiddlewareOptions) -> Any:
        def failed(_cause: Cause[Any]) -> Any:
            return fx.fail_cause(make())

        return effect.catch_cause(failed)

    hidden = M.visibility(lambda _: fx.succeed(False))
    return hidden.combine(M.middleware(fn))


@pytest.mark.parametrize("name", list(CAUSES))
@testing.effect
def test_legacy_calls_answer_the_serialized_cause(name: str):
    """Under Node: a 2025-11-25 call failed by middleware with an interruption.
    ``tools/call`` answers an internal error (Effect's ``fromTool`` cannot map
    a middleware's failure, so it dies) unless the failure is the tool's own
    kind, the others the cause; an interruption alone is an internal error."""
    harness = yield from stdio_harness(P.v2025_11_25, layer=_registrations(_failing(CAUSES[name])))
    yield from harness.initialize()
    for method, params in CALLS.items():
        response = yield from harness.send_request(method, params)
        _check(name, method, response, legacy=True)


@pytest.mark.parametrize("name", list(CAUSES))
@testing.effect
def test_lists_answer_the_serialized_cause_of_middleware_outside_a_visibility(name: str):
    """Under Node: middleware outside a visibility adds an interruption to the
    hidden request's failure; every list answers the cause (2025-11-25)."""
    harness = yield from stdio_harness(
        P.v2025_11_25, layer=_registrations(_outside_hidden(CAUSES[name]))
    )
    yield from harness.initialize()
    for method in LISTS:
        response = yield from harness.send_request(method, {})
        assert response["error"] == EXPECTED.get(name, INTERNAL), method


@pytest.mark.parametrize("name", list(CAUSES))
@pytest.mark.parametrize("outside_visibility", [False, True])
@testing.effect
def test_stateless_requests_answer_the_serialized_cause(name: str, outside_visibility: bool):
    """Under Node: on 2026-07-28 every request maps its failure as a feature's
    (``tools/call`` included); lists run middleware only outside a visibility."""
    make = CAUSES[name]
    middleware = _outside_hidden(make) if outside_visibility else _failing(make)
    harness = yield from stdio_harness(P.v2026_07_28, layer=_registrations(middleware))
    methods = [*LISTS, *CALLS] if outside_visibility else list(CALLS)
    for method in methods:
        params = {**CALLS.get(method, {}), "_meta": META}
        response = yield from harness.send_request(method, params)
        _check(name, method, response, legacy=False)


@testing.effect
def test_hidden_list_answers_the_serialized_cause():
    """McpServer visibility / propagates interruption from middleware outside a
    visibility on lists, with the answer read under Node: the hidden request's
    ``Not found`` and the interruption, as Effect's ``Cause`` encoding."""

    def interrupt(effect: Any, _options: M.MiddlewareOptions) -> Any:
        def failed(cause: Cause[Any]) -> fx.Effect[Never, Any]:
            return fx.fail_cause(cause + C.interrupt(123))

        return effect.catch_cause(failed)

    hidden = M.visibility(lambda _: fx.succeed(False))
    harness = yield from stdio_harness(
        P.v2025_11_25,
        layer=M.toolkit(TOOLS)
        .pipe(provide(hidden.combine(M.middleware(interrupt)).layer))
        .pipe(provide(HANDLERS)),
    )
    yield from harness.initialize()

    response = yield from harness.send_request("tools/list", {})

    assert response["error"] == {
        "_tag": "Cause",
        "code": MS.INVALID_PARAMS_ERROR_CODE,
        "message": "Not found",
        "data": [
            {"_tag": "Fail", "error": {"code": -32602, "message": "Not found"}},
            {"_tag": "Interrupt", "fiberId": 123},
        ],
    }


# Combining causes never elects defects (Effect's ``Cause.combine``), so a
# cause can hold a typed failure, a defect and an interruption together.
MIXED_CAUSES: dict[str, Any] = {
    "fail die interrupt": lambda: (
        C.fail(Unauthorized("no", data={"x": 1})) + C.die("boom") + C.interrupt(7)
    ),
    "die fail interrupt": lambda: C.die(RuntimeError("boom")) + C.fail("plain") + C.interrupt(7),
    "invalid params die interrupt": lambda: (
        C.fail(MS.InvalidParams("Not found")) + C.die("boom") + C.interrupt()
    ),
}
MIXED_EXPECTED = {
    "fail die interrupt": {
        "_tag": "Cause",
        "code": -32001,
        "message": "no",
        "data": [
            {"_tag": "Fail", "error": {"code": -32001, "message": "no", "data": {"x": 1}}},
            {"_tag": "Die", "defect": "boom"},
            {"_tag": "Interrupt", "fiberId": 7},
        ],
    },
    "die fail interrupt": {
        "_tag": "Cause",
        "code": -32603,
        "message": "MCP feature handler failed",
        "data": [
            {"_tag": "Die", "defect": {"name": "RuntimeError", "message": "boom"}},
            {"_tag": "Fail", "error": {"code": -32603, "message": "MCP feature handler failed"}},
            {"_tag": "Interrupt", "fiberId": 7},
        ],
    },
    "invalid params die interrupt": {
        "_tag": "Cause",
        "code": -32602,
        "message": "Not found",
        "data": [
            {"_tag": "Fail", "error": {"code": -32602, "message": "Not found"}},
            {"_tag": "Die", "defect": "boom"},
            {"_tag": "Interrupt", "fiberId": None},
        ],
    },
}


@pytest.mark.parametrize("name", list(MIXED_CAUSES))
@pytest.mark.parametrize("outside_visibility", [False, True])
@pytest.mark.parametrize("stateless", [False, True])
@testing.effect
def test_a_failure_beside_a_defect_and_an_interruption_is_answered_whole(
    name: str, outside_visibility: bool, stateless: bool
):
    """Under Node: middleware failing with ``Cause.combine`` of a ``Fail``, a
    ``Die`` and an ``Interrupt``. Every request but ``tools/call`` answers
    the whole cause with the ``Fail`` still a failure (nothing on the way
    elects defects); ``tools/call`` answers an internal error, its
    ``catchTags`` electing the defect (also for an ``InvalidParams``, which
    alone would be the tool's ``isError`` result)."""
    make = MIXED_CAUSES[name]
    middleware = _outside_hidden(make) if outside_visibility else _failing(make)
    protocol = P.v2026_07_28 if stateless else P.v2025_11_25
    harness = yield from stdio_harness(protocol, layer=_registrations(middleware))
    if not stateless:
        yield from harness.initialize()
    methods = [*LISTS, *CALLS] if outside_visibility else list(CALLS)
    for method in methods:
        params = {**CALLS.get(method, {}), **({"_meta": META} if stateless else {})}
        response = yield from harness.send_request(method, params)
        expected = INTERNAL if method == "tools/call" else MIXED_EXPECTED[name]
        assert response["error"] == expected, method
