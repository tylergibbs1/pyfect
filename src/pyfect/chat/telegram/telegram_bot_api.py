"""The minimal Bot API client the Telegram adapter is built on (Effect's
``@effect/chat-telegram/TelegramBotApi``). It is public, so a consumer can
call a method the adapter has no op for, with the same error mapping, the
same rule for writes and the same care for the token.

The bot token is part of every request's path, and ``HttpClient`` records a
request's path in its span and its errors. So the client's own span is off
for every request made here, each call gets a span
``TelegramBotApi.{method}`` whose ``url.path`` is ``/bot<redacted>/{method}``,
and every failure is a ``ChatError`` whose ``cause`` holds no request,
response or URL. Redirects are never followed: the next hop would see the
token.
"""

from __future__ import annotations

import re
from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Never, cast

import pyfect as fx
from pyfect import schema as S
from pyfect._core import Effect
from pyfect._digits import parse_digits
from pyfect._json_text import Json, stringify
from pyfect.chat.chat_adapter import File, retry_safe
from pyfect.chat.chat_error import ChatError
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.telegram import _address, _errors, _json
from pyfect.context import Tag
from pyfect.duration import Duration, from_input_unsafe
from pyfect.duration import Input as DurationInput
from pyfect.http import body as http_body
from pyfect.http import request as http_request
from pyfect.http.client import HttpClient, HttpClientService, TracerDisabledWhen
from pyfect.http.error import HttpClientError
from pyfect.http.response import HttpClientResponse
from pyfect.layer import Layer
from pyfect.layer import effect as _layer_effect
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value
from pyfect.stream import Stream
from pyfect.stream import _constructors as _stream

type Environment = Literal["production", "test"]
"""Which Telegram environment a bot lives in. The test environment has its
own accounts and bots, and its methods sit under ``/bot<token>/test/``."""

DEFAULT_API_URL = "https://api.telegram.org"
"""The cloud Bot API server."""

_METHOD_NAME = re.compile(r"[A-Za-z]{1,64}")
_FILE_PATH = re.compile(r"[A-Za-z0-9_.-]++(?:/[A-Za-z0-9_.-]++)*+")
_TOKEN = re.compile(r"([0-9]{1,20}):[A-Za-z0-9_-]+")


class TelegramChatMigrated(
    S.TaggedError,
    tag="TelegramChatMigrated",
    identifier="@effect/chat-telegram/TelegramBotApi/TelegramChatMigrated",
):
    """The cause of a ``NotFound`` with detail ``chat_migrated``: the group
    became a supergroup, which has a new chat id. The adapter does not follow
    it, since the consumer is the one that stores the old address."""

    thread: ChatThread

    @property
    def message(self) -> str:
        return "The Telegram group became a supergroup with a new address"

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class Upload:
    """A file sent as one part of a ``multipart/form-data`` body."""

    field: str
    file: File


def _form_value(value: object) -> str:
    return value if isinstance(value, str) else stringify(value)


