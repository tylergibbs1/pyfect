"""Layer cases of ``pyfect.chat.telegram``: each run calls the fake Bot API
of ``tests/_telegram_fake.py``, posts through ``Chat``, sends an update to
the webhook with its secret, or polls one batch."""

from __future__ import annotations

import json
from typing import Any

from _telegram_fake import THREAD, TOKEN, FakeApi, message_update

import pyfect as fx
from layer_cases._case import Case
from pyfect import layer as L
from pyfect.chat import chat, chat_handler
from pyfect.chat.chat import Chat
from pyfect.chat.telegram import telegram_bot_api, telegram_chat
from pyfect.chat.telegram.telegram_bot_api import TelegramBotApi
from pyfect.http import request as http_request
from pyfect.http import router
from pyfect.redacted import make as redacted

type AnyEffect = fx.Effect[Any, Any, Any]
type AnyLayer = fx.Layer[Any, Any, Any]

_SECRET = "layer-case-secret-token-of-32-chars"
_TOKEN = redacted(TOKEN)


def _telegram(api: FakeApi | None = None) -> AnyLayer:
    """``TelegramChat`` on a fresh fake, with ``Chat`` and its ``Registry``."""
    return (
        telegram_chat.layer(token=_TOKEN)
        .pipe(L.provide_merge(chat.layer))
        .pipe(L.provide((api or FakeApi()).layer))
    )


def _posts() -> AnyEffect:
    return Chat().flat_map(lambda service: service.post(THREAD, markdown="hello")).as_void()


def _webhook_run(value: AnyLayer) -> AnyEffect:
    needs = L.merge(_telegram(), chat_handler.layer(lambda _: fx.void))
    body = json.dumps(message_update({"text": "hi"}))

    @fx.gen
    def run():
        http = yield from router.in_memory_client(value.pipe(L.provide(needs)))
        sent = http_request.post("http://x").body_text(body, "application/json").body
        response = yield from http.post(
            "http://localhost/telegram",
            body=sent,
            headers={telegram_chat.SECRET_HEADER: _SECRET},
        )
        if response.status != 200:
            return (yield from fx.die(AssertionError(response.status)))
        return None

    return fx.scoped(run)


def _polling_needs() -> AnyLayer:
    api = FakeApi()
    api.updates.append([])
    return L.merge(_telegram(api), chat_handler.layer(lambda _: fx.void))


CASES: dict[str, Case] = {
    "pyfect.chat.telegram.telegram_bot_api.layer": Case(
        layer=lambda: telegram_bot_api.layer(token=_TOKEN),
        needs=lambda: FakeApi().layer,
        use=lambda: TelegramBotApi().flat_map(lambda api: api.call("getMe")).ignore(),
    ),
    "pyfect.chat.telegram.telegram_chat.layer": Case(
        layer=lambda: telegram_chat.layer(token=_TOKEN),
        needs=lambda: L.merge(chat.layer, FakeApi().layer),
        use=_posts,
    ),
    "pyfect.chat.telegram.telegram_chat.layer_webhook": Case(
        layer=lambda: telegram_chat.layer_webhook(path="/telegram", secret_token=redacted(_SECRET)),
        run=_webhook_run,
    ),
    "pyfect.chat.telegram.telegram_chat.layer_polling": Case(
        layer=telegram_chat.layer_polling,
        needs=_polling_needs,
        use=lambda: fx.void,
    ),
}

SKIPPED: dict[str, str] = {}
