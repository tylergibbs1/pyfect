import json
from typing import Never

import pyfect as fx
from pyfect import layer
from pyfect.chat import chat, chat_handler, chat_markdown
from pyfect.chat.chat import Chat
from pyfect.chat.chat_event import ChatEvent, MessageCreated
from pyfect.chat.telegram import telegram_chat
from pyfect.http import body as http_body
from pyfect.http import client, router
from pyfect.http import request as http_request
from pyfect.http import response as http_response
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redacted

SECRET = "Xq3_k9-ZpT7wLm2vRb8nYc4dHf6sJg1a"


# Answers every message that mentions the bot with **bold** Markdown.
def on_event(event: ChatEvent) -> fx.Effect[None, Never, Chat]:
    if not isinstance(event, MessageCreated) or not event.message.mentions:
        return fx.void
    reply = chat_markdown.post(event.thread, "Deploying **docs** now")
    return reply.as_void().or_die()


# The Telegram app: the webhook, the adapter and the handler.
app = (
    telegram_chat.layer_webhook(path="/telegram", secret_token=redacted(SECRET))
    .pipe(layer.provide(chat_handler.layer(on_event)))
    .pipe(layer.provide_merge(telegram_chat.layer(token=redacted("123456789:AAH-example"))))
    .pipe(layer.provide_merge(chat.layer))
)


# Stands in for the Bot API here, printing what the bot sends.
def bot_api(request: HttpClientRequest) -> fx.Effect[http_response.HttpClientResponse]:
    method = request.url.rsplit("/", 1)[-1]
    assert isinstance(request.body, http_body.Bytes)
    sent = json.loads(request.body.body)
    if method == "getMe":
        result: object = {"id": 123456789, "is_bot": True, "username": "deploy_bot"}
    else:
        print(method, sent["chat_id"], repr(sent["rich_message"]["markdown"]))
        result = {"message_id": 2, "date": 1794600001}
    body = json.dumps({"ok": True, "result": result})
    return fx.succeed(http_response.make(request, body))


# What Telegram would send when someone mentions the bot in a group.
update = {
    "update_id": 900001,
    "message": {
        "message_id": 1,
        "date": 1794600000,
        "chat": {"id": -1001234567890, "type": "supergroup", "title": "Ops"},
        "from": {"id": 4242, "is_bot": False, "first_name": "Ada"},
        "text": "@deploy_bot ship the docs",
        "entities": [{"type": "mention", "offset": 0, "length": 11}],
    },
}


@fx.gen
def program():
    http = yield from router.in_memory_client(app)
    body = http_request.post("http://x").body_text(json.dumps(update), "application/json").body
    headers = {telegram_chat.SECRET_HEADER: SECRET}
    answered = yield from http.post("http://localhost/telegram", body=body, headers=headers)
    print("answered", answered.status)
    unsigned = yield from http.post("http://localhost/telegram", body=body)
    print("without the secret", unsigned.status)


fx.run_blocking(fx.scoped(program).pipe(fx.provide(client.layer_test(bot_api))).or_die())
