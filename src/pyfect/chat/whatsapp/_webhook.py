"""The webhook: Meta's subscription check, the ``X-Hub-Signature-256`` check,
the body limit, and one delivery's updates in order."""

from __future__ import annotations

import hmac
import re
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Never
from urllib.parse import parse_qsl, urlsplit

import pyfect as fx
from pyfect import clock as _clock
from pyfect._core import Effect, _call_user
from pyfect._fiber import Fiber
from pyfect._js import text_encode
from pyfect.byte_size import ByteSize
from pyfect.chat import chat_interaction as ci
from pyfect.chat.chat_error import Unsupported
from pyfect.chat.chat_event import ChatEvent, MessageCreated, ReactionAdded
from pyfect.chat.chat_handler import NotAccepted
from pyfect.chat.whatsapp import _json
from pyfect.chat.whatsapp._errors import chat_error
from pyfect.chat.whatsapp._normalize import Inbound, group_messages
from pyfect.crypto import mac as _mac
from pyfect.crypto.mac import Mac
from pyfect.duration import Duration, millis
from pyfect.http import server_response
from pyfect.http.incoming_message import MaxBodySize
from pyfect.http.server_error import HttpServerError, RequestParseError
from pyfect.http.server_request import ServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value

DEFAULT_MAX_BODY_BYTES = 3 * 1024 * 1024
DEFAULT_DEADLINE = "10 seconds"
CLICK_DEADLINE = "3 seconds"

_CLICK_MARGIN_MILLIS = 250
"""What a click leaves of the deadline for the rest of the request."""

_SIGNATURE = re.compile(r"sha256=((?:[0-9a-fA-F]{2})++)")

type Headers = Mapping[str, str]
type Verify = Callable[[Headers, bytes], Effect[bool]]
type OnUpdate = Callable[[Any], Effect[None, NotAccepted]]

LOGGED_NOT_ACCEPTED = "whatsapp webhook: an update was refused, answered 503"
LOGGED_DEADLINE = "whatsapp webhook: the request passed its deadline, answered 503"
LOGGED_NO_HANDLER = "whatsapp webhook: a click arrived with no ChatInteraction.Handler, dropped"
LOGGED_GROUP = "whatsapp webhook: group messages are not supported, dropped"


def make_verifier(app_secret: Redacted[str]) -> Effect[Verify, Never, Mac]:
    """Checks Meta's ``X-Hub-Signature-256``: ``sha256=`` and the hex
    HMAC-SHA256 of the raw body with the app secret, compared in constant
    time by ``Mac``. An app secret that can't make a key is a defect; a
    crypto failure fails the check."""

    @fx.gen
    def build() -> Generator[Effect[Any, Any, Mac], Any, Verify]:
        service = yield from Mac()
        key = yield from _mac.key(
            _mac.hmac_sha256, text_encode(redacted_value(app_secret))
        ).or_die()

        def verify(headers: Headers, body: bytes) -> Effect[bool]:
            signature = headers.get("x-hub-signature-256")
            match = None if signature is None else _SIGNATURE.fullmatch(signature)
            if match is None:
                return fx.succeed(False)
            tag = bytes.fromhex(match.group(1))
            return service.verify(key, tag, body).or_else_succeed(lambda _: False)

        return verify

    return build


def _query(request: ServerRequest) -> dict[str, str]:
    """The query's fields, as ``URLSearchParams.get`` reads them: a repeated
    field keeps its first value."""
    fields: dict[str, str] = {}
    for key, value in parse_qsl(
        urlsplit(request.url).query, keep_blank_values=True, errors="replace"
    ):
        fields.setdefault(key, value)
    return fields


def handle_verification(request: ServerRequest, verify_token: Redacted[str]) -> HttpServerResponse:
    """Meta's subscription check: ``hub.mode=subscribe`` with the verify
    token, compared in constant time, is answered with ``hub.challenge``;
    anything else 403."""
    params = _query(request)
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    matches = token is not None and hmac.compare_digest(
        text_encode(token), text_encode(redacted_value(verify_token))
    )
    if params.get("hub.mode") == "subscribe" and matches and challenge is not None:
        return server_response.text(challenge)
    return server_response.empty(status=403)


@dataclass(frozen=True, kw_only=True)
class ReceiveOptions:
    handle: Callable[[ChatEvent], Effect[None, NotAccepted]]
    on_update: OnUpdate | None
    click_deadline: Effect[Duration]
    """How long the click about to run may take."""


def _click(
    item: ci.ButtonClicked | ci.SelectChanged, options: ReceiveOptions
) -> Effect[None, Never, Any]:
    def with_handler(found: fx.Option[ci.HandlerService]) -> Effect[None]:
        if found is None:
            return fx.log_warning(LOGGED_NO_HANDLER)
        handler = found.value

        def replied(reply: object) -> Effect[None]:
            if not isinstance(reply, ci.OpenModal):
                return fx.void
            refusal = handler.refused(
                item, chat_error("openModal", Unsupported(capability="modals"))
            )
            # Awaited only for what is left of the click's share, then left running.
            return (
                refusal.fork_daemon()
                .flat_map(
                    lambda fiber: options.click_deadline.flat_map(
                        lambda left: fiber.await_exit().timeout_option(left)
                    )
                )
                .as_void()
            )

        return (
            options.click_deadline.flat_map(lambda deadline: ci.handle(item, deadline))
            .pipe(fx.provide_service(ci.Handler, handler))
            .flat_map(replied)
        )

    return fx.service_option(ci.Handler).flat_map(with_handler)


