"""The stdio transport: one client, newline-delimited JSON-RPC on standard
input and output."""

from __future__ import annotations

from typing import Any, Never, cast

from pyfect import _json_text, stream
from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect._fiber import Fiber
from pyfect._json_text import parse as parse_json_text
from pyfect.ai._mcp import batch
from pyfect.ai._mcp.core import McpServer
from pyfect.ai._mcp.dispatch import Connection, ServerInfo, error_response
from pyfect.ai.mcp_protocol import Registry
from pyfect.ai.mcp_schema import InvalidRequest, JsonObject, ParseError
from pyfect.effect import gen, provide_service, succeed, suspend, sync
from pyfect.errors import Done
from pyfect.logger import CurrentLogLevel, LogToStderr
from pyfect.platform_error import PlatformError
from pyfect.queue import Queue
from pyfect.stdio import Stdio

_VOID: Effect[None] = succeed(None)


def _encode(message: JsonObject) -> str:
    return _json_text.stringify(message) + "\n"


def _await_batch(fiber: Fiber[None, Never]) -> Effect[object]:
    return fiber.await_exit()


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

        batches: list[Fiber[None, Never]] = []

        def write_batch(replies: list[JsonObject]) -> Effect[None]:
            return lines.offer(_encode(cast("Any", replies))).as_void()

        level = yield from CurrentLogLevel()
        connection = Connection(
            server,
            info,
            registry,
            server.next_client_id(),
            "stdio",
            broadcast=write,
            default_log_level=level,
        )

        def receive(line: str) -> Effect[None]:
            if not line.strip():
                return _VOID
            try:
                message: Any = parse_json_text(line)
            except ValueError:
                return write(error_response(None, ParseError("Parse error")))
            if isinstance(message, list):
                messages = cast("list[object]", message)
                if not batch.accepts(connection, messages):
                    return write(
                        error_response(None, InvalidRequest("JSON-RPC batches are not supported"))
                    )
                # On its own fiber: the batch may wait on answers still to be read.
                answered = batch.answer(connection, messages, write).flat_map(
                    lambda replies: write_batch(replies) if replies else _VOID
                )
                return answered.fork_daemon().map(batches.append)
            return connection.dispatch(message, write)

        writer = yield from stream.from_queue(lines).run(io.stdout()).fork()
        server.connect(connection)
        reading = io.stdin.decode_text().split_lines().run_for_each(receive)
        finished = suspend(lambda: for_each(list(batches), _await_batch)).as_void()
        yield from (
            reading.and_then(connection.drain())
            .and_then(finished)
            .ensuring(
                sync(lambda: server.disconnect(connection.client_id))
                .and_then(connection.close())
                .and_then(lines.end())
            )
        )
        yield from writer.join()

    return run.pipe(provide_service(LogToStderr, True))
