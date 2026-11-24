"""A scripted Discord for the Discord adapter's tests (Effect's
``chat/discord/test/utils.ts`` and ``discord.ts``): an ``HttpClient`` that
reads each REST request back into dfx's method name and arguments, records
it, and answers from a handler. A method with no handler dies, so a test sees
any call it didn't expect. Nothing here reaches the network."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Never, cast
from urllib.parse import unquote, urlsplit

import pyfect as fx
from pyfect import layer
from pyfect._core import Effect
from pyfect.chat import chat
from pyfect.chat.chat_adapter import ChatAdapter, Registry
from pyfect.chat.chat_test import Interactions, NoSuchElement
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.discord import discord_chat
from pyfect.chat.discord.discord_gateway import GatewayDispatch
from pyfect.chat.discord.discord_rest import DEFAULT_BASE_URL
from pyfect.http import body as http_body
from pyfect.http import client
from pyfect.http import response as http_response
from pyfect.http.error import HttpClientError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.redacted import make as redacted

BOT_USER_ID = "1564742987727118426"
"""The Janitor application the fixtures were recorded with."""
TIM = "449108784879763458"
GUILD = "840178841540362250"
SCRATCH = "1570607253965246584"

FIXTURES = Path(__file__).parent / "fixtures" / "chat_discord"


def events(name: str) -> list[dict[str, Any]]:
    """The dispatches of a gateway fixture in ``fixtures/events``."""
    return json.loads((FIXTURES / "events" / f"{name}.json").read_text("utf-8"))["dispatches"]


def dispatch(raw: Mapping[str, Any]) -> GatewayDispatch:
    """A fixture's dispatch as the gateway hands it on."""
    return GatewayDispatch(t=raw["t"], d=raw["d"])


def _recorded(name: str) -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "recorded" / f"{name}.json").read_text("utf-8"))["calls"]


RECORDED_COMMANDS: Any = json.loads((FIXTURES / "recorded" / "commands.json").read_text("utf-8"))
"""The slash commands recorded in EFF-3802; the built command payloads start from these."""


def step(name: str, step_name: str) -> dict[str, Any]:
    """The one recorded call for ``step_name``."""
    found = [call for call in _recorded(name) if call["step"] == step_name]
    if len(found) != 1:
        raise AssertionError(f"{name}/{step_name}: {len(found)} calls")
    return found[0]


@dataclass(frozen=True)
class Status:
    """An HTTP answer that is not a plain 200 JSON body."""

    status: int
    body: object = None
    headers: Mapping[str, str] = field(default_factory=dict[str, str])


HANG = object()
"""An answer that never comes."""

type Answer = object


def error_response(status: int, data: object) -> Status:
    """Discord's 4xx answer with its JSON error."""
    return Status(status, data)


def status_code_error(status: int) -> Status:
    """A 5xx answer with no JSON."""
    return Status(status, "")


def answer(call: Mapping[str, Any]) -> Answer:
    """A recorded call as the fake's answer: its body, or its failure."""
    return Status(call["status"], call["response"]) if call["status"] >= 400 else call["response"]


type Handler = Callable[..., Answer]


@dataclass(frozen=True)
class Call:
    method: str
    args: tuple[Any, ...]


_ROUTES: list[tuple[str, re.Pattern[str], str]] = [
    ("GET", re.compile(r"/users/@me"), "getMyUser"),
    ("GET", re.compile(r"/users/([^/]+)"), "getUser"),
    ("GET", re.compile(r"/channels/([^/]+)"), "getChannel"),
    ("GET", re.compile(r"/channels/([^/]+)/messages"), "listMessages"),
    ("POST", re.compile(r"/channels/([^/]+)/messages"), "createMessage"),
    ("GET", re.compile(r"/channels/([^/]+)/messages/([^/]+)"), "getMessage"),
    ("PATCH", re.compile(r"/channels/([^/]+)/messages/([^/]+)"), "updateMessage"),
    ("DELETE", re.compile(r"/channels/([^/]+)/messages/([^/]+)"), "deleteMessage"),
    ("POST", re.compile(r"/channels/([^/]+)/messages/([^/]+)/threads"), "createThreadFromMessage"),
    ("GET", re.compile(r"/guilds/([^/]+)/members/([^/]+)"), "getGuildMember"),
    ("POST", re.compile(r"/interactions/([^/]+)/([^/]+)/callback"), "createInteractionResponse"),
    (
        "PATCH",
        re.compile(r"/webhooks/([^/]+)/([^/]+)/messages/@original"),
        "updateOriginalWebhookMessage",
    ),
    ("GET", re.compile(r"/applications/@me"), "getMyApplication"),
    ("PUT", re.compile(r"/applications/([^/]+)/commands"), "bulkSetApplicationCommands"),
]


