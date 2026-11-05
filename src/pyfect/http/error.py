"""The error of an HTTP client (Effect's ``HttpClientError``).

Every client failure is one ``HttpClientError`` whose ``reason`` says what
went wrong. Request reasons (``TransportError``, ``EncodeError``,
``InvalidUrlError``) carry the request; response reasons
(``StatusCodeError``, ``DecodeError``, ``EmptyBodyError``) the response too.
Match a reason with ``catch_reason``::

    client.get(url).pipe(
        fx.catch_reason(HttpClientError, StatusCodeError, lambda reason, _e: fx.succeed(None))
    )

Messages name the method and the URL with its secrets redacted
(``url_params.redact_url``), and never the headers or the body. ``str()``
of an error without a description adds its cause:
``Transport error (POST http://.../jobs): ConnectError: ...``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, Literal

from pyfect.errors import TaggedError, with_cause
from pyfect.http.url_params import redact_url

if TYPE_CHECKING:
    from pyfect.http.request import HttpClientRequest
    from pyfect.http.response import HttpClientResponse


def _message(name: str, description: str | None, info: str) -> str:
    return f"{name}: {description} ({info})" if description else f"{name} error ({info})"


def _with_cause(message: str, description: str | None, cause: object) -> str:
    """``message``, then the cause when no description says what went wrong."""
    return message if description else with_cause(message, cause)


def _method_and_url(request: HttpClientRequest) -> str:
    return f"{request.method} {redact_url(request.url)}"


@dataclass(eq=False)
class _RequestReason(TaggedError):
    request: HttpClientRequest
    cause: object = None
    description: str | None = None

    @property
    def message(self) -> str:
        return _message(
            type(self).__name__.removesuffix("Error"),
            self.description,
            _method_and_url(self.request),
        )

    def __str__(self) -> str:
        return _with_cause(self.message, self.description, self.cause)

    def to_json(self) -> dict[str, object]:
        return {
            "_tag": type(self).__name__,
            "request": {
                "_id": "HttpClientRequest",
                "method": self.request.method,
                "url": redact_url(self.request.url),
            },
        }


@dataclass(eq=False)
class TransportError(_RequestReason):
    """The request could not be sent or its response not received."""

    tag: ClassVar[Literal["TransportError"]] = "TransportError"


@dataclass(eq=False)
class EncodeError(_RequestReason):
    """The request body could not be encoded (or its stream failed)."""

    tag: ClassVar[Literal["EncodeError"]] = "EncodeError"


@dataclass(eq=False)
class InvalidUrlError(_RequestReason):
    """The request's URL is not a valid absolute URL."""

    tag: ClassVar[Literal["InvalidUrlError"]] = "InvalidUrlError"


@dataclass(eq=False)
class _ResponseReason(TaggedError):
    request: HttpClientRequest
    response: HttpClientResponse
    cause: object = None
    description: str | None = None

    @property
    def message(self) -> str:
        info = f"{self.response.status} {_method_and_url(self.request)}"
        return _message(type(self).__name__.removesuffix("Error"), self.description, info)

    def __str__(self) -> str:
        return _with_cause(self.message, self.description, self.cause)

    def to_json(self) -> dict[str, object]:
        return {
            "_tag": type(self).__name__,
            "request": {
                "_id": "HttpClientRequest",
                "method": self.request.method,
                "url": redact_url(self.request.url),
            },
            "response": {"_id": "HttpClientResponse", "status": self.response.status},
        }


@dataclass(eq=False)
class StatusCodeError(_ResponseReason):
    """The response's status is not one the caller accepts."""

    tag: ClassVar[Literal["StatusCodeError"]] = "StatusCodeError"


@dataclass(eq=False)
class DecodeError(_ResponseReason):
    """The response body could not be read or decoded."""

    tag: ClassVar[Literal["DecodeError"]] = "DecodeError"


@dataclass(eq=False)
class EmptyBodyError(_ResponseReason):
    """The response has no body to stream."""

    tag: ClassVar[Literal["EmptyBodyError"]] = "EmptyBodyError"


type RequestError = TransportError | EncodeError | InvalidUrlError
type ResponseError = StatusCodeError | DecodeError | EmptyBodyError
type HttpClientErrorReason = RequestError | ResponseError


@dataclass(eq=False)
class HttpClientError(TaggedError):
    """An HTTP client failed; ``reason`` says how. The reason's ``cause`` is
    this error's ``cause`` too (Python's ``__cause__``)."""

    reason: HttpClientErrorReason
    cause: object = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.cause = self.reason.cause

    @property
    def request(self) -> HttpClientRequest:
        return self.reason.request

    @property
    def response(self) -> HttpClientResponse | None:
        return self.reason.response if isinstance(self.reason, _ResponseReason) else None

    @property
    def message(self) -> str:
        return self.reason.message

    def __str__(self) -> str:
        return str(self.reason)

    def to_json(self) -> dict[str, object]:
        return {"_tag": "HttpClientError", "reason": self.reason.to_json()}


__all__ = [
    "DecodeError",
    "EmptyBodyError",
    "EncodeError",
    "HttpClientError",
    "HttpClientErrorReason",
    "InvalidUrlError",
    "RequestError",
    "ResponseError",
    "StatusCodeError",
    "TransportError",
]
