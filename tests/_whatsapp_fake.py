"""A fake Graph API for the WhatsApp adapter's tests (Effect's
``chat/whatsapp/test/utils.ts``): it keeps the messages the adapter sends by
id, and the media it uploads. ``next`` holds one-shot answers for a path.
Nothing here reaches the network."""

from __future__ import annotations

import itertools
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Never, cast
from urllib.parse import urlsplit

import pyfect as fx
from pyfect import layer
from pyfect._core import Effect
from pyfect.chat import chat, chat_handler
from pyfect.chat.chat_event import ChatEvent
from pyfect.chat.chat_test import Interactions, NoSuchElement
from pyfect.chat.whatsapp import whatsapp_chat
from pyfect.http import body as http_body
from pyfect.http import client
from pyfect.http import response as http_response
from pyfect.http.error import HttpClientError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.redacted import make as redacted

PHONE_NUMBER_ID = "106540352242922"
BUSINESS = "15550783881"
BSUID = "US.13491208655302741918"
PHONE = "16505551234"
THREAD = whatsapp_chat.thread(phone_number_id=PHONE_NUMBER_ID, user=BSUID)
JOIN = "␟"


@dataclass(frozen=True)
class Status:
    """An answer with a status, or a JSON body for a 200."""

    status: int
    body: object = None


def graph_error(code: int, status: int = 400, subcode: int | None = None) -> Status:
    """A Graph error answer, as Meta sends it."""
    error: dict[str, object] = {
        "message": "refused",
        "type": "OAuthException",
        "code": code,
        "fbtrace_id": "A",
    }
    if subcode is not None:
        error["error_subcode"] = subcode
    return Status(status, {"error": error})


@dataclass(frozen=True)
class FakeCall:
    method: str
    path: str
    body: Any


@dataclass
class Graph:
    calls: list[FakeCall] = field(default_factory=list[FakeCall])
    messages: dict[str, Any] = field(default_factory=dict[str, Any])
    media: dict[str, tuple[str, bytes]] = field(default_factory=dict[str, tuple[str, bytes]])
    next: dict[str, Status | Mapping[str, Any]] = field(
        default_factory=dict[str, "Status | Mapping[str, Any]"]
    )
    _count: itertools.count[int] = field(default_factory=lambda: itertools.count(1))

    def sent(self) -> list[Any]:
        return [call.body for call in self.calls if call.path == f"{PHONE_NUMBER_ID}/messages"]

    def _body(self, request: HttpClientRequest) -> Any:
        body = request.body
        if isinstance(body, http_body.FormData):
            return dict(body.entries)
        if isinstance(body, http_body.Bytes):
            return json.loads(body.body.decode("utf-8"))
        return None

    def _answer(self, request: HttpClientRequest) -> Status | Mapping[str, Any] | bytes:  # noqa: PLR0911
        url = urlsplit(request.url)
        lookaside = url.hostname == "lookaside.test"
        path = url.path if lookaside else url.path.removeprefix("/v24.0/")
        body = self._body(request)
        self.calls.append(FakeCall(request.method, path, body))
        scripted = self.next.pop(path, None)
        if scripted is not None:
            return scripted
        if lookaside:
            return self.media[path[1:]][1]
        if path == f"{PHONE_NUMBER_ID}/media":
            id = f"media-{next(self._count)}"
            file = cast("http_body.File", body["file"])
            self.media[id] = (cast("str", body["type"]), cast("bytes", file.content))
            return {"id": id}
        if path == f"{PHONE_NUMBER_ID}/messages":
            if body.get("status") == "read":
                return {"success": True}
            id = f"wamid.out{next(self._count)}"
            self.messages[id] = body
            to = body.get("to") or body.get("recipient")
            contact = {"input": to, ("user_id" if "to" not in body else "wa_id"): to}
            return {
                "messaging_product": "whatsapp",
                "contacts": [contact],
                "messages": [{"id": id}],
            }
        stored = self.media.get(path)
        if stored is None:
            return graph_error(100, 400, 33)
        return {
            "url": f"https://lookaside.test/{path}",
            "mime_type": stored[0],
            "file_size": len(stored[1]),
            "id": path,
        }

    def _respond(self, request: HttpClientRequest) -> Effect[HttpClientResponse, HttpClientError]:
        result = self._answer(request)
        if isinstance(result, bytes):
            return fx.succeed(http_response.make(request, result))
        if isinstance(result, Status):
            text = json.dumps({} if result.body is None else result.body)
            return fx.succeed(http_response.make(request, text, status=result.status))
        return fx.succeed(
            http_response.make(
                request, json.dumps(result), headers={"content-type": "application/json"}
            )
        )

    @property
    def layer(self) -> layer.Layer[client.HttpClient]:
        return client.layer_test(self._respond)


