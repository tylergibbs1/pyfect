"""A scripted Slack for the Slack adapter's tests (Effect's ``chat/slack/test/utils.ts``):
each Web API method answers from a queue, the last answer repeating, or with
``{"ok": true}`` when it has none. Nothing here reaches the network."""

from __future__ import annotations

import binascii
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Never, cast
from urllib.parse import urlsplit

import pyfect as fx
from pyfect import layer
from pyfect._core import Effect
from pyfect.chat import chat
from pyfect.chat import chat_interaction as ci
from pyfect.chat.chat_adapter import ChatAdapter, Registry
from pyfect.chat.chat_test import Interactions, NoSuchElement
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.slack import slack_chat
from pyfect.http import body as http_body
from pyfect.http import client
from pyfect.http import response as http_response
from pyfect.http.error import HttpClientError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.redacted import make as redacted

TEAM = "T05479Z6JBW"
BOT_USER_ID = "U0CCLMD4S1L"
APP_ID = "A0CCHBHDK7X"
CHANNEL = "C0CH1LGJ4F3"

FIXTURES = Path(__file__).parent / "fixtures" / "chat_slack"


def _form_decode(text: str) -> str:
    # Quoted-printable's ``=XX`` is form encoding's ``%XX``, and binascii
    # decodes it in C: urllib's per-escape loop was most of a long test.
    quoted = text.replace("+", " ").replace("=", "%3D").replace("%", "=")
    return binascii.a2b_qp(quoted.encode("ascii")).decode("utf-8")


def parse_form(text: str) -> list[tuple[str, str]]:
    """``urllib.parse.parse_qsl(text, keep_blank_values=True)`` for the
    well-formed ASCII bodies the adapter sends."""
    return [
        (_form_decode(name), _form_decode(value))
        for name, _, value in (pair.partition("=") for pair in text.split("&") if pair)
    ]


def unix_now(offset_seconds: int = 0) -> str:
    """A Slack request timestamp: whole seconds since the epoch, from the wall
    clock the signature check reads, not a timing."""
    return str(int(datetime.now(UTC).timestamp()) + offset_seconds)


def fixture(kind: str, name: str) -> Any:
    """A JSON fixture: ``recorded``, ``events`` or ``synthetic``."""
    return json.loads((FIXTURES / kind / f"{name}.json").read_text("utf-8"))


def message_envelope(
    message: Mapping[str, Any],
    *,
    type: str = "message",
    channel: str = CHANNEL,
    channel_type: str = "channel",
    team_id: str = TEAM,
) -> dict[str, Any]:
    """An ``event_callback`` envelope built around a message as a Web API
    read returned it."""
    event: dict[str, Any] = {**message, "type": type, "channel": channel}
    if type != "app_mention":
        event["channel_type"] = channel_type
    event["event_ts"] = message.get("ts")
    return {
        "token": "verification-token",
        "team_id": team_id,
        "api_app_id": APP_ID,
        "type": "event_callback",
        "event_id": "Ev01",
        "event_time": 1794509000,
        "authorizations": [{"team_id": team_id, "user_id": BOT_USER_ID, "is_bot": True}],
        "event": event,
    }


@dataclass(frozen=True)
class Status:
    """An HTTP answer that is not a plain 200 JSON body."""

    status: int
    body: object = None
    headers: Mapping[str, str] = field(default_factory=dict[str, str])


HANG = object()
"""An answer that never comes."""

type Answer = Mapping[str, Any] | Status | object
type Script = Mapping[str, Answer | Sequence[Answer] | Callable[[dict[str, Any]], Answer]]


@dataclass(frozen=True)
class FakeCall:
    """A Web API call's method and form fields, or a ``response_url`` post's
    JSON body with its ``url``."""

    method: str
    params: dict[str, Any]


def _request_text(request: HttpClientRequest) -> str:
    body = request.body
    if isinstance(body, http_body.Bytes):
        return body.body.decode("utf-8")
    return ""


class Fake:
    """The scripted Slack and the calls it took."""

    def __init__(self, script: Script) -> None:
        self.script = dict(script)
        self.calls: list[FakeCall] = []
        self._queues: dict[str, list[Answer]] = {
            method: list(cast("Sequence[Answer]", answer))
            for method, answer in script.items()
            if isinstance(answer, list | tuple)
        }

    def called(self, method: str) -> list[FakeCall]:
        """The calls of one method, in order."""
        return [call for call in self.calls if call.method == method]

    def _answer(self, request: HttpClientRequest) -> Effect[HttpClientResponse, HttpClientError]:
        url = urlsplit(request.url)
        response_url = url.path.startswith("/commands/")
        method = "response_url" if response_url else url.path.removeprefix("/api/")
        text = _request_text(request)
        params: dict[str, Any] = (
            {"url": request.url, **json.loads(text)} if response_url else dict(parse_form(text))
        )
        self.calls.append(FakeCall(method, params))
        entry = self.script.get(method)
        if callable(entry):
            answer = cast("Callable[[dict[str, Any]], Answer]", entry)(params)
        elif method in self._queues:
            queue = self._queues[method]
            answer = queue.pop(0) if len(queue) > 1 else queue[0]
        else:
            answer = {"ok": True} if entry is None else entry
        if answer is HANG:
            return fx.never
        if isinstance(answer, Status):
            text = (
                ""
                if answer.body is None
                else answer.body
                if isinstance(answer.body, str)
                else json.dumps(answer.body)
            )
            return fx.succeed(
                http_response.make(
                    request, text, status=answer.status, headers=dict(answer.headers)
                )
            )
        return fx.succeed(
            http_response.make(
                request, json.dumps(answer), headers={"content-type": "application/json"}
            )
        )

    @property
    def layer(self) -> layer.Layer[client.HttpClient]:
        return client.layer_test(self._answer)