class TelegramBotApiService:
    """The Bot API client, with the bot's token.

    - ``call`` posts ``params`` to a method and succeeds with its
      ``result``. Objects in ``params`` are sent as JSON; with ``files`` the
      body is multipart and each object is a JSON string part. A ``write``
      is never repeated once the request left, and a failure that may have
      landed is ``uncertain``; ``retry`` (default true) retries ``retry``
      failures as ``chat_adapter.retry_safe`` does. ``timeout``, when given,
      bounds each request: one without an answer by then fails
      ``Transport`` with detail ``timeout``, ``uncertain`` for a write.
    - An answer with ``ok: false`` fails with the reason for its
      ``error_code`` and ``parameters``. Its ``detail`` is a fixed string,
      never Telegram's description, which can quote the message. A
      ``migrate_to_chat_id`` gives ``NotFound`` with detail
      ``chat_migrated`` and a ``TelegramChatMigrated`` cause.
    - ``file`` streams a file by its ``file_path`` from ``getFile``, failing
      ``TooLarge`` once more than ``max_bytes`` arrive.
    - ``bot_id`` is the numeric id in front of the token's colon.
    - The error's ``op`` is the method.
    """

    def __init__(
        self,
        *,
        http: HttpClientService[HttpClientError, Never],
        token: Redacted[str],
        bot_id: str,
        environment: Environment,
        api_url: str,
    ) -> None:
        self._http = http
        self._token = token
        self._bot_id = bot_id
        self._environment: Environment = environment
        self._api_url = api_url
        self._suffix = "/test" if environment == "test" else ""

    @property
    def bot_id(self) -> str:
        """The numeric id in front of the token's colon."""
        return self._bot_id

    @property
    def environment(self) -> Environment:
        """``"production"``, or ``"test"`` for Telegram's test environment."""
        return self._environment

    def _method_url(self, method: str) -> str:
        return f"{self._api_url}/bot{redacted_value(self._token)}{self._suffix}/{method}"

    def _file_url(self, path: str) -> str:
        return f"{self._api_url}/file/bot{redacted_value(self._token)}{self._suffix}/{path}"

    def _send(
        self, request: http_request.HttpClientRequest, op: str, write: bool
    ) -> Effect[HttpClientResponse, ChatError]:
        return (
            self._http.execute(request)
            .pipe(fx.provide_service(TracerDisabledWhen, lambda _request: True))
            .map_error(
                lambda error: _errors.chat_error(
                    op, _errors.transport(write, type(error.reason).__name__)
                )
            )
        )

    def _decode(
        self, op: str, write: bool, response: HttpClientResponse
    ) -> Effect[Json, ChatError]:
        success = 200 <= response.status < 300
        status_error = _errors.ApiError(code=response.status)

        def unreadable(_error: HttpClientError) -> Effect[Never, ChatError]:
            reason = (
                _errors.invalid_response(write, "invalid_json")
                if success
                else _errors.reason_for_api_error(status_error, write=write)
            )
            return fx.fail(_errors.chat_error(op, reason))

        def read(body: Json) -> Effect[Json, ChatError]:
            obj = _json.as_object(body)
            if obj is not None and obj.get("ok") is True and "result" in obj:
                result: Json = cast("Json", obj["result"])
                return fx.succeed(result)
            error = _errors.api_error(body, response.status) or (None if success else status_error)
            if error is None:
                return fx.fail(
                    _errors.chat_error(op, _errors.invalid_response(write, "invalid_answer"))
                )
            cause = (
                None
                if error.migrate_to is None
                else TelegramChatMigrated(thread=_address.thread(error.migrate_to))
            )
            return fx.fail(
                _errors.chat_error(
                    op, _errors.reason_for_api_error(error, write=write, cause=cause)
                )
            )

        return response.json.match_effect(on_failure=unreadable, on_success=read)

    def _once(
        self,
        method: str,
        params: Mapping[str, object],
        write: bool,
        files: Sequence[Upload],
        timeout: Duration | None,
    ) -> Effect[Json, ChatError]:
        request = http_request.post(self._method_url(method))
        if files:
            form = http_body.FormData()
            for key, value in params.items():
                if value is not None:
                    form = form.append(key, _form_value(value))
            for upload in files:
                form = form.append(
                    upload.field,
                    http_body.File(upload.file.content, upload.file.name, upload.file.content_type),
                )
            request = request.body_form_data(form)
        else:
            request = request.body_json_unsafe(
                {key: value for key, value in params.items() if value is not None}
            )
        answered = self._send(request, method, write).flat_map(
            lambda response: self._decode(method, write, response)
        )
        if timeout is not None:
            timed_out = _errors.chat_error(method, _errors.transport(write, "timeout"))
            answered = answered.timeout_or_else(timeout, lambda: fx.fail(timed_out))
        return answered.with_span(
            f"TelegramBotApi.{method}",
            kind="client",
            attributes={
                "http.request.method": "POST",
                "url.path": f"/bot<redacted>{self._suffix}/{method}",
                "telegram.method": method,
            },
        )

    def call(
        self,
        method: str,
        params: Mapping[str, object] | None = None,
        *,
        write: bool = False,
        files: Sequence[Upload] = (),
        retry: bool = True,
        timeout: DurationInput | None = None,
    ) -> Effect[Json, ChatError]:
        """Posts ``params`` to ``method`` and succeeds with its ``result``;
        see the class. A ``None`` value is left out, as JavaScript's
        ``undefined`` is."""
        if _METHOD_NAME.fullmatch(method) is None:
            return fx.fail(_errors.chat_error(method, _errors.invalid_request("invalid_method")))
        deadline = None if timeout is None else from_input_unsafe(timeout)
        once = self._once(method, params or {}, write, files, deadline)
        return retry_safe(once) if retry else once

    def file(self, file_path: str, *, max_bytes: int) -> Stream[bytes, ChatError]:
        """Streams the file at ``file_path``; see the class."""
        op = "download"

        def fail(reason: _errors.AnyReason) -> Effect[Never, ChatError]:
            return fx.fail(_errors.chat_error(op, reason))

        @fx.gen
        def make() -> Generator[Effect[Any, ChatError, Any], Any, Stream[bytes, ChatError]]:
            if _FILE_PATH.fullmatch(file_path) is None or any(
                segment in (".", "..") for segment in file_path.split("/")
            ):
                yield from fail(_errors.invalid_response(False, "untrusted_file_path"))
            response = yield from self._send(http_request.get(self._file_url(file_path)), op, False)
            if 300 <= response.status < 400:
                yield from fail(_errors.invalid_response(False, "redirect"))
            if not 200 <= response.status < 300:
                yield from fail(
                    _errors.reason_for_api_error(
                        _errors.ApiError(code=response.status), write=False
                    )
                )
            too_large = _errors.chat_error(op, _errors.too_large("files", "max_bytes"))
            length = response.headers.get("content-length")
            declared = None if length is None else parse_digits(length)
            if declared is not None and declared > max_bytes:
                yield from fx.fail(too_large)
            received = 0

            def counted(chunk: bytes) -> Effect[bytes, ChatError]:
                nonlocal received
                received += len(chunk)
                return fx.fail(too_large) if received > max_bytes else fx.succeed(chunk)

            return response.stream.map_error(
                lambda error: _errors.chat_error(
                    op, _errors.transport(False, type(error.reason).__name__)
                )
            ).map_effect(counted)

        return _stream.unwrap(
            make.with_span(
                "TelegramBotApi.file",
                kind="client",
                attributes={"http.request.method": "GET", "url.path": "/file/bot<redacted>"},
            )
        )


