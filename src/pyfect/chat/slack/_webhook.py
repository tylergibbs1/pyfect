"""The Events API and Interactivity routes: Slack's ``v0`` signature, the body
limit, and the request's parse at the boundary."""

from __future__ import annotations

import re
from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass
from typing import Any, Never
from urllib.parse import parse_qsl

import pyfect as fx
from pyfect import clock as _clock
from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect.byte_size import ByteSize
from pyfect.chat.chat_error import ChatError
from pyfect.chat.chat_event import ChatEvent
from pyfect.chat.chat_handler import NotAccepted
from pyfect.chat.chat_interaction import Late
from pyfect.chat.slack import _json
from pyfect.chat.slack._interactions import Body
from pyfect.chat.slack._normalize import normalize
from pyfect.crypto import mac as _mac
from pyfect.crypto.mac import Mac
from pyfect.duration import Duration
from pyfect.http import server_response
from pyfect.http.incoming_message import MaxBodySize
from pyfect.http.server_request import ServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value

MAX_SKEW_SECONDS = 60 * 5
"""How far a request's timestamp may be from now, as Slack recommends."""

DEFAULT_MAX_BODY_BYTES = 1024 * 1024

_TIMESTAMP = re.compile(r"[0-9]{1,20}")
"""Whole seconds; twenty digits is far past any skew, and bounds the
conversion of an attacker's header."""
_HEX = re.compile(r"[0-9a-fA-F]+")

type Headers = Mapping[str, str]
type Verify = Callable[[Headers, bytes], Effect[bool]]


def make_verifier(signing_secret: Redacted[str]) -> Effect[Verify, Never, Mac]:
    """Checks Slack's ``v0`` request signature: an HMAC-SHA256 of
    ``v0:{timestamp}:{body}`` with the signing secret, compared in constant
    time, and a timestamp within five minutes of now. A key that can't be
    built is a defect; a crypto failure fails the check."""

    @fx.gen
    def build() -> Generator[Effect[Any, Any, Mac], Any, Verify]:
        service = yield from Mac()
        key = yield from _mac.key(
            _mac.hmac_sha256, text_encode(redacted_value(signing_secret))
        ).or_die()

        def verify(headers: Headers, body: bytes) -> Effect[bool]:
            timestamp = headers.get("x-slack-request-timestamp")
            signature = headers.get("x-slack-signature")
            if timestamp is None or signature is None or _TIMESTAMP.fullmatch(timestamp) is None:
                return fx.succeed(False)
            hex = signature[3:] if signature.startswith("v0=") else None
            if hex is None or len(hex) % 2 == 1 or _HEX.fullmatch(hex) is None:
                return fx.succeed(False)
            tag = bytes.fromhex(hex)

            def checked(now: float) -> Effect[bool]:
                if abs(now / 1000 - int(timestamp)) > MAX_SKEW_SECONDS:
                    return fx.succeed(False)
                message = text_encode(f"v0:{timestamp}:") + body
                return service.verify(key, tag, message).or_else_succeed(lambda _: False)

            return _clock.current_time_millis().flat_map(checked)

        return verify

    return build


def _read_body(request: ServerRequest, max_body_size: ByteSize) -> Effect[bytes | None]:
    """The body, or ``None`` past ``max_body_size`` or when it can't be read,
    both answered 413. The length is checked again because the request
    caches its body: one read earlier under a larger limit comes back as it
    was."""
    return (
        request.bytes_.map(lambda body: None if len(body) > max_body_size else body)
        .or_else_succeed(lambda _: None)
        .pipe(fx.provide_service(MaxBodySize, max_body_size))
    )


def _status(code: int) -> HttpServerResponse:
    return server_response.empty(status=code)


UNAVAILABLE_BOT_USER = "slack webhook: the bot user could not be read, answered 503"
UNAVAILABLE_NOT_ACCEPTED = "slack webhook: the handler refused the event, answered 503"
UNAVAILABLE_DEADLINE = "slack webhook: the request passed its deadline, answered 503"


@dataclass(frozen=True, kw_only=True)
class Options:
    verify: Verify
    app_id: str
    team_id: str
    bot_user_id: Effect[str, ChatError]
    handle: Callable[[ChatEvent], Effect[None, NotAccepted]]
    deadline: Duration
    max_body_size: ByteSize


