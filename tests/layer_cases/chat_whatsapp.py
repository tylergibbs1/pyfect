"""Layer cases of ``pyfect.chat.whatsapp``: each run calls the fake Graph API
of ``tests/_whatsapp_fake.py``, posts through ``Chat`` or sends a signed
delivery to the webhook."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from _whatsapp_fake import PHONE_NUMBER_ID, THREAD, Graph, inbound

import pyfect as fx
from layer_cases._case import Case
from pyfect import layer as L
from pyfect.chat import chat, chat_handler
from pyfect.chat.chat import Chat
from pyfect.chat.whatsapp import whatsapp_chat, whatsapp_graph_api
from pyfect.chat.whatsapp.whatsapp_graph_api import WhatsAppGraphApi
from pyfect.crypto.native import layer_mac
from pyfect.http import request as http_request
from pyfect.http import router
from pyfect.redacted import make as redacted

type AnyEffect = fx.Effect[Any, Any, Any]
type AnyLayer = fx.Layer[Any, Any, Any]

_SECRET = "layer-case-app-secret"
_TOKEN = redacted("EAAG-layer-case")


def _whatsapp() -> AnyLayer:
    """``WhatsAppChat`` on a fresh fake, with ``Chat`` and its ``Registry``."""
    return (
        whatsapp_chat.layer(access_token=_TOKEN, phone_number_id=PHONE_NUMBER_ID)
        .pipe(L.provide_merge(chat.layer))
        .pipe(L.provide(Graph().layer))
    )


def _posts() -> AnyEffect:
    return Chat().flat_map(lambda service: service.post(THREAD, markdown="hello")).as_void()


def _webhook_run(value: AnyLayer) -> AnyEffect:
    needs = L.merge(_whatsapp(), layer_mac, chat_handler.layer(lambda _: fx.void))
    body = json.dumps(inbound({"type": "text", "text": {"body": "hi"}}))
    signature = "sha256=" + hmac.new(_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()

    @fx.gen
    def run():
        http = yield from router.in_memory_client(value.pipe(L.provide(needs)))
        sent = http_request.post("http://x").body_text(body, "application/json").body
        response = yield from http.post(
            "http://localhost/whatsapp", body=sent, headers={"x-hub-signature-256": signature}
        )
        if response.status != 200:
            return (yield from fx.die(AssertionError(response.status)))
        return None

    return fx.scoped(run)


CASES: dict[str, Case] = {
    "pyfect.chat.whatsapp.whatsapp_graph_api.layer": Case(
        layer=lambda: whatsapp_graph_api.layer(access_token=_TOKEN),
        needs=lambda: Graph().layer,
        use=lambda: WhatsAppGraphApi().flat_map(lambda api: api.call("media-1")).ignore(),
    ),
    "pyfect.chat.whatsapp.whatsapp_chat.layer": Case(
        layer=lambda: whatsapp_chat.layer(access_token=_TOKEN, phone_number_id=PHONE_NUMBER_ID),
        needs=lambda: L.merge(chat.layer, Graph().layer),
        use=_posts,
    ),
    "pyfect.chat.whatsapp.whatsapp_chat.layer_webhook": Case(
        layer=lambda: whatsapp_chat.layer_webhook(
            path="/whatsapp", app_secret=redacted(_SECRET), verify_token=redacted("v")
        ),
        run=_webhook_run,
    ),
}

SKIPPED: dict[str, str] = {}
