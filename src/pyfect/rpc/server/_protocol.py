"""The transport of an RPC server (Effect's ``RpcServer.Protocol``)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Never

from pyfect._core import Effect
from pyfect.context import Context, Tag
from pyfect.effect import context, gen, never, provide_context, succeed, suspend
from pyfect.queue import Queue
from pyfect.rpc.serialization import CodecFor
from pyfect.semaphore import Semaphore

type Message = Mapping[str, Any]
"""An encoded message (``FromClientEncoded`` / ``FromServerEncoded``)."""

type WriteRequest = Callable[[int, Message], Effect[None]]


@dataclass(frozen=True, slots=True)
class ServerProtocolService:
    """A server transport: ``run`` hands each message of a client to the
    server (and never returns); ``send`` writes a response to a client,
    ``end`` closes it; ``disconnects`` yields the clients that left."""

    run: Callable[[WriteRequest], Effect[Never]]
    disconnects: Queue[int]
    send: Callable[[int, Message], Effect[None]]
    end: Callable[[int], Effect[None]]
    supports_ack: bool
    supports_span_propagation: bool
    codec_for: CodecFor


class ServerProtocol(Tag[ServerProtocolService], key="effect/rpc/RpcServer/Protocol"):
    """The transport the server in the context runs over."""


@dataclass(frozen=True, slots=True)
class ProtocolParts:
    """A protocol without its ``run`` (see ``with_run``)."""

    disconnects: Queue[int]
    send: Callable[[int, Message], Effect[None]]
    end: Callable[[int], Effect[None]]
    supports_ack: bool
    supports_span_propagation: bool
    codec_for: CodecFor


def with_run[EX, RX](
    make: Callable[[WriteRequest], Effect[ProtocolParts, EX, RX]],
) -> Effect[ServerProtocolService, EX, RX]:
    """A protocol from its parts, made with the function writing requests
    to the server (Effect's ``Utils.withRun``). Requests written before the
    server runs are kept, and handed to it (with their services) when it
    does."""
    buffer: list[tuple[int, Message, Context[Any]]] = []
    current: list[WriteRequest] = []
    semaphore = Semaphore(1)

    def buffered(client_id: int, message: Message) -> Effect[None]:
        def keep(services: Context[Any]) -> None:
            buffer.append((client_id, message, services))

        return context().map(keep)

    def write(client_id: int, message: Message) -> Effect[None]:
        return suspend(lambda: (current[-1] if current else buffered)(client_id, message))

    def build(parts: ProtocolParts) -> ServerProtocolService:
        def run(f: WriteRequest) -> Effect[Never]:
            @gen
            def running():
                pending = list(buffer)
                buffer.clear()
                for client_id, message, services in pending:
                    yield from suspend(lambda c=client_id, m=message: f(c, m)).pipe(
                        provide_context(services)
                    )
                current.append(f)
                return (yield from never.on_exit(lambda _: succeed(current.remove(f))))

            return semaphore.with_permits(running)

        return ServerProtocolService(
            run,
            parts.disconnects,
            parts.send,
            parts.end,
            parts.supports_ack,
            parts.supports_span_propagation,
            parts.codec_for,
        )

    return make(write).map(build)


__all__ = [
    "Message",
    "ProtocolParts",
    "ServerProtocol",
    "ServerProtocolService",
    "WriteRequest",
    "with_run",
]
