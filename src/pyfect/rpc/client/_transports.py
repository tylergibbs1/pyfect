"""The socket transport of an RPC client (Effect's ``makeProtocolSocket``)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Never, cast

from pyfect import schedule
from pyfect._core import Effect
from pyfect.cause import Cause
from pyfect.clock import Clock
from pyfect.context import Reference
from pyfect.duration import Duration, to_seconds
from pyfect.effect import fail, gen, succeed, suspend
from pyfect.latch import Latch
from pyfect.result import Ok
from pyfect.rpc.client._protocol import (
    ClientProtocolParts,
    ClientProtocolService,
    Message,
    WriteTo,
    with_run_client,
)
from pyfect.rpc.client_error import RpcClientDefect, RpcClientError
from pyfect.rpc.message import PING
from pyfect.rpc.serialization import Frame, Parser, RpcSerialization, RpcSerializationService
from pyfect.schedule import Schedule
from pyfect.scope import Scope, fork_scoped, scoped
from pyfect.socket import (
    Socket,
    SocketError,
    SocketOpenError,
    SocketReadError,
    SocketService,
    Writer,
)
from pyfect.socket import SocketError as SocketErrorClass

_VOID: Effect[None] = succeed(None)


def _key(request_id: object) -> tuple[type[object], object]:
    """A request id as a dict key: ``1`` and ``"1"`` stay apart."""
    return (type(request_id), request_id)


def _defect(message: str, cause: object) -> RpcClientError:
    return RpcClientError(RpcClientDefect(message, cause))


@dataclass(frozen=True, slots=True)
class ConnectionHooksService:
    """Run when a socket protocol connects and when it disconnects."""

    on_connect: Effect[None]
    on_disconnect: Effect[None]


class ConnectionHooks(
    Reference[ConnectionHooksService | None], key="effect/rpc/RpcClient/ConnectionHooks"
):
    """The ``ConnectionHooks`` of the socket protocols made here."""

    @classmethod
    def default(cls) -> ConnectionHooksService | None:
        return None


def default_retry_policy() -> Schedule[Any, Any, Never, Never]:
    """Exponential from 0.5s by 1.5, at most 5s apart."""
    return cast(
        "Schedule[Any, Any, Never, Never]",
        schedule.min(schedule.exponential(0.5, 1.5), schedule.spaced(5.0)),
    )


class _Pinger:
    __slots__ = ("_awaiting", "_clock", "_last_seen", "_timeout", "latch")

    def __init__(self, clock: Any, timeout: float) -> None:
        self._clock = clock
        self._timeout = timeout
        self._last_seen = clock.unsafe_monotonic()
        self._awaiting = False
        self.latch = Latch(False)

    def on_frame(self) -> None:
        self._last_seen = self._clock.unsafe_monotonic()
        self._awaiting = False

    def reset(self) -> None:
        self.on_frame()
        self.latch.unsafe_close()

    def tick(self, write_ping: Effect[None, Any]) -> Effect[None, Any]:
        def body() -> Effect[None, Any]:
            if self._awaiting and self._clock.unsafe_monotonic() - self._last_seen > self._timeout:
                return self.latch.open().as_void()
            self._awaiting = True
            return write_ping

        return suspend(body)


@dataclass(frozen=True, slots=True)
class SocketOptions:
    """How a socket protocol keeps its connection: a ping every
    ``ping_interval`` (dropping the connection when nothing came back
    within ``ping_timeout``), reconnecting by ``retry_policy``.
    ``retry_transient_errors`` keeps requests waiting while the socket
    cannot open (reporting each error to ``on_transient_error``)."""

    ping_interval: Duration = 5.0
    ping_timeout: Duration | None = None
    retry_transient_errors: bool = False
    retry_policy: Schedule[Any, Any, Never, Never] | None = None
    on_transient_error: Callable[[RpcClientError], Effect[None]] | None = None
    on_ping_timeout: Effect[None] | None = None


class _SocketClient:
    __slots__ = (
        "_current_error",
        "_ids",
        "_options",
        "_parser",
        "_pinger",
        "_requests",
        "_serialization",
        "_write",
        "_writer",
    )

    def __init__(
        self,
        serialization: RpcSerializationService,
        *,
        write: WriteTo,
        ids: set[int],
        writer: Writer,
        pinger: _Pinger,
        options: SocketOptions,
    ) -> None:
        self._serialization = serialization
        self._write = write
        self._ids = ids
        self._writer = writer
        self._pinger = pinger
        self._options = options
        self._parser: Parser = serialization.make_unsafe()
        self._requests: dict[object, int] = {}
        self._current_error: RpcClientError | None = None

    def write_ping(self) -> Effect[None, Any]:
        return suspend(lambda: self._write_frame(self._parser.encode(PING)))

    def _write_frame(self, frame: Frame | None) -> Effect[None, Any]:
        return _VOID if frame is None else self._writer.write(frame)

    def _broadcast(self, response: Message) -> Effect[None]:
        @gen
        def deliver():
            for client_id in list(self._ids):
                yield from self._write(client_id, response)

        if response.get("_tag") not in ("Defect", "ClientProtocolError"):
            return deliver
        self._requests.clear()
        return deliver.uninterruptible()

    def broadcast_error(self, error: RpcClientError) -> Effect[None]:
        self._current_error = error
        return self._broadcast({"_tag": "ClientProtocolError", "error": error})

    def _process(self, data: Frame) -> Effect[None]:
        try:
            responses = cast("list[Message]", self._parser.decode(data))
        except Exception as cause:
            return self._broadcast(
                {"_tag": "ClientProtocolError", "error": _defect("Error decoding message", cause)}
            )
        if not responses:
            return _VOID
        self._pinger.on_frame()

        @gen
        def each():
            for response in responses:
                yield from self._route(response)

        return each

    def _route(self, response: Message) -> Effect[None]:
        if response.get("_tag") == "Pong":
            return _VOID
        if "requestId" in response:
            request_id = response["requestId"]
            client_id = self._requests.get(_key(request_id))
            if client_id is not None:
                if response.get("_tag") == "Exit":
                    self._requests.pop(_key(request_id), None)
                return self._write(client_id, response)
        return self._broadcast(response)

    def connection(
        self, socket: SocketService, hooks: ConnectionHooksService | None
    ) -> Effect[Never, SocketError, Any]:
        """One connection: read until the socket fails or a ping times out.
        ``hooks`` run when it connects, and when it ends, connected or not."""

        def body() -> Effect[Never, SocketError, Any]:
            self._parser = self._serialization.make_unsafe()
            self._pinger.reset()
            connected: list[bool] = []

            @gen
            def read():
                reader = yield from socket.reader
                self._current_error = None
                connected.append(True)
                if hooks is not None:
                    yield from hooks.on_connect
                while True:
                    frames = yield from reader.pull
                    for frame in frames:
                        yield from self._process(frame)

            on_timeout = self._options.on_ping_timeout or _VOID

            @gen
            def timed_out():
                yield from scoped(read).race_first(self._pinger.latch.wait())
                if connected:
                    yield from on_timeout.ignore_cause()
                return (
                    yield from fail(SocketErrorClass(SocketReadError(RuntimeError("ping timeout"))))
                )

            return timed_out

        connection = suspend(body)
        return connection if hooks is None else connection.ensuring(hooks.on_disconnect)

    def on_cause(self, cause: Cause[SocketError]) -> Effect[None]:
        """Tell the clients how the connection ended: its socket error, or
        an ``RpcClientDefect`` for a defect or an interruption."""
        found = cause.find_error()
        if not isinstance(found, Ok):
            defect = _defect("Unknown socket error", cause.squash())
            return self.broadcast_error(defect)
        error = found.value
        rpc_error = RpcClientError(error.reason)
        if self._options.retry_transient_errors and isinstance(error.reason, SocketOpenError):
            hook = self._options.on_transient_error
            return _VOID if hook is None else hook(rpc_error).ignore_cause()
        return self.broadcast_error(rpc_error)

    def send(self, client_id: int, message: Message) -> Effect[None, RpcClientError]:
        def body() -> Effect[None, RpcClientError]:
            if self._current_error is not None:
                return fail(self._current_error)
            tag = message.get("_tag")
            if tag == "Interrupt":
                request_id = message["requestId"]
                self._requests.pop(_key(request_id), None)
            written = suspend(lambda: self._write_frame(self._parser.encode(message))).or_die()
            if tag != "Request":
                return written
            key = _key(message["id"])
            self._requests[key] = client_id
            return written.on_error(lambda _: succeed(self._requests.pop(key, None)).as_void())

        return suspend(body)


def make_protocol_socket(
    options: SocketOptions | None = None,
) -> Effect[ClientProtocolService, Never, Scope | RpcSerialization | Socket]:
    """A client protocol over the ``Socket`` in the context, reconnecting
    when it drops."""
    resolved = options or SocketOptions()

    def parts(write: WriteTo, ids: set[int]) -> Effect[ClientProtocolParts, Never, Any]:
        @gen
        def make():
            socket = yield from Socket()
            serialization = yield from RpcSerialization()
            hooks = yield from ConnectionHooks()
            clock = yield from Clock()
            writer = yield from socket.writer
            interval = to_seconds(resolved.ping_interval)
            timeout = (
                interval if resolved.ping_timeout is None else to_seconds(resolved.ping_timeout)
            )
            pinger = _Pinger(clock, timeout)
            client = _SocketClient(
                serialization, write=write, ids=ids, writer=writer, pinger=pinger, options=resolved
            )
            yield from fork_scoped(
                pinger.tick(client.write_ping()).delay(interval).ignore().forever().interruptible()
            )
            policy = resolved.retry_policy or default_retry_policy()
            connection = client.connection(socket, hooks).tap_cause(client.on_cause)
            yield from fork_scoped(
                connection.retry(policy).catch_all(
                    lambda error: client.broadcast_error(RpcClientError(error.reason))
                )
            )
            return ClientProtocolParts(client.send, True, serialization.codec_for)

        return make

    return cast(
        "Effect[ClientProtocolService, Never, Scope | RpcSerialization | Socket]",
        with_run_client(parts),
    )


__all__ = [
    "ConnectionHooks",
    "ConnectionHooksService",
    "SocketOptions",
    "default_retry_policy",
    "make_protocol_socket",
]
