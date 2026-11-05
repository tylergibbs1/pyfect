"""Harnesses for the MCP tests: an ``McpServer`` over an in-memory stdio
(Effect's ``makeMcpStdioHarness``) and over an in-memory HTTP router."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

import pyfect as fx
from pyfect import sink, stdio, stream
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_server as M
from pyfect.errors import Done
from pyfect.queue import Queue
from pyfect.scope import Scope

type Json = dict[str, Any]

CLIENT_INFO: Json = {"name": "test-client", "version": "1.0.0"}


@dataclass
class StdioHarness:
    """A client of an in-memory stdio server."""

    protocol: P.AnyProtocolAdapter
    server: M.McpServerService
    stdin: Queue[bytes, Done]
    stdout: Queue[Json, Done]
    raw_stdout: Queue[str, Done]
    """Each write to stdout, as written."""
    fiber: fx.Fiber[Any, Any]
    """The server, serving until stdin ends."""
    next_id: int = 1

    @property
    def close(self) -> fx.Effect[None]:
        """End stdin, as a client closing it."""
        return self.stdin.end().as_void()

    def send_chunk(self, chunk: bytes) -> fx.Effect[None]:
        return self.stdin.offer(chunk).as_void()

    def send(self, message: Json) -> fx.Effect[None]:
        return self.stdin.offer((json.dumps(message) + "\n").encode()).as_void()

    def send_raw(self, line: str) -> fx.Effect[None]:
        return self.stdin.offer((line + "\n").encode()).as_void()

    def with_metadata(self, params: Json | None) -> Json | None:
        if not self.protocol.is_stateless:
            return params
        meta = {
            "io.modelcontextprotocol/protocolVersion": self.protocol.protocol_version,
            "io.modelcontextprotocol/clientInfo": CLIENT_INFO,
            "io.modelcontextprotocol/clientCapabilities": {},
        }
        out = dict(params or {})
        out["_meta"] = {**meta, **out.get("_meta", {})}
        return out

    def receive(self) -> fx.Effect[Json]:
        return self.stdout.take().or_die()

    def response_to(self, id: object) -> fx.Effect[Json]:
        """The next response to ``id``, skipping other messages."""

        @fx.gen
        def run():
            while True:
                message = yield from self.receive()
                if "method" not in message and message.get("id") == id:
                    return message

        return run

    def send_request(
        self, method: str, params: Json | None = None, id: object = None
    ) -> fx.Effect[Json]:
        if id is None:
            id = self.next_id
            self.next_id += 1
        message: Json = {"jsonrpc": "2.0", "id": id, "method": method}
        projected = self.with_metadata(params)
        if projected is not None:
            message["params"] = projected
        return self.send(message).and_then(self.response_to(id))

    def send_notification(self, method: str, params: Json | None = None) -> fx.Effect[None]:
        message: Json = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        return self.send(message)

    def initialize(self, capabilities: Json | None = None) -> fx.Effect[Json]:
        """``initialize`` then ``notifications/initialized`` (a no-op for a
        stateless protocol)."""
        if self.protocol.is_stateless:
            return fx.succeed({})
        return self.send_request(
            "initialize",
            {
                "protocolVersion": self.protocol.protocol_version,
                "capabilities": capabilities or {},
                "clientInfo": CLIENT_INFO,
            },
        ).flat_map(lambda reply: self.send_notification("notifications/initialized").as_(reply))


def stdio_harness(
    protocol: P.AnyProtocolAdapter,
    protocols: Sequence[P.AnyProtocolAdapter] | None = None,
    *registrations: fx.Effect[None, Any, Any],
    instructions: str | None = None,
) -> fx.Effect[StdioHarness, Any, Scope]:
    """A stdio server speaking ``protocols`` (default ``(protocol,)``) with
    ``registrations`` run first, and a client of it speaking
    ``protocol``."""

    @fx.gen
    def run():
        server = yield from M.make()
        stdin = Queue[bytes, Done]()
        stdout = Queue[Json, Done]()
        raw_stdout = Queue[str, Done]()

        def output(*, end_on_done: bool = False) -> stdio.Output:
            def write(chunk: str | bytes) -> fx.Effect[None]:
                text = chunk.decode() if isinstance(chunk, bytes) else chunk

                def record() -> None:
                    raw_stdout.offer_unsafe(text)
                    for line in text.splitlines():
                        if line:
                            stdout.offer_unsafe(json.loads(line))

                return fx.sync(record)

            return cast("stdio.Output", sink.for_each(write))

        for registration in registrations:
            yield from registration.pipe(fx.provide_service(M.McpServer, server))
        serving = M.run_stdio(
            name="test-server",
            version="1.0.0",
            protocols=tuple(protocols or (protocol,)),
            instructions=instructions,
        )
        fiber = yield from (
            serving.pipe(fx.provide_service(M.McpServer, server))
            .pipe(fx.provide(stdio.layer_test(stdin=stream.from_queue(stdin), stdout=output)))
            .fork_scoped()
        )
        return StdioHarness(protocol, server, stdin, stdout, raw_stdout, fiber)

    return run


MCP_ENDPOINT = "http://localhost:3000/mcp"


def in_memory_http(app: Any) -> fx.Effect[Any, Any, Scope]:
    """An ``HttpClientService`` whose requests ``app`` (a layer adding
    routes to the router) handles in memory."""
    from pyfect.http.router import in_memory_client

    return in_memory_client(app)
