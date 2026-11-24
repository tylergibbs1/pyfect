"""A fake Bot API for the Telegram adapter's tests (Effect's
``chat/telegram/test/utils.ts``): it keeps the messages the adapter sends by
id. ``next`` holds one-shot answers for a method, and ``updates`` the
batches ``getUpdates`` gives; once they run out it never answers. Nothing
here reaches the network."""

from __future__ import annotations

import itertools
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Never
from urllib.parse import urlsplit

import pyfect as fx
from pyfect import layer
from pyfect._core import Effect
from pyfect.chat import chat, chat_handler
from pyfect.chat.chat_event import ChatEvent
from pyfect.chat.chat_test import Interactions, NoSuchElement
from pyfect.chat.telegram import telegram_chat
from pyfect.http import body as http_body
from pyfect.http import client
from pyfect.http import response as http_response
from pyfect.http.error import HttpClientError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.redacted import make as redacted

TOKEN = "123456789:AAH-marker_TOKEN_must_not_leak"
"""A marker token: no error, span or log may contain it."""
BOT_ID = "123456789"
USERNAME = "effect_bot"
CHAT_ID = -1001234567890
THREAD = telegram_chat.thread(CHAT_ID)
USER: dict[str, Any] = {"id": 4242, "is_bot": False, "first_name": "Ada"}
CONTEXT = telegram_chat.NormalizeContext(bot_id=BOT_ID, bot_username=USERNAME)


DATE = 1_794_600_000
"""The date the fake stamps on messages (Effect's tests use ``Date.now()``;
tests here read no clock)."""


@dataclass(frozen=True)
class Answer:
    status: int
    body: object


def ok(result: object) -> Answer:
    return Answer(200, {"ok": True, "result": result})


def api_error(code: int, description: str, parameters: object = None) -> Answer:
    """A Bot API error answer, as Telegram sends it."""
    body: dict[str, object] = {"ok": False, "error_code": code, "description": description}
    if parameters is not None:
        body["parameters"] = parameters
    return Answer(code, body)


@dataclass(frozen=True)
class FakeCall:
    method: str
    body: Any


def _read_body(request: HttpClientRequest) -> dict[str, Any]:
    body = request.body
    if isinstance(body, http_body.Bytes):
        return json.loads(body.body.decode("utf-8"))
    if not isinstance(body, http_body.FormData):
        return {}
    out: dict[str, Any] = {}
    for key, value in body.entries:
        if not isinstance(value, str):
            out[key] = value
            continue
        try:
            out[key] = json.loads(value)
        except ValueError:
            out[key] = value
    return out


@dataclass
class FakeApi:
    calls: list[FakeCall] = field(default_factory=list[FakeCall])
    messages: dict[int, dict[str, Any]] = field(default_factory=dict[int, dict[str, Any]])
    next: dict[str, Answer] = field(default_factory=dict[str, Answer])
    updates: list[list[object]] = field(default_factory=list[list[object]])
    _count: itertools.count[int] = field(default_factory=lambda: itertools.count(101))

    def sent(self, method: str) -> list[Any]:
        return [call.body for call in self.calls if call.method == method]

    def _answer(self, method: str, body: dict[str, Any]) -> Answer:  # noqa: PLR0911
        match method:
            case "getMe":
                return ok(
                    {
                        "id": int(BOT_ID),
                        "is_bot": True,
                        "first_name": "Effect",
                        "username": USERNAME,
                    }
                )
            case "sendRichMessage":
                id = next(self._count)
                self.messages[id] = body
                result: dict[str, Any] = {
                    "message_id": id,
                    "date": DATE,
                    "chat": {"id": body.get("chat_id"), "type": "supergroup", "title": "Effect"},
                }
                if "reply_markup" in body:
                    result["reply_markup"] = body["reply_markup"]
                return ok(result)
            case "editMessageText":
                if body.get("message_id") not in self.messages:
                    return api_error(400, "Bad Request: message to edit not found")
                self.messages[body["message_id"]] = {**self.messages[body["message_id"]], **body}
                return ok(True)
            case "deleteMessage":
                if self.messages.pop(body.get("message_id", -1), None) is None:
                    return api_error(400, "Bad Request: message to delete not found")
                return ok(True)
            case "getChat":
                return ok({"id": body.get("chat_id"), "type": "supergroup", "title": "Effect"})
            case "getChatMember":
                return ok({"status": "member", "user": {**USER, "id": body.get("user_id")}})
            case "getFile":
                return ok(
                    {
                        "file_id": body.get("file_id"),
                        "file_unique_id": "u",
                        "file_size": 5,
                        "file_path": "documents/file_1.txt",
                    }
                )
            case "answerCallbackQuery":
                return ok(True)
            case _:
                return api_error(404, "Not Found")

    def _respond(self, request: HttpClientRequest) -> Effect[HttpClientResponse, HttpClientError]:
        path = urlsplit(request.url).path
        if path.startswith("/file/bot"):
            self.calls.append(FakeCall("file", path.split("/", 3)[3]))
            return fx.succeed(http_response.make(request, b"hello"))
        method = path.rsplit("/", 1)[-1]
        self.calls.append(FakeCall(method, _read_body(request)))
        scripted = self.next.pop(method, None)
        if scripted is None and method == "getUpdates":
            if not self.updates:
                return fx.never
            scripted = ok(self.updates.pop(0))
        answer = scripted or self._answer(method, self.calls[-1].body)
        return fx.succeed(
            http_response.make(
                request,
                json.dumps(answer.body),
                status=answer.status,
                headers={"content-type": "application/json"},
            )
        )

    @property
    def layer(self) -> layer.Layer[client.HttpClient]:
        return client.layer_test(self._respond)