def receive(items: Sequence[Inbound], options: ReceiveOptions) -> Effect[None, NotAccepted, Any]:
    """Runs one delivery's updates in order. A ``NotAccepted`` stops the
    rest. A click never fails: ``Ack`` and ``Late`` count as handled, and
    ``OpenModal`` is refused with ``Unsupported("modals")``."""

    def one(item: Inbound) -> Effect[None, NotAccepted, Any]:
        if isinstance(item, (MessageCreated, ReactionAdded)):
            return options.handle(item)
        if isinstance(item, (ci.ButtonClicked, ci.SelectChanged)):
            return _click(item, options)
        on_update = options.on_update
        return fx.void if on_update is None else _call_user(on_update, item)

    return fx.for_each(items, one, discard=True)


@dataclass(frozen=True, kw_only=True)
class Options:
    verify: Verify
    normalize: Callable[[object], Sequence[Inbound]]
    handle: Callable[[ChatEvent], Effect[None, NotAccepted]]
    on_update: OnUpdate | None
    deadline: Duration
    max_body_size: ByteSize


def _status(code: int) -> HttpServerResponse:
    return server_response.empty(status=code)


def _read_failed(error: HttpServerError) -> int:
    reason = error.reason
    return 413 if isinstance(reason, RequestParseError) and reason.kind == "BodyTooLarge" else 400


def _work(request: ServerRequest, options: Options) -> Effect[HttpServerResponse, Never, Any]:
    @fx.gen
    def run() -> Generator[Effect[Any, Never, Any], Any, HttpServerResponse]:
        until: float = (yield from _clock.current_time_millis()) + options.deadline.to_millis()
        read: bytes | int = yield from request.bytes_.pipe(
            fx.provide_service(MaxBodySize, options.max_body_size)
        ).catch_all(lambda error: fx.succeed(_read_failed(error)))
        if isinstance(read, int):
            return _status(read)
        # Measured again: the request caches its body, so one read earlier under a larger
        # limit comes back whole.
        if len(read) > options.max_body_size:
            return _status(413)
        if not (yield from options.verify(request.headers, read)):
            return _status(401)
        envelope = _json.as_object(_json.parse(read))
        if envelope is None:
            return _status(400)
        if envelope.get("object") != "whatsapp_business_account":
            return _status(200)
        if group_messages(envelope) > 0:
            yield from fx.log_debug(LOGGED_GROUP)

        def left(now: float) -> Duration:
            return millis(max(0.0, until - now - _CLICK_MARGIN_MILLIS))

        return (
            yield from receive(
                options.normalize(envelope),
                ReceiveOptions(
                    handle=options.handle,
                    on_update=options.on_update,
                    click_deadline=_clock.current_time_millis().map(left),
                ),
            )
            .as_(_status(200))
            .catch_all(lambda _: fx.log_warning(LOGGED_NOT_ACCEPTED).as_(_status(503)))
        )

    return run


def handle_request(
    request: ServerRequest, options: Options
) -> Effect[HttpServerResponse, Never, Any]:
    """One webhook POST.

    - 413 past the body limit, 400 for a body that can't be read, then 401
      for a bad signature and 400 for a body that is not a JSON object
      (nested past ``_json.MAX_DEPTH`` included). Another ``object`` than
      ``whatsapp_business_account`` is answered 200 and dropped.
    - 503 when an update fails ``NotAccepted``, or the whole request takes
      longer than the deadline. Meta then delivers the batch again.
    - A click gets what is left of the deadline, less a margin.
    - At the deadline the work is interrupted without waiting for its
      finalizers, so a slow release can't hold the 503 past Meta's cutoff.
    """

    # Masked, so a cancellation can't land between forking the worker and arranging its
    # interruption; only the wait itself is interruptible.
    def body(restore: fx.Restore) -> Effect[HttpServerResponse, Never, Any]:
        def started(fiber: Fiber[HttpServerResponse, Never]) -> Effect[HttpServerResponse]:
            # Interrupted without being awaited, here and at the deadline, so no finalizer
            # delays the answer.
            stop = fiber.interrupt().fork_daemon().as_void()
            waited: Effect[fx.Option[HttpServerResponse]] = restore(
                fiber.join().timeout_option(options.deadline)
            )

            def answered(response: fx.Option[HttpServerResponse]) -> Effect[HttpServerResponse]:
                if response is not None:
                    return fx.succeed(response.value)
                return stop.and_then(fx.log_warning(LOGGED_DEADLINE)).as_(_status(503))

            return waited.on_interrupt(stop).flat_map(answered)

        return _work(request, options).fork_daemon().flat_map(started)

    return fx.uninterruptible_mask(body)
