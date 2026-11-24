"""The minimal Discord REST client the adapter is built on (in Effect, dfx's
``DiscordREST``). It is public, so a consumer can call a route the adapter has
no op for, with the same error mapping and the same rule for writes.

- Every request carries the bot token and Discord's ``User-Agent``; JSON
  goes as JSON and a message with files as ``multipart/form-data``, its JSON
  in ``payload_json`` and the files as ``files[n]``.
- A non-2xx answer fails with the reason for Discord's JSON error ``code``,
  or for the status when there is none; a 429 is ``RateLimited`` with the
  ``retry_after`` wait. It sends nothing again by itself: the adapter retries
  what is safe to send again, and a 429 is, since nothing happened.
- A ``write`` is ``uncertain`` once the request left: a transport failure,
  a server error or an unreadable answer may have landed.
- Path segments are percent-encoded, so an id from a payload can't reach
  another route.
"""

from __future__ import annotations

from collections.abc import Generator, Mapping, Sequence
from typing import Any, Literal, Never, cast
from urllib.parse import quote

import pyfect as fx
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._json_text import Json, stringify
from pyfect._version import VERSION
from pyfect.chat.chat_adapter import File
from pyfect.chat.chat_error import AnyReason, ChatError
from pyfect.chat.discord import _errors, _json
from pyfect.context import Tag
from pyfect.http import body as http_body
from pyfect.http import request as http_request
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.layer import Layer
from pyfect.layer import effect as _layer_effect
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value

DEFAULT_BASE_URL = "https://discord.com/api/v10"
"""Discord's API, version 10."""

USER_AGENT = f"DiscordBot (https://pyfect.dev, {VERSION})"
"""Discord's required ``User-Agent`` form: ``DiscordBot ($url, $version)``."""

type Method = Literal["GET", "POST", "PATCH", "PUT", "DELETE"]


def path(*segments: str) -> str:
    """A route from its segments, each percent-encoded: ``path("channels",
    id, "messages")`` is ``/channels/{id}/messages``. A segment that is empty,
    ``.`` or ``..`` raises ``ValueError``: a URL parser would drop it or step
    up a level, even percent-encoded."""
    for segment in segments:
        if segment in ("", ".", ".."):
            raise ValueError(f"not a path segment: {segment!r}")
    return "".join("/" + quote(segment, safe="@") for segment in segments)


def build_request(  # noqa: PLR0917
    base_url: str,
    method: Method,
    route: str,
    body: object = None,
    files: Sequence[File] = (),
    query: Mapping[str, str] | None = None,
) -> HttpClientRequest:
    """A request to ``{base_url}{route}`` without credentials: JSON, or
    multipart when there are files."""
    request = http_request.make(method, base_url + route).set_header("User-Agent", USER_AGENT)
    if query:
        request = request.set_url_params(dict(query))
    if files:
        form = http_body.FormData((("payload_json", stringify(body)),))
        for i, file in enumerate(files):
            form = form.append(
                f"files[{i}]", http_body.File(file.content, file.name, file.content_type)
            )
        return request.body_form_data(form)
    if body is not None:
        return request.body_text(stringify(body), "application/json")
    return request


def read_answer(
    op: str, write: bool, sent: Effect[HttpClientResponse, HttpClientError]
) -> Effect[Json, ChatError]:
    """Discord's answer to ``sent``: its JSON (``None`` for an empty body), or
    the ``ChatError`` of ``op`` for a failure."""
    require_effect(sent, "sent")

    def fail(reason: AnyReason) -> Effect[Never, ChatError]:
        return fx.fail(_errors.chat_error(op, reason))

    def answered(response: HttpClientResponse) -> Effect[Json, ChatError]:
        def read(text: str) -> Effect[Json, ChatError]:
            data = None if text == "" else _json.parse(text)
            if not 200 <= response.status < 300:
                return fail(_errors.reason_for_response(response.status, data, write=write))
            if text != "" and data is None and text.strip() != "null":
                return fail(_errors.invalid_response(write, "invalid_json"))
            return fx.succeed(cast("Json", data))

        return response.text.catch_all(
            lambda error: fail(_errors.transport(write, type(error.reason).__name__, error))
        ).flat_map(read)

    return sent.catch_all(
        lambda error: fail(_errors.transport(write, type(error.reason).__name__, error))
    ).flat_map(answered)


