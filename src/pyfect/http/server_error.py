"""Errors of HTTP servers (Effect's ``HttpServerError``), and the response
a failed handler's cause becomes.

Every request failure is one ``HttpServerError`` whose ``reason`` says what
went wrong: ``RequestParseError`` (400, or 413 for a body too large),
``RouteNotFound`` (404, skipped by error reporters), ``InternalError``
(500) or ``ResponseError`` (500, a response could not be sent). Each reason
is respondable, so a server answers with its status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, Literal

from pyfect._core import Effect
from pyfect._stack_frame import StackFrame, StackTrace
from pyfect.cause import Cause, Die, Fail, Interrupt, Reason, UnhandledError, from_reasons
from pyfect.context import Context, Tag
from pyfect.effect import succeed
from pyfect.errors import TaggedError
from pyfect.exit import Exit, Success
from pyfect.http.server_respondable import to_response_or_else, to_response_or_else_defect
from pyfect.http.server_response import HttpServerResponse, empty, response_of_defect
from pyfect.http.url_params import redact_url

if TYPE_CHECKING:
    from pyfect.http.server_request import ServerRequest as HttpServerRequest


def _method_and_url(request: HttpServerRequest) -> str:
    return f"{request.method} {redact_url(request.url)}"


def _request_message(reason: str, description: str | None, info: str) -> str:
    prefix = f"{reason} ({info})"
    return f"{prefix}: {description}" if description else prefix


@dataclass(eq=False)
class _RequestReason(TaggedError):
    request: HttpServerRequest
    description: str | None = None
    cause: object = None
    status: ClassVar[int] = 500

    @property
    def method_and_url(self) -> str:
        return _method_and_url(self.request)

    @property
    def message(self) -> str:
        return _request_message(type(self).__name__, self.description, self.method_and_url)

    def __http_response__(self) -> Effect[HttpServerResponse]:
        return succeed(empty(status=self.status))


@dataclass(eq=False)
class RequestParseError(_RequestReason):
    """The request could not be read: ``"Parse"`` (400), or
    ``"BodyTooLarge"`` (413) past ``MaxBodySize``."""

    kind: Literal["Parse", "BodyTooLarge"] = "Parse"

    def __http_response__(self) -> Effect[HttpServerResponse]:
        return succeed(empty(status=413 if self.kind == "BodyTooLarge" else 400))


@dataclass(eq=False)
class RouteNotFound(_RequestReason):
    """No route matched (404). Error reporters skip it."""

    status: ClassVar[int] = 404
    report_ignored: bool = field(default=True, init=False, repr=False, compare=False)


@dataclass(eq=False)
class OriginNotAllowed(_RequestReason):
    """A browser page of an origin ``AllowedOrigins`` does not list sent the
    request: a WebSocket upgrade or RPC call is refused (403)."""

    status: ClassVar[int] = 403


@dataclass(eq=False)
class InternalError(_RequestReason):
    """The server failed handling the request (500)."""


@dataclass(eq=False)
class ResponseError(TaggedError):
    """The response could not be sent (500)."""

    request: HttpServerRequest
    response: HttpServerResponse
    description: str | None = None
    cause: object = None

    @property
    def method_and_url(self) -> str:
        return _method_and_url(self.request)

    @property
    def message(self) -> str:
        info = f"ResponseError ({self.response.status} {self.method_and_url})"
        return f"{info}: {self.description}" if self.description else info

    def __http_response__(self) -> Effect[HttpServerResponse]:
        return succeed(empty(status=500))


type RequestError = RequestParseError | RouteNotFound | OriginNotAllowed | InternalError
type HttpServerErrorReason = RequestError | ResponseError


@dataclass(eq=False)
class HttpServerError(TaggedError):
    """A request failed; ``reason`` says how, and gives the response."""

    reason: HttpServerErrorReason
    cause: object = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.cause = self.reason.cause
        self.report_ignored = self.reason.report_ignored

    @property
    def request(self) -> HttpServerRequest:
        return self.reason.request

    @property
    def response(self) -> HttpServerResponse | None:
        return self.reason.response if isinstance(self.reason, ResponseError) else None

    @property
    def message(self) -> str:
        return self.reason.message

    def __http_response__(self) -> Effect[HttpServerResponse]:
        return self.reason.__http_response__()


def is_http_server_error(value: object) -> bool:
    return isinstance(value, HttpServerError)


@dataclass(eq=False)
class ServeError(TaggedError):
    """The server could not start or keep serving."""

    cause: object


class ClientAbort(Tag[bool], key="effect/http/HttpServerError/ClientAbort"):
    """Annotates the interruption of a request whose client went away."""


CLIENT_ABORT_ANNOTATION: Context[ClientAbort | StackTrace] = Context.make(ClientAbort, True).add(
    StackTrace, StackFrame("ClientAbort", lambda: None, None)
)


def request_parse_error(
    request: HttpServerRequest,
    description: str | None = None,
    cause: object = None,
    kind: Literal["Parse", "BodyTooLarge"] = "Parse",
) -> HttpServerError:
    return HttpServerError(RequestParseError(request, description, cause, kind))


_INTERNAL_SERVER_ERROR = empty(status=500)
_CLIENT_ABORT = empty(status=499)
_SERVER_ABORT = empty(status=503)


def cause_response[E](cause: Cause[E]) -> Effect[tuple[HttpServerResponse, Cause[E]]]:
    """The response for a failed handler's ``cause``, and the cause to
    report: a response carried by a defect wins; else the last failure's
    respondable (500 otherwise); an interruption alone is 499 when the
    client aborted, else 503. The response is added to the reported cause
    as a defect."""
    response: HttpServerResponse | None = None
    effect = succeed(_INTERNAL_SERVER_ERROR)
    failures: list[Reason[E]] = []
    interrupts: list[Interrupt] = []
    client_interrupt = False
    for reason in cause.reasons:
        match reason:
            case Fail(error):
                effect = to_response_or_else(error, _INTERNAL_SERVER_ERROR)
                failures.append(reason)
            case Die(defect):
                carried = response_of_defect(defect)
                if carried is not None:
                    response = carried
                else:
                    effect = to_response_or_else_defect(defect, _INTERNAL_SERVER_ERROR)
                    failures.append(reason)
            case Interrupt():
                client_interrupt = ClientAbort in reason.annotations
                if not failures:
                    interrupts.append(reason)
    if response is not None:
        return succeed((response, from_reasons(failures)))
    if interrupts and not failures:
        failures.extend(interrupts)
        effect = succeed(_CLIENT_ABORT if client_interrupt else _SERVER_ABORT)

    def with_response(sent: HttpServerResponse) -> tuple[HttpServerResponse, Cause[E]]:
        failures.append(Die(UnhandledError(sent)))
        return sent, from_reasons(failures)

    return effect.map(with_response)


def cause_response_stripped[E](
    cause: Cause[E],
) -> tuple[HttpServerResponse, Cause[E] | None]:
    """The response a defect of ``cause`` carries (else 500), and the rest
    of the cause, if any."""
    response: HttpServerResponse | None = None
    rest: list[Reason[E]] = []
    for reason in cause.reasons:
        carried = response_of_defect(reason.defect) if isinstance(reason, Die) else None
        if carried is not None:
            response = carried
        else:
            rest.append(reason)
    return (
        _INTERNAL_SERVER_ERROR if response is None else response,
        from_reasons(rest) if rest else None,
    )


def exit_response[E](exit: Exit[HttpServerResponse, E]) -> HttpServerResponse:
    """The response of a handler's exit."""
    if isinstance(exit, Success):
        return exit.value
    return cause_response_stripped(exit.cause)[0]


__all__ = [
    "CLIENT_ABORT_ANNOTATION",
    "ClientAbort",
    "HttpServerError",
    "HttpServerErrorReason",
    "InternalError",
    "OriginNotAllowed",
    "RequestError",
    "RequestParseError",
    "ResponseError",
    "RouteNotFound",
    "ServeError",
    "cause_response",
    "cause_response_stripped",
    "exit_response",
    "is_http_server_error",
    "request_parse_error",
]
