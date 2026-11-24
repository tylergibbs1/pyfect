"""Discord's Gateway, one shard over a websocket (in Effect, dfx's
``DiscordGateway``): it identifies or resumes, heartbeats, keeps the session
in a ``ShardStateStore`` and hands each dispatch to the ``DispatchHook``
before storing its sequence, then to every subscriber of ``dispatch``.

- The websocket is ``DiscordWs``; ``layer_ws`` builds it on a
  ``WebSocketConstructor`` (``pyfect.socket.ws``, extra ``websockets``). It
  reconnects by itself, and a ``RECONNECT`` written to it drops the
  connection with close code 4000, which keeps the session for a RESUME.
- A host built again with the same ``ShardStateStore`` sends RESUME, not
  IDENTIFY, and Discord sends what it missed.
- A hook that fails or dies drops the connection without storing the
  dispatch's sequence, so the RESUME brings it back: after 1 second,
  doubling with every failure in a row up to 2 minutes. Whatever was already
  read from a dropped connection is skipped, unstored, until the next HELLO,
  and comes back with the RESUME too. A refused ``READY`` stores no session.
- Op 7 (reconnect) resumes; op 9 (invalid session) that can't be resumed
  clears the stored session and identifies again. A heartbeat Discord did
  not acknowledge before the next one drops the connection.
- Inbound frames are untrusted: one that is not a JSON object, or nests
  deeper than 64, is dropped.
"""

from __future__ import annotations

import platform as _platform
from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass, replace
from typing import Any, Never, Protocol, cast

import pyfect as fx
from pyfect import clock as _clock
from pyfect import random as _random
from pyfect import stream as _stream
from pyfect._core import Effect, _call_user
from pyfect._fiber import Fiber
from pyfect._json_text import stringify
from pyfect._json_value import JsonValue
from pyfect.chat.discord import _json
from pyfect.context import Reference, Tag
from pyfect.duration import Duration, millis, minutes, seconds, zero
from pyfect.exit import Success
from pyfect.layer import Layer
from pyfect.layer import effect as _layer_effect
from pyfect.pubsub import PubSub
from pyfect.queue import Queue
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value
from pyfect.scope import Scope
from pyfect.socket import CloseEvent
from pyfect.socket._socket import reader_string
from pyfect.socket._web_socket import WebSocketConstructor, make_web_socket
from pyfect.stream import Stream

DEFAULT_URL = "wss://gateway.discord.gg"
"""Discord's gateway; ``/?v=10&encoding=json`` is added to it, and to the
resume URL Discord gives."""

GUILDS = 1 << 0
GUILD_MESSAGES = 1 << 9
GUILD_MESSAGE_REACTIONS = 1 << 10
DIRECT_MESSAGES = 1 << 12
DIRECT_MESSAGE_REACTIONS = 1 << 13
MESSAGE_CONTENT = 1 << 15
"""A privileged intent: switch it on for the application in the developer portal."""

DEFAULT_INTENTS = (
    GUILDS
    | GUILD_MESSAGES
    | GUILD_MESSAGE_REACTIONS
    | DIRECT_MESSAGES
    | DIRECT_MESSAGE_REACTIONS
    | MESSAGE_CONTENT
)
"""The intents the chat adapter reads."""

_DEFAULT_HEARTBEAT = millis(41_250)
_FIRST_BACKOFF = seconds(1)
_MAX_BACKOFF = minutes(2)
_RECONNECT_CLOSE = 4000
"""A close code other than 1000 and 1001, so Discord keeps the session."""


@dataclass(frozen=True, slots=True)
class GatewayDispatch:
    """One dispatch (op 0): its event name ``t``, its sequence ``s`` and its
    data ``d``, undecoded."""

    t: str
    d: JsonValue
    s: int | None = None


@dataclass(frozen=True, slots=True)
class ShardState:
    """What a shard needs to resume: the session, where to resume it and the
    sequence of the last dispatch handled."""

    session_id: str
    resume_url: str
    sequence: int | None


@dataclass(frozen=True, slots=True)
class ShardStore:
    """One shard's state, in storage the consumer chooses."""

    get: Effect[ShardState | None]
    set: Callable[[ShardState], Effect[None]]
    clear: Effect[None]


class ShardStateStoreService(Protocol):
    def for_shard(self, shard: tuple[int, int]) -> ShardStore:
        """The store of shard ``(id, count)``."""
        ...


class ShardStateStore(Tag[ShardStateStoreService], key="@effect/chat-discord/ShardStateStore"):
    """Where shards keep their sessions. Without one, a shard keeps its own
    in memory, so a host built again identifies afresh."""


