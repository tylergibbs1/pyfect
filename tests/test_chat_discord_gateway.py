"""Port of Effect's ``packages/chat/discord/test/gateway.test.ts``: the shard
over a websocket the test drives, with ``layer_dispatch_hook`` and storage
that outlives a host behind it. Closing the scope stops the host, as an
eviction does."""

from __future__ import annotations

from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass
from typing import Any

from _discord_fake import Fake, discord_layer, events

import pyfect as fx
from pyfect import layer, testing
from pyfect._core import Effect
from pyfect.chat.chat_event import ChatEvent, MessageCreated
from pyfect.chat.chat_handler import ChatHandler, NotAccepted
from pyfect.chat.chat_handler import Service as HandlerService
from pyfect.chat.discord import discord_chat, discord_gateway
from pyfect.chat.discord.discord_gateway import (
    DiscordWs,
    Reconnect,
    ShardState,
    ShardStateStore,
    ShardStore,
    WsConnection,
)
from pyfect.queue import Queue
from pyfect.redacted import make as redacted
from pyfect.scope import Scope

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]

type Storage = dict[str, ShardState]
"""Storage that outlives a host: what a Durable Object keeps between evictions."""


class _Store:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def for_shard(self, shard: tuple[int, int]) -> ShardStore:
        key = f"{shard[0]}/{shard[1]}"
        return ShardStore(
            get=fx.sync(lambda: self.storage.get(key)),
            set=lambda state: fx.sync(lambda: self.storage.__setitem__(key, state)),
            clear=fx.sync(lambda: self.storage.pop(key, None)).as_void(),
        )


def stored(storage: Storage) -> ShardState | None:
    return storage.get("0/1")


HELLO = {"op": 10, "d": {"heartbeat_interval": 41_250}}
READY = {
    "op": 0,
    "t": "READY",
    "s": 1,
    "d": {"session_id": "session-1", "resume_gateway_url": "wss://resume.example"},
}
CREATED = events("channel-message")[0]


def message(s: int) -> dict[str, Any]:
    return {"op": 0, "t": CREATED["t"], "s": s, "d": CREATED["d"]}


def sequence(storage: Storage) -> int | None:
    state = stored(storage)
    return None if state is None else state.sequence


def until(done: Callable[[], bool]) -> Effect[None]:
    """Lets the shard's fibers run until ``done``."""

    @fx.gen
    def run() -> Gen[None]:
        for _ in range(1000):
            if done():
                break
            yield from fx.yield_now()
        assert done(), "the shard did not get there"

    return run


@dataclass
class Host:
    receive: Callable[[Mapping[str, Any]], Effect[bool]]
    written: list[Mapping[str, object] | Reconnect]
    on_connecting: list[Effect[None]]

    def sent(self, op: int) -> list[Any]:
        """What the shard wrote with ``op``: 2 is IDENTIFY and 6 RESUME."""
        return [
            payload["d"]
            for payload in self.written
            if not isinstance(payload, Reconnect) and payload.get("op") == op
        ]

    def reconnects(self) -> int:
        return sum(1 for payload in self.written if isinstance(payload, Reconnect))

    @property
    def reopened(self) -> Effect[None]:
        """The socket opened again, as the websocket does after it drops the connection."""
        return fx.suspend(lambda: self.on_connecting[-1])


class _Ws:
    def __init__(self, inbound: Queue[Any], host: Host) -> None:
        self.inbound = inbound
        self.host = host

    def connect(self, url: str, on_connecting: Effect[None]) -> Effect[WsConnection, Any, Scope]:
        def make() -> WsConnection:
            self.host.on_connecting.append(on_connecting)
            return WsConnection(
                take=self.inbound.take(),
                set_url=lambda _url: fx.void,
                write=lambda sent: fx.sync(lambda: self.host.written.append(sent)),
            )

        return fx.sync(make)


def host(
    storage: Storage, handle: Callable[[ChatEvent], Effect[None, NotAccepted]]
) -> Effect[Host, Any, Scope]:
    """One host: the shard over a socket the test drives, with
    ``layer_dispatch_hook`` and ``storage`` behind it."""

    @fx.gen
    def build() -> Gen[Host]:
        inbound: Queue[Any] = yield from Queue[Any].unbounded()
        found = Host(receive=inbound.offer, written=[], on_connecting=[])
        socket = layer.succeed(DiscordWs, _Ws(inbound, found))
        hook = discord_chat.layer_dispatch_hook().pipe(
            layer.provide(
                layer.merge(
                    layer.succeed(ChatHandler, HandlerService(handle)), discord_layer(Fake({}))
                )
            )
        )
        gateway = discord_gateway.layer(token=redacted("token")).pipe(
            layer.provide(
                layer.merge(socket, layer.succeed(ShardStateStore, _Store(storage)), hook)
            )
        )
        yield from gateway.build()
        return found

    return build


