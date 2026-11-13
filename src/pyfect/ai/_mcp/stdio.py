"""The stdio transport: one client, newline-delimited JSON-RPC on standard
input and output."""

from __future__ import annotations

from typing import Any, Never, cast

from pyfect import stream
from pyfect._catch import catch_tag
from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect._fiber import Fiber
from pyfect.ai._mcp import batch, frames
from pyfect.ai._mcp.core import McpServer
from pyfect.ai._mcp.dispatch import Connection, ServerInfo, error_response
from pyfect.ai.mcp_protocol import Registry
from pyfect.ai.mcp_schema import InvalidRequest, JsonObject, ParseError
from pyfect.channel import LineTooLongError
from pyfect.effect import die, gen, provide_service, succeed, suspend, sync
from pyfect.errors import Done
from pyfect.logger import CurrentLogLevel, LogToStderr
from pyfect.platform_error import PlatformError
from pyfect.queue import Queue
from pyfect.rpc.serialization import DEFAULT_MAX_BUFFER_SIZE, MaxBufferSizeExceeded
from pyfect.stdio import Stdio

_VOID: Effect[None] = succeed(None)
_OUTPUT_BUFFER = 8


def _encode(message: JsonObject) -> str:
    return frames.write(message) + "\n"


def _await_batch(fiber: Fiber[None, Never]) -> Effect[object]:
    return fiber.await_exit()


def _too_long(error: LineTooLongError) -> Effect[Never]:
    return die(MaxBufferSizeExceeded(max_buffer_size=error.max_length))


def serve(info: ServerInfo, registry: Registry) -> Effect[None, PlatformError, McpServer | Stdio]:
    """Serve the client on standard input until it ends, then let the
    requests still running finish. Standard output carries only the
    protocol: the console loggers write to standard error (``LogToStderr``),
    so a logged defect cannot corrupt it."""

    @gen
    def run():
        server = yield from McpServer()
        io = yield from Stdio()
        # Bounded, as in Effect's stdio protocol: a client that stops reading
        # holds up writers, so a subscription's backlog can overflow.
        lines = Queue[str, Done](_OUTPUT_BUFFER)

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
                message: Any = frames.read(line)
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
        # A line past 16 MiB ends the server, as Effect's NDJSON-RPC framing does.
        reading = (
            io.stdin.decode_text()
            .split_lines_within(DEFAULT_MAX_BUFFER_SIZE)
            .run_for_each(receive)
            .pipe(catch_tag(LineTooLongError, _too_long))
        )
        finished = suspend(lambda: for_each(list(batches), _await_batch)).as_void()
        serving = yield from (
            reading.and_then(connection.drain())
            .and_then(finished)
            .ensuring(
                sync(lambda: server.disconnect(connection.client_id)).and_then(connection.close())
            )
            .fork()
        )
        # A dead writer would leave every writer waiting on the bounded output. Only a writer
        # that ended early can interrupt anything: the output ends after serving has exited.
        yield from writer.await_exit().and_then(serving.interrupt()).fork()
        yield from serving.await_exit()
        yield from lines.end()
        yield from writer.join()
        yield from serving.join()

    return run.pipe(provide_service(LogToStderr, True))
