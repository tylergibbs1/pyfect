import json
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import pyfect as fx
from pyfect import layer
from pyfect.chat import chat
from pyfect.chat import chat_interaction as ci
from pyfect.chat.discord import discord_chat
from pyfect.crypto.native import layer_signature
from pyfect.http import client, router
from pyfect.http import request as http_request
from pyfect.http import response as http_response
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redacted

# Discord signs each interaction with the application's key; this one stands in for it.
discord_key = Ed25519PrivateKey.generate()
PUBLIC_KEY = discord_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()

summarize = ci.command("summarize", description="Summarize this thread")


def on_summarize(command: ci.CommandInvoked) -> fx.Effect[ci.Respond]:
    return fx.succeed(ci.respond(markdown=f"On it, <@{command.user_id}>."))


interactions = (
    ci.group(summarize)
    .to_layer(summarize.handler(on_summarize))
    .pipe(layer.provide_merge(ci.layer()))
)

# The interactions endpoint, checking signatures with Signature, and the adapter.
app = (
    discord_chat.layer_interactions(path="/discord/interactions", public_key=PUBLIC_KEY)
    .pipe(layer.provide(layer.merge(interactions, layer_signature)))
    .pipe(layer.provide_merge(discord_chat.layer(bot_token=redacted("bot-token"))))
    .pipe(layer.provide_merge(chat.layer))
)


# Stands in for Discord's REST API here: the adapter reads its own user once.
def discord(request: HttpClientRequest) -> fx.Effect[http_response.HttpClientResponse]:
    return fx.succeed(http_response.make(request, json.dumps({"id": "1564742987727118426"})))


# What Discord sends when someone types /summarize, signed as Discord signs it.
def delivery() -> tuple[bytes, dict[str, str]]:
    body = json.dumps(
        {
            "id": "1570700000000000100",
            "application_id": "1564742987727118426",
            "type": 2,
            "token": "interaction-token",
            "channel_id": "1570607253965246584",
            "member": {"user": {"id": "449108784879763458"}},
            "data": {"id": "1570700000000000900", "name": "summarize", "type": 1},
        }
    ).encode()
    timestamp = str(int(time.time()))
    signature = discord_key.sign(timestamp.encode() + body).hex()
    return body, {"x-signature-timestamp": timestamp, "x-signature-ed25519": signature}


@fx.gen
def program():
    http = yield from router.in_memory_client(app)
    body, headers = delivery()
    sent = http_request.post("http://localhost").body_bytes(body, "application/json").body
    url = "http://localhost/discord/interactions"
    response = yield from http.post(url, body=sent, headers=headers)
    print("answered", response.status, (yield from response.json))
    unsigned = yield from http.post(url, body=sent)
    print("unsigned", unsigned.status)


fx.run_blocking(fx.scoped(program).pipe(fx.provide(client.layer_test(discord))).or_die())