@dataclass(frozen=True)
class SentFile:
    name: str
    content_type: str
    content: bytes


def _body(request: HttpClientRequest) -> tuple[object, list[SentFile] | None]:
    body = request.body
    if isinstance(body, http_body.Bytes):
        return json.loads(body.body.decode("utf-8")), None
    if isinstance(body, http_body.FormData):
        payload: object = None
        files: list[SentFile] = []
        for name, value in body.entries:
            if name == "payload_json":
                payload = json.loads(cast("str", value))
            elif isinstance(value, http_body.File):
                files.append(SentFile(value.name, value.content_type, cast("bytes", value.content)))
        return payload, files
    return None, None


def _my_user() -> Answer:
    return {"id": BOT_USER_ID, "username": "Janitor", "bot": True}


class Fake:
    """The scripted Discord and the calls it took, by dfx's method names.
    ``withFiles`` records the files a request sent; ``download`` answers any
    request off Discord's API, an attachment's GET."""

    def __init__(
        self, handlers: Mapping[str, Handler], *, base_url: str = DEFAULT_BASE_URL
    ) -> None:
        self.handlers = {"getMyUser": _my_user, **handlers}
        self.calls: list[Call] = []
        self.requests: list[HttpClientRequest] = []
        self._base = urlsplit(base_url)

    def called(self, method: str) -> list[tuple[Any, ...]]:
        """The arguments of each call of ``method``, in order."""
        return [call.args for call in self.calls if call.method == method]

    def _route(self, request: HttpClientRequest) -> tuple[str, tuple[Any, ...]]:
        url = urlsplit(request.url)
        if url.netloc != self._base.netloc or not url.path.startswith(self._base.path):
            return "download", (request.url,)
        route = url.path.removeprefix(self._base.path)
        for method, pattern, name in _ROUTES:
            match = pattern.fullmatch(route)
            if method == request.method and match is not None:
                args = tuple(unquote(group) for group in match.groups())
                body, files = _body(request)
                if files is not None:
                    self.calls.append(Call("withFiles", (files,)))
                if name == "listMessages":
                    params = {key: str(value) for key, value in request.url_params}
                    return name, (*args, {**params, "limit": int(params["limit"])})
                return name, (*args, body) if body is not None else args
        raise AssertionError(f"unexpected request {request.method} {route}")

    def _answer(self, request: HttpClientRequest) -> Effect[HttpClientResponse, HttpClientError]:
        self.requests.append(request)
        method, args = self._route(request)
        self.calls.append(Call(method, args))
        handler = self.handlers.get(method)
        if handler is None:
            return fx.die(AssertionError(f"unexpected {method}"))
        found = handler(*args)
        if found is HANG:
            return fx.never
        if isinstance(found, bytes):
            return fx.succeed(http_response.make(request, found))
        if isinstance(found, Status):
            text = (
                found.body
                if isinstance(found.body, str)
                else ""
                if found.body is None
                else json.dumps(found.body)
            )
            return fx.succeed(
                http_response.make(request, text, status=found.status, headers=dict(found.headers))
            )
        return fx.succeed(
            http_response.make(
                request,
                "" if found is None else json.dumps(found),
                status=200 if found is not None else 204,
                headers={"content-type": "application/json"},
            )
        )

    @property
    def layer(self) -> layer.Layer[client.HttpClient]:
        return client.layer_test(self._answer)


def discord_layer(fake: Fake) -> layer.Layer[Any]:
    """``Chat``, ``Registry`` and the Discord adapter on a fake."""
    return (
        discord_chat.layer(bot_token=redacted("bot-token"))
        .pipe(layer.provide_merge(chat.layer))
        .pipe(layer.provide(fake.layer))
    )


@fx.gen
def adapter():
    """The Discord adapter from the registry."""
    registry = yield from Registry()
    found: ChatAdapter = yield from registry.get("discord")
    return found