AUTH_TEST = {"ok": True, "user_id": BOT_USER_ID, "team_id": TEAM}

RESPONSE_URL = f"https://hooks.slack.com/commands/{TEAM}/1794600000/abcdef"
"""A command's ``response_url``, on Slack's host as the adapter requires."""


def command_fields(command: str, text: str, **overrides: str) -> dict[str, str]:
    """A slash command's form fields, from ``recorded/commands.json``."""
    return {
        **fixture("recorded", "commands")["commands"]["private"],
        "token": "verification",
        "channel_id": CHANNEL,
        "channel_name": "scratch",
        "command": command,
        "text": text,
        "response_url": RESPONSE_URL,
        "trigger_id": "trigger-command",
        **overrides,
    }


def slack_layer(fake: Fake) -> layer.Layer[Any]:
    """``Chat``, ``Registry`` and the Slack adapter on a fake."""
    return (
        slack_chat.layer(bot_token=redacted("xoxb-test"), team_id=TEAM)
        .pipe(layer.provide_merge(chat.layer))
        .pipe(layer.provide(fake.layer))
    )


@fx.gen
def adapter():
    """The Slack adapter from the registry."""
    registry = yield from Registry()
    found: ChatAdapter = yield from registry.get("slack")
    return found


TIM = "U080YLYB277"


