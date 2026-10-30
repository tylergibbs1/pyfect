"""The transport of an RPC client (Effect's ``RpcClient.Protocol``)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Never

from pyfect._core import Effect
from pyfect.context import Context, Tag
from pyfect.effect import context, gen, never, provide_context, succeed, suspend
from pyfect.rpc.client_error import RpcClientError
from pyfect.rpc.serialization import CodecFor

_VOID: Effect[None] = succeed(None)

type Message = Mapping[str, Any]
type WriteResponse = Callable[[Message], Effect[None]]


@dataclass(frozen=True, slots=True)
class ClientProtocolService:
    """A client transport: ``run(client_id, f)`` hands each response for
    the client to ``f`` (and never returns); ``send`` writes a message."""

    run: Callable[[int, WriteResponse], Effect[Never]]
    send: Callable[[int, Message], Effect[None, RpcClientError]]
    supports_ack: bool
    codec_for: CodecFor


class ClientProtocol(Tag[ClientProtocolService], key="effect/rpc/RpcClient/Protocol"):
    """The transport of the clients made in the context."""


@dataclass(frozen=True, slots=True)
class ClientProtocolParts:
    """A client protocol without its ``run`` (see ``with_run_client``)."""

    send: Callable[[int, Message], Effect[None, RpcClientError]]
    supports_ack: bool
    codec_for: CodecFor


type WriteTo = Callable[[int, Message], Effect[None]]


def with_run_client[EX, RX](
    make: Callable[[WriteTo, set[int]], Effect[ClientProtocolParts, EX, RX]],
) -> Effect[ClientProtocolService, EX, RX]:
    """A client protocol from its parts, made with the function writing a
    response to a client and the set of running clients (Effect's
    ``Utils.withRunClient``). Responses for a client that sent a request
    but is not running yet are kept until it runs; responses for any other
    client (one that stopped running) are dropped, so nothing is kept for
    a client that never runs again (Effect keeps them)."""
    client_ids: set[int] = set()
    buffers: dict[int, list[tuple[Message, Context[Any]]]] = {}
    writes: dict[int, WriteResponse] = {}
    awaited: set[int] = set()
    """The clients that sent a request and have not stopped running."""

    def write(client_id: int, response: Message) -> Effect[None]:
        def body() -> Effect[None]:
            found = writes.get(client_id)
            if found is not None:
                return found(response)
            if client_id not in awaited:
                return _VOID

            def keep(services: Context[Any]) -> None:
                buffers.setdefault(client_id, []).append((response, services))

            return context().map(keep)

        return suspend(body)

    def build(parts: ClientProtocolParts) -> ClientProtocolService:
        def send(client_id: int, message: Message) -> Effect[None, RpcClientError]:
            def body() -> Effect[None, RpcClientError]:
                if message.get("_tag") == "Request":
                    awaited.add(client_id)
                return parts.send(client_id, message)

            return suspend(body)

        def run(client_id: int, f: WriteResponse) -> Effect[Never]:
            @gen
            def running():
                client_ids.add(client_id)
                writes[client_id] = f
                for response, services in buffers.pop(client_id, []):
                    yield from suspend(lambda r=response: f(r)).pipe(provide_context(services))

                def leave(_: object) -> Effect[None]:
                    client_ids.discard(client_id)
                    awaited.discard(client_id)
                    writes.pop(client_id, None)
                    buffers.pop(client_id, None)
                    return _VOID

                return (yield from never.on_exit(leave))

            return running

        return ClientProtocolService(run, send, parts.supports_ack, parts.codec_for)

    return make(write, client_ids).map(build)


__all__ = [
    "ClientProtocol",
    "ClientProtocolParts",
    "ClientProtocolService",
    "Message",
    "WriteResponse",
    "WriteTo",
    "with_run_client",
]