def telegram_layer(api: FakeApi) -> layer.Layer[Any, Any]:
    """``Chat``, ``Registry`` and the adapter on a fake Bot API, with every
    capability on."""
    return (
        telegram_chat.layer(
            token=redacted(TOKEN),
            unverified_files=True,
            unverified_buttons=True,
            unverified_commands=True,
        )
        .pipe(layer.provide_merge(chat.layer))
        .pipe(layer.provide(api.layer))
    )


_update_id = itertools.count(900_001)


def message_update(message: Mapping[str, Any], sender: object = None) -> dict[str, Any]:
    """An update with one message from ``sender`` in the test supergroup."""
    id = next(_update_id)
    return {
        "update_id": id,
        "message": {
            "message_id": id,
            "date": DATE,
            "chat": {"id": CHAT_ID, "type": "supergroup", "title": "Effect"},
            "from": USER if sender is None else sender,
            **message,
        },
    }


def command_update(
    name: str, text: str = "", extra: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """A command message, with its ``bot_command`` entity."""
    return message_update(
        {
            "text": f"/{name}" if text == "" else f"/{name} {text}",
            "entities": [{"type": "bot_command", "offset": 0, "length": len(name) + 1}],
            **(extra or {}),
        }
    )


def callback_update(message: Mapping[str, Any], data: str) -> dict[str, Any]:
    """A click on ``data`` from the test user, on the message as Telegram
    keeps it."""
    id = next(_update_id)
    return {
        "update_id": id,
        "callback_query": {
            "id": f"cq{id}",
            "from": USER,
            "chat_instance": "1",
            "data": data,
            "message": dict(message),
        },
    }


def user_posts(_thread: object, text: str) -> Effect[ChatEvent]:
    """The user's text, as ``chat_test.conformance`` wants it."""
    return fx.sync(lambda: telegram_chat.normalize(message_update({"text": text}), CONTEXT)[0])


class Clicks:
    """The conformance hook: clicks and commands go through
    ``TelegramChatService.receive``."""

    def __init__(self, api: FakeApi) -> None:
        self._api = api
        self._service: telegram_chat.TelegramChatService | None = None

    @property
    def bind(self) -> Effect[None, Never, Any]:
        return telegram_chat.TelegramChat().flat_map(
            lambda service: fx.sync(lambda: setattr(self, "_service", service))
        )

    def _receive(self, update: object) -> Effect[None, Never, Any]:
        assert self._service is not None
        return (
            self._service.receive(update)
            .pipe(fx.provide(chat_handler.layer(lambda _: fx.void)))
            .as_void()
        )

    def _click(self, message_id: str, id: str, _option: str | None) -> Effect[None, Any, Any]:
        sent = self._api.messages.get(int(message_id)) if message_id.isdigit() else None
        markup: dict[str, Any] = (sent or {}).get("reply_markup") or {}
        rows: list[list[dict[str, Any]]] = markup.get("inline_keyboard") or []
        button = next(
            (
                b
                for row in rows
                for b in row
                if "callback_data" in b and b["callback_data"].split("\x1f")[0] == id
            ),
            None,
        )
        if button is None or sent is None:
            return fx.fail(NoSuchElement(message_id=message_id, id=id))
        return self._receive(
            callback_update(
                {
                    "message_id": int(message_id),
                    "date": DATE,
                    "chat": {"id": sent["chat_id"], "type": "supergroup", "title": "Effect"},
                    "from": {"id": int(BOT_ID), "is_bot": True, "first_name": "Effect"},
                    "text": "x",
                    "reply_markup": markup,
                },
                button["callback_data"],
            )
        )

    def _command(self, _thread: object, id: str, text: str | None) -> Effect[None, Any, Any]:
        return self._receive(command_update(id, text or ""))

    @property
    def interactions(self) -> Interactions:
        return Interactions(
            click=self._click, submit=lambda _values: fx.void, command=self._command
        )
