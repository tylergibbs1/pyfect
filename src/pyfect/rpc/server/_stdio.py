"""The standard streams as a transport of an RPC server (Effect's
``makeProtocolStdio``). One client, id 0: its messages come from ``Stdio.stdin``
and its responses go to ``Stdio.stdout``. The end of input ends the client; once
its requests are answered and written the fiber that made the protocol (a
``.launch()``) is interrupted, so the program ends."""

from __future__ import annotations

from typing import Any, Never, cast

from pyfect._core import Effect
from pyfect.effect import current_fiber, gen, succeed
from pyfect.errors import Done
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.logger import log_error
from pyfect.queue import Queue
from pyfect.rpc.message import EofEncoded
from pyfect.rpc.serialization import Frame, RpcSerialization
from pyfect.rpc.server._protocol import (
    Message,
    ProtocolParts,
    ServerProtocol,
    ServerProtocolService,
    WriteRequest,
    with_run,
)
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

        def parts(write: WriteRequest) -> Effect[ProtocolParts, Never, Any]:
            @gen
            def build():
                output = yield from Queue[Frame, Done].bounded(_OUTPUT_BUFFER)
                parser = serialization.make_unsafe()

                def on_input(data: bytes) -> Effect[None]:
                    @gen
                    def each():
                        for message in parser.decode(data):
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
                    .ensuring(fiber.interrupt().fork_daemon(start_immediately=True).as_void())
                )

                def send(_client: int, response: Message) -> Effect[None]:
                    encoded = parser.encode(response)
                    return succeed(None) if encoded is None else output.offer(encoded).as_void()

                return ProtocolParts(
                    disconnects=(yield from Queue[int].unbounded()),
                    send=send,
                    end=lambda _client: output.end().as_void(),
                    supports_ack=True,
                    supports_span_propagation=True,
                    codec_for=serialization.codec_for,
                )

            return build

        return (yield from with_run(parts))

    return make


layer_protocol_stdio: Layer[ServerProtocol, Never, Stdio | RpcSerialization] = layer_effect(
    ServerProtocol, make_protocol_stdio()
)
"""A server protocol over the current ``Stdio``: requests are read from
standard input and responses written to standard output. Once input has
ended and the last response is written, it interrupts the fiber that built
it, as Effect's ``layerProtocolStdio`` does, so a launched server under
``run_main`` exits 130."""

__all__ = ["layer_protocol_stdio", "make_protocol_stdio"]
