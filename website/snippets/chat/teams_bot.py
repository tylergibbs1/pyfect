import json
import time
from typing import Never, NotRequired, TypedDict
from urllib.parse import urlsplit

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.chat import chat, chat_handler, chat_markdown
from pyfect.chat.chat import Chat
from pyfect.chat.chat_event import ChatEvent, MessageCreated
from pyfect.chat.teams import teams_chat
from pyfect.crypto.native import layer_digest, layer_mac, layer_signature
from pyfect.http import body as http_body
from pyfect.http import client, router
from pyfect.http import request as http_request
from pyfect.http import response as http_response
from pyfect.http.request import HttpClientRequest
from pyfect.jose import jwk, jwt
from pyfect.redacted import make as redacted
from pyfect.redacted import value as reveal

APP_ID = "00000000-0000-0000-0000-0000000000a1"
TENANT_ID = "00000000-0000-0000-0000-0000000000b2"
SERVICE_URL = "https://smba.trafficmanager.net/emea/"
crypto = layer.merge(layer.merge(layer_mac, layer_digest), layer_signature)


# Answers every message in the thread it came from.
def on_event(event: ChatEvent) -> fx.Effect[None, Never, Chat]:
    if not isinstance(event, MessageCreated):
        return fx.void
    reply = chat_markdown.post(event.thread, f"You said: {event.message.text}")
    return reply.as_void().or_die()


# The bot: the messaging endpoint, the adapter and the handler.
app = (
    teams_chat.layer_webhook(path="/api/messages")
    .pipe(layer.provide(chat_handler.layer(on_event)))
    .pipe(
        layer.provide_merge(
            teams_chat.layer(app_id=APP_ID, tenant_id=TENANT_ID, credentials=redacted("secret"))
        )
    )
    .pipe(layer.provide_merge(chat.layer))
)


class Claims(TypedDict):
    iss: str
    aud: str
    exp: int
    serviceurl: NotRequired[str]


# Stands in for Bot Framework here: its key set, Entra's token endpoint and the
# Connector, printing what the bot posts.
def bot_framework(keys: object) -> layer.Layer[client.HttpClient]:
    def answer(request: HttpClientRequest) -> fx.Effect[http_response.HttpClientResponse]:
        url = urlsplit(request.url)
        body: object = {"id": "1800000000002"}
        if url.path.endswith("/openidconfiguration"):
            body = {"jwks_uri": "https://login.botframework.com/v1/.well-known/keys"}
        elif url.path.endswith("/keys"):
            body = keys
        elif url.hostname == "login.microsoftonline.com":
            body = {"access_token": "connector-token", "expires_in": 3600}
        elif isinstance(request.body, http_body.Bytes):
            print("POST", url.path, json.loads(request.body.body)["text"])
        return fx.succeed(http_response.make(request, json.dumps(body)))

    return client.layer_test(answer)


@fx.gen
def program():
    # Bot Framework signs its requests with RS256 keys endorsed for Teams.
    pair = yield from jwk.generate_key_pair("RS256", kid="k1")
    key = yield from jwk.import_private(pair.private_key, "RS256")
    keys = {"keys": [{**pair.public_key, "endorsements": ["msteams"]}]}
    claims: Claims = {
        "iss": "https://api.botframework.com",
        "aud": APP_ID,
        "exp": int(time.time()) + 600,
        "serviceurl": SERVICE_URL,
    }
    token = reveal((yield from jwt.sign(S.Struct(Claims), claims, key)))
    activity = {
        "type": "message",
        "id": "1800000000001",
        "timestamp": "2026-11-15T10:00:00.000Z",
        "serviceUrl": SERVICE_URL,
        "channelId": "msteams",
        "from": {"id": "29:user", "aadObjectId": "user", "name": "User"},
        "recipient": {"id": f"28:{APP_ID}", "name": "Bot"},
        "conversation": {"id": "a:direct", "conversationType": "personal", "tenantId": TENANT_ID},
        "text": "deploy the docs",
    }
    served = app.pipe(layer.provide(bot_framework(keys)))
    http = yield from router.in_memory_client(served)
    body = http_request.post("http://x").body_text(json.dumps(activity), "application/json").body
    url = "http://localhost/api/messages"
    signed = yield from http.post(url, body=body, headers={"authorization": f"Bearer {token}"})
    print("answered", signed.status)
    unsigned = yield from http.post(url, body=body)
    print("unsigned", unsigned.status)


fx.run_blocking(fx.scoped(program).pipe(fx.provide(crypto)).or_die())