class Slack:
    """A Slack that keeps the messages the adapter posts, with their blocks,
    and records every view it opens (Effect's ``test/slack.ts``).
    ``interactions`` is the conformance hook: it builds Slack's
    ``block_actions`` and ``view_submission`` payloads from what was posted
    and opened, and a slash command's form fields, and sends them through
    ``SlackChatService.interaction``. A command's ``response_url`` answers
    ``ok``. ``refuse_files`` makes the next file upload fail."""

    def __init__(self) -> None:
        self.messages: dict[str, dict[str, Any]] = {}
        self.views: list[dict[str, Any]] = []
        self._next = 1794600000
        self._refuse = False
        self._opened: dict[str, Any] | None = None
        self._service: slack_chat.SlackChatService | None = None
        self.fake = Fake(
            {
                "auth.test": AUTH_TEST,
                "chat.postMessage": self._post,
                "chat.update": self._update,
                "chat.delete": lambda params: (
                    {"ok": True}
                    if self.messages.pop(params["ts"], None) is not None
                    else {"ok": False, "error": "message_not_found"}
                ),
                "conversations.replies": lambda params: (
                    {"ok": True, "messages": [self.messages[params["ts"]]]}
                    if params["ts"] in self.messages
                    else {"ok": False, "error": "thread_not_found"}
                ),
                "views.open": self._open,
                "conversations.history": lambda params: {
                    "ok": True,
                    "messages": [
                        message
                        for message in reversed(self.messages.values())
                        if message["channel"] == params["channel"]
                    ],
                },
                "files.getUploadURLExternal": {
                    "ok": True,
                    "upload_url": "https://files.slack.test/upload/F1",
                    "file_id": "F1",
                },
                "files.completeUploadExternal": lambda _: (
                    {"ok": False, "error": "invalid_arguments"}
                    if self._refuse
                    else {"ok": True, "files": [{"id": "F1"}]}
                ),
                "response_url": Status(200, "ok"),
            }
        )

    def _post(self, params: dict[str, Any]) -> Answer:
        ts = f"{self._next}.000100"
        self._next += 1
        message: dict[str, Any] = {"type": "message", "ts": ts, "channel": params["channel"]}
        if "thread_ts" in params:
            message["thread_ts"] = params["thread_ts"]
        message |= {
            "user": BOT_USER_ID,
            "bot_id": "B0CCQH77VA5",
            "app_id": APP_ID,
            "team": TEAM,
            "text": params["text"],
            "blocks": json.loads(params["blocks"]),
        }
        self.messages[ts] = message
        return {"ok": True, "channel": params["channel"], "ts": ts}

    def _update(self, params: dict[str, Any]) -> Answer:
        message = self.messages.get(params["ts"])
        if message is None:
            return {"ok": False, "error": "message_not_found"}
        message["text"] = params["text"]
        message["blocks"] = json.loads(params["blocks"])
        return {"ok": True, "channel": params["channel"], "ts": params["ts"]}

    def _open(self, params: dict[str, Any]) -> Answer:
        view = {**json.loads(params["view"]), "id": f"V{len(self.views) + 1}"}
        self.views.append(view)
        return {"ok": True, "view": view}

    def _deliver(self, payload: dict[str, Any]) -> Effect[Any, Any, Any]:
        assert self._service is not None
        return self._service.interaction({**payload, "token": "verification", "api_app_id": APP_ID})

    def _opened_since(self, before: int) -> dict[str, Any] | None:
        return self.views[-1] if len(self.views) > before else None

    @property
    def bind(self) -> Effect[None, Never, Any]:
        """Keeps the ``SlackChatService`` the hook delivers through."""
        return slack_chat.SlackChat().flat_map(
            lambda service: fx.sync(lambda: setattr(self, "_service", service))
        )

    def refuse_files(self) -> Effect[None]:
        return fx.sync(lambda: setattr(self, "_refuse", True))

    def _command(self, thread: ChatThread, id: str, text: str) -> Effect[None, Never, Any]:
        parts = slack_chat.parts(thread)
        if parts is None:
            return fx.void
        before = len(self.views)
        fields = command_fields("/" + id, text, channel_id=parts.channel)
        del fields["token"]

        def after(_: object) -> None:
            self._opened = self._opened_since(before)

        return self._deliver(fields).map(after)

    def _click(self, message_id: str, id: str, option: str | None) -> Effect[None, Any, Any]:
        message = self.messages.get(message_id)
        blocks: list[dict[str, Any]] = [] if message is None else message["blocks"]
        block = next((b for b in blocks if b.get("type") == "actions"), None)
        elements: list[dict[str, Any]] = [] if block is None else block["elements"]
        element = next((e for e in elements if e.get("action_id") == id), None)
        if message is None or block is None or element is None:
            return fx.fail(NoSuchElement(message_id=message_id, id=id))
        before = len(self.views)
        options: list[dict[str, Any]] = element.get("options", [])
        value: str | None = (
            (option if option is not None else options[0]["value"])
            if element["type"] == "static_select"
            else None
        )
        action: dict[str, Any] = {
            **element,
            "block_id": block["block_id"],
            "action_ts": "1794600000.000001",
        }
        if value is not None:
            action["selected_option"] = next((o for o in options if o["value"] == value), None)
        payload: dict[str, Any] = {
            "type": "block_actions",
            "user": {"id": TIM, "username": "tim", "name": "tim", "team_id": TEAM},
            "team": {"id": TEAM, "domain": "effectfulworkspace"},
            "container": {
                "type": "message",
                "message_ts": message_id,
                "channel_id": message["channel"],
                "is_ephemeral": False,
            },
            "trigger_id": "trigger-" + message_id,
            "channel": {"id": message["channel"], "name": "scratch"},
            "message": message,
            "state": {"values": {}},
            "response_url": "https://hooks.slack.test/actions",
            "actions": [action],
        }

        def after(_: object) -> None:
            self._opened = self._opened_since(before)

        return self._deliver(payload).map(after)

    def _submit(self, values: Mapping[str, str]) -> Effect[None, Never, Any]:
        opened = self._opened
        if opened is None:
            return fx.void
        state: dict[str, Any] = {}
        for block in opened["blocks"]:
            if block["type"] != "input":
                continue
            element = block["element"]
            value = values.get(block["block_id"])
            state[block["block_id"]] = {
                element["action_id"]: (
                    {"type": element["type"], "value": value}
                    if element["type"] == "plain_text_input"
                    else {
                        "type": element["type"],
                        "selected_option": None
                        if value is None
                        else next((o for o in element["options"] if o["value"] == value), None),
                    }
                )
            }
        payload: dict[str, Any] = {
            "type": "view_submission",
            "team": {"id": TEAM, "domain": "effectfulworkspace"},
            "user": {"id": TIM, "username": "tim", "name": "tim", "team_id": TEAM},
            "trigger_id": "trigger-submit",
            "view": {
                **opened,
                "team_id": TEAM,
                "state": {"values": state},
                "hash": "1794600000.abc",
                "app_id": APP_ID,
            },
            "response_urls": [],
        }

        def after(answer: object) -> None:
            # An `errors` answer, or none in time, keeps the view open.
            keeps = isinstance(answer, ci.Late) or (
                isinstance(answer, dict)
                and cast("dict[str, object]", answer).get("response_action") == "errors"
            )
            if not keeps:
                self._opened = None

        return self._deliver(payload).map(after)

    @property
    def interactions(self) -> Interactions:
        return Interactions(click=self._click, submit=self._submit, command=self._command)
