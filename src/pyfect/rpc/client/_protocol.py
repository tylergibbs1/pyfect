"""The transport of an RPC client (Effect's ``RpcClient.Protocol``)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Never

from pyfect._context_effects import service_option
from pyfect._core import Effect
from pyfect._released import closed_message
from pyfect.context import Context, Tag
from pyfect.effect import context, fail, gen, never, provide_context, succeed, suspend
from pyfect.rpc.client_error import RpcClientDefect, RpcClientError
from pyfect.rpc.serialization import CodecFor
from pyfect.scope import Scope

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
    a client that never runs again (Effect keeps them).

    When the ``Scope`` the protocol is made in closes, the calls waiting
    and every later call fail with an ``RpcClientError`` saying the
    protocol is closed (in Effect they wait forever): a client made with
    ``make(Group).pipe(provide(protocol))`` outlives its protocol."""
    client_ids: set[int] = set()
    buffers: dict[int, list[tuple[Message, Context[Any]]]] = {}
    writes: dict[int, WriteResponse] = {}
    awaited: set[int] = set()
    """The clients that sent a request and have not stopped running."""
    released: list[RpcClientError] = []

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
                if released:
                    return fail(released[0])
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

    def release(_: object) -> Effect[None]:
        error = protocol_closed()
        released.append(error)
        failure: Message = {"_tag": "ClientProtocolError", "error": error}

        @gen
        def fail_waiting():
            for f in list(writes.values()):
                yield from f(failure)

        return fail_waiting.uninterruptible()

    @gen
    def made():
        service = yield from make(write, client_ids).map(build)
        scope = yield from service_option(Scope)
        if scope is not None:
            # Added last, so it runs first: the waiting calls fail before
            # the transport is torn down.
            yield from scope.value.add_finalizer(release)
        return service

    return made


def protocol_closed() -> RpcClientError:
    """The error of a call through a client protocol whose scope closed."""
    return RpcClientError(
        RpcClientDefect(
            closed_message("RPC client protocol")
            + ": provide the protocol around the code that uses the client,"
            " or pass it as make(Group, layer=protocol)"
        )
    )


__all__ = [
    "ClientProtocol",
    "ClientProtocolParts",
    "ClientProtocolService",
    "Message",
    "WriteResponse",
    "WriteTo",
    "protocol_closed",
    "with_run_client",
]