def whatsapp_layer(graph: Graph, *, messaging_account_id: str | None = None) -> layer.Layer[Any]:
    """``Chat``, ``Registry`` and the WhatsApp adapter on a fake Graph API."""
    return (
        whatsapp_chat.layer(
            access_token=redacted("EAAG-test"),
            phone_number_id=PHONE_NUMBER_ID,
            messaging_account_id=messaging_account_id,
        )
        .pipe(layer.provide_merge(chat.layer))
        .pipe(layer.provide(graph.layer))
    )


_inbound = itertools.count(1)


def inbound(
    message: Mapping[str, Any], *, phone_number_id: str = PHONE_NUMBER_ID
) -> dict[str, Any]:
    """A webhook delivery with one message from the test user."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "102290129340398",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": BUSINESS,
                                "phone_number_id": phone_number_id,
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Sheena Nelson"},
                                    "user_id": BSUID,
                                    "wa_id": PHONE,
                                }
                            ],
                            "messages": [
                                {
                                    "from": PHONE,
                                    "from_user_id": BSUID,
                                    "id": f"wamid.in{next(_inbound)}",
                                    "timestamp": "1794600000",
                                    **message,
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def statuses(*items: Mapping[str, Any]) -> dict[str, Any]:
    """A webhook delivery with statuses."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "102290129340398",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": BUSINESS,
                                "phone_number_id": PHONE_NUMBER_ID,
                            },
                            "statuses": list(items),
                        },
                    }
                ],
            }
        ],
    }


def user_posts(_thread: object, text: str) -> Effect[ChatEvent]:
    """The user's text, as ``chat_test.conformance`` wants it."""

    def event() -> ChatEvent:
        found = whatsapp_chat.normalize(
            inbound({"type": "text", "text": {"body": text}}), phone_number_id=PHONE_NUMBER_ID
        )[0]
        return cast("ChatEvent", found)

    return fx.sync(event)


class Clicks:
    """The conformance hook: builds the ``button_reply`` or ``list_reply`` of
    a reply button or list row the adapter sent, and delivers it through
    ``WhatsAppChatService.receive``."""

    def __init__(self, graph: Graph) -> None:
        self._graph = graph
        self._service: whatsapp_chat.WhatsAppChatService | None = None

    @property
    def bind(self) -> Effect[None, Never, Any]:
        return whatsapp_chat.WhatsAppChat().flat_map(
            lambda service: fx.sync(lambda: setattr(self, "_service", service))
        )

    def _click(self, message_id: str, id: str, option: str | None) -> Effect[None, Any, Any]:
        sent: dict[str, Any] = self._graph.messages.get(message_id) or {}
        interactive: dict[str, Any] = sent.get("interactive") or {}
        kind = interactive.get("type")
        action: dict[str, Any] = interactive.get("action") or {}
        buttons: list[dict[str, Any]] = action.get("buttons") or []
        sections: list[dict[str, Any]] = action.get("sections") or []
        choices: list[dict[str, str]] = (
            [button["reply"] for button in buttons]
            if kind == "button"
            else [row for section in sections for row in section["rows"]]
        )

        def matches(choice: dict[str, str]) -> bool:
            if choice["id"].startswith("b"):
                return choice["id"][1:].split(JOIN)[0] == id
            select, *value = choice["id"][1:].split(JOIN)
            return select == id and (option is None or JOIN.join(value) == option)

        choice = next((choice for choice in choices if matches(choice)), None)
        if choice is None or self._service is None:
            return fx.fail(NoSuchElement(message_id=message_id, id=id))
        reply = "button_reply" if kind == "button" else "list_reply"
        delivery = inbound(
            {
                "type": "interactive",
                "context": {"from": BUSINESS, "id": message_id},
                "interactive": {"type": reply, reply: choice},
            }
        )
        return (
            self._service.receive(delivery)
            .pipe(fx.provide(chat_handler.layer(lambda _: fx.void)))
            .or_die()
        )

    @property
    def interactions(self) -> Interactions:
        return Interactions(click=self._click, submit=lambda _values: fx.void)
