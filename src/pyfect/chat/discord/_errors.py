"""Discord's JSON error codes and HTTP statuses as ``ChatError`` reasons."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import cast

from pyfect.chat._retry_after import parse_retry_after
from pyfect.chat.chat_error import (
    FILE_REFUSED,
    INTERACTION_EXPIRED,
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
from pyfect.chat.discord import _json
from pyfect.chat.discord._normalize import PLATFORM

_NOT_FOUND = frozenset({10003, 10004, 10007, 10008, 10013, 10014, 10015})
_FORBIDDEN = frozenset({20001, 20028, 50001, 50005, 50013, 50021, 50083, 160005, 160006})
_UNAUTHENTICATED = frozenset({0, 40001})
_TOO_LARGE_FILES = frozenset({40005, 50045})
_INVALID_FORM_BODY = 50035


def _is_too_long(errors: object) -> bool:
    """Whether a 50035's ``errors`` say a field is too long: some ``code``
    in the tree is ``BASE_TYPE_MAX_LENGTH`` or the like. Walked without
    recursion, so a deep tree costs its size."""
    pending = [errors]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if "MAX_LENGTH" in item:
                return True
        elif isinstance(item, dict):
            obj = cast("dict[str, object]", item)
            pending.extend(obj.values())
            pending.extend(obj.keys())
        elif isinstance(item, list):
            pending.extend(cast("list[object]", item))
    return False


def _code(value: object) -> int | None:
    """Discord's JSON error code: a whole number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def reason_for_response(  # noqa: PLR0911
    status: int, data: object, *, write: bool, cause: object = None
) -> AnyReason:
    """The reason for an answer Discord sent: a JSON error ``code`` when there
    is one, otherwise the HTTP status. ``detail`` is the code, or
    ``http_{status}``."""
    body = _json.as_object(data) or {}
    code = _code(body.get("code"))
    if status == 429:
        wait = parse_retry_after(body.get("retry_after"))
        return RateLimited(
            detail="http_429" if code is None else str(code), cause=cause, retry_after=wait
        )
    if status >= 500:
        return PlatformUnavailable(
            retry="uncertain" if write else "retry", detail=f"http_{status}", cause=cause
        )
    detail = f"http_{status}" if code is None else str(code)
    if code is not None:
        if code in _NOT_FOUND:
            return NotFound(detail=detail, cause=cause)
        if code in _FORBIDDEN:
            return Forbidden(detail=detail, cause=cause)
        if code in _TOO_LARGE_FILES:
            return TooLarge(subject="files", detail=detail, cause=cause)
        if code == _INVALID_FORM_BODY and _is_too_long(body.get("errors")):
            return TooLarge(subject="text", detail=detail, cause=cause)
        if code in _UNAUTHENTICATED and status == 401:
            return Unauthenticated(detail=detail, cause=cause)
    if status == 401:
        return Unauthenticated(detail=detail, cause=cause)
    if status == 403:
        return Forbidden(detail=detail, cause=cause)
    if status == 404:
        return NotFound(detail=detail, cause=cause)
    if status == 413:
        return TooLarge(subject="files", detail=detail, cause=cause)
    return InvalidRequest(detail=detail, cause=cause)


def transport(write: bool, detail: str, cause: object = None) -> AnyReason:
    """A request that failed before an answer came."""
    return Transport(retry="uncertain" if write else "retry", detail=detail, cause=cause)


def invalid_response(write: bool, detail: str, cause: object = None) -> AnyReason:
    """An answer the adapter cannot read. A write may have landed."""
    if write:
        return Unknown(detail=detail, cause=cause)
    return InvalidResponse(detail=detail, cause=cause)


def chat_error(op: str, reason: AnyReason) -> ChatError:
    """A Discord ``ChatError`` of ``op``."""
    return ChatError(platform=PLATFORM, op=op, reason=reason)


def with_op(op: str, error: ChatError) -> ChatError:
    """``error`` as an error of ``op``."""
    if error.op == op:
        return error
    return ChatError(platform=error.platform, op=op, reason=error.reason)


def has_code(code: int) -> Callable[[ChatError], bool]:
    """Whether a failure carries Discord's JSON error code ``code``."""
    detail = str(code)
    return lambda error: error.reason.detail == detail


def expired(op: str, cause: AnyReason | None = None) -> ChatError:
    """The ``interaction_expired`` failure, with the reason Discord gave as its ``cause``."""
    return chat_error(op, NotFound(detail=INTERACTION_EXPIRED, cause=cause))


def file_refused(reason: AnyReason) -> AnyReason:
    """A ``denied`` reason from a post that carries files, as a refused file:
    the same reason with detail ``file_refused``, and the reason it replaces,
    with Discord's code, as its ``cause``. Any other reason is returned as it
    is."""
    if reason.retry != "denied" or reason.detail == FILE_REFUSED:
        return reason
    if isinstance(reason, (RateLimited, Unknown)):
        return reason
    return copy.replace(reason, detail=FILE_REFUSED, cause=reason)
