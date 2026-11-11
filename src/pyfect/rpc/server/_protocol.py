"""The transport of an RPC server (Effect's ``RpcServer.Protocol``)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Set
from dataclasses import dataclass, field
from typing import Any, Never, Self

from pyfect._core import Effect
from pyfect._service_copy import replaced
from pyfect.context import Context, Tag
from pyfect.effect import context, gen, never, provide_context, succeed, suspend
from pyfect.option import Option
from pyfect.queue import Queue
from pyfect.rpc.serialization import CodecFor
from pyfect.semaphore import Semaphore

type Message = Mapping[str, Any]
"""An encoded message (``FromClientEncoded`` / ``FromServerEncoded``)."""

type WriteRequest = Callable[[int, Message], Effect[None]]


def _no_initial_message() -> Effect[Option[object]]:
    return succeed(None)


_NO_INITIAL_MESSAGE: Effect[Option[object]] = succeed(None)


class ServerProtocolService:
    """A server transport (Effect's ``RpcServer.Protocol``): ``run``
    hands each message of a client to the server, ``send`` and ``end``
    answer a client. ``with_run`` builds one from its parts."""

    __slots__ = (
        "_client_ids",
        "_codec_for",
        "_end",
        "_initial_message",
        "_run",
        "_send",
        "disconnects",
        "supports_ack",
        "supports_notifications",
        "supports_span_propagation",
    )

    disconnects: Queue[int]
    """The ids of the clients that left, as they leave."""
    supports_ack: bool
    """Whether clients send an ``Ack`` after each stream chunk."""
    supports_span_propagation: bool
    """Whether requests carry their caller's span."""
    supports_notifications: bool
    """Whether the server can write to a client unasked (an MCP server
    over it serves no subscriptions otherwise)."""

    def __replace__(self, **changes: Any) -> Self:
        """A copy with ``changes`` to the constructor's arguments (``copy.replace``)."""
        return replaced(self, changes)

    def __init__(  # noqa: PLR0917
        self,
        run: Callable[[WriteRequest], Effect[Never]],
        disconnects: Queue[int],
        send: Callable[[int, Message], Effect[None]],
        end: Callable[[int], Effect[None]],
        supports_ack: bool,
        supports_span_propagation: bool,
        codec_for: CodecFor,
        initial_message: Effect[Option[object]] = _NO_INITIAL_MESSAGE,
        supports_notifications: bool = True,
        client_ids: Effect[Set[int]] | None = None,
    ) -> None:
        self._run = run
        self.disconnects = disconnects
        self._send = send
        self._end = end
        self.supports_ack = supports_ack
        self.supports_span_propagation = supports_span_propagation
        self._codec_for = codec_for
        self._initial_message = initial_message
        self.supports_notifications = supports_notifications
        self._client_ids = client_ids

    def run(self, f: WriteRequest) -> Effect[Never]:
        """Hands each encoded message to ``f`` with its client's id, until
        interrupted (it never returns and never fails). Messages that
        arrived before the server ran are handed over first."""
        return self._run(f)

    def send(self, client_id: int, response: Message) -> Effect[None]:
        """Writes the encoded ``response`` to ``client_id``; never fails
        (the built-in transports drop it for a client that has left)."""
        return self._send(client_id, response)

    def end(self, client_id: int) -> Effect[None]:
        """Ends the responses to ``client_id``: the HTTP transport closes
        its response body and stdio its output; the socket and worker
        transports do nothing. Never fails."""
        return self._end(client_id)

    @property
    def codec_for(self) -> CodecFor:
        """``codec_for(schema)``: the codec filling the value holes of the
        messages for ``schema``, the very function of the
        ``RpcSerialization`` behind this transport (encode caches compare
        it by identity)."""
        return self._codec_for

    @property
    def initial_message(self) -> Effect[Option[object]]:
        """The value a worker client sent first
        (``rpc.worker.initial_message``), waiting for it; ``None`` on the
        other transports. Never fails."""
        return self._initial_message

    @property
    def client_ids(self) -> Effect[Set[int]] | None:
        """The ids of the clients connected now (never fails), or ``None``
        when the transport does not report them."""
        return self._client_ids


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
    initial_message: Effect[Option[object]] = field(default_factory=_no_initial_message)
    supports_notifications: bool = True
    client_ids: Effect[Set[int]] | None = None


def with_run[EX, RX](
    make: Callable[[WriteRequest], Effect[ProtocolParts, EX, RX]],
) -> Effect[ServerProtocolService, EX, RX]:
    """A protocol from its parts, made with the function writing requests
    to the server (Effect's ``Utils.withRun``). Requests written before the
    server runs are kept, and handed to it (with their services) when it
    does. Each run of the effect makes its own buffer, so a layer over it
    serves every run (and every worker) it is built for."""

    def per_run() -> Effect[ServerProtocolService, EX, RX]:
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
                    # What these requests' startup writes joins the buffer, and is run too.
                    for client_id, message, services in buffer:
                        yield from suspend(lambda c=client_id, m=message: f(c, m)).pipe(
                            provide_context(services)
                        )
                    buffer.clear()
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
                parts.initial_message,
                parts.supports_notifications,
                parts.client_ids,
            )

        return make(write).map(build)

    return suspend(per_run)


__all__ = [
    "Message",
    "ProtocolParts",
    "ServerProtocol",
    "ServerProtocolService",
    "WriteRequest",
    "with_run",
]
