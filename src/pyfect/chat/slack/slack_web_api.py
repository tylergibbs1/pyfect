"""The minimal Slack Web API client the adapter is built on (Effect's
``@effect/chat-slack/SlackWebApi``). It is public, so a consumer can call a
method the adapter has no op for, with the same error mapping and the same
rule for writes."""

from __future__ import annotations

from collections.abc import Generator, Mapping
from typing import Any, Never

import pyfect as fx
from pyfect._core import Effect
from pyfect._json_text import Json, stringify
from pyfect.chat.chat_adapter import retry_safe
from pyfect.chat.chat_error import AnyReason, ChatError
from pyfect.chat.slack import _errors
from pyfect.context import Tag
from pyfect.http import request as http_request
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.http.response import HttpClientResponse
from pyfect.layer import Layer
from pyfect.layer import effect as _layer_effect
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value

DEFAULT_BASE_URL = "https://slack.com/api"


def _form_body(body: Mapping[str, object]) -> dict[str, str]:
    return {
        key: value if isinstance(value, str) else stringify(value)
        for key, value in body.items()
        if value is not None
    }


class SlackWebApiService:
    """The minimal Web API client, with the bot token.

    - ``call`` posts form parameters to ``{base_url}/{method}``. A string
      goes as it is, any other value as JSON, and ``None`` is left out. It
      succeeds with the answer once Slack says ``ok``.
    - An ``ok: false`` answer fails with the reason for Slack's error code,
      which becomes the reason's ``detail``. ``ratelimited`` and an HTTP
      429 give ``RateLimited`` with the ``Retry-After`` wait.
    - A ``write`` never repeats once the request left: a transport failure,
      a server error or an unreadable answer is ``uncertain``. A read
      retries ``retry`` failures unless ``retry=False``.
    - The error's ``op`` is the method name.
    """

    def __init__(
        self,
        http: HttpClientService[HttpClientError, Never],
        bot_token: Redacted[str],
        base_url: str,
    ) -> None:
        self._http = http
        self._bot_token = bot_token
        self._base_url = base_url

    def call(
        self, method: str, body: Mapping[str, object], *, write: bool = False, retry: bool = True
    ) -> Effect[Json, ChatError]:
        """Calls a Web API method with ``body`` as form fields and succeeds
        with Slack's answer when it is ``ok``. ``write`` marks a call that may
        land without an answer, so a failure is ``uncertain`` rather than
        retried; ``retry`` retries a safe failure, as ``retry_safe`` does."""
        once = self._once(method, body, write)
        return retry_safe(once) if retry else once

    def _once(
        self, method: str, body: Mapping[str, object], write: bool
    ) -> Effect[Json, ChatError]:
        def fail(reason: AnyReason) -> Effect[Never, ChatError]:
            return fx.fail(_errors.chat_error(method, reason))

        request = (
            http_request.post(f"{self._base_url}/{method}")
            .bearer_token(redacted_value(self._bot_token))
            .body_url_params(_form_body(body))
        )

        def answered(response: HttpClientResponse) -> Effect[Json, ChatError]:
            retry_after = _errors.parse_retry_after(response.headers.get("retry-after"))
            if not 200 <= response.status < 300:
                return fail(
                    _errors.reason_for_status(response.status, write=write, retry_after=retry_after)
                )

            def read(json: Json) -> Effect[Json, ChatError]:
                if not isinstance(json, dict) or not isinstance(json.get("ok"), bool):
                    return fail(_errors.invalid_response(write, "invalid_response"))
                if json["ok"]:
                    return fx.succeed(json)
                code = json.get("error")
                return fail(
                    _errors.reason_for_code(
                        code if isinstance(code, str) else "unknown_error",
                        write=write,
                        retry_after=retry_after,
                    )
                )

            return response.json.catch_all(
                lambda error: fail(_errors.invalid_response(write, "invalid_json", error))
            ).flat_map(read)

        return (
            self._http.execute(request)
            .catch_all(
                lambda error: fail(_errors.transport(write, type(error.reason).__name__, error))
            )
            .flat_map(answered)
        )


class SlackWebApi(Tag[SlackWebApiService], key="@effect/chat-slack/SlackWebApi"):
    """The Slack Web API client."""


def make(
    *, bot_token: Redacted[str], base_url: str = DEFAULT_BASE_URL
) -> Effect[SlackWebApiService, Never, HttpClient]:
    """Builds the client from an ``HttpClient`` and a bot token."""

    @fx.gen
    def body() -> Generator[Effect[Any, Never, HttpClient], Any, SlackWebApiService]:
        http = yield from HttpClient()
        return SlackWebApiService(http, bot_token, base_url)

    return body


def layer(
    *, bot_token: Redacted[str], base_url: str = DEFAULT_BASE_URL
) -> Layer[SlackWebApi, Never, HttpClient]:
    """The client as a layer."""
    return _layer_effect(SlackWebApi, make(bot_token=bot_token, base_url=base_url))


__all__ = ["DEFAULT_BASE_URL", "ChatError", "SlackWebApi", "SlackWebApiService", "layer", "make"]