class DiscordRestService:
    """The client, with the bot token. Each method's failure is a
    ``ChatError`` whose ``op`` is the method's name."""

    def __init__(
        self,
        http: HttpClientService[HttpClientError, Never],
        bot_token: Redacted[str],
        base_url: str,
    ) -> None:
        self._http = http
        self._bot_token = bot_token
        self._base_url = base_url

    @property
    def base_url(self) -> str:
        """The API's base URL, which ``follow_up`` sends to as well."""
        return self._base_url

    def request(
        self,
        method: Method,
        route: str,
        *,
        op: str = "request",
        body: object = None,
        files: Sequence[File] = (),
        query: Mapping[str, str] | None = None,
        write: bool = False,
    ) -> Effect[Json, ChatError]:
        """Sends one request to ``route`` (built with ``path``) and succeeds
        with Discord's JSON answer. ``write`` marks a request that may land
        without an answer, so a failure is ``uncertain``."""
        request = build_request(self._base_url, method, route, body, files, query).set_header(
            "Authorization", "Bot " + redacted_value(self._bot_token)
        )
        return read_answer(op, write, self._http.execute(request))

    # The routes the adapter uses, named as dfx names them.

    def get_my_user(self) -> Effect[Json, ChatError]:
        """``GET /users/@me``: the bot's own user."""
        return self.request("GET", path("users", "@me"), op="getMyUser")

    def get_user(self, user_id: str) -> Effect[Json, ChatError]:
        """``GET /users/{id}``: a user."""
        return self.request("GET", path("users", user_id), op="getUser")

    def get_channel(self, channel_id: str) -> Effect[Json, ChatError]:
        """``GET /channels/{id}``: a channel, thread or direct."""
        return self.request("GET", path("channels", channel_id), op="getChannel")

    def get_message(self, channel_id: str, message_id: str) -> Effect[Json, ChatError]:
        """``GET /channels/{id}/messages/{id}``: one message."""
        return self.request(
            "GET", path("channels", channel_id, "messages", message_id), op="getMessage"
        )

    def list_messages(
        self,
        channel_id: str,
        *,
        before: str | None = None,
        after: str | None = None,
        limit: int = 50,
    ) -> Effect[Json, ChatError]:
        """``GET /channels/{id}/messages``: up to ``limit`` messages before or after an id,
        newest first."""
        query = {"limit": str(limit)}
        if before is not None:
            query["before"] = before
        if after is not None:
            query["after"] = after
        return self.request(
            "GET", path("channels", channel_id, "messages"), op="listMessages", query=query
        )

    def create_message(
        self, channel_id: str, body: Mapping[str, object], files: Sequence[File] = ()
    ) -> Effect[Json, ChatError]:
        """``POST /channels/{id}/messages``: a write, multipart when there are files."""
        return self.request(
            "POST",
            path("channels", channel_id, "messages"),
            op="createMessage",
            body=body,
            files=files,
            write=True,
        )

    def update_message(
        self, channel_id: str, message_id: str, body: Mapping[str, object]
    ) -> Effect[Json, ChatError]:
        """``PATCH /channels/{id}/messages/{id}``: a write."""
        return self.request(
            "PATCH",
            path("channels", channel_id, "messages", message_id),
            op="updateMessage",
            body=body,
            write=True,
        )

    def delete_message(self, channel_id: str, message_id: str) -> Effect[Json, ChatError]:
        """``DELETE /channels/{id}/messages/{id}``: a write."""
        return self.request(
            "DELETE",
            path("channels", channel_id, "messages", message_id),
            op="deleteMessage",
            write=True,
        )

    def create_thread_from_message(
        self, channel_id: str, message_id: str, body: Mapping[str, object]
    ) -> Effect[Json, ChatError]:
        """``POST /channels/{id}/messages/{id}/threads``: a write."""
        return self.request(
            "POST",
            path("channels", channel_id, "messages", message_id, "threads"),
            op="createThreadFromMessage",
            body=body,
            write=True,
        )

    def get_guild_member(self, guild_id: str, user_id: str) -> Effect[Json, ChatError]:
        """``GET /guilds/{id}/members/{id}``: a member, with their nick and roles."""
        return self.request(
            "GET", path("guilds", guild_id, "members", user_id), op="getGuildMember"
        )

    def create_interaction_response(
        self, interaction_id: str, token: str, body: Mapping[str, object]
    ) -> Effect[Json, ChatError]:
        """``POST /interactions/{id}/{token}/callback``: an interaction's answer."""
        return self.request(
            "POST",
            path("interactions", interaction_id, token, "callback"),
            op="createInteractionResponse",
            body=body,
            write=True,
        )

    def get_my_application(self) -> Effect[Json, ChatError]:
        """``GET /applications/@me``: the bot's application."""
        return self.request("GET", path("applications", "@me"), op="getMyApplication")

    def bulk_set_application_commands(
        self, application_id: str, commands: Sequence[Mapping[str, object]]
    ) -> Effect[Json, ChatError]:
        """Replaces the application's whole list of global commands."""
        return self.request(
            "PUT",
            path("applications", application_id, "commands"),
            op="bulkSetApplicationCommands",
            body=list(commands),
            write=True,
        )


class DiscordRest(Tag[DiscordRestService], key="@effect/chat-discord/DiscordRest"):
    """The Discord REST client."""


def make(
    *, bot_token: Redacted[str], base_url: str = DEFAULT_BASE_URL
) -> Effect[DiscordRestService, Never, HttpClient]:
    """Builds the client from an ``HttpClient`` and a bot token."""

    @fx.gen
    def body() -> Generator[Effect[Any, Never, HttpClient], Any, DiscordRestService]:
        http = yield from HttpClient()
        return DiscordRestService(http, bot_token, base_url)

    return body


def layer(
    *, bot_token: Redacted[str], base_url: str = DEFAULT_BASE_URL
) -> Layer[DiscordRest, Never, HttpClient]:
    """The client as a layer."""
    return _layer_effect(DiscordRest, make(bot_token=bot_token, base_url=base_url))


__all__ = [
    "DEFAULT_BASE_URL",
    "USER_AGENT",
    "ChatError",
    "DiscordRest",
    "DiscordRestService",
    "Method",
    "build_request",
    "layer",
    "make",
    "path",
    "read_answer",
]