@testing.effect
def test_a_host_built_again_resumes_the_stored_session():
    """layerDispatchHook / a host built again resumes the stored session, having handled each event
    before its sequence was stored"""
    storage: Storage = {}
    seen: list[tuple[str, int | None]] = []

    def handle(event: ChatEvent) -> Effect[None]:
        def record() -> None:
            if isinstance(event, MessageCreated):
                state = stored(storage)
                seen.append((event.message.id, None if state is None else state.sequence))

        return fx.sync(record)

    @fx.gen
    def first_host() -> Gen[None]:
        first = yield from host(storage, handle)
        yield from first.receive(HELLO)
        yield from until(lambda: len(first.sent(2)) == 1)
        assert first.sent(6) == []
        yield from first.receive(READY)
        yield from first.receive(message(2))
        yield from until(lambda: sequence(storage) == 2)
        assert seen == [(CREATED["d"]["id"], 1)]

    @fx.gen
    def second_host() -> Gen[None]:
        second = yield from host(storage, handle)
        yield from second.receive(HELLO)
        yield from until(lambda: len(second.sent(6)) == 1)
        assert second.sent(6) == [{"token": "token", "session_id": "session-1", "seq": 2}]
        assert second.sent(2) == []

    @fx.gen
    def program() -> Gen[None]:
        yield from fx.scoped(first_host)
        assert stored(storage) == ShardState(
            session_id="session-1", resume_url="wss://resume.example", sequence=2
        )
        yield from fx.scoped(second_host)

    return program


@testing.effect
def test_an_event_refused_with_not_accepted_is_not_stored_and_comes_back_with_the_resume():
    """layerDispatchHook / an event refused with NotAccepted is not stored and comes back with the
    RESUME"""
    storage: Storage = {}
    attempts = [0]

    def handle(_event: ChatEvent) -> Effect[None, NotAccepted]:
        def run() -> Effect[None, NotAccepted]:
            attempts[0] += 1
            return fx.fail(NotAccepted()) if attempts[0] == 1 else fx.void

        return fx.suspend(run)

    @fx.gen
    def program() -> Gen[None]:
        gateway = yield from host(storage, handle)
        yield from gateway.receive(HELLO)
        yield from gateway.receive(READY)
        yield from until(lambda: sequence(storage) == 1)
        yield from gateway.receive(message(2))
        yield from until(lambda: gateway.reconnects() == 1)
        assert attempts[0] == 1
        assert sequence(storage) == 1
        # The shard waits a second after the first failure before it resumes.
        yield from gateway.reopened
        yield from gateway.receive(HELLO)
        yield from testing.adjust("1 second")
        yield from until(lambda: len(gateway.sent(6)) == 1)
        assert gateway.sent(6) == [{"token": "token", "session_id": "session-1", "seq": 1}]
        # Discord replays what came after sequence 1.
        yield from gateway.receive(message(2))
        yield from until(lambda: sequence(storage) == 2)
        assert attempts[0] == 2
        assert gateway.reconnects() == 1

    return fx.scoped(program)


@testing.effect
def test_a_handler_defect_is_logged_and_the_event_dropped_so_the_events_after_it_still_arrive():
    """layerDispatchHook / a handler defect is logged and the event dropped, so the events after it
    still arrive"""
    storage: Storage = {}
    handled = [0]

    def handle(_event: ChatEvent) -> Effect[None]:
        def run() -> Effect[None]:
            handled[0] += 1
            return fx.die(RuntimeError("bug")) if handled[0] == 1 else fx.void

        return fx.suspend(run)

    @fx.gen
    def program() -> Gen[None]:
        gateway = yield from host(storage, handle)
        yield from gateway.receive(HELLO)
        yield from gateway.receive(READY)
        yield from gateway.receive(message(2))
        yield from gateway.receive(message(3))
        yield from until(lambda: sequence(storage) == 3)
        assert handled[0] == 2
        assert gateway.reconnects() == 0

    return fx.scoped(program)
