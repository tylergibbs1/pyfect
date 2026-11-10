"""Ports of Effect's ``test/ai/McpServer/Visibility.test.ts``: ``mcp_server.visibility``,
middleware hiding registrations per request, on lists and on calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, TypedDict

import pyfect as fx
from pyfect import cause as C
from pyfect import layer, testing
from pyfect import schema as S
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai._mcp.core import ToolEntry
from pyfect.cause import Cause
from pyfect.context import Context, Tag
from pyfect.http import router
from pyfect.http.server_request import HttpServerRequest
from pyfect.layer import provide

from ._mcp import Json, StdioHarness, stdio_harness
from ._mcp_http import http_harness, initialize_session, read_message


class CurrentUser(Tag[str], key="test/CurrentUser"):
    pass


class CurrentTenant(Tag[str], key="test/CurrentTenant"):
    pass


@dataclass(eq=False)
class Unauthorized(MS.McpError):
    _tag: ClassVar[str] = "Unauthorized"
    CODE: ClassVar[int] = -32001


Search = T.make("Search", success=S.String)
PUBLIC_TOOLS = K.make(Search)
PUBLIC_HANDLERS = PUBLIC_TOOLS.to_layer(Search.handler(lambda _, __: fx.succeed("found")))
DeleteUser = T.make("DeleteUser", success=S.String)
ResetPassword = T.make("ResetPassword", success=S.String)
ADMIN_TOOLS = K.make(DeleteUser, ResetPassword)
ADMIN_HANDLERS = ADMIN_TOOLS.to_layer(
    DeleteUser.handler(lambda _, __: fx.succeed("deleted")),
    ResetPassword.handler(lambda _, __: fx.succeed("reset")),
)

ADMIN_ONLY = M.visibility(lambda _: CurrentUser().map(lambda user: user == "admin"))


def names(message: Json, key: str) -> list[str]:
    return sorted(entry["name"] for entry in message["result"][key])


@dataclass
class _State:
    user: str = "guest"
    calls: list[str] = field(default_factory=list[str])
    invoked: list[str] = field(default_factory=list[str])

    def take_calls(self) -> list[str]:
        calls = self.calls[:]
        self.calls.clear()
        return calls


def _fixture() -> tuple[_State, M.Middleware[CurrentUser], M.Middleware]:
    state = _State()

    def auth(effect: Any, options: M.MiddlewareOptions) -> Any:
        state.calls.append(f"auth {options.method} {options.target}")
        return effect.pipe(fx.provide_service(CurrentUser, state.user))

    def audit(effect: Any, options: M.MiddlewareOptions) -> Any:
        return fx.sync(lambda: state.calls.append(f"audit {options.method}")).and_then(effect)

    return state, M.middleware(auth, provides=CurrentUser), M.middleware(audit)


class _Topic(TypedDict):
    topic: str


def _server() -> fx.Effect[tuple[StdioHarness, _State], Any, Any]:
    @fx.gen
    def run():
        state, auth, audit = _fixture()

        def invoked(name: str, result: str) -> fx.Effect[str]:
            return fx.sync(lambda: state.invoked.append(name)).as_(result)

        admin_handlers = ADMIN_TOOLS.to_layer(
            DeleteUser.handler(lambda _, __: invoked("DeleteUser", "deleted")),
            ResetPassword.handler(lambda _, __: invoked("ResetPassword", "reset")),
        )
        secret = layer.merge(
            M.toolkit(ADMIN_TOOLS).pipe(provide(admin_handlers)),
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
        ).pipe(provide(audit.combine(ADMIN_ONLY.combine(auth)).layer))
        registrations = layer.merge(
            M.toolkit(PUBLIC_TOOLS).pipe(provide(PUBLIC_HANDLERS)),
            M.resource_template(
                M.uri_template("test://", S.String),
                name="public-docs",
                content=lambda _uri, _name: fx.succeed("public"),
            ),
            secret,
        )
        harness = yield from stdio_harness(P.v2025_11_25, layer=registrations)
        yield from harness.initialize()
        return harness, state

    return run


@testing.effect
def test_filters_lists_running_only_the_middleware_outside_the_visibility():
    """McpServer visibility / filters lists running only the middleware outside the visibility"""
    harness, state = yield from _server()

    assert names((yield from harness.send_request("tools/list", {})), "tools") == ["Search"]
    assert state.take_calls() == ["auth tools/list DeleteUser", "auth tools/list ResetPassword"]
    assert names((yield from harness.send_request("resources/list", {})), "resources") == []
    templates = yield from harness.send_request("resources/templates/list", {})
    assert names(templates, "resourceTemplates") == ["public-docs"]
    assert names((yield from harness.send_request("prompts/list", {})), "prompts") == []

    state.user = "admin"
    tools = yield from harness.send_request("tools/list", {})
    assert names(tools, "tools") == ["DeleteUser", "ResetPassword", "Search"]
    assert names((yield from harness.send_request("resources/list", {})), "resources") == ["secret"]
    templates = yield from harness.send_request("resources/templates/list", {})
    assert names(templates, "resourceTemplates") == ["public-docs", "secret-docs"]
    assert names((yield from harness.send_request("prompts/list", {})), "prompts") == ["secret"]


@testing.effect
def test_rejects_requests_for_hidden_entries_as_not_found():
    """McpServer visibility / rejects requests for hidden entries as not found"""
    harness, state = yield from _server()

    call = yield from harness.send_request("tools/call", {"name": "DeleteUser", "arguments": {}})
    assert call["error"] == {"code": -32602, "message": "Tool 'DeleteUser' not found"}
    assert state.invoked == []
    # The visible ``test://{param0}`` template matches too, but a hidden resource stays hidden.
    read = yield from harness.send_request("resources/read", {"uri": "test://secret"})
    assert read["error"] == {"code": -32002, "message": "Resource 'test://secret' not found"}
    prompt = yield from harness.send_request(
        "prompts/get", {"name": "secret", "arguments": {"topic": "a"}}
    )
    assert prompt["error"] == {"code": -32602, "message": "Prompt 'secret' not found"}
    completion = yield from harness.send_request(
        "completion/complete",
        {
            "ref": {"type": "ref/prompt", "name": "secret"},
            "argument": {"name": "topic", "value": ""},
        },
    )
    assert completion["error"] == {
        "code": -32602,
        "message": "Unknown completion reference or argument",
    }

    state.user = "admin"
    state.calls.clear()
    allowed = yield from harness.send_request("tools/call", {"name": "DeleteUser", "arguments": {}})
    assert allowed["result"]["content"] == [{"type": "text", "text": "deleted"}]
    assert state.calls == ["auth tools/call DeleteUser", "audit tools/call"]


@testing.effect
def test_fails_the_whole_list_when_middleware_outside_a_visibility_fails():
    """McpServer visibility / fails the whole list when middleware outside a visibility fails"""
    reject = M.middleware(lambda _, __: fx.fail(Unauthorized("Unauthorized")), provides=CurrentUser)
    registrations = layer.merge(
        M.toolkit(PUBLIC_TOOLS).pipe(provide(PUBLIC_HANDLERS)),
        M.toolkit(ADMIN_TOOLS)
        .pipe(provide(ADMIN_ONLY.combine(reject).layer))
        .pipe(provide(ADMIN_HANDLERS)),
    )
    harness = yield from stdio_harness(P.v2025_11_25, layer=registrations)
    yield from harness.initialize()

    response = yield from harness.send_request("tools/list", {})

    assert response["error"] == {"code": -32001, "message": "Unauthorized"}


@testing.effect
def test_reads_services_provided_by_http_router_middleware_under_layer_http():
    """McpServer visibility / reads services provided by HttpRouter middleware under layerHttp"""
    http_auth = router.middleware(
        lambda effect: HttpServerRequest().flat_map(
            lambda request: effect.pipe(
                fx.provide_service(CurrentUser, request.headers.get("x-user", "guest"))
            )
        )
    )
    who_am_i = T.make("WhoAmI", success=S.String, dependencies=[CurrentUser])
    kit = K.make(who_am_i)
    registrations = (
        M.toolkit(kit)
        .pipe(provide(ADMIN_ONLY.layer))
        .pipe(provide(kit.to_layer(who_am_i.handler(lambda _, __: CurrentUser()))))
    )
    harness = yield from http_harness(
        M.layer_http(
            name="VisibilityServer",
            version="1.0.0",
            path="/mcp",
            protocols=(P.v2025_11_25,),
            registrations=registrations,
        ).pipe(provide(http_auth.layer))
    )
    headers = yield from initialize_session(harness, P.v2025_11_25)

    def send(user: str, method: str, params: Json) -> fx.Effect[Json]:
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        return harness.post(body, {**headers, "x-user": user}).flat_map(read_message)

    assert names((yield from send("guest", "tools/list", {})), "tools") == []
    hidden = yield from send("guest", "tools/call", {"name": "WhoAmI", "arguments": {}})
    assert hidden["error"] == {"code": -32602, "message": "Tool 'WhoAmI' not found"}

    assert names((yield from send("admin", "tools/list", {})), "tools") == ["WhoAmI"]
    visible = yield from send("admin", "tools/call", {"name": "WhoAmI", "arguments": {}})
    assert visible["result"]["content"] == [{"type": "text", "text": "admin"}]


@testing.effect
def test_applies_a_global_visibility_to_every_registration():
    """McpServer visibility / applies a global visibility to every registration"""
    registrations = layer.merge(
        M.resource(uri="test://shown", name="shown", content=fx.succeed("shown")),
        M.resource(uri="test://hidden", name="hidden", content=fx.succeed("hidden")),
        M.visibility(lambda options: fx.succeed(options.target != "test://hidden"), global_=True),
    )
    harness = yield from stdio_harness(P.v2025_11_25, layer=registrations)
    yield from harness.initialize()

    assert names((yield from harness.send_request("resources/list", {})), "resources") == ["shown"]
    read = yield from harness.send_request("resources/read", {"uri": "test://hidden"})
    assert read["error"] == {"code": -32002, "message": "Resource 'test://hidden' not found"}


@testing.effect
def test_re_checks_visibility_on_input_required_continuations():
    """McpServer visibility / re-checks visibility on input_required continuations"""
    state, auth, _ = _fixture()

    @fx.gen
    def register():
        server = yield from M.McpServer()
        yield from server.add_tool(
            ToolEntry(
                {"name": "Approve", "inputSchema": {"type": "object"}},
                Context.empty(),
                lambda _: fx.succeed(
                    MS.InputRequired(
                        input_requests={"roots": {"method": "roots/list"}}, request_state="round"
                    )
                ),
                (yield from fx.context()),
            )
        )

    registrations = layer.effect_discard(register).pipe(provide(ADMIN_ONLY.combine(auth).layer))
    harness = yield from stdio_harness(P.v2026_07_28, layer=registrations)
    meta: Json = {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {"roots": {}},
        "io.modelcontextprotocol/clientInfo": {"name": "client", "version": "1"},
    }

    state.user = "admin"
    first = yield from harness.send_request(
        "tools/call", {"name": "Approve", "arguments": {}, "_meta": meta}
    )
    assert first["result"]["resultType"] == "input_required"

    state.user = "guest"
    second = yield from harness.send_request(
        "tools/call",
        {
            "name": "Approve",
            "arguments": {},
            "requestState": "round",
            "inputResponses": {"roots": {"roots": []}},
            "_meta": meta,
        },
    )
    assert second["error"] == {"code": -32602, "message": "Tool 'Approve' not found"}


@testing.effect
def test_keeps_middleware_provided_locally_and_globally_outside_a_visibility_that_reads_it():
    """McpServer visibility / keeps middleware provided locally and globally outside a visibility that reads it"""  # noqa: E501
    state, auth, _ = _fixture()
    registrations = layer.merge(
        M.toolkit(ADMIN_TOOLS).pipe(provide(auth.layer)).pipe(provide(ADMIN_HANDLERS)),
        ADMIN_ONLY.combine(auth).layer_global,
    )
    harness = yield from stdio_harness(P.v2025_11_25, layer=registrations)
    yield from harness.initialize()

    assert names((yield from harness.send_request("tools/list", {})), "tools") == []
    state.user = "admin"
    tools = yield from harness.send_request("tools/list", {})
    assert names(tools, "tools") == ["DeleteUser", "ResetPassword"]
    call = yield from harness.send_request("tools/call", {"name": "DeleteUser", "arguments": {}})
    assert call["result"]["content"] == [{"type": "text", "text": "deleted"}]


@testing.effect
def test_runs_nested_visibilities_from_the_outside_in_on_lists():
    """McpServer visibility / runs nested visibilities from the outside in on lists"""
    state = {"user": "guest", "plan": "free"}
    calls: list[str] = []

    def noted[A](note: str, effect: fx.Effect[A, Any, Any]) -> fx.Effect[A, Any, Any]:
        return fx.sync(lambda: calls.append(note)).and_then(effect)

    auth = M.middleware(
        lambda effect, _: fx.suspend(
            lambda: noted("auth", effect.pipe(fx.provide_service(CurrentUser, state["user"])))
        ),
        provides=CurrentUser,
    )

    def signed_in(user: str) -> bool:
        calls.append(f"signed-in {user}")
        return user != "guest"

    signed_in_only = M.visibility(lambda _: CurrentUser().map(signed_in))
    tenant = M.middleware(
        lambda effect, _: fx.suspend(
            lambda: noted("tenant", effect.pipe(fx.provide_service(CurrentTenant, state["plan"])))
        ),
        provides=CurrentTenant,
    )

    @fx.gen
    def paid_plan():
        user = yield from CurrentUser()
        plan = yield from CurrentTenant()
        calls.append(f"paid {user} {plan}")
        return plan == "paid"

    paid = M.visibility(lambda _: paid_plan)
    audit = M.middleware(lambda effect, _: noted("audit", effect))
    invoice = T.make("Invoice", success=S.String)
    billing = K.make(invoice)
    combined = audit.combine(paid.combine(tenant.combine(signed_in_only.combine(auth))))
    registrations = (
        M.toolkit(billing)
        .pipe(provide(combined.layer))
        .pipe(provide(billing.to_layer(invoice.handler(lambda _, __: fx.succeed("invoice")))))
    )
    harness = yield from stdio_harness(P.v2025_11_25, layer=registrations)
    yield from harness.initialize()

    def take() -> list[str]:
        taken = calls[:]
        calls.clear()
        return taken

    assert names((yield from harness.send_request("tools/list", {})), "tools") == []
    assert take() == ["auth", "signed-in guest"]

    state["user"] = "alice"
    assert names((yield from harness.send_request("tools/list", {})), "tools") == []
    assert take() == ["auth", "signed-in alice", "tenant", "paid alice free"]

    state["plan"] = "paid"
    assert names((yield from harness.send_request("tools/list", {})), "tools") == ["Invoice"]
    assert take() == ["auth", "signed-in alice", "tenant", "paid alice paid"]


@testing.effect
def test_passes_middleware_outside_a_visibility_an_mcp_error_for_hidden_requests():
    """McpServer visibility / passes middleware outside a visibility an MCP error for hidden requests"""  # noqa: E501
    codes: list[int] = []
    log_code = M.middleware(
        lambda effect, _: effect.tap_error(lambda error: fx.sync(lambda: codes.append(error.code)))
    )
    hidden = M.visibility(lambda _: fx.succeed(False))
    registrations = (
        M.toolkit(ADMIN_TOOLS)
        .pipe(provide(hidden.combine(log_code).layer))
        .pipe(provide(ADMIN_HANDLERS))
    )
    harness = yield from stdio_harness(P.v2025_11_25, layer=registrations)
    yield from harness.initialize()

    call = yield from harness.send_request("tools/call", {"name": "DeleteUser", "arguments": {}})

    assert call["error"] == {"code": -32602, "message": "Tool 'DeleteUser' not found"}
    assert codes == [-32602]


@testing.effect
def test_propagates_interruption_from_middleware_outside_a_visibility_on_lists():
    """McpServer visibility / propagates interruption from middleware outside a visibility on lists"""  # noqa: E501
    targets: list[str] = []

    def interrupt(effect: Any, options: M.MiddlewareOptions) -> Any:
        def failed(cause: Cause[Any]) -> fx.Effect[Any, Any]:
            targets.append(options.target)
            return fx.fail_cause(C.merge(cause, C.interrupt(123)))

        return effect.catch_cause(failed)

    hidden = M.visibility(lambda _: fx.succeed(False))
    registrations = (
        M.toolkit(ADMIN_TOOLS)
        .pipe(provide(hidden.combine(M.middleware(interrupt)).layer))
        .pipe(provide(ADMIN_HANDLERS))
    )
    harness = yield from stdio_harness(P.v2025_11_25, layer=registrations)
    yield from harness.initialize()

    response = yield from harness.send_request("tools/list", {})

    assert "result" not in response
    assert targets == ["DeleteUser"]
