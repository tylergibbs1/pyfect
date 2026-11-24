import hashlib
import hmac
import json
import time
from typing import Never
from urllib.parse import parse_qsl

import pyfect as fx
from pyfect import layer
from pyfect.chat import chat, chat_handler, chat_markdown
from pyfect.chat.chat import Chat
from pyfect.chat.chat_event import ChatEvent, MessageCreated
from pyfect.chat.slack import slack_chat
from pyfect.chat.slack.slack_chat import SlackPostOptions
from pyfect.crypto.native import layer_mac
from pyfect.http import body as http_body
from pyfect.http import client, router
from pyfect.http import request as http_request
from pyfect.http import response as http_response
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redacted

SIGNING_SECRET = "8f742231b10e8888abcd99yyyzzz85a5"


# Answers a message that mentions the bot. A mention in a post notifies no one
# unless the post's options allow it; this one allows the person who asked.
def on_event(event: ChatEvent) -> fx.Effect[None, Never, Chat]:
    if not isinstance(event, MessageCreated):
        return fx.void
    message = event.message
    if not any(mention.is_self for mention in message.mentions):
        return fx.void
    reply = chat_markdown.post(event.thread, f"On it, <@{message.author.id}>. Ping <@U0OTHER>?")
    allowed = SlackPostOptions(notify_users=(message.author.id,))
    return reply.pipe(slack_chat.with_post_options(allowed)).as_void().or_die()


# The Slack app: the Events API route, the adapter and the handler.
app = (
    slack_chat.layer_webhook(
        path="/slack/events", signing_secret=redacted(SIGNING_SECRET), app_id="A0APP"
    )
    .pipe(layer.provide(layer.merge(chat_handler.layer(on_event), layer_mac)))
    .pipe(layer.provide_merge(slack_chat.layer(bot_token=redacted("xoxb-1"), team_id="T0TEAM")))
    .pipe(layer.provide_merge(chat.layer))
)


# Stands in for Slack's Web API here, printing what the bot posts.
def slack(request: HttpClientRequest) -> fx.Effect[http_response.HttpClientResponse]:
    assert isinstance(request.body, http_body.Bytes)
    fields = dict(parse_qsl(request.body.body.decode()))
    if request.url.endswith("/chat.postMessage"):
        print("chat.postMessage", repr(fields["text"]))
    answer = {"ok": True, "user_id": "U0BOT", "channel": "C0GENERAL", "ts": "1794600000.000100"}
    return fx.succeed(http_response.make(request, json.dumps(answer)))


# What Slack would send when someone mentions the bot, signed with the app's secret.
def delivery() -> tuple[bytes, dict[str, str]]:
    event = {
        "type": "message",
        "channel": "C0GENERAL",
        "channel_type": "channel",
        "user": "U0ASKER",
        "text": "<@U0BOT> deploy the docs",
        "ts": "1794509003.000001",
    }
    body = json.dumps(
        {"type": "event_callback", "team_id": "T0TEAM", "api_app_id": "A0APP", "event": event}
    ).encode()
    timestamp = str(int(time.time()))
    signed = f"v0:{timestamp}:".encode() + body
    signature = hmac.new(SIGNING_SECRET.encode(), signed, hashlib.sha256).hexdigest()
    headers = {"x-slack-request-timestamp": timestamp, "x-slack-signature": "v0=" + signature}
    return body, headers


@fx.gen
def program():
    http = yield from router.in_memory_client(app)
    body, headers = delivery()
    sent = http_request.post("http://localhost").body_bytes(body, "application/json").body
    response = yield from http.post("http://localhost/slack/events", body=sent, headers=headers)
    print("answered", response.status)
    unsigned = yield from http.post("http://localhost/slack/events", body=sent)
    print("unsigned", unsigned.status)


fx.run_blocking(fx.scoped(program).pipe(fx.provide(client.layer_test(slack))).or_die())
