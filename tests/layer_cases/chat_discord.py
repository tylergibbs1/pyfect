"""Layer cases of ``pyfect.chat.discord``: each run calls the scripted Discord
of ``tests/_discord_fake.py``, posts through ``Chat``, sends a signed request
to the interactions endpoint or drives a gateway shard over a fake socket."""

from __future__ import annotations

import json
import time
from typing import Any

from _discord_fake import SCRATCH, Fake
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import pyfect as fx
from layer_cases._case import Case
from pyfect import layer as L
from pyfect.chat import chat, chat_handler
from pyfect.chat import chat_interaction as ci
from pyfect.chat.chat import Chat
from pyfect.chat.discord import discord_chat, discord_gateway, discord_rest
from pyfect.chat.discord.discord_gateway import DiscordGateway, DiscordWs, WsConnection
from pyfect.chat.discord.discord_rest import DiscordRest
from pyfect.crypto.native import layer_signature
from pyfect.http import request as http_request
from pyfect.http import router
from pyfect.redacted import make as redacted
from pyfect.scope import Scope
from pyfect.socket import ws

type AnyEffect = fx.Effect[Any, Any, Any]
type AnyLayer = fx.Layer[Any, Any, Any]

_TOKEN = redacted("layer-case-token")
_KEY = Ed25519PrivateKey.generate()
_PUBLIC_KEY = _KEY.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
_POSTED = {
    "id": "1570700000000000001",
    "channel_id": SCRATCH,
    "type": 0,
    "content": "hello",
    "timestamp": "2026-05-12T10:00:00.000000+00:00",
    "author": {"id": "1564742987727118426", "username": "Janitor", "bot": True},
}


def _fake() -> Fake:
    return Fake({"createMessage": lambda *_: _POSTED})


def _discord() -> AnyLayer:
    """``DiscordChat`` on a fresh fake, with ``Chat`` and its ``Registry``."""
    return (
        discord_chat.layer(bot_token=_TOKEN)
        .pipe(L.provide_merge(chat.layer))
        .pipe(L.provide(_fake().layer))
    )


def _posts() -> AnyEffect:
    thread = discord_chat.thread(SCRATCH)
    return Chat().flat_map(lambda service: service.post(thread, markdown="hello")).as_void()


class _QuietWs:
    """A socket that connects and never receives anything."""

    def connect(self, url: str, on_connecting: AnyEffect) -> fx.Effect[WsConnection, Any, Scope]:
        return fx.succeed(
            WsConnection(take=fx.never, set_url=lambda _: fx.void, write=lambda _: fx.void)
        )


def _socket() -> AnyLayer:
    return L.succeed(DiscordWs, _QuietWs())


def _gateway() -> AnyLayer:
    return discord_gateway.layer(token=_TOKEN).pipe(L.provide(_socket()))


def _interactions_run(value: AnyLayer) -> AnyEffect:
    """One signed PING through the endpoint; dies unless it is a 200."""
    needs = L.merge(_discord(), layer_signature, ci.layer())

    @fx.gen
    def run():
        http = yield from router.in_memory_client(value.pipe(L.provide(needs)))
        body = json.dumps({"type": 1, "id": "1", "token": "t"}).encode()
        timestamp = str(int(time.time()))
        headers = {
            "x-signature-timestamp": timestamp,
            "x-signature-ed25519": _KEY.sign(timestamp.encode() + body).hex(),
        }
        sent = http_request.post("http://x").body_bytes(body, "application/json").body
        response = yield from http.post(
            "http://localhost/discord/interactions", body=sent, headers=headers
        )
        if response.status != 200:
            return (yield from fx.die(AssertionError(response.status)))
        return None

    return fx.scoped(run)


CASES: dict[str, Case] = {
    "pyfect.chat.discord.discord_rest.layer": Case(
        layer=lambda: discord_rest.layer(bot_token=_TOKEN),
        needs=lambda: _fake().layer,
        use=lambda: DiscordRest().flat_map(lambda rest: rest.get_my_user()).as_void(),
    ),
    "pyfect.chat.discord.discord_chat.layer": Case(
        layer=lambda: discord_chat.layer(bot_token=_TOKEN),
        needs=lambda: L.merge(chat.layer, _fake().layer),
        use=_posts,
    ),
    "pyfect.chat.discord.discord_chat.layer_interactions": Case(
        layer=lambda: discord_chat.layer_interactions(
            path="/discord/interactions", public_key=_PUBLIC_KEY
        ),
        run=_interactions_run,
    ),
    "pyfect.chat.discord.discord_chat.layer_gateway": Case(
        layer=discord_chat.layer_gateway,
        needs=lambda: L.merge(_gateway(), _discord(), chat_handler.layer(lambda _: fx.void)),
    ),
    "pyfect.chat.discord.discord_chat.layer_gateway_interactions": Case(
        layer=discord_chat.layer_gateway_interactions,
        needs=lambda: L.merge(_gateway(), _discord(), ci.layer()),
    ),
    "pyfect.chat.discord.discord_chat.layer_dispatch_hook": Case(
        layer=discord_chat.layer_dispatch_hook,
        needs=lambda: L.merge(_discord(), chat_handler.layer(lambda _: fx.void)),
    ),
    "pyfect.chat.discord.discord_gateway.layer": Case(
        layer=lambda: discord_gateway.layer(token=_TOKEN),
        needs=_socket,
        use=lambda: DiscordGateway().as_void(),
    ),
    "pyfect.chat.discord.discord_gateway.layer_ws": Case(
        layer=lambda: discord_gateway.layer_ws,
        needs=lambda: ws.layer_web_socket_constructor,
        use=lambda: DiscordWs().as_void(),
    ),
}

SKIPPED: dict[str, str] = {}
