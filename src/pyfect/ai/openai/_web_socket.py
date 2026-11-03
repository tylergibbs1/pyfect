"""The Responses API's WebSocket mode (Effect's ``makeSocket``): response
streams sent as ``response.create`` messages over one connection to
``/responses``, one at a time.

The connection is shared through an ``RcRef`` (kept 60 seconds after its
last use). Each request is a turn with its own queue, which the reader
ends at a terminal event or fails at an error event; a turn still current
when its stream is left, or that failed with anything but
``previous_response_not_found``, replaces the connection for the next one.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Never, NotRequired, TypedDict, cast

import pyfect as fx
from pyfect import cause
from pyfect import schema as S
from pyfect import scope as scope_mod
from pyfect import stream as St
from pyfect._core import Effect, uninterruptible_mask
from pyfect._json_text import parse as parse_json_text
from pyfect.ai import _provider as P
from pyfect.ai import ai_error as E
from pyfect.ai import response_id_tracker as RIT
from pyfect.ai.ai_error import AiError
from pyfect.ai.openai import _schema as W
from pyfect.ai.openai._errors import OPENAI
from pyfect.cause import Cause
from pyfect.errors import Done
from pyfect.exit import Exit
from pyfect.http import request as http_request
from pyfect.http import response as http_response
from pyfect.http.client import HttpClientService
from pyfect.http.response import HttpClientResponse
from pyfect.queue import Queue
from pyfect.rc_ref import RcRef
from pyfect.scope import CloseableScope, Scope
from pyfect.semaphore import Semaphore
from pyfect.socket import SocketError, Writer, make_web_socket
from pyfect.stream import Stream

type ResponseStream = tuple[HttpClientResponse, Stream[W.ResponseStreamEvent, AiError]]
type _Turn = Queue[W.ResponseStreamEvent, AiError | Done]
type _Request = http_request.HttpClientRequest


@dataclass(frozen=True)
class SocketService:
    """Response streams over a WebSocket connection (Effect's
    ``OpenAiSocket``)."""

    create_response_stream: Callable[[W.CreateResponse], Effect[ResponseStream, AiError]]


_ERROR_TYPE_TO_STATUS = {
    "invalid_request_error": 400,
    "invalid_api_key_error": 401,
    "insufficient_quota_error": 429,
    "rate_limit_error": 429,
    "service_unavailable_error": 503,
}
_RESPONSE_NOT_FOUND = re.compile(r"^gRPC error: Response with id=\S+ not found\Z")
_IDLE_TIME_TO_LIVE = 60.0


class _NestedError(TypedDict):
    type: NotRequired[str]
    code: NotRequired[str]
    message: str


class _ErrorEvent(TypedDict):
    """An error event with its details under ``error`` (xAI sends ``code``
    in place of ``type``, and may leave ``type`` out)."""

    type: NotRequired[Literal["error"]]
    status: NotRequired[int]
    error: _NestedError


_decode_error_event = P.wire_parser_option(S.Struct(_ErrorEvent), _ErrorEvent)


def _request_details(request: _Request) -> E.HttpRequestDetails:
    return P.request_details(request, secret_headers=OPENAI.secret_headers)


def _transport_error(request: _Request, description: str) -> AiError:
    return AiError(
        module="OpenAiClient",
        method="createResponseStream",
        reason=E.NetworkError(
            reason="TransportError", request=_request_details(request), description=description
        ),
    )


def _read_message(
    message: bytes | str,
) -> tuple[dict[str, Any], dict[str, Any]] | W.ResponseStreamEvent | None:
    """A message as an error event (its details and the event), an event,
    or ``None`` for one that is neither."""
    try:
        json = parse_json_text(message.decode() if isinstance(message, bytes) else message)
    except ValueError:
        return None
    nested = _decode_error_event(json)
    if nested is not None:
        return {**nested["error"]}, {**nested}
    event = W.parse_event(json)
    if event is not None and event.get("type") == "error":
        return event, event
    return event


def _event_error(
    error: dict[str, Any], event: dict[str, Any], request: _Request
) -> tuple[AiError, bool]:
    """The ``AiError`` of an error event, and whether it says the previous
    response is gone (``LanguageModel`` retries those with the full prompt
    on the same connection)."""
    kind = error.get("type")
    code = error.get("code")
    if isinstance(code, str):
        error_type = code
    elif kind == "api_error" and _RESPONSE_NOT_FOUND.match(error["message"]):
        error_type = "previous_response_not_found"
    else:
        error_type = kind if isinstance(kind, str) else "unknown"
    not_found = error_type == "previous_response_not_found"
    raw_status = event.get("status")
    if not_found:
        status = 400
    elif isinstance(raw_status, int):
        status = raw_status
    else:
        status = _ERROR_TYPE_TO_STATUS.get(error_type, 500)
    body = P.dumps(error)
    reason = E.reason_from_http_status(
        status=status,
        description=body,
        metadata=error,
        http={"body": body, "request": _request_details(request)},
    )
    return AiError(module="OpenAiClient", method="createResponseStream", reason=reason), not_found


class _Connection:
    """One WebSocket connection and the turn streaming on it."""

    def __init__(self, writer: Writer, request: _Request) -> None:
        self._writer = writer
        self._request = request
        self.current: _Turn | None = None

    def send(self, message: W.CreateResponse) -> Effect[None, AiError]:
        text = P.dumps({"type": "response.create", **message})
        return self._writer.write(text).map_error(
            lambda _: _transport_error(self._request, "Failed to send message over WebSocket")
        )

    def handle(self, message: bytes | str) -> None:
        turn = self.current
        if turn is None:
            return
        read = _read_message(message)
        if read is None:
            return
        if isinstance(read, tuple):
            failure, not_found = _event_error(*read, self._request)
            # Other errors leave the turn current, so leaving it replaces
            # the connection.
            if not_found:
                self.current = None
            turn.fail_cause_unsafe(cause.fail(failure))
            return
        turn.offer_unsafe(read)
        if read.get("type") in W.TERMINAL_EVENT_TYPES:
            self.current = None
            cast("Queue[Any, Done]", turn).end_unsafe()

    def fail_turn(self, failure: Cause[Any]) -> Effect[None]:
        turn = self.current
        return fx.void if turn is None else turn.fail_cause(failure).as_(None)


def _open(
    request: _Request, tracker: RIT.Service, invalidate: Effect[None]
) -> Effect[_Connection, Never, Any]:
    """Connect, and read messages into the current turn until the
    connection ends (which ``invalidate``s it)."""

    @fx.gen
    def acquire():
        scope: CloseableScope = yield from Scope()
        url = re.sub(r"^http", "ws", request.url)
        socket = yield from make_web_socket(url, headers=dict(request.headers.items()))
        connection = _Connection((yield from socket.writer), request)

        def on_close(_: Exit[Any, Any]) -> Effect[None]:
            return fx.sync(tracker.clear_unsafe)

        yield from scope.add_finalizer(on_close)

        @fx.gen
        def read():
            reader = yield from socket.reader
            while True:
                for message in (yield from reader.pull):
                    connection.handle(message)

        def transport(error: SocketError) -> Effect[Never, AiError]:
            return fx.fail(_transport_error(request, error.message))

        reading: Effect[Any, Any, Any] = (
            scope_mod.scoped(read)
            .pipe(fx.catch_tag(SocketError, transport))
            .catch_cause(connection.fail_turn)
            .ensuring(invalidate)
        )
        yield from scope_mod.fork_scoped(reading, start_immediately=True)
        return connection

    return acquire


def make(
    http_client: Effect[HttpClientService[Any], Any, Any],
) -> Effect[tuple[SocketService, RIT.Service], Never, Any]:
    """WebSocket mode over the client ``http_client`` gives, primed with a
    first connection, and the response id tracker it clears when a
    connection closes."""

    @fx.gen
    def build():
        tracker: RIT.Service = yield from RIT.make
        socket_scope: CloseableScope = yield from Scope()
        make_request: Effect[_Request] = http_client.flat_map(
            lambda http: http.preprocess(http_request.post("/responses"))
        ).or_die()

        def forget() -> Effect[None]:
            # A connection that ends is forgotten; ``ref`` is bound by then.
            return ref.invalidate()

        invalidate = scope_mod.fork_in(
            fx.suspend(forget), socket_scope, start_immediately=True
        ).as_(None)
        ref: RcRef[_Connection, Never] = yield from RcRef.make(
            make_request.flat_map(lambda request: _open(request, tracker, invalidate)),
            idle_time_to_live=_IDLE_TIME_TO_LIVE,
        )
        yield from scope_mod.scoped(ref.get())
        semaphore: Semaphore = yield from Semaphore.make(1)
        request: _Request = yield from make_request
        service = SocketService(lambda options: _stream(ref, semaphore, request, options))
        return service, tracker

    return build


def _stream(
    ref: RcRef[_Connection, Never],
    semaphore: Semaphore,
    request: _Request,
    options: W.CreateResponse,
) -> Effect[ResponseStream, AiError]:
    @fx.gen
    def open_turn():
        scope: CloseableScope = yield from Scope()
        # One request at a time; waiting for the permit stays interruptible.
        yield from uninterruptible_mask(
            lambda restore: restore(semaphore.take(1)).flat_map(
                lambda _: scope.add_finalizer(lambda _: semaphore.release(1))
            )
        )
        connection: _Connection = yield from ref.get()
        turn: _Turn = yield from Queue[W.ResponseStreamEvent, AiError | Done].unbounded()
        connection.current = turn

        # Leaving while the response is still streaming makes the socket
        # unusable for the next turn.
        def leave(_: Exit[Any, Any]) -> Effect[None]:
            return ref.invalidate() if connection.current is turn else fx.void

        yield from scope.add_finalizer(leave)
        yield from scope_mod.fork_scoped(connection.send(options), start_immediately=True)
        return St.from_queue(turn)

    stream: Stream[W.ResponseStreamEvent, AiError] = St.unwrap(open_turn)
    return fx.succeed((http_response.make(request, "", status=200), stream))