class TelegramBotApi(Tag[TelegramBotApiService], key="@effect/chat-telegram/TelegramBotApi"):
    """The Bot API client."""


def make(
    *,
    token: Redacted[str],
    environment: Environment = "production",
    api_url: str = DEFAULT_API_URL,
) -> Effect[TelegramBotApiService, ChatError, HttpClient]:
    """Builds the client from an ``HttpClient`` and a bot token. Fails
    ``Unauthenticated`` with detail ``invalid_token`` when the token has no
    numeric bot id in front of a colon. ``api_url`` is for a local Bot API
    server and is privileged configuration."""

    @fx.gen
    def body() -> Generator[Effect[Any, ChatError, HttpClient], Any, TelegramBotApiService]:
        http = yield from HttpClient()
        match = _TOKEN.fullmatch(redacted_value(token))
        if match is None:
            return (yield from fx.fail(_errors.chat_error("layer", _errors.UNAUTHENTICATED_TOKEN)))
        bot_id: str = match[1]
        return TelegramBotApiService(
            http=http,
            token=token,
            bot_id=bot_id,
            environment=environment,
            api_url=api_url.rstrip("/"),
        )

    return body


def layer(
    *,
    token: Redacted[str],
    environment: Environment = "production",
    api_url: str = DEFAULT_API_URL,
) -> Layer[TelegramBotApi, ChatError, HttpClient]:
    """The client as a layer."""
    return _layer_effect(
        TelegramBotApi, make(token=token, environment=environment, api_url=api_url)
    )


__all__ = [
    "DEFAULT_API_URL",
    "ChatError",
    "Environment",
    "TelegramBotApi",
    "TelegramBotApiService",
    "TelegramChatMigrated",
    "Upload",
    "layer",
    "make",
]
