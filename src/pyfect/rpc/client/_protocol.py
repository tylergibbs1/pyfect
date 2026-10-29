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
    ``Utils.withRunClient``). Responses for a client that is not running
    yet are kept until it runs."""
    client_ids: set[int] = set()
    buffers: dict[int, list[tuple[Message, Context[Any]]]] = {}
    writes: dict[int, WriteResponse] = {}

    def write(client_id: int, response: Message) -> Effect[None]:
        def body() -> Effect[None]:
            found = writes.get(client_id)
            if found is not None:
                return found(response)

            def keep(services: Context[Any]) -> None:
                buffers.setdefault(client_id, []).append((response, services))

            return context().map(keep)

        return suspend(body)

    def build(parts: ClientProtocolParts) -> ClientProtocolService:
        def run(client_id: int, f: WriteResponse) -> Effect[Never]:
            @gen
            def running():
                client_ids.add(client_id)
                writes[client_id] = f
                for response, services in buffers.pop(client_id, []):
                    yield from suspend(lambda r=response: f(r)).pipe(provide_context(services))

                def leave(_: object) -> Effect[None]:
                    client_ids.discard(client_id)
                    writes.pop(client_id, None)
                    return succeed(None)

                return (yield from never.on_exit(leave))

            return running

        return ClientProtocolService(run, parts.send, parts.supports_ack, parts.codec_for)

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
