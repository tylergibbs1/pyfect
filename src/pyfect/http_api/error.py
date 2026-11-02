"""The errors of HTTP APIs (Effect's ``HttpApiError``): one schema error
class per common status, each answering with its empty response, and the
errors the server makes when a request or response does not fit its
schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Literal

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.byte_size import ByteSize
from pyfect.effect import succeed
from pyfect.errors import TaggedError
from pyfect.http.server_response import HttpServerResponse, empty, json_unsafe
from pyfect.http_api.schema import as_no_content

_STATUSES = (400, 401, 403, 404, 405, 406, 408, 409, 410, 413, 422, 500, 501, 503)
_RESPONSES = {status: empty(status=status) for status in _STATUSES}


def _annotations(name: str, status: int) -> dict[str, object]:
    return {"description": name, "http_api_status": status}


class _StatusError:
    """Responds with the empty response of its ``http_api_status``."""

    status: ClassVar[int]

    def __http_response__(self) -> Effect[HttpServerResponse]:
        return succeed(_RESPONSES[self.status])


class BadRequest(
    _StatusError,
    S.TaggedError,
    tag="BadRequest",
    identifier="effect/HttpApiError/BadRequest",
    annotations=_annotations("BadRequest", 400),
):
    status = 400
    report_ignored = True


class Unauthorized(
    _StatusError,
    S.TaggedError,
    tag="Unauthorized",
    identifier="effect/HttpApiError/Unauthorized",
    annotations=_annotations("Unauthorized", 401),
):
    status = 401
    report_ignored = True


class Forbidden(
    _StatusError,
    S.TaggedError,
    tag="Forbidden",
    identifier="effect/HttpApiError/Forbidden",
    annotations=_annotations("Forbidden", 403),
):
    status = 403
    report_ignored = True


class NotFound(
    _StatusError,
    S.TaggedError,
    tag="NotFound",
    identifier="effect/HttpApiError/NotFound",
    annotations=_annotations("NotFound", 404),
):
    status = 404
    report_ignored = True


class MethodNotAllowed(
    _StatusError,
    S.TaggedError,
    tag="MethodNotAllowed",
    identifier="effect/HttpApiError/MethodNotAllowed",
    annotations=_annotations("MethodNotAllowed", 405),
):
    status = 405
    report_ignored = True


class NotAcceptable(
    _StatusError,
    S.TaggedError,
    tag="NotAcceptable",
    identifier="effect/HttpApiError/NotAcceptable",
    annotations=_annotations("NotAcceptable", 406),
):
    status = 406
    report_ignored = True


class RequestTimeout(
    _StatusError,
    S.TaggedError,
    tag="RequestTimeout",
    identifier="effect/HttpApiError/RequestTimeout",
    annotations=_annotations("RequestTimeout", 408),
):
    status = 408
    report_ignored = True


class Conflict(
    _StatusError,
    S.TaggedError,
    tag="Conflict",
    identifier="effect/HttpApiError/Conflict",
    annotations=_annotations("Conflict", 409),
):
    status = 409
    report_ignored = True


class Gone(
    _StatusError,
    S.TaggedError,
    tag="Gone",
    identifier="effect/HttpApiError/Gone",
    annotations=_annotations("Gone", 410),
):
    status = 410
    report_ignored = True


class UnprocessableEntity(
    _StatusError,
    S.TaggedError,
    tag="UnprocessableEntity",
    identifier="effect/HttpApiError/UnprocessableEntity",
    annotations=_annotations("UnprocessableEntity", 422),
):
    status = 422
    report_ignored = True


class InternalServerError(
    _StatusError,
    S.TaggedError,
    tag="InternalServerError",
    identifier="effect/HttpApiError/InternalServerError",
    annotations=_annotations("InternalServerError", 500),
):
    status = 500


class NotImplemented(
    _StatusError,
    S.TaggedError,
    tag="NotImplemented",
    identifier="effect/HttpApiError/NotImplemented",
    annotations=_annotations("NotImplemented", 501),
):
    status = 501


class ServiceUnavailable(
    _StatusError,
    S.TaggedError,
    tag="ServiceUnavailable",
    identifier="effect/HttpApiError/ServiceUnavailable",
    annotations=_annotations("ServiceUnavailable", 503),
):
    status = 503


BadRequestNoContent = as_no_content(BadRequest, decode=BadRequest)
UnauthorizedNoContent = as_no_content(Unauthorized, decode=Unauthorized)
ForbiddenNoContent = as_no_content(Forbidden, decode=Forbidden)
NotFoundNoContent = as_no_content(NotFound, decode=NotFound)
MethodNotAllowedNoContent = as_no_content(MethodNotAllowed, decode=MethodNotAllowed)
NotAcceptableNoContent = as_no_content(NotAcceptable, decode=NotAcceptable)
RequestTimeoutNoContent = as_no_content(RequestTimeout, decode=RequestTimeout)
ConflictNoContent = as_no_content(Conflict, decode=Conflict)
GoneNoContent = as_no_content(Gone, decode=Gone)
UnprocessableEntityNoContent = as_no_content(UnprocessableEntity, decode=UnprocessableEntity)
InternalServerErrorNoContent = as_no_content(InternalServerError, decode=InternalServerError)
NotImplementedNoContent = as_no_content(NotImplemented, decode=NotImplemented)
ServiceUnavailableNoContent = as_no_content(ServiceUnavailable, decode=ServiceUnavailable)

type SchemaErrorKind = Literal["Params", "Headers", "Query", "Body", "Payload", "ResponseHeaders"]


@dataclass(eq=False)
class HttpApiSchemaError(TaggedError):
    """A request part (``Params``, ``Headers``, ``Query``, ``Payload``)
    that did not decode, answered with 400 and not reported; or a
    response part (``Body``, ``ResponseHeaders``) that did not encode,
    answered with 500 and reported."""

    kind: SchemaErrorKind
    cause: S.SchemaError
    details: bool = field(default=False, kw_only=True, repr=False, compare=False)
    """The 400 sends ``{"_tag", "kind", "message"}``, the message being the
    schema issue (``builder.layer(api, schema_error_details=True)``). A 500
    stays empty."""
    report_ignored: bool = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.report_ignored = self.kind not in ("Body", "ResponseHeaders")

    @property
    def message(self) -> str:
        return self.kind

    def __http_response__(self) -> Effect[HttpServerResponse]:
        if not self.report_ignored:
            return succeed(_RESPONSES[500])
        if not self.details:
            return succeed(_RESPONSES[400])
        body = {"_tag": "HttpApiSchemaError", "kind": self.kind, "message": str(self.cause)}
        return succeed(json_unsafe(body, status=400))

    @staticmethod
    def wrap[A, R](
        kind: SchemaErrorKind, effect: Effect[A, S.SchemaError, R]
    ) -> Effect[A, HttpApiSchemaError, R]:
        """``effect`` failing with this error of ``kind`` instead."""
        require_effect(effect, "effect")
        return effect.map_error(lambda error: HttpApiSchemaError(kind, error))


@dataclass(eq=False)
class HttpApiPayloadTooLarge(TaggedError):
    """A request body over its ``limit`` (``maxBytes``, or
    ``maxElementBytes`` for an NDJSON line), answered with 413."""

    limit: Literal["maxBytes", "maxElementBytes"]
    size: ByteSize
    report_ignored = True

    @property
    def message(self) -> str:
        return f"Payload exceeds {self.limit} of {self.size} bytes"

    def __http_response__(self) -> Effect[HttpServerResponse]:
        return succeed(_RESPONSES[413])


__all__ = [
    "BadRequest",
    "BadRequestNoContent",
    "Conflict",
    "ConflictNoContent",
    "Forbidden",
    "ForbiddenNoContent",
    "Gone",
    "GoneNoContent",
    "HttpApiPayloadTooLarge",
    "HttpApiSchemaError",
    "InternalServerError",
    "InternalServerErrorNoContent",
    "MethodNotAllowed",
    "MethodNotAllowedNoContent",
    "NotAcceptable",
    "NotAcceptableNoContent",
    "NotFound",
    "NotFoundNoContent",
    "NotImplemented",
    "NotImplementedNoContent",
    "RequestTimeout",
    "RequestTimeoutNoContent",
    "SchemaErrorKind",
    "ServiceUnavailable",
    "ServiceUnavailableNoContent",
    "Unauthorized",
    "UnauthorizedNoContent",
    "UnprocessableEntity",
    "UnprocessableEntityNoContent",
]
