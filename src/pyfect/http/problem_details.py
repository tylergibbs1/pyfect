"""RFC 9457 problem details (Effect's ``http/ProblemDetails``): the
``application/problem+json`` body a server sends to describe an error.

``Schema`` is the lenient codec RFC 9457 asks for: a missing ``type`` is
``about:blank``, a standard member of the wrong JSON type is dropped, and any
other member is an extension, kept as it is. Encoding always writes ``type``.
``to_response`` renders a problem. ``pyfect.http_api.error.Problem`` builds
typed problem classes on the same members.
"""

from __future__ import annotations

from typing import Any, Final, LiteralString, Never, NotRequired, cast

from typing_extensions import TypedDict

from pyfect import schema as S
from pyfect._core import Effect
from pyfect.effect import succeed
from pyfect.http.server_response import HttpServerResponse, json_unsafe
from pyfect.option import Option, Some

CONTENT_TYPE: Final = "application/problem+json"
"""The media type of a problem details body."""

BLANK_TYPE: Final = "about:blank"
"""The problem type of a problem that only carries an HTTP status."""


class ProblemDetails(TypedDict, extra_items=object):
    """A decoded problem: the standard members ``type``, ``status``,
    ``title``, ``detail`` and ``instance``; any other key is an extension."""

    type: str
    status: NotRequired[float]
    title: NotRequired[str]
    detail: NotRequired[str]
    instance: NotRequired[str]


def optional_member[A, E](schema: S.Codec[A, E, Any, Any], /) -> S.Bottom[A, E, Any, Any]:
    """A standard member left out when it has the wrong JSON type (RFC 9457
    section 3.1); its key must be optional (``NotRequired``, or a default)."""

    def missing(_: object) -> Effect[Option[A], Any, Never]:
        return succeed(None)

    return schema.__codec__().pipe(S.catch_decoding(missing))


def fixed_member[L: str | int](value: L, /) -> S.Bottom[L, L, Any, Any]:
    """A member that always decodes to ``value``, whatever (or whether) the
    body carries it; ``value`` is also its constructor default."""
    literal = cast("LiteralString | int", value)
    defaulted = S.with_decoding_default_key(succeed(literal))(S.tag(literal))

    def fixed(_: object) -> Effect[Option[LiteralString | int], Any, Never]:
        return succeed(Some(literal))

    return cast("S.Bottom[L, L, Any, Any]", defaulted.pipe(S.catch_decoding(fixed)))


Schema: S.Bottom[ProblemDetails, dict[str, object]] = S.Struct(
    ProblemDetails,
    type=S.with_decoding_default_key(succeed(BLANK_TYPE))(S.String).pipe(
        S.catch_decoding(lambda _: succeed(Some(BLANK_TYPE)))
    ),
    status=optional_member(S.Number),
    title=optional_member(S.String),
    detail=optional_member(S.String),
    instance=optional_member(S.String),
)  # pyright: ignore[reportAssignmentType]
"""The lenient problem details codec (see the module docstring)."""


def to_response(problem: ProblemDetails) -> HttpServerResponse:
    """``problem`` as an ``application/problem+json`` response, with its
    ``status`` (500 when it has none)."""
    status = problem.get("status")
    return json_unsafe(
        problem, status=500 if status is None else int(status), content_type=CONTENT_TYPE
    )


__all__ = [
    "BLANK_TYPE",
    "CONTENT_TYPE",
    "ProblemDetails",
    "Schema",
    "fixed_member",
    "optional_member",
    "to_response",
]
