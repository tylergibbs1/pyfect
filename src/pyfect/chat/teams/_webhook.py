"""The messaging endpoint: the body limit, the parse at the boundary, the
Bot Framework token, and where each activity goes."""

from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Any, Never

import pyfect as fx
from pyfect._core import Effect
from pyfect.byte_size import ByteSize
from pyfect.chat.chat_event import ChatEvent
from pyfect.chat.chat_handler import NotAccepted
from pyfect.chat.teams import _json
from pyfect.chat.teams._auth import Activity, Verify, tenant_of
from pyfect.chat.teams._interactions import InvokeResponse, is_submit_fallback
from pyfect.chat.teams._json import JsonObject
from pyfect.chat.teams._normalize import Context, is_targeted, normalize
from pyfect.duration import Duration
from pyfect.http import server_response
from pyfect.http.incoming_message import MaxBodySize
from pyfect.http.server_error import HttpServerError, RequestParseError
from pyfect.http.server_request import ServerRequest
from pyfect.http.server_response import HttpServerResponse

DEFAULT_MAX_BODY_BYTES = 1024 * 1024

UNAVAILABLE_KEYS = "teams webhook: the signing keys could not be read, answered 503"
UNAVAILABLE_NORMALIZE = "teams webhook: the activity could not be normalised, answered 503"
UNAVAILABLE_NOT_ACCEPTED = "teams webhook: the handler refused the event, answered 503"
UNAVAILABLE_DEADLINE = "teams webhook: the request passed its deadline, answered 503"


@dataclass(frozen=True, kw_only=True)
class Options:
    verify: Verify
    context: Context
    handle: Callable[[ChatEvent], Effect[None, NotAccepted]]
    on_unhandled: Callable[[JsonObject], Effect[None]]
    invoke: Callable[[JsonObject], Effect[InvokeResponse]]
    command: Callable[[JsonObject], Effect[None]]
    deadline: Duration
    max_body_size: ByteSize


def _status(code: int) -> HttpServerResponse:
    return server_response.empty(status=code)


def _respond(response: InvokeResponse) -> HttpServerResponse:
    if response.body is None:
        return _status(response.status)
    return server_response.json_unsafe(response.body, status=response.status)


def _too_large(error: HttpServerError) -> bool:
    reason = error.reason
    return isinstance(reason, RequestParseError) and reason.kind == "BodyTooLarge"


def _read_body(request: ServerRequest, max_body_size: ByteSize) -> Effect[bytes | int]:
    """The body, or the status that refuses it: 413 past ``max_body_size``,
    400 when it can't be read. The length is checked again because the
    request caches its body: one read earlier under a larger limit comes
    back whole."""
    return (
        request.bytes_.map(lambda body: 413 if len(body) > max_body_size else body)
        .catch_all(lambda error: fx.succeed(413 if _too_large(error) else 400))
        .pipe(fx.provide_service(MaxBodySize, max_body_size))
    )


def handle_request(request: ServerRequest, options: Options) -> Effect[HttpServerResponse]:
    """One Bot Framework activity.

    - 413 past the body limit, 400 for a body that is not a JSON object.
    - 403 when the token, its ``serviceurl``, the channel or the tenant does
      not check out, and 503 when the signing keys can't be read.
    - A targeted activity is classified first, whatever its type: a message
      takes the command path, an invoke goes to the interaction handler, and
      anything else is answered 200 and dropped. None reaches
      ``ChatHandler`` or ``on_unhandled``.
    - An invoke, or a card's submit fallback, goes to the interaction
      handler, whose answer is the response.
    - Every other activity is normalised and handed to the ``ChatHandler``
      one event at a time: 200 when all succeed, 503 when one fails
      ``NotAccepted``, or when a ``message`` can't be normalised. Any other
      activity that gives no event goes to ``on_unhandled`` and is answered
      200.
    - 503 past ``deadline``, the handler interrupted. Each 503 is logged
      with its own message.
    """

    @fx.gen
    def run() -> Generator[Effect[Any, Never, Any], Any, HttpServerResponse]:  # noqa: PLR0911
        body = yield from _read_body(request, options.max_body_size)
        if isinstance(body, int):
            return _status(body)
        activity = _json.as_object(_json.parse(body.decode("utf-8", "replace")))
        if activity is None:
            return _status(400)
        verdict = yield from options.verify(
            request.headers.get("authorization"),
            Activity(
                service_url=activity.get("serviceUrl"),
                channel_id=activity.get("channelId"),
                tenant_id=tenant_of(activity),
            ),
        )
        if verdict == "forbidden":
            return _status(403)
        if verdict == "unavailable":
            return (yield from fx.log_warning(UNAVAILABLE_KEYS).as_(_status(503)))
        kind = activity.get("type")
        if is_targeted(activity):
            if kind == "message":
                return (yield from options.command(activity).as_(_status(200)))
            if kind == "invoke":
                return _respond((yield from options.invoke(activity)))
            return _status(200)
        if kind == "invoke" or is_submit_fallback(activity):
            return _respond((yield from options.invoke(activity)))
        events = normalize(activity, options.context)
        if not events and kind == "message":
            return (yield from fx.log_warning(UNAVAILABLE_NORMALIZE).as_(_status(503)))
        if not events:
            return (yield from options.on_unhandled(activity).as_(_status(200)))
        return (
            yield from fx.for_each(events, options.handle, discard=True)
            .as_(_status(200))
            .catch_all(lambda _: fx.log_warning(UNAVAILABLE_NOT_ACCEPTED).as_(_status(503)))
        )

    def answered(response: fx.Option[HttpServerResponse]) -> Effect[HttpServerResponse]:
        if response is None:
            return fx.log_warning(UNAVAILABLE_DEADLINE).as_(_status(503))
        return fx.succeed(response.value)

    return run.timeout_option(options.deadline).flat_map(answered)
