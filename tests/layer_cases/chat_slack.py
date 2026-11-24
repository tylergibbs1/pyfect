"""Layer cases of ``pyfect.chat.slack``: each run calls the scripted Slack
Web API of ``tests/_slack_fake.py``, posts through ``Chat`` or sends a signed
request to a route."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from _slack_fake import APP_ID, AUTH_TEST, CHANNEL, TEAM, Fake, message_envelope, unix_now

import pyfect as fx
from layer_cases._case import Case
from pyfect import layer as L
from pyfect.chat import chat, chat_handler
from pyfect.chat import chat_interaction as ci
from pyfect.chat.chat import Chat
from pyfect.chat.slack import slack_chat, slack_web_api
from pyfect.chat.slack.slack_web_api import SlackWebApi
from pyfect.crypto.native import layer_mac
from pyfect.http import request as http_request
from pyfect.http import router
from pyfect.redacted import make as redacted

type AnyEffect = fx.Effect[Any, Any, Any]
type AnyLayer = fx.Layer[Any, Any, Any]

_SECRET = "layer-case-signing-secret"
_TOKEN = redacted("xoxb-layer-case")


def _fake() -> Fake:
    return Fake(
        {
            "auth.test": AUTH_TEST,
            "chat.postMessage": {"ok": True, "channel": CHANNEL, "ts": "1794600000.000100"},
        }
    )


def _slack() -> AnyLayer:
    """``SlackChat`` on a fresh fake, with ``Chat`` and its ``Registry``."""
    return (
        slack_chat.layer(bot_token=_TOKEN, team_id=TEAM)
        .pipe(L.provide_merge(chat.layer))
        .pipe(L.provide(_fake().layer))
    )


def _posts() -> AnyEffect:
    thread = slack_chat.thread(team=TEAM, channel=CHANNEL)
    return Chat().flat_map(lambda service: service.post(thread, markdown="hello")).as_void()


def _signed(body: str, content_type: str) -> tuple[Any, dict[str, str]]:
    timestamp = unix_now()
    digest = hmac.new(_SECRET.encode(), f"v0:{timestamp}:{body}".encode(), hashlib.sha256)
    headers = {
        "x-slack-request-timestamp": timestamp,
        "x-slack-signature": "v0=" + digest.hexdigest(),
    }
    return http_request.post("http://x").body_text(body, content_type).body, headers


def _route(value: AnyLayer, needs: AnyLayer, path: str, body: str, content_type: str) -> AnyEffect:
    """One signed request through the route ``value`` serves; dies unless it is a 200."""

    @fx.gen
    def run():
        http = yield from router.in_memory_client(value.pipe(L.provide(needs)))
        sent, headers = _signed(body, content_type)
        response = yield from http.post(f"http://localhost{path}", body=sent, headers=headers)
        if response.status != 200:
            return (yield from fx.die(AssertionError(response.status)))
        return None

    return fx.scoped(run)


def _webhook_run(value: AnyLayer) -> AnyEffect:
    needs = L.merge(_slack(), layer_mac, chat_handler.layer(lambda _: fx.void))
    body = json.dumps(message_envelope({"ts": "1794509003.000001", "user": "U0PEER", "text": "hi"}))
    return _route(value, needs, "/slack/events", body, "application/json")


def _interactivity_run(value: AnyLayer) -> AnyEffect:
    needs = L.merge(_slack(), layer_mac, ci.layer())
    payload: dict[str, object] = {"type": "block_actions", "api_app_id": APP_ID, "actions": []}
    body = "payload=" + json.dumps(payload).replace("%", "%25").replace("&", "%26")
    return _route(value, needs, "/slack/interactivity", body, "application/x-www-form-urlencoded")


CASES: dict[str, Case] = {
    "pyfect.chat.slack.slack_web_api.layer": Case(
        layer=lambda: slack_web_api.layer(bot_token=_TOKEN),
        needs=lambda: _fake().layer,
        use=lambda: SlackWebApi().flat_map(lambda api: api.call("auth.test", {})).as_void(),
    ),
    "pyfect.chat.slack.slack_chat.layer": Case(
        layer=lambda: slack_chat.layer(bot_token=_TOKEN, team_id=TEAM),
        needs=lambda: L.merge(chat.layer, _fake().layer),
        use=_posts,
    ),
    "pyfect.chat.slack.slack_chat.layer_webhook": Case(
        layer=lambda: slack_chat.layer_webhook(
            path="/slack/events", signing_secret=redacted(_SECRET), app_id=APP_ID
        ),
        run=_webhook_run,
    ),
    "pyfect.chat.slack.slack_chat.layer_interactivity": Case(
        layer=lambda: slack_chat.layer_interactivity(
            path="/slack/interactivity", signing_secret=redacted(_SECRET), app_id=APP_ID
        ),
        run=_interactivity_run,
    ),
}

SKIPPED: dict[str, str] = {}
