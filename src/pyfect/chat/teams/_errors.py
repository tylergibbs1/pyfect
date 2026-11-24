"""The Connector's HTTP statuses and failures as ``ChatError`` reasons."""

from __future__ import annotations

import re
from typing import Literal

from pyfect.chat.chat_error import (
    AnyReason,
    Capability,
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
    Unsupported,
)
from pyfect.chat.teams._address import PLATFORM
from pyfect.duration import Duration, seconds

_CODE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def reason_for_status(  # noqa: PLR0911
    status: int,
    *,
    write: bool,
    code: str | None = None,
    retry_after: Duration | None = None,
    cause: object = None,
) -> AnyReason:
    """The reason for an HTTP status. ``detail`` is ``http_{status}``, or the
    Connector's error ``code`` when it sent one, which holds no message text
    or ids."""
    detail = code if code is not None and _CODE.fullmatch(code) else f"http_{status}"
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
    """A request that failed before an answer came."""
    return Transport(retry="uncertain" if write else "retry", detail=detail, cause=cause)


def invalid_response(write: bool, detail: str, cause: object = None) -> AnyReason:
    """An answer the adapter cannot read. A write may have landed."""
    if write:
        return Unknown(detail=detail, cause=cause)
    return InvalidResponse(detail=detail, cause=cause)


def parse_retry_after(value: str | None) -> Duration | None:
    """A ``Retry-After`` header in seconds, or ``None``."""
    if value is None:
        return None
    text = value.strip()
    if text and _DECIMAL.fullmatch(text) is None:
        return None
    number = float(text) if text else 0.0
    return seconds(number) if 0 <= number < float("inf") else None


def chat_error(op: str, reason: AnyReason) -> ChatError:
    """A Teams ``ChatError`` of ``op``."""
    return ChatError(platform=PLATFORM, op=op, reason=reason)


def with_op(op: str, error: ChatError) -> ChatError:
    """``error`` as an error of ``op``."""
    if error.op == op:
        return error
    return ChatError(platform=error.platform, op=op, reason=error.reason)


def invalid_request(detail: str) -> AnyReason:
    return InvalidRequest(detail=detail)


def not_found(detail: str) -> AnyReason:
    return NotFound(detail=detail)


def unsupported(capability: Capability, detail: str | None = None) -> AnyReason:
    return Unsupported(capability=capability, detail=detail)


def too_large(subject: Literal["text", "files"] | None, detail: str) -> AnyReason:
    return TooLarge(subject=subject, detail=detail)


def untrusted_url() -> AnyReason:
    """A URL outside the adapter's allowlists. Nothing of it is kept."""
    return Forbidden(detail="untrusted_url")
