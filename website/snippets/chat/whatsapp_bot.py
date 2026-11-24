import hashlib
import hmac
import json
from typing import Never

import pyfect as fx
from pyfect import layer
from pyfect.chat import chat, chat_handler, chat_markdown
from pyfect.chat.chat import Chat
from pyfect.chat.chat_event import ChatEvent, MessageCreated
from pyfect.chat.chat_ui import Button
from pyfect.chat.whatsapp import whatsapp_chat
from pyfect.crypto.native import layer_mac
from pyfect.http import body as http_body
from pyfect.http import client, router
from pyfect.http import request as http_request
from pyfect.http import response as http_response
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redacted

APP_SECRET = "6f1e0c9a2b4d4e8f9a1b2c3d4e5f6a7b"
PHONE_NUMBER_ID = "106540352242922"


# Answers every message with **bold** Markdown and two reply buttons.
def on_event(event: ChatEvent) -> fx.Effect[None, Never, Chat]:
    if not isinstance(event, MessageCreated):
        return fx.void
    actions = [Button(id="yes", label="Deploy"), Button(id="no", label="Cancel")]
    reply = chat_markdown.post(event.thread, "Deploy **docs** now?", actions=actions)
    return reply.as_void().or_die()


# The WhatsApp app: the webhook, the adapter and the handler.
app = (
    whatsapp_chat.layer_webhook(
        path="/whatsapp", app_secret=redacted(APP_SECRET), verify_token=redacted("my-token")
    )
    .pipe(layer.provide(layer.merge(chat_handler.layer(on_event), layer_mac)))
    .pipe(
        layer.provide_merge(
            whatsapp_chat.layer(access_token=redacted("EAAG-1"), phone_number_id=PHONE_NUMBER_ID)
        )
    )
    .pipe(layer.provide_merge(chat.layer))
)


# Stands in for Meta's Graph API here, printing what the bot sends.
def graph(request: HttpClientRequest) -> fx.Effect[http_response.HttpClientResponse]:
    assert isinstance(request.body, http_body.Bytes)
    sent = json.loads(request.body.body)
    interactive = sent["interactive"]
    titles = [button["reply"]["title"] for button in interactive["action"]["buttons"]]
    print("to", sent["recipient"], repr(interactive["body"]["text"]), titles)
    answer = {"messaging_product": "whatsapp", "messages": [{"id": "wamid.out1"}]}
    return fx.succeed(http_response.make(request, json.dumps(answer)))


# What Meta would send when someone writes to the number, signed with the app secret.
def delivery() -> tuple[bytes, dict[str, str]]:
    message = {
        "from": "16505551234",
        "from_user_id": "US.13491208655302741918",
        "id": "wamid.in1",
        "timestamp": "1794600000",
        "type": "text",
        "text": {"body": "deploy the docs"},
    }
    value = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "15550783881", "phone_number_id": PHONE_NUMBER_ID},
        "messages": [message],
    }
    body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [{"id": "1", "changes": [{"field": "messages", "value": value}]}],
        }
    ).encode()
    signature = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return body, {"x-hub-signature-256": "sha256=" + signature}


@fx.gen
def program():
    http = yield from router.in_memory_client(app)
    check = "hub.mode=subscribe&hub.verify_token=my-token&hub.challenge=1158201444"
    subscribed = yield from http.get(f"http://localhost/whatsapp?{check}")
    print("subscription check", subscribed.status, (yield from subscribed.text))
    body, headers = delivery()
    sent = http_request.post("http://localhost").body_bytes(body, "application/json").body
    response = yield from http.post("http://localhost/whatsapp", body=sent, headers=headers)
    print("answered", response.status)
    unsigned = yield from http.post("http://localhost/whatsapp", body=sent)
    print("unsigned", unsigned.status)


fx.run_blocking(fx.scoped(program).pipe(fx.provide(client.layer_test(graph))).or_die())
