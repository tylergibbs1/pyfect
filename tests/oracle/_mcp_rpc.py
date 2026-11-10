"""A custom RPC server transport for MCP tests (Effect's tests build one
with ``RpcServer.Protocol.make``): the test writes client messages with
``send`` and reads what the server sends from ``outbound``."""

from __future__ import annotations

from collections.abc import Callable, Set
from dataclasses import dataclass
from typing import Any

import pyfect as fx
from pyfect.deferred import Deferred
from pyfect.queue import Queue
from pyfect.rpc import serialization as rs
from pyfect.rpc import server as rpc_server

type Message = dict[str, Any]
type Send = Callable[[int, Message], fx.Effect[None]]


@dataclass(frozen=True, slots=True)
class CustomTransport:
    protocol: rpc_server.ServerProtocolService
    ready: Deferred[Send]
    """The function writing a client's message to the server, once it runs."""
    outbound: Queue[tuple[int, Message]]
    """``(client id, message)`` of each message the server sent."""
    disconnects: Queue[int]


def _reading(client_ids: Set[int]) -> fx.Effect[Set[int]]:
    return fx.sync(lambda: frozenset(client_ids))


def custom_transport(
    *,
    client_ids: Set[int] | None = None,
    supports_notifications: bool = True,
    send: Callable[[int, Message], fx.Effect[None]] | None = None,
) -> fx.Effect[CustomTransport]:
    """A transport whose ``client_ids`` are read on each call (the set may
    change); ``send`` runs before a message is queued on ``outbound``."""

    @fx.gen
    def make():
        ready = Deferred[Send]()
        outbound = yield from Queue[tuple[int, Message]].unbounded()
        disconnects = yield from Queue[int].unbounded()

        def queued(client_id: int, message: Any) -> fx.Effect[None]:
            offered = outbound.offer((client_id, dict(message))).as_void()
            return offered if send is None else send(client_id, dict(message)).and_then(offered)

        def parts(write: Any) -> fx.Effect[rpc_server.ProtocolParts]:
            return ready.succeed(write).as_(
                rpc_server.ProtocolParts(
                    disconnects=disconnects,
                    send=queued,
                    end=lambda _: fx.succeed(None),
                    supports_ack=False,
                    supports_span_propagation=False,
                    codec_for=rs.json.codec_for,
                    supports_notifications=supports_notifications,
                    client_ids=None if client_ids is None else _reading(client_ids),
                )
            )

        protocol = yield from rpc_server.with_run(parts)
        return CustomTransport(protocol, ready, outbound, disconnects)

    return make


def request(id: object, tag: str, payload: object, *, notification: bool = False) -> Message:
    message: Message = {"_tag": "Request", "id": id, "tag": tag, "payload": payload, "headers": []}
    if notification:
        message["isNotification"] = True
    return message


@dataclass(frozen=True, slots=True)
class Inbox:
    """``outbound`` sorted by client: each client's messages in order."""

    transport: CustomTransport
    held: dict[int, list[Message]]

    @staticmethod
    def of(transport: CustomTransport) -> Inbox:
        return Inbox(transport, {})

    def take(self, client_id: int) -> fx.Effect[Message]:
        @fx.gen
        def run():
            while not self.held.get(client_id):
                received, message = yield from self.transport.outbound.take()
                self.held.setdefault(received, []).append(message)
            return self.held[client_id].pop(0)

        return run

    def exit(self, client_id: int, request_id: object) -> fx.Effect[Message]:
        """The client's next ``Exit`` answering ``request_id``."""

        @fx.gen
        def run():
            while True:
                message = yield from self.take(client_id)
                if message["_tag"] == "Exit" and message["requestId"] == request_id:
                    return message

        return run

    def request(self, client_id: int, tag: str) -> fx.Effect[Message]:
        """The client's next ``Request`` with ``tag``."""

        @fx.gen
        def run():
            while True:
                message = yield from self.take(client_id)
                if message["_tag"] == "Request" and message["tag"] == tag:
                    return message

        return run

    @property
    def empty(self) -> bool:
        return self.transport.outbound.size_unsafe() == 0 and not any(self.held.values())
