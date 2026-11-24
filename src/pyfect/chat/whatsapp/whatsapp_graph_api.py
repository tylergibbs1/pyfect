"""The minimal Graph API client the WhatsApp adapter is built on (Effect's
``@effect/chat-whatsapp/WhatsAppGraphApi``). It is public, so a consumer can
call an endpoint the adapter has no op for, with the same error mapping and
the same rule for writes."""

from __future__ import annotations

from collections.abc import Generator, Mapping
from typing import Any, Literal, Never

import pyfect as fx
from pyfect._core import Effect
from pyfect._json_text import Json
from pyfect.chat._retry_after import parse_retry_after
from pyfect.chat.chat_adapter import retry_safe
from pyfect.chat.chat_error import AnyReason, ChatError
from pyfect.chat.whatsapp import _errors, _json
from pyfect.context import Tag
from pyfect.duration import Duration, from_input_unsafe
from pyfect.duration import Input as DurationInput
from pyfect.http import body as http_body
from pyfect.http import request as http_request
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.http.response import HttpClientResponse
from pyfect.layer import Layer
from pyfect.layer import effect as _layer_effect
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value

DEFAULT_BASE_URL = "https://graph.facebook.com/v24.0"
"""The Graph API version the adapter was written against."""

type Method = Literal["GET", "POST", "DELETE"]


class WhatsAppGraphApiService:
    """The minimal Graph API client, with the access token.

    - ``call`` requests ``{base_url}/{path}`` with the token as a bearer
      token, and succeeds with the JSON of a 2xx answer. ``body`` goes as
      JSON, ``form`` as ``multipart/form-data`` (as a media upload does) and
      ``params`` as query parameters. ``method`` is ``GET``, or ``POST``
      when there is a ``body`` or a ``form``.
    - Another answer fails with the reason for its Graph error code, whose
      ``detail`` is ``graph_{code}`` and whose ``cause`` is the Graph
      ``error`` object, or for its HTTP status when it has no Graph error.
    - A ``write`` never repeats once the request left: a transport failure,
      a server error or an unreadable answer is ``uncertain``. A refusal
      Meta answers before sending, such as a rate limit, is retried unless
      ``retry=False``, as a read's ``retry`` failures are.
    - A rate limit is retried after the answer's ``Retry-After``, however
      long, unless ``max_retry_after`` is set: a longer wait then fails at
      once with ``RateLimited``, its ``retry_after`` the wait asked for.
      Without the header the backoff starts at 500 milliseconds.
    - The error's ``op`` is the path.
    """

    def __init__(
        self,
        http: HttpClientService[HttpClientError, Never],
        access_token: Redacted[str],
        base_url: str,
        max_retry_after: Duration | None = None,
    ) -> None:
        self._http = http
        self._access_token = access_token
        self._base_url = base_url
        self._max_retry_after = max_retry_after

    def call(
        self,
        path: str,
        *,
        method: Method | None = None,
        body: Mapping[str, object] | None = None,
        form: http_body.FormData | None = None,
        params: Mapping[str, str] | None = None,
        write: bool = False,
        retry: bool = True,
    ) -> Effect[Json, ChatError]:
        """Calls ``{base_url}/{path}`` and succeeds with the JSON of a 2xx
        answer; see the class."""
        once = self._once(path, method, body, form, params, write)
        return retry_safe(once, max_retry_after=self._max_retry_after) if retry else once

    def _once(  # noqa: PLR0917
        self,
        path: str,
        method: Method | None,
        body: Mapping[str, object] | None,
        form: http_body.FormData | None,
        params: Mapping[str, str] | None,
        write: bool,
    ) -> Effect[Json, ChatError]:
        def fail(reason: AnyReason) -> Effect[Never, ChatError]:
            return fx.fail(_errors.chat_error(path, reason))

        chosen: Method = method or ("POST" if body is not None or form is not None else "GET")
        request = http_request.make(chosen, f"{self._base_url}/{path}").bearer_token(
            redacted_value(self._access_token)
        )
        if params is not None:
            request = request.set_url_params(dict(params))
        if form is not None:
            request = request.body_form_data(form)
        elif body is not None:
            request = request.body_json_unsafe(body)

        def answered(response: HttpClientResponse) -> Effect[Json, ChatError]:
            ok = 200 <= response.status < 300
            retry_after = parse_retry_after(response.headers.get("retry-after"))

            def unreadable(error: HttpClientError) -> Effect[Never, ChatError]:
                if ok:
                    return fail(_errors.invalid_response(write, "invalid_json", error))
                return fail(
                    _errors.reason_for_status(response.status, write=write, retry_after=retry_after)
                )

            def read(json: Json) -> Effect[Json, ChatError]:
                if ok:
                    return fx.succeed(json)
                graph = _errors.graph_error(json)
                obj = _json.as_object(json)
                cause = obj["error"] if obj is not None and "error" in obj else json
                if graph is None:
                    return fail(
                        _errors.reason_for_status(
                            response.status, write=write, cause=cause, retry_after=retry_after
                        )
                    )
                return fail(
                    _errors.reason_for_graph_error(
                        graph, write=write, cause=cause, retry_after=retry_after
                    )
                )

            return response.json.match_effect(on_failure=unreadable, on_success=read)

        return (
            self._http.execute(request)
            .catch_all(
                lambda error: fail(_errors.transport(write, type(error.reason).__name__, error))
            )
            .flat_map(answered)
        )


class WhatsAppGraphApi(Tag[WhatsAppGraphApiService], key="@effect/chat-whatsapp/WhatsAppGraphApi"):
    """The Graph API client."""


def make(
    *,
    access_token: Redacted[str],
    base_url: str = DEFAULT_BASE_URL,
    max_retry_after: DurationInput | None = None,
) -> Effect[WhatsAppGraphApiService, Never, HttpClient]:
    """Builds the client from an ``HttpClient`` and a system user access
    token. ``max_retry_after`` caps the ``Retry-After`` a retry waits for;
    see ``WhatsAppGraphApiService``."""
    ceiling = None if max_retry_after is None else from_input_unsafe(max_retry_after)

    @fx.gen
    def body() -> Generator[Effect[Any, Never, HttpClient], Any, WhatsAppGraphApiService]:
        http = yield from HttpClient()
        return WhatsAppGraphApiService(http, access_token, base_url, ceiling)

    return body


def layer(
    *,
    access_token: Redacted[str],
    base_url: str = DEFAULT_BASE_URL,
    max_retry_after: DurationInput | None = None,
) -> Layer[WhatsAppGraphApi, Never, HttpClient]:
    """The client as a layer."""
    return _layer_effect(
        WhatsAppGraphApi,
        make(access_token=access_token, base_url=base_url, max_retry_after=max_retry_after),
    )


__all__ = [
    "DEFAULT_BASE_URL",
    "ChatError",
    "Method",
    "WhatsAppGraphApi",
    "WhatsAppGraphApiService",
    "layer",
    "make",
]
