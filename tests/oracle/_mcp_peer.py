"""Effect's ``McpTestPeer`` (McpConformance/McpTestPeer.ts): a client
that records the requests a server sends it and answers them with
handlers.

Effect's peer drives a protocol's reverse client over a recording RPC
protocol. pyfect's reverse client is part of the server's session, so this
peer is a real client of a stdio server: ``run`` runs an effect needing
``McpServerClient`` inside a tool call of that session, answering the
server's requests meanwhile.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, cast

import pyfect as fx
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai._mcp.core import ToolEntry
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.scope import Scope

from ._mcp import Json, StdioHarness, stdio_harness

type Handler = Callable[[Json], fx.Effect[Json, Json]]
"""Answers a recorded request with a result, or fails with an MCP error."""

_RUN_TOOL = "McpTestPeerRun"


@dataclass
class Peer:
    harness: StdioHarness
    handlers: Mapping[str, Handler]
    requests: list[Json] = field(default_factory=list[Json])
    """``{"id", "method", "payload"}`` of each request the server sent."""
    _next: list[fx.Effect[Any, Any, Any]] = field(default_factory=list[fx.Effect[Any, Any, Any]])
    _runs: int = 0

    def run[A, E](self, effect: fx.Effect[A, E, MS.McpServerClient]) -> fx.Effect[fx.Exit[A, E]]:
        """``effect`` 's exit, run inside a request of this peer's session."""
        self._runs += 1
        id = f"peer-run-{self._runs}"
        done = Deferred[fx.Exit[A, E]]()
        self._next.append(effect.exit().flat_map(done.succeed))
        harness = self.harness

        @fx.gen
        def run():
            yield from harness.send(
                {
                    "jsonrpc": "2.0",
                    "id": id,
                    "method": "tools/call",
                    "params": {"name": _RUN_TOOL, "arguments": {}},
                }
            )
            while True:
                message = yield from harness.receive()
                if "method" in message and "id" in message:
                    yield from self._answer(message)
                elif message.get("id") == id:
                    return (yield from done.wait())

        return run

    def _answer(self, message: Json) -> fx.Effect[None]:
        request: Json = {
            "id": message["id"],
            "method": message["method"],
            "payload": message.get("params", {}),
        }
        self.requests.append(request)
        handler = self.handlers.get(message["method"])
        answered: fx.Effect[Json, Json] = (
            fx.fail({"code": -32601, "message": f"No test peer handler for {message['method']}"})
            if handler is None
            else handler(request)
        )
        reply = answered.match(
            on_success=lambda result: {"jsonrpc": "2.0", "id": message["id"], "result": result},
            on_failure=lambda error: {"jsonrpc": "2.0", "id": message["id"], "error": error},
        )
        return reply.flat_map(self.harness.send)

    def serve_next(self, _: object) -> fx.Effect[Any]:
        return self._next.pop(0).as_(cast("MS.CallToolResult", {"content": []}))


def peer(
    protocol: P.AnyProtocolAdapter,
    capabilities: Json | None = None,
    handlers: Mapping[str, Handler] | None = None,
) -> fx.Effect[Peer, Any, Scope]:
    """Effect's ``makeMcpTestPeer``: an initialized client advertising
    ``capabilities``."""

    @fx.gen
    def run():
        harness = yield from stdio_harness(protocol)
        made = Peer(harness, handlers or {})
        entry = ToolEntry(
            {"name": _RUN_TOOL, "inputSchema": {"type": "object"}},
            Context.empty(),
            made.serve_next,
        )
        yield from harness.server.add_tool(entry)
        yield from harness.initialize(capabilities or {})
        return made

    return run


def reverse_client() -> fx.Effect[MS.ReverseClient, Any, MS.McpServerClient]:
    """The reverse client of the request being served."""
    return MS.McpServerClient().flat_map(lambda client: client.get_client)
