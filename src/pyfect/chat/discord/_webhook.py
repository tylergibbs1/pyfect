"""The HTTP interactions endpoint: Discord's Ed25519 signature, the bounded
timestamp and body, and the request's parse at the boundary."""

from __future__ import annotations

import re
from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass
from typing import Any, Never

import pyfect as fx
from pyfect import clock as _clock
from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect.byte_size import ByteSize
from pyfect.chat.chat_error import ChatError
from pyfect.chat.chat_interaction import Handler
from pyfect.chat.discord import _interactions, _json
from pyfect.chat.discord._adapter import SendCallback
from pyfect.chat.discord._interactions import AnswerTo, Payload
from pyfect.crypto import signature as _signature
from pyfect.crypto.signature import Signature
from pyfect.deferred import Deferred
from pyfect.duration import Duration
from pyfect.http import server_response
from pyfect.http.incoming_message import MaxBodySize
from pyfect.http.server_request import ServerRequest
from pyfect.http.server_response import HttpServerResponse

MAX_SKEW_SECONDS = 60 * 5
"""How far a request's timestamp may be from now. Discord signs the timestamp
with the body; a request older than this is refused as a replay."""

DEFAULT_MAX_BODY_BYTES = 256 * 1024
"""An interaction is a few kilobytes; a modal submit or a command with its
resolved data stays far under this."""

_TIMESTAMP = re.compile(r"[0-9]{1,20}")
"""Whole seconds; twenty digits is far past any skew, and bounds the
conversion of an attacker's header."""
_SIGNATURE = re.compile(r"[0-9a-fA-F]{128}")
"""An Ed25519 signature is 64 bytes, 128 hex digits."""
_PUBLIC_KEY = re.compile(r"[0-9a-fA-F]{64}")

type Headers = Mapping[str, str]
type Verify = Callable[[Headers, bytes], Effect[bool]]


def parse_public_key(public_key: str) -> bytes:
    """The application's public key, as the developer portal shows it: 64 hex
    digits. Anything else raises ``ValueError`` when the layer is made."""
    if _PUBLIC_KEY.fullmatch(public_key) is None:
        raise ValueError("public_key must be the application's public key: 64 hex digits")
    return bytes.fromhex(public_key)


def make_verifier(public_key: bytes) -> Effect[Verify, Never, Signature]:
    """Checks Discord's request signature: an Ed25519 signature, in
    ``X-Signature-Ed25519``, of ``X-Signature-Timestamp`` followed by the
    body, and a timestamp within five minutes of now. A key that can't be
    built is a defect; a crypto failure fails the check."""

    @fx.gen
    def build() -> Generator[Effect[Any, Any, Signature], Any, Verify]:
        service = yield from Signature()
        key = yield from _signature.public_key(_signature.ed25519, public_key).or_die()

        def verify(headers: Headers, body: bytes) -> Effect[bool]:
            timestamp = headers.get("x-signature-timestamp")
            signature = headers.get("x-signature-ed25519")
            if (
                timestamp is None
                or signature is None
                or _TIMESTAMP.fullmatch(timestamp) is None
                or _SIGNATURE.fullmatch(signature) is None
            ):
                return fx.succeed(False)
            signed = bytes.fromhex(signature)

            def checked(now: float) -> Effect[bool]:
                if abs(now / 1000 - int(timestamp)) > MAX_SKEW_SECONDS:
                    return fx.succeed(False)
                message = text_encode(timestamp) + body
                return service.verify(key, signed, message).or_else_succeed(lambda _: False)

            return _clock.current_time_millis().flat_map(checked)

        return verify

    return build


def _read_body(request: ServerRequest, max_body_size: ByteSize) -> Effect[bytes | None]:
    """The body, or ``None`` past ``max_body_size`` or when it can't be read,
    both answered 413. The length is checked again because the request caches
    its body: one read earlier under a larger limit comes back as it was."""
    return (
        request.bytes_.map(lambda body: None if len(body) > max_body_size else body)
        .or_else_succeed(lambda _: None)
        .pipe(fx.provide_service(MaxBodySize, max_body_size))
    )


def _status(code: int) -> HttpServerResponse:
    return server_response.empty(status=code)


type Interaction = Callable[[object, Duration, SendCallback], Effect[None, Never, Handler]]


@dataclass(frozen=True, kw_only=True)
class Options:
    verify: Verify
    interaction: Interaction
    deadline: Duration
    max_body_size: ByteSize


def handle_request(
    request: ServerRequest, options: Options
) -> Effect[HttpServerResponse, Never, Handler]:
    """One request to the interactions endpoint.

    - 413 past the body limit, 401 for a bad signature or timestamp, 400 for
      a body that is not a JSON object.
    - ``PING`` is answered ``PONG``.
    - Anything else goes to the interaction entry, whose callback is the
      response: 200 with the callback as JSON, or 204 when the entry answers
      nothing (a late handler, a command nobody handles, a payload that is
      not the adapter's), and Discord shows its own failure.
    """

    @fx.gen
    def run() -> Generator[Effect[Any, Never, Any], Any, HttpServerResponse]:
        body = yield from _read_body(request, options.max_body_size)
        if body is None:
            return _status(413)
        if not (yield from options.verify(request.headers, body)):
            return _status(401)
        payload = _json.as_object(_json.parse(body.decode("utf-8", "replace")))
        if payload is None:
            return _status(400)
        if _interactions.is_ping(payload):
            return server_response.json_unsafe(_interactions.PONG)
        answered: Deferred[Payload] = yield from Deferred[Payload].make()

        def send(_op: str, _to: AnswerTo, callback: Payload) -> Effect[None, ChatError]:
            return answered.succeed(callback).as_void()

        # Detached, so a refusal reported after the answer still runs.
        fiber = yield from options.interaction(payload, options.deadline, send).fork_daemon()
        yield from answered.wait().as_void().race_first(fiber.await_exit().as_void())
        # The entry may end in the same step it answered: the deferred decides.
        polled = yield from answered.poll()
        if polled is None:
            return _status(204)
        return server_response.json_unsafe((yield from polled))

    return run
