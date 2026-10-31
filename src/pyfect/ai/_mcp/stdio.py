"""The stdio transport: one client, newline-delimited JSON-RPC on standard
input and output."""

from __future__ import annotations

from typing import Any

from pyfect import _json_text, stream
from pyfect._core import Effect
from pyfect._json_text import parse as parse_json_text
from pyfect.ai._mcp.core import McpServer
from pyfect.ai._mcp.dispatch import Connection, ServerInfo, error_response
from pyfect.ai.mcp_protocol import Registry
from pyfect.ai.mcp_schema import InvalidRequest, JsonObject, ParseError
from pyfect.effect import gen, provide_service, succeed, sync
from pyfect.errors import Done
from pyfect.logger import LogToStderr
from pyfect.platform_error import PlatformError
from pyfect.queue import Queue
from pyfect.stdio import Stdio

_VOID: Effect[None] = succeed(None)


def _encode(message: JsonObject) -> str:
    return _json_text.stringify(message) + "\n"


def serve(info: ServerInfo, registry: Registry) -> Effect[None, PlatformError, McpServer | Stdio]:
    """Serve the client on standard input until it ends, then let the
    requests still running finish. Standard output carries only the
    protocol: the console loggers write to standard error (``LogToStderr``),
    so a logged defect cannot corrupt it."""

    @gen
    def run():
        server = yield from McpServer()
        io = yield from Stdio()
        lines = Queue[str, Done]()

        def write(message: JsonObject) -> Effect[None]:
            return lines.offer(_encode(message)).as_void()

        connection = Connection(
            server, info, registry, server.next_client_id(), "stdio", broadcast=write
        )

        def receive(line: str) -> Effect[None]:
            if not line.strip():
                return _VOID
            try:
                message: Any = parse_json_text(line)
            except ValueError:
                return write(error_response(None, ParseError("Parse error")))
            if isinstance(message, list):
                return write(
                    error_response(None, InvalidRequest("JSON-RPC batches are not supported"))
                )
            return connection.dispatch(message, write)

        writer = yield from stream.from_queue(lines).run(io.stdout()).fork()
        server.connect(connection)
        reading = io.stdin.decode_text().split_lines().run_for_each(receive)
        yield from reading.and_then(connection.drain()).ensuring(
            sync(lambda: server.disconnect(connection.client_id))
            .and_then(connection.close())
            .and_then(lines.end())
        )
        yield from writer.join()

    return run.pipe(provide_service(LogToStderr, True))
