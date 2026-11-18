"""The standard streams as a transport of an RPC server (Effect's
``makeProtocolStdio``). One client, id 0: its messages come from ``Stdio.stdin``
and its responses go to ``Stdio.stdout``. The end of input ends the client; once
its requests are answered and written the fiber that made the protocol (a
``.launch()``) is interrupted, so the program ends."""

from __future__ import annotations

from typing import Any, Never, cast

from pyfect._core import Effect
from pyfect._fiber import Fiber
from pyfect.context import Context
from pyfect.effect import current_fiber, gen, succeed, void
from pyfect.errors import Done
from pyfect.exit import Exit, Failure, Success
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.logger import log_error
from pyfect.queue import Queue
from pyfect.rpc.message import EofEncoded, response_defect_encoded
from pyfect.rpc.serialization import Frame, RpcSerialization
from pyfect.rpc.server._protocol import (
    Message,
    ProtocolParts,
    ServerProtocol,
    ServerProtocolService,
    WriteRequest,
    with_run,
)
from pyfect.rpc.server._serialized import encode_defect_for
from pyfect.run import InterruptExitCode
from pyfect.schedule import spaced
from pyfect.scope import Scope, fork_scoped
from pyfect.stdio import Stdio
from pyfect.stream import from_queue

_CLIENT = 0
_OUTPUT_BUFFER = 8
_RETRY_EVERY = "500 millis"
_EOF: EofEncoded = {"_tag": "Eof"}


def make_protocol_stdio() -> Effect[ServerProtocolService, Never, Stdio | RpcSerialization | Scope]:
    """A server protocol over ``Stdio``, for the current scope."""

    @gen
    def make():
        stdio = yield from Stdio()
        fiber = yield from current_fiber()
        serialization = yield from RpcSerialization()
        encode_defect = encode_defect_for(serialization.codec_for)

        def parts(write: WriteRequest) -> Effect[ProtocolParts, Never, Any]:
            @gen
            def build():
                output = yield from Queue[Frame, Done].bounded(_OUTPUT_BUFFER)
                errors: list[object] = []
                parser = serialization.make_unsafe(on_decode_error=errors.append)

                def send(_client: int, response: Message) -> Effect[None]:
                    encoded = parser.encode(response)
                    return succeed(None) if encoded is None else output.offer(encoded).as_void()

                def on_input(data: bytes) -> Effect[None]:
                    decoded: list[object] = []
                    try:
                        decoded = parser.decode(data)
                    except Exception as cause:
                        errors.append(cause)
                    # Decode failures are answered, not raised: a failure would resubscribe to
                    # stdin and lose the rest of the input (Effect #10579).
                    failed = errors.copy()
                    errors.clear()

                    @gen
                    def each():
                        for error in failed:
                            defect = response_defect_encoded(encode_defect(error))
                            yield from send(_CLIENT, cast("Message", defect))
                        for message in decoded:
                            yield from write(_CLIENT, cast("Message", message))

                    return each

                yield from fork_scoped(
                    stdio.stdin.run_for_each(on_input)
                    .sandbox()
                    .tap_error(log_error)
                    .retry(spaced(_RETRY_EVERY))
                    .flat_map(lambda _: write(_CLIENT, cast("Message", _EOF)))
                )
                yield from fork_scoped(
                    from_queue(output)
                    .run(stdio.stdout())
                    .retry(spaced(_RETRY_EVERY))
                    .on_exit(lambda exit: _end_server(fiber, exit))
                )

                return ProtocolParts(
                    disconnects=(yield from Queue[int].unbounded()),
                    send=send,
                    end=lambda _client: output.end().as_void(),
                    supports_ack=True,
                    supports_span_propagation=True,
                    codec_for=serialization.codec_for,
                    client_ids=succeed(frozenset({_CLIENT})),
                )

            return build

        return (yield from with_run(parts))

    return make


def _end_server(server: Fiber[Any, Any], output: Exit[Any, Any]) -> Effect[None]:
    """Ends the server once its output stops: with exit code 0 once the output has drained,
    with a plain interruption (130) after a failed write, and not at all when the output was
    interrupted, as the server is ending already."""
    if isinstance(output, Failure) and output.cause.has_interrupts_only:
        return void
    done = Context.make(InterruptExitCode, 0) if isinstance(output, Success) else None
    return server.interrupt_as(None, done).fork_daemon(start_immediately=True).as_void()


layer_protocol_stdio: Layer[ServerProtocol, Never, Stdio | RpcSerialization] = layer_effect(
    ServerProtocol, make_protocol_stdio()
)
"""A server protocol over the current ``Stdio``: requests are read from
standard input and responses written to standard output. Once input has
ended and the last response is written, it interrupts the fiber that built
it, as Effect's ``layerProtocolStdio`` does, so a launched server under
``run_main`` exits 130."""

__all__ = ["layer_protocol_stdio", "make_protocol_stdio"]