def handle_request(request: ServerRequest, options: Options) -> Effect[HttpServerResponse]:
    """One Events API request.

    - 413 past the body limit, 401 for a bad signature, 400 for a body that
      is not a JSON object.
    - ``url_verification`` is answered with its challenge.
    - An envelope for another app or workspace, or of another type, is
      answered 200 and dropped, so Slack does not retry it.
    - 503 when the bot user can't be read, the handler fails
      ``NotAccepted``, or the whole request takes longer than the deadline.
      Each is logged with its own message.
    """

    @fx.gen
    def run() -> Generator[Effect[Any, Never, Any], Any, HttpServerResponse]:  # noqa: PLR0911
        body = yield from _read_body(request, options.max_body_size)
        if body is None:
            return _status(413)
        if not (yield from options.verify(request.headers, body)):
            return _status(401)
        envelope = _json.as_object(_json.parse(body.decode("utf-8", "replace")))
        if envelope is None:
            return _status(400)
        if envelope.get("type") == "url_verification":
            challenge = envelope.get("challenge")
            return server_response.text(challenge) if isinstance(challenge, str) else _status(400)
        if envelope.get("type") != "event_callback" or envelope.get("api_app_id") != options.app_id:
            return _status(200)
        bot_user_id = yield from options.bot_user_id.catch_all(
            lambda error: fx.log_error(UNAVAILABLE_BOT_USER, error).as_(None)
        )
        if bot_user_id is None:
            return _status(503)
        events = normalize(envelope, team_id=options.team_id, bot_user_id=bot_user_id)
        return (
            yield from fx.for_each(events, options.handle, discard=True)
            .as_(_status(200))
            .catch_all(lambda _: fx.log_warning(UNAVAILABLE_NOT_ACCEPTED).as_(_status(503)))
        )

    def answered(response: HttpServerResponse | None) -> Effect[HttpServerResponse]:
        if response is None:
            return fx.log_warning(UNAVAILABLE_DEADLINE).as_(_status(503))
        return fx.succeed(response)

    return run.timeout_option(options.deadline).map(_unsome).flat_map(answered)


def _unsome[A](option: fx.Option[A]) -> A | None:
    return None if option is None else option.value


@dataclass(frozen=True, kw_only=True)
class InteractivityOptions:
    verify: Verify
    app_id: str
    interaction: Callable[[object, Duration], Effect[Body]]
    deadline: Duration
    max_body_size: ByteSize


def form_fields(text: str) -> dict[str, str]:
    """A form body's fields, as ``URLSearchParams`` reads them; a repeated
    field keeps its first value."""
    fields: dict[str, str] = {}
    for key, value in parse_qsl(text, keep_blank_values=True, errors="replace"):
        fields.setdefault(key, value)
    return fields


def handle_interactivity(
    request: ServerRequest, options: InteractivityOptions
) -> Effect[HttpServerResponse]:
    """One Interactivity request: a form-encoded body whose ``payload`` field
    holds the JSON, or a slash command's, whose fields are the payload.

    - 413 past the body limit, 401 for a bad signature, 400 for a body with
      neither a ``payload`` that is a JSON object nor a ``command``.
    - A payload or command for another app is answered 200 and dropped.
    - ``Late`` is answered 503, which keeps a modal open. Anything else is a
      200, with the body as JSON when there is one.
    """

    @fx.gen
    def run() -> Generator[Effect[Any, Never, Any], Any, HttpServerResponse]:  # noqa: PLR0911
        body = yield from _read_body(request, options.max_body_size)
        if body is None:
            return _status(413)
        if not (yield from options.verify(request.headers, body)):
            return _status(401)
        form = form_fields(body.decode("utf-8", "replace"))
        field = form.get("payload")
        payload: object = (
            _json.parse(field) if field is not None else form if "command" in form else None
        )
        obj = _json.as_object(payload)
        if obj is None:
            return _status(400)
        if obj.get("api_app_id") != options.app_id:
            return _status(200)
        answer: Body = yield from options.interaction(obj, options.deadline)
        if answer is None:
            return _status(200)
        if isinstance(answer, Late):
            return _status(503)
        return server_response.json_unsafe(answer)

    return run
