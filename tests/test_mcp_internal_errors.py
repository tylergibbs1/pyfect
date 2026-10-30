"""A defect in a resource, prompt or completion handler reaches the MCP
peer as a generic internal error, as a tool defect does; a declared
failure keeps its message."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M

_SECRET = "postgresql://admin:hunter2@db.internal/app"


def _direct[A, E](effect: fx.Effect[A, E, MS.McpServerClient]) -> fx.Effect[A, E]:
    client = MS.ServerClient(
        client_id=0,
        protocol_version="2025-06-18",
        client_capabilities={},
        client_info=None,
        initialize_payload={},
        get_client=fx.die(RuntimeError("no reverse client")),
    )
    return effect.pipe(fx.provide_service(MS.McpServerClient, client))


def _read(content: fx.Effect[Any, Any]) -> fx.Effect[MS.McpError]:
    def program() -> Any:
        server = yield from M.make()
        yield from M.register_resource(uri="file:///r", name="r", content=content).pipe(
            fx.provide_service(M.McpServer, server)
        )
        return (yield from _direct(server.find_resource("file:///r")).flip())

    return fx.gen(program)


@testing.effect
def test_a_resource_defect_is_answered_without_its_message():
    error = yield from _read(fx.die(RuntimeError(f"connect to {_SECRET} failed")))
    assert isinstance(error, MS.InternalError)
    assert _SECRET not in str(error)


@testing.effect
def test_a_declared_resource_failure_keeps_its_message():
    error = yield from _read(fx.fail(Exception("not ready yet")))
    assert isinstance(error, MS.InternalError)
    assert str(error) == "not ready yet"


@dataclass(frozen=True)
class _Busy:
    message: str
    api_token: str


@testing.effect
def test_a_declared_failure_that_is_no_exception_sends_its_message_not_its_fields():
    error = yield from _read(fx.fail(_Busy(message="busy", api_token="tok-secret")))
    assert isinstance(error, MS.InternalError)
    assert str(error) == "busy"


@testing.effect
def test_a_declared_string_failure_is_sent_as_is():
    error = yield from _read(fx.fail("not ready yet"))
    assert str(error) == "not ready yet"
