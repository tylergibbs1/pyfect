"""The MCP server over an RPC server transport (Effect's ``McpServer.run``
on an ``RpcServer.Protocol``).

Each client of the protocol is a session, keyed by the protocol's client id.
Its messages arrive as RPC messages: a ``Request`` (``tag`` the method,
``payload`` the params, ``isNotification`` for a notification), an ``Exit``
answering a reverse request, ``Interrupt``, ``Ping``, ``Ack`` and ``Eof``.
What the session writes goes back as RPC messages: an ``Exit`` per answer
and a ``Request`` per notification or reverse request, each client's in
order. A protocol without ``supports_notifications`` serves no
subscriptions and gets no notifications; one reporting ``client_ids`` has
the sessions of clients that left forgotten when a notification goes out.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass, field
from typing import Any, Never, cast

from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect._json_value import JsonValue
from pyfect.ai._mcp.core import McpServer, McpServerService
from pyfect.ai._mcp.dispatch import Connection, ServerInfo
from pyfect.ai._mcp.failure import INTERNAL_ERROR
from pyfect.ai.mcp_protocol import Registry
from pyfect.ai.mcp_schema import JsonObject
from pyfect.deferred import Deferred
from pyfect.effect import gen, succeed, suspend
from pyfect.logger import CurrentLogLevel, Severity
from pyfect.rpc.server import ServerProtocol, ServerProtocolService
from pyfect.rpc.server._protocol import Message
from pyfect.scope import scoped

_VOID: Effect[None] = succeed(None)
_PONG: Message = {"_tag": "Pong"}


def _request(message: Message) -> JsonObject:
    """An RPC ``Request`` as the JSON-RPC request or notification it carries."""
    request: JsonObject = {"jsonrpc": "2.0", "method": message.get("tag")}
    if not message.get("isNotification"):
        request["id"] = message.get("id")
    payload = message.get("payload")
    if payload is not None:
        request["params"] = payload
    return request


def _reply(message: Message) -> JsonObject:
    """A client's RPC ``Exit`` as the JSON-RPC response to a reverse request."""
    exit = cast("Mapping[str, Any]", message.get("exit") or {})
    reply: JsonObject = {"jsonrpc": "2.0", "id": message.get("requestId")}
    if exit.get("_tag") == "Success":
        reply["result"] = exit.get("value")
        return reply
    cause = cast("Sequence[Mapping[str, Any]]", exit.get("cause") or ())
    failure = next((r for r in cause if r.get("_tag") == "Fail"), None)
    error = INTERNAL_ERROR if failure is None else failure.get("error")
    reply["error"] = cast("JsonValue", error)
    return reply


def _outbound(message: JsonObject) -> Message:
    """A JSON-RPC message of the session as the RPC message carrying it."""
    if "method" in message:
        request: dict[str, Any] = {
            "_tag": "Request",
            "id": message.get("id", ""),
            "tag": message["method"],
            "payload": message.get("params", {}),
            "headers": [],
        }
        if "id" not in message:
            request["isNotification"] = True
        return request
    if "error" in message:
        error = cast("Mapping[str, Any]", message["error"])
        # An answer carrying its serialized cause (``failure``) sends the cause.
        cause = (
            error["data"] if error.get("_tag") == "Cause" else [{"_tag": "Fail", "error": error}]
        )
        exit: Message = {"_tag": "Failure", "cause": cause}
    else:
        exit = {"_tag": "Success", "value": message.get("result")}
    return {"_tag": "Exit", "requestId": message.get("id"), "exit": exit}


@dataclass(eq=False)
class _Client:
    """One client of the protocol: its session and the tail of its writes."""

    connection: Connection = field(init=False)
    tail: Deferred[None] | None = None