JOIN = "␟"


def _id_of(custom_id: str) -> str:
    return custom_id.split(JOIN, maxsplit=1)[0]


def _iso(id: str) -> str:
    millis = (int(id) >> 22) + 1420070400000
    return datetime.fromtimestamp(millis / 1000, UTC).isoformat().replace("+00:00", "Z")


class Discord:
    """A Discord that keeps the messages the adapter posts, with their
    components, and records every interaction callback (Effect's
    ``test/discord.ts``). ``interactions`` is the conformance hook: it builds
    Discord's ``INTERACTION_CREATE`` payload from what was posted, or a slash
    command's, and sends it through ``DiscordChatService.interaction``. A
    command starts from the one recorded in ``recorded/commands.json``, and
    so does the submit of the modal it opened, which has no message."""

    def __init__(self, channel_type: int = 0) -> None:
        self.channel_type = channel_type
        self.messages: dict[str, dict[str, Any]] = {}
        self.callbacks: list[dict[str, Any]] = []
        self._next = 1570700000000000000
        self._refuse = 0
        self._count = 0
        self._opened: dict[str, Any] | None = None
        self._service: discord_chat.DiscordChatService | None = None
        self.fake = Fake(
            {
                "getChannel": self._get_channel,
                "createMessage": self._create,
                "updateMessage": self._update,
                "getMessage": self._get_message,
                "deleteMessage": self._delete,
                "listMessages": self._list,
                "createInteractionResponse": self._callback,
                "updateOriginalWebhookMessage": self._edit_original,
            }
        )

    def _get_channel(self, id: str) -> Answer:
        return {"id": id, "type": self.channel_type, "guild_id": GUILD, "name": "scratch"}

    def _get_message(self, _channel_id: str, id: str) -> Answer:
        return self.messages.get(id) or self._unknown()

    def _delete(self, _channel_id: str, id: str) -> Answer:
        return None if self.messages.pop(id, None) is not None else self._unknown()

    def _id(self) -> str:
        found = str(self._next)
        self._next += 1
        return found

    @staticmethod
    def _unknown() -> Answer:
        return error_response(404, {"code": 10008, "message": "Unknown Message"})

    def _create(self, channel_id: str, body: dict[str, Any]) -> Answer:
        if body.get("attachments") and self._refuse > 0:
            self._refuse -= 1
            # Discord's answer to an oversize upload, from recorded/uploads.json.
            return answer(step("uploads", "upload-20MiB-plus-1"))
        id = self._id()
        message: dict[str, Any] = {
            "id": id,
            "channel_id": channel_id,
            "type": 0,
            "content": body["content"],
            "timestamp": _iso(id),
            "author": {"id": BOT_USER_ID, "username": "Janitor", "bot": True},
            "attachments": [],
            "components": body.get("components", []),
        }
        self.messages[id] = message
        return message

    def _update(self, _channel_id: str, id: str, body: dict[str, Any]) -> Answer:
        message = self.messages.get(id)
        if message is None:
            return self._unknown()
        message["content"] = body["content"]
        if "components" in body:
            message["components"] = body["components"]
        return message

    def _list(self, channel_id: str, params: dict[str, Any]) -> Answer:
        after, before = params.get("after"), params.get("before")
        found = [
            message
            for message in self.messages.values()
            if message["channel_id"] == channel_id
            and (after is None or int(message["id"]) > int(after))
            and (before is None or int(message["id"]) < int(before))
        ]
        found.sort(key=lambda message: int(message["id"]), reverse=True)
        return found[: params["limit"]]

    def _callback(self, id: str, token: str, payload: dict[str, Any]) -> Answer:
        self.callbacks.append({"id": id, "token": token, "payload": payload})
        return None

    def _edit_original(self, _application_id: str, token: str, payload: dict[str, Any]) -> Answer:
        # Only a token a type 5 callback answered has an original response to edit.
        if not any(c["token"] == token and c["payload"]["type"] == 5 for c in self.callbacks):
            return error_response(404, {"code": 10015, "message": "Unknown Webhook"})
        return {"id": self._id(), "content": payload["content"]}

    def _deliver(self, payload: dict[str, Any]) -> Effect[Any, Never, Any]:
        assert self._service is not None
        before = len(self.callbacks)

        def found(_: object) -> object:
            return next(
                (c["payload"] for c in self.callbacks[before:] if c["id"] == payload["id"]), None
            )

        return self._service.interaction(payload).map(found)

    def _base(self, channel_id: str, message: dict[str, Any] | None = None) -> dict[str, Any]:
        self._count += 1
        n = self._count
        base: dict[str, Any] = {
            "id": "9" + str(n).zfill(18),
            "application_id": BOT_USER_ID,
            "token": f"token-{n}",
            "version": 1,
            "channel_id": channel_id,
            "guild_id": GUILD,
            "member": {"user": {"id": TIM, "username": "tim"}, "roles": []},
        }
        if message is not None:
            base["message"] = message
        return base

    def _click(self, message_id: str, id: str, option: str | None) -> Effect[None, Any, Any]:
        message = self.messages.get(message_id)
        rows: list[dict[str, Any]] = [] if message is None else message["components"]
        component = next(
            (
                c
                for row in rows
                for c in row["components"]
                if isinstance(c.get("custom_id"), str) and _id_of(c["custom_id"]) == id
            ),
            None,
        )
        if message is None or component is None:
            return fx.fail(NoSuchElement(message_id=message_id, id=id))
        value = (option or component["options"][0]["value"]) if component["type"] == 3 else None
        data: dict[str, Any] = {
            "custom_id": component["custom_id"],
            "component_type": component["type"],
        }
        if value is not None:
            data["values"] = [value]
        channel_id = message["channel_id"]

        def after(found: Any) -> None:
            self._opened = (
                {"data": found["data"], "channel_id": channel_id, "message": message}
                if isinstance(found, dict) and cast("dict[str, Any]", found).get("type") == 9
                else None
            )

        return self._deliver({**self._base(channel_id, message), "type": 3, "data": data}).map(
            after
        )

    def _command(self, thread: ChatThread, id: str, text: str) -> Effect[None, Never, Any]:
        private = RECORDED_COMMANDS["commands"]["private"]
        data: dict[str, Any] = {"id": "1570700000000000999", "name": id, "type": 1}
        if text:
            data["options"] = [{"type": 3, "name": "text", "value": text}]
        payload = {
            **private,
            "channel": {**private["channel"], "id": thread.id, "type": self.channel_type},
            **self._base(thread.id),
            "type": 2,
            "data": data,
        }

        def after(found: Any) -> None:
            self._opened = (
                {"data": found["data"], "channel_id": thread.id, "message": None}
                if isinstance(found, dict) and cast("dict[str, Any]", found).get("type") == 9
                else None
            )

        return self._deliver(payload).map(after)

    def _submit(self, values: Mapping[str, str]) -> Effect[None, Never, Any]:
        opened = self._opened
        if opened is None:
            return fx.void
        components: list[dict[str, Any]] = []
        for component in opened["data"]["components"]:
            if component["type"] != 18:
                components.append({"type": component["type"]})
                continue
            input = component["component"]
            value = values.get(input["custom_id"])
            components.append(
                {
                    "type": 18,
                    "component": {"type": 4, "custom_id": input["custom_id"], "value": value or ""}
                    if input["type"] == 4
                    else {
                        "type": 3,
                        "custom_id": input["custom_id"],
                        "values": [] if value is None else [value],
                    },
                }
            )
        message = opened["message"]
        payload: dict[str, Any] = {
            **(RECORDED_COMMANDS["commandModal"]["submitClose"] if message is None else {}),
            **self._base(opened["channel_id"], message),
            "type": 5,
            "data": {"custom_id": opened["data"]["custom_id"], "components": components},
        }

        def after(_: object) -> None:
            # Discord closes the modal on every answer, ``errors`` included.
            self._opened = None

        return self._deliver(payload).map(after)

    @property
    def bind(self) -> Effect[None, Never, Any]:
        """Keeps the ``DiscordChatService`` the hook delivers through."""
        return discord_chat.DiscordChat().flat_map(
            lambda service: fx.sync(lambda: setattr(self, "_service", service))
        )

    def refuse_files(self) -> Effect[None]:
        def more() -> None:
            self._refuse += 1

        return fx.sync(more)

    @property
    def interactions(self) -> Interactions:
        return Interactions(click=self._click, submit=self._submit, command=self._command)
