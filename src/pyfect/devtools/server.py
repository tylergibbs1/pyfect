"""The DevTools side of the protocol (Effect's ``devtools/DevToolsServer``):
``run`` hands each connected app to ``handle`` as a ``Client``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Never

from pyfect._core import Effect
from pyfect.devtools import schema as D
from pyfect.effect import gen
from pyfect.encoding.ndjson import NdjsonError, duplex_schema_string
from pyfect.queue import Dequeue, Queue
from pyfect.schema import SchemaError
from pyfect.socket import SocketChannel, SocketService, to_channel_string
from pyfect.socket.server import SocketServer, SocketServerError
from pyfect.stream import from_queue

__all__ = ["Client", "run"]

type RequestWithoutPing = D.Span | D.SpanEvent | D.MetricsSnapshot


@dataclass(frozen=True, slots=True)
class Client:
    """A connected app: ``queue`` has its requests (``Ping``\\s are
    answered for it); ``send`` sends it a ``MetricsRequest``."""

    queue: Dequeue[RequestWithoutPing, Any]
    send: Callable[[D.MetricsRequest], Effect[None]]


def run[E = Never, R = Never](
    handle: Callable[[Client], Effect[object, E, R]],
) -> Effect[Never, SocketServerError, R | SocketServer]:
    """Serve the ``SocketServer``'s connections with ``handle``."""

    def connection(socket: SocketService) -> Effect[object, E, R]:
        def body():
            responses = yield from Queue[D.Response, Any].unbounded()
            requests = yield from Queue[RequestWithoutPing, Any].unbounded()

            def on_request(request: D.Request) -> Effect[None]:
                if request["_tag"] == "Ping":
                    return responses.offer({"_tag": "Pong"}).as_void()
                return requests.offer(request).as_void()

            socket_channel: SocketChannel[str, NdjsonError | SchemaError] = to_channel_string(
                socket
            )
            channel = duplex_schema_string(
                socket_channel, input_schema=D.RESPONSE_CODEC, output_schema=D.REQUEST_CODEC
            )
            yield from (
                from_queue(responses)
                .pipe_through_channel(channel)
                .run_for_each(on_request)
                .ensuring(responses.shutdown().and_then(requests.shutdown()))
                .fork()
            )
            client = Client(requests, lambda response: responses.offer(response).as_void())
            return (yield from handle(client))

        return gen(body)

    return SocketServer().flat_map(lambda server: server.run(connection))
