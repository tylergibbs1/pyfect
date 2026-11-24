"""The webhook: one request, checked and run (Effect's
``internal/webhook.ts``)."""

from __future__ import annotations

import hmac
import re
from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Any, Never

import pyfect as fx
from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect.byte_size import ByteSize
from pyfect.chat.chat_error import ChatError
from pyfect.chat.telegram import _errors, _json
from pyfect.chat.telegram._receive import Outcome
from pyfect.http import server_response
from pyfect.http.incoming_message import MaxBodySize
from pyfect.http.server_error import HttpServerError, RequestParseError
from pyfect.http.server_request import ServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value

SECRET_HEADER = "x-telegram-bot-api-secret-token"
"""The header Telegram sends the webhook secret in."""

DEFAULT_MAX_BODY_BYTES = 1024 * 1024

LOGGED_INVALID = "telegram webhook: the update could not be read, answered 503"
LOGGED_NOT_ACCEPTED = (
    "telegram webhook: the handler refused the event or passed the deadline, answered 503"
)

_SECRET_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,256}")


def secret_token(op: str, token: Redacted[str]) -> Effect[str, ChatError]:
    """A secret token's value, if it keeps Telegram's rule with the
    adapter's floor of 32 characters."""
    secret = redacted_value(token)
    if _SECRET_TOKEN.fullmatch(secret) is None:
        return fx.fail(_errors.chat_error(op, _errors.invalid_request("invalid_secret_token")))
    return fx.succeed(secret)


@dataclass(frozen=True, kw_only=True)
class Options:
    secret: bytes
    max_body_size: ByteSize
    receive: Callable[[object], Effect[Outcome]]


def _status(code: int) -> HttpServerResponse:
    return server_response.empty(status=code)


def _read_failed(error: HttpServerError) -> int:
    reason = error.reason
    return 413 if isinstance(reason, RequestParseError) and reason.kind == "BodyTooLarge" else 400


def _is_update(value: object) -> bool:
    obj = _json.as_object(value)
    update_id = None if obj is None else obj.get("update_id")
    return isinstance(update_id, (int, float)) and not isinstance(update_id, bool)


def handle_request(request: ServerRequest, options: Options) -> Effect[HttpServerResponse]:
    """One webhook request.

    - 401 without the secret, compared in constant time, before the body is
      read. 413 past ``max_body_size``, 400 for a body that can't be read, is
      not JSON, nests past 64 levels or is not an update.
    - 200 once the update was accepted, answered or sent to
      ``on_unhandled``; 503 when its event was not accepted in time, or could
      not be read, so that Telegram sends it again.
    """

    @fx.gen
    def run() -> Generator[Effect[Any, Never, Any], Any, HttpServerResponse]:  # noqa: PLR0911
        header = request.headers.get(SECRET_HEADER)
        if header is None or not hmac.compare_digest(text_encode(header), options.secret):
            return _status(401)
        read: bytes | int = yield from request.bytes_.pipe(
            fx.provide_service(MaxBodySize, options.max_body_size)
        ).catch_all(lambda error: fx.succeed(_read_failed(error)))
        if isinstance(read, int):
            return _status(read)
        # Measured again: the request caches its body, so one read earlier under a larger
        # limit comes back whole.
        if len(read) > options.max_body_size:
            return _status(413)
        update = _json.parse(read)
        if not _is_update(update):
            return _status(400)
        outcome: Outcome = yield from options.receive(update)
        if outcome == "invalid":
            yield from fx.log_warning(LOGGED_INVALID)
            return _status(503)
        if outcome == "notAccepted":
            yield from fx.log_warning(LOGGED_NOT_ACCEPTED)
            return _status(503)
        return _status(200)

    return run
