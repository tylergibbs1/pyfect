"""Graph API errors as chat error reasons."""

from __future__ import annotations

from dataclasses import dataclass

from pyfect.chat.chat_error import (
    AnyReason,
    ChatError,
    Forbidden,
    InvalidRequest,
    InvalidResponse,
    NotFound,
    PlatformUnavailable,
    RateLimited,
    TooLarge,
    Transport,
    Unauthenticated,
    Unknown,
)
from pyfect.chat.whatsapp import _json
from pyfect.chat.whatsapp._address import PLATFORM
from pyfect.duration import Duration

OUTSIDE_WINDOW = "graph_131047"
"""The detail of a send refused outside the 24 hour window, Graph error 131047."""

_UNAUTHENTICATED = frozenset({0, 102, 190})
_FORBIDDEN = frozenset({3, 10, 368, 131030, 131031, 131042, 131045, 131047, 131049, 131050, 133010})
_RATE_LIMITED = frozenset({4, 17, 32, 613, 80007, 130429, 131048, 131056})
_UNAVAILABLE = frozenset({1, 2, 131000, 131016})


@dataclass(frozen=True)
class GraphError:
    """An error a Graph answer carries, in an ``error`` field or in a
    status's ``errors``."""

    code: int
    subcode: int | None = None


def graph_error(body: object) -> GraphError | None:
    """The Graph error in an answer's body, if it has one."""
    error = _json.object_(body, "error") or _json.as_object(body)
    code = _json.code(error)
    if error is None or code is None:
        return None
    subcode = error.get("error_subcode")
    return GraphError(
        code, subcode if isinstance(subcode, int) and not isinstance(subcode, bool) else None
    )


def reason_for_graph_error(  # noqa: PLR0911
    error: GraphError, *, write: bool, cause: object = None, retry_after: Duration | None = None
) -> AnyReason:
    """Maps a Graph error code to a reason. ``detail`` is ``graph_{code}``,
    which holds no message text or ids; the Graph error itself is the
    ``cause``. A rate limit keeps the answer's ``retry_after``."""
    detail = f"graph_{error.code}"
    code = error.code
    if code in _RATE_LIMITED:
        return RateLimited(detail=detail, cause=cause, retry_after=retry_after)
    if code in _UNAUTHENTICATED:
        return Unauthenticated(detail=detail, cause=cause)
    if code in _FORBIDDEN or 200 <= code < 300:
        return Forbidden(detail=detail, cause=cause)
    if code in _UNAVAILABLE:
        return PlatformUnavailable(
            retry="uncertain" if write else "retry", detail=detail, cause=cause
        )
    if code == 100 and error.subcode == 33:
        return NotFound(detail=detail, cause=cause)
    if code == 131053:
        return TooLarge(subject="files", detail=detail, cause=cause)
    return InvalidRequest(detail=detail, cause=cause)


def reason_for_status(  # noqa: PLR0911
    status: int, *, write: bool, cause: object = None, retry_after: Duration | None = None
) -> AnyReason:
    """Maps an HTTP status without a Graph error to a reason, with detail
    ``http_{status}``. A 429 keeps the answer's ``retry_after``."""
    detail = f"http_{status}"
    if status == 429:
        return RateLimited(detail=detail, cause=cause, retry_after=retry_after)
    if status >= 500:
        return PlatformUnavailable(
            retry="uncertain" if write else "retry", detail=detail, cause=cause
        )
    if status == 401:
        return Unauthenticated(detail=detail, cause=cause)
    if status == 403:
        return Forbidden(detail=detail, cause=cause)
    if status == 404:
        return NotFound(detail=detail, cause=cause)
    if status == 413:
        return TooLarge(detail=detail, cause=cause)
    return InvalidRequest(detail=detail, cause=cause)


def transport(write: bool, detail: str, cause: object = None) -> AnyReason:
    """A request that failed before an answer came. A write may have landed."""
    return Transport(retry="uncertain" if write else "retry", detail=detail, cause=cause)


def invalid_response(write: bool, detail: str, cause: object = None) -> AnyReason:
    """An answer the adapter cannot read. A write may have landed."""
    return (
        Unknown(detail=detail, cause=cause)
        if write
        else InvalidResponse(detail=detail, cause=cause)
    )


def chat_error(op: str, reason: AnyReason) -> ChatError:
    return ChatError(platform=PLATFORM, op=op, reason=reason)