class MemoryStateStore:
    """A ``ShardStateStoreService`` in a dict, for one process."""

    def __init__(self) -> None:
        self.states: dict[tuple[int, int], ShardState] = {}

    def for_shard(self, shard: tuple[int, int]) -> ShardStore:
        return ShardStore(
            get=fx.sync(lambda: self.states.get(shard)),
            set=lambda state: fx.sync(lambda: self.states.__setitem__(shard, state)),
            clear=fx.sync(lambda: self.states.pop(shard, None)).as_void(),
        )


type Hook = Callable[[GatewayDispatch], Effect[None, object]]


class DispatchHook(Reference[Hook | None], key="@effect/chat-discord/DispatchHook"):
    """Runs on each dispatch before its sequence is stored; a failure drops
    the connection so the RESUME replays the dispatch. None by default."""

    @classmethod
    def default(cls) -> Hook | None:
        return None


class Reconnect:
    """Written to a ``WsConnection``: drops the connection and opens another."""

    __slots__ = ()


RECONNECT = Reconnect()

type GatewaySend = Mapping[str, object]


@dataclass(frozen=True, slots=True)
class WsConnection:
    """A websocket that reconnects by itself. ``take`` gives each inbound
    payload, a JSON object; ``set_url`` changes where the next connection
    goes; ``write`` sends a payload, or ``RECONNECT``."""

    take: Effect[_json.JsonObject]
    set_url: Callable[[str], Effect[None]]
    write: Callable[[GatewaySend | Reconnect], Effect[None]]


class DiscordWsService(Protocol):
    def connect(self, url: str, on_connecting: Effect[None]) -> Effect[WsConnection, Never, Scope]:
        """Connects to ``url`` until the scope closes, running ``on_connecting``
        before each connection, the first and every reconnection."""
        ...


class DiscordWs(Tag[DiscordWsService], key="@effect/chat-discord/DiscordWs"):
    """The gateway's websocket."""


def with_query(url: str) -> str:
    """A gateway URL with the version and encoding the shard speaks."""
    base = url.split("?", 1)[0].rstrip("/")
    return f"{base}/?v=10&encoding=json"


# --- the websocket -------------------------------------------------------------------


class _Dropped(Exception):
    pass


class _SocketWs:
    """``DiscordWsService`` on a ``WebSocketConstructor``."""

    def __init__(self, construct: Any) -> None:
        self._construct = construct

    def connect(self, url: str, on_connecting: Effect[None]) -> Effect[WsConnection, Never, Scope]:
        construct = self._construct

        @fx.gen
        def build() -> Generator[Effect[Any, Never, Any], Any, WsConnection]:
            inbound: Queue[_json.JsonObject] = yield from Queue[_json.JsonObject].unbounded()
            outbound: Queue[str | Reconnect] = yield from Queue[str | Reconnect].unbounded()
            current = [url]
            backoff = [_FIRST_BACKOFF]
            socket = yield from make_web_socket(fx.sync(lambda: current[0])).pipe(
                fx.provide_service(WebSocketConstructor, construct)
            )

            @fx.gen
            def one() -> Generator[Effect[Any, Any, Any], Any]:
                yield from on_connecting
                pull = yield from reader_string(socket)
                writer = yield from socket.writer

                def received(texts: tuple[str, ...]) -> Effect[None]:
                    backoff[0] = _FIRST_BACKOFF
                    found = [_json.as_object(_json.parse(text)) for text in texts]
                    return fx.for_each(
                        [obj for obj in found if obj is not None], inbound.offer, discard=True
                    )

                def send(item: str | Reconnect) -> Effect[None, Any]:
                    if isinstance(item, Reconnect):
                        return writer.write(CloseEvent(_RECONNECT_CLOSE)).and_then(
                            fx.fail(_Dropped())
                        )
                    return writer.write(item)

                reading = pull.flat_map(received).forever()
                writing = outbound.take().flat_map(send).forever()
                yield from reading.race_first(writing)

            def retry(error: object) -> Effect[None]:
                if isinstance(error, _Dropped):
                    return fx.void
                wait = backoff[0]
                backoff[0] = min(wait.times(2), minutes(1))
                return fx.log_debug("discord gateway: connection lost", error).and_then(
                    _clock.sleep(wait)
                )

            yield from fx.scoped(one).catch_all(retry).forever().fork_scoped()

            def write(item: GatewaySend | Reconnect) -> Effect[None]:
                return outbound.offer(
                    item if isinstance(item, Reconnect) else stringify(item)
                ).as_void()

            def set_url(next_url: str) -> Effect[None]:
                return fx.sync(lambda: current.__setitem__(0, next_url))

            return WsConnection(take=inbound.take(), set_url=set_url, write=write)

        return build


