"""Layer cases of ``pyfect.chat.teams``: each run calls the stubbed Bot
Framework of ``tests/_teams_fake.py``, posts through ``Chat`` or sends a
request with a signed token to the messaging endpoint."""

from __future__ import annotations

import json
from typing import Any

from _teams_fake import APP_ID, CONVERSATION, TENANT_ID, Bot, activity, crypto, make_bot

import pyfect as fx
from layer_cases._case import Case
from pyfect import layer as L
from pyfect.chat import chat, chat_handler
from pyfect.chat.chat import Chat
from pyfect.chat.teams import teams_chat
from pyfect.http import request as http_request
from pyfect.http import router
from pyfect.redacted import make as redacted

type AnyEffect = fx.Effect[Any, Any, Any]
type AnyLayer = fx.Layer[Any, Any, Any]


def _teams() -> AnyLayer:
    return teams_chat.layer(app_id=APP_ID, tenant_id=TENANT_ID, credentials=redacted("secret"))


def _posts() -> AnyEffect:
    thread = teams_chat.thread(CONVERSATION)
    return Chat().flat_map(lambda service: service.post(thread, markdown="hello")).as_void()


def _webhook_run(value: AnyLayer) -> AnyEffect:
    """One message with a signed token; dies unless it is answered 200."""

    @fx.gen
    def run():
        bot = yield from make_bot()
        needs = L.merge(
            _teams().pipe(L.provide_merge(chat.layer)),
            chat_handler.layer(lambda _: fx.void),
        ).pipe(L.provide_merge(L.merge(bot.layer, crypto)))
        http = yield from router.in_memory_client(value.pipe(L.provide(needs)))
        token = yield from bot.token()
        body = http_request.post("http://x").body_text(json.dumps(activity()), "application/json")
        response = yield from http.post(
            "http://localhost/api/messages",
            body=body.body,
            headers={"authorization": f"Bearer {token}"},
        )
        if response.status != 200:
            return (yield from fx.die(AssertionError(response.status)))
        return None

    return fx.scoped(run).pipe(fx.provide(crypto))


CASES: dict[str, Case] = {
    "pyfect.chat.teams.teams_chat.layer": Case(
        layer=_teams,
        needs=lambda: L.merge(L.merge(chat.layer, Bot().layer), crypto),
        use=_posts,
    ),
    "pyfect.chat.teams.teams_chat.layer_webhook": Case(
        layer=lambda: teams_chat.layer_webhook(path="/api/messages"),
        run=_webhook_run,
    ),
}

SKIPPED: dict[str, str] = {}