@dataclass(eq=False)
class _Transport:
    protocol: ServerProtocolService
    server: McpServerService
    info: ServerInfo
    registry: Registry
    level: Severity
    clients: dict[int, _Client] = field(default_factory=dict[int, _Client])

    def write(self, client: _Client, message: JsonObject) -> Effect[None]:
        """Write ``message`` after the client's earlier writes (Effect's
        notification tails), so one client that stopped reading holds up only
        itself, and its messages keep their order."""
        if (
            not self.protocol.supports_notifications
            and "method" in message
            and "id" not in message
            and message["method"] != "notifications/cancelled"
        ):
            return _VOID

        def ordered() -> Effect[None]:
            previous, done = client.tail, Deferred[None]()
            client.tail = done
            sent = self.protocol.send(client.connection.client_id, _outbound(message))
            waited = sent if previous is None else previous.wait().and_then(sent)
            return waited.ensuring(done.succeed(None).as_void())

        return suspend(ordered)

    def client(self, client_id: int) -> _Client:
        found = self.clients.get(client_id)
        if found is not None:
            return found
        created = _Client()

        def write(message: JsonObject) -> Effect[None]:
            return self.write(created, message)

        created.connection = Connection(
            self.server,
            self.info,
            self.registry,
            client_id,
            "custom",
            broadcast=write,
            default_log_level=self.level,
            supports_subscriptions=self.protocol.supports_notifications,
        )
        self.clients[client_id] = created
        self.server.connect(_Peer(self, created))
        return created

    def forget(self, client_id: int) -> Connection | None:
        """Drop the client's session; its requests still running go on."""
        found = self.clients.pop(client_id, None)
        if found is None:
            return None
        self.server.disconnect(client_id)
        return found.connection

    def receive(self, client_id: int, message: Message) -> Effect[None]:
        match message.get("_tag"):
            case "Request":
                connection = self.client(client_id).connection
                return connection.dispatch(_request(message), connection.broadcast)
            case "Exit" | "Interrupt":
                return self._to_session(client_id, message)
            case "Ping":
                return self.protocol.send(client_id, _PONG)
            case "Eof":
                return self.ended(client_id)
            case _:
                return _VOID

    def _to_session(self, client_id: int, message: Message) -> Effect[None]:
        """A reverse request's answer, or an RPC interrupt (a cancellation),
        for the client's session; a client without one has nothing to match."""
        client = self.clients.get(client_id)
        if client is None:
            return _VOID
        if message["_tag"] == "Exit":
            body = _reply(message)
        else:
            cancelled = {"requestId": message.get("requestId")}
            body = {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": cancelled}
        return client.connection.dispatch(body, client.connection.broadcast)

    def ended(self, client_id: int) -> Effect[None]:
        """The client sent its last message: its session ends now, and the
        protocol ends it once its requests are answered."""
        connection = self.forget(client_id)
        if connection is None:
            return self.protocol.end(client_id)
        return connection.drain().and_then(self.protocol.end(client_id)).fork_daemon().as_void()

    def left(self, client_id: int) -> Effect[None]:
        connection = self.forget(client_id)
        return _VOID if connection is None else connection.close()

    def close_all(self) -> Effect[None]:
        return suspend(lambda: for_each(list(self.clients), self.left)).as_void()


@dataclass(frozen=True, slots=True, eq=False)
class _Peer:
    """The server's view of a client: a notification first forgets the
    sessions of clients the protocol no longer reports."""

    transport: _Transport
    client: _Client

    @property
    def client_id(self) -> int:
        return self.client.connection.client_id

    def deliver(self, method: str, params: JsonObject, revision: int | None = None) -> Effect[None]:
        transport = self.transport
        client_ids = transport.protocol.client_ids

        def connected(ids: Set[int]) -> Effect[None]:
            if self.client_id not in ids:
                transport.forget(self.client_id)
                return _VOID
            if not transport.protocol.supports_notifications:
                return _VOID
            return self.client.connection.deliver(method, params, revision)

        if client_ids is None:
            return connected({self.client_id})
        return client_ids.flat_map(connected)


def serve(info: ServerInfo, registry: Registry) -> Effect[Never, Never, McpServer | ServerProtocol]:
    """Serve every client of the ``ServerProtocol`` in the context."""

    @gen
    def run():
        protocol = yield from ServerProtocol()
        transport = _Transport(
            protocol,
            (yield from McpServer()),
            info,
            registry,
            (yield from CurrentLogLevel()),
        )
        yield from (protocol.disconnects.take().flat_map(transport.left).forever().fork_scoped())
        # As Effect's RpcServer: the requests still running end with the server.
        return (yield from protocol.run(transport.receive).ensuring(transport.close_all()))

    return cast("Any", scoped(run))


__all__ = ["serve"]