layer_ws: Layer[DiscordWs, Never, WebSocketConstructor] = _layer_effect(
    DiscordWs,
    WebSocketConstructor().map(lambda construct: cast("DiscordWsService", _SocketWs(construct))),
)
"""``DiscordWs`` on the ``WebSocketConstructor`` in context."""


# --- the shard -----------------------------------------------------------------------


class DiscordGatewayService:
    """The gateway's dispatches."""

    def __init__(self, pubsub: PubSub[GatewayDispatch]) -> None:
        self._pubsub = pubsub

    @property
    def dispatch(self) -> Stream[GatewayDispatch]:
        """Every dispatch, after its sequence is stored."""
        return _stream.from_pubsub(self._pubsub)

    def from_dispatch(self, t: str) -> Stream[GatewayDispatch]:
        """The dispatches named ``t``."""
        return self.dispatch.filter(lambda found: found.t == t)


class DiscordGateway(Tag[DiscordGatewayService], key="@effect/chat-discord/DiscordGateway"):
    """The gateway's dispatches; ``discord_gateway.layer`` provides it."""


def _sequence(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _heartbeat_interval(d: object) -> Duration:
    value = _json.as_object(d)
    found = None if value is None else value.get("heartbeat_interval")
    if _json.is_number(found) and 1_000 <= cast("float", found) <= 600_000:
        return millis(cast("float", found))
    return _DEFAULT_HEARTBEAT


@dataclass(kw_only=True)
class _Shard:
    token: Redacted[str]
    intents: int
    shard: tuple[int, int]
    url: str
    store: ShardStore
    hook: Hook | None
    pubsub: PubSub[GatewayDispatch]
    conn: WsConnection | None = None
    acked: bool = True
    received: int | None = None
    backoff: Duration = zero
    heartbeat: Fiber[Any, Any] | None = None
    connecting: bool = True
    """From a dropped connection until the next HELLO: what is still queued
    from the old socket is skipped, unstored, and the RESUME replays it."""

    def _write(self, item: GatewaySend | Reconnect) -> Effect[None]:
        assert self.conn is not None
        return self.conn.write(item)

    def _reconnect(self) -> Effect[None]:
        def run() -> Effect[None]:
            self.connecting = True
            return self._write(RECONNECT)

        return fx.suspend(run)

    def on_connecting(self) -> None:
        self.connecting = True

    def _drop(self) -> Effect[None]:
        self.backoff = (
            _FIRST_BACKOFF if self.backoff == zero else min(self.backoff.times(2), _MAX_BACKOFF)
        )
        return self._reconnect()

    def _get(self) -> Effect[ShardState | None]:
        return _call_user(lambda: self.store.get)

    def _set(self, state: ShardState) -> Effect[None]:
        return _call_user(self.store.set, state)

    def _beats(self, interval: Duration) -> Effect[Never]:
        def beat() -> Effect[None]:
            if self.connecting:
                return fx.void
            if not self.acked:
                # Discord did not answer the last one: the connection is a zombie.
                self.acked = True
                return self._reconnect()
            self.acked = False
            return self._write({"op": 1, "d": self.received})

        first = _random.next().flat_map(
            lambda jitter: _clock.sleep(millis(interval.to_millis() * jitter))
        )
        return first.and_then(fx.suspend(beat).and_then(_clock.sleep(interval)).forever())

    def _hello(self, d: object) -> Effect[None]:
        @fx.gen
        def run() -> Generator[Effect[Any, Never, Any], Any]:
            if self.heartbeat is not None:
                yield from self.heartbeat.interrupt()
            self.acked = True
            self.heartbeat = yield from self._beats(_heartbeat_interval(d)).fork_daemon()
            if self.backoff != zero:
                yield from _clock.sleep(self.backoff)
            state = yield from self._get()
            token = redacted_value(self.token)
            if state is not None and state.sequence is not None:
                yield from self._write(
                    {
                        "op": 6,
                        "d": {
                            "token": token,
                            "session_id": state.session_id,
                            "seq": state.sequence,
                        },
                    }
                )
                return
            yield from self._write(
                {
                    "op": 2,
                    "d": {
                        "token": token,
                        "intents": self.intents,
                        "properties": {
                            "os": _platform.system().lower(),
                            "browser": "pyfect",
                            "device": "pyfect",
                        },
                        "shard": list(self.shard),
                    },
                }
            )

        return run

    def _dispatch(self, payload: _json.JsonObject) -> Effect[None]:
        t = payload.get("t")
        if not isinstance(t, str):
            return fx.void
        s = _sequence(payload.get("s"))
        dispatch = GatewayDispatch(t=t, d=cast("JsonValue", payload.get("d")), s=s)

        @fx.gen
        def run() -> Generator[Effect[Any, Never, Any], Any]:
            if s is not None:
                self.received = s
            state = yield from self._get()
            resume_url: str | None = None
            if t == "READY":
                session = _json.string_field(dispatch.d, "session_id")
                resume = _json.string_field(dispatch.d, "resume_gateway_url")
                if session and resume and resume.startswith("wss://"):
                    # Stored once the hook took READY: a refused READY leaves no session.
                    state = ShardState(session_id=session, resume_url=resume, sequence=s)
                    resume_url = with_query(resume)
            if self.hook is not None:
                hook = self.hook
                exit = yield from _call_user(hook, dispatch).exit()
                if not isinstance(exit, Success):
                    # The sequence stays unstored: the RESUME replays the dispatch.
                    yield from fx.log_warning("discord gateway: the dispatch hook failed", exit)
                    yield from self._drop()
                    return
            self.backoff = zero
            if state is not None and (s is not None or resume_url is not None):
                yield from self._set(replace(state, sequence=s))
            if resume_url is not None:
                assert self.conn is not None
                yield from self.conn.set_url(resume_url)
            yield from self.pubsub.publish(dispatch)

        return run

    def on_payload(self, payload: _json.JsonObject) -> Effect[None]:  # noqa: PLR0911
        op = payload.get("op")
        if self.connecting and op != 10:
            # From the socket being dropped: nothing of it is handled or stored.
            return fx.void
        match op:
            case 0:
                return self._dispatch(payload)
            case 10:
                self.connecting = False
                return self._hello(payload.get("d"))
            case 11:
                return fx.sync(lambda: setattr(self, "acked", True))
            case 1:
                return self._write({"op": 1, "d": self.received})
            case 7:
                return self._reconnect()
            case 9:
                if payload.get("d") is True:
                    return self._reconnect()
                assert self.conn is not None
                conn = self.conn
                return (
                    _call_user(lambda: self.store.clear)
                    .and_then(conn.set_url(with_query(self.url)))
                    .and_then(self._reconnect())
                )
            case _:
                return fx.void


def layer(
    *,
    token: Redacted[str],
    intents: int = DEFAULT_INTENTS,
    shard: tuple[int, int] = (0, 1),
    url: str = DEFAULT_URL,
) -> Layer[DiscordGateway, Never, DiscordWs]:
    """One shard of the gateway, running until the layer's scope closes. It
    keeps its session in the ``ShardStateStore`` in context, or in memory,
    and runs the ``DispatchHook`` in context on each dispatch."""
    if not (0 <= shard[0] < shard[1]):
        raise ValueError(f"shard must be (id, count) with 0 <= id < count, got {shard!r}")

    @fx.gen
    def build() -> Generator[Effect[Any, Never, Any], Any, DiscordGatewayService]:
        ws = yield from DiscordWs()
        found = yield from fx.service_option(ShardStateStore)
        stores: ShardStateStoreService = MemoryStateStore() if found is None else found.value
        hook = yield from DispatchHook()
        store = yield from fx.sync(lambda: stores.for_shard(shard))
        pubsub: PubSub[GatewayDispatch] = yield from PubSub[GatewayDispatch].unbounded()
        state = _Shard(
            token=token,
            intents=intents,
            shard=shard,
            url=url,
            store=store,
            hook=hook,
            pubsub=pubsub,
        )
        stored = yield from state._get()  # pyright: ignore[reportPrivateUsage]
        start = with_query(url if stored is None else stored.resume_url)
        state.conn = yield from ws.connect(start, fx.sync(state.on_connecting))
        conn = state.conn
        yield from conn.take.flat_map(state.on_payload).forever().fork_scoped()

        def stop(_: object) -> Effect[None]:
            beating = state.heartbeat
            return fx.void if beating is None else beating.interrupt()

        yield from fx.add_finalizer(stop)
        return DiscordGatewayService(pubsub)

    return _layer_effect(DiscordGateway, build)


__all__ = [
    "DEFAULT_INTENTS",
    "DEFAULT_URL",
    "DIRECT_MESSAGES",
    "DIRECT_MESSAGE_REACTIONS",
    "GUILDS",
    "GUILD_MESSAGES",
    "GUILD_MESSAGE_REACTIONS",
    "MESSAGE_CONTENT",
    "RECONNECT",
    "DiscordGateway",
    "DiscordGatewayService",
    "DiscordWs",
    "DiscordWsService",
    "DispatchHook",
    "GatewayDispatch",
    "GatewaySend",
    "Hook",
    "MemoryStateStore",
    "Reconnect",
    "ShardState",
    "ShardStateStore",
    "ShardStateStoreService",
    "ShardStore",
    "WsConnection",
    "layer",
    "layer_ws",
    "with_query",
]
