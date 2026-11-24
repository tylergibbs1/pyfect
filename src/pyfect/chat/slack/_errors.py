"""Slack's error codes and HTTP statuses as ``ChatError`` reasons."""

from __future__ import annotations

import copy

from pyfect.chat.chat_error import (
    FILE_REFUSED,
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
from pyfect.chat.slack._address import PLATFORM
from pyfect.duration import Duration

_UNAUTHENTICATED = frozenset(
    {
        "invalid_auth",
        "not_authed",
        "account_inactive",
        "token_revoked",
        "token_expired",
        "org_login_required",
    }
)

_FORBIDDEN = frozenset(
    {
        "access_denied",
        "accesslimited",
        "missing_scope",
        "not_in_channel",
        "is_archived",
        "channel_is_archived",
        "no_permission",
        "not_allowed_token_type",
        "not_authorized",
        "restricted_action",
        "restricted_action_read_only_channel",
        "restricted_action_thread_only_channel",
        "restricted_action_non_threadable_channel",
        "cant_update_message",
        "cant_delete_message",
        "cant_delete_file",
        "edit_window_closed",
        "ekm_access_denied",
        "enterprise_is_restricted",
        "team_access_not_granted",
        "posting_to_general_channel_denied",
        "message_not_owned_by_app",
        "messages_tab_disabled",
        "message_limit_exceeded",
        "thread_locked",
        "user_is_restricted",
        "feature_disabled",
        "channel_type_not_supported",
    }
)

_NOT_FOUND = frozenset(
    {
        "channel_not_found",
        "message_not_found",
        "thread_not_found",
        "user_not_found",
        "users_not_found",
        "file_not_found",
        "file_deleted",
        "bot_not_found",
        "team_not_found",
    }
)


_TOO_LARGE = frozenset({"msg_too_long", "msg_blocks_too_long"})
_SERVER_ERRORS = frozenset(
    {
        "internal_error",
        "fatal_error",
        "service_unavailable",
        "request_timeout",
    }
)


def reason_for_code(code: str, *, write: bool, retry_after: Duration | None = None) -> AnyReason:  # noqa: PLR0911
    """The reason for the ``error`` of an ``ok: false`` answer. ``detail`` is
    always Slack's error code, which holds no message text or ids."""
    if code in ("ratelimited", "rate_limited"):
        return RateLimited(detail=code, retry_after=retry_after)
    if code in _UNAUTHENTICATED:
        return Unauthenticated(detail=code)
    if code in _FORBIDDEN:
        return Forbidden(detail=code)
    if code in _NOT_FOUND:
        return NotFound(detail=code)
    if code in _TOO_LARGE:
        return TooLarge(subject="text", detail=code)
    if code in ("file_too_large", "too_many_files"):
        return TooLarge(subject="files", detail=code)
    if code in _SERVER_ERRORS:
        return PlatformUnavailable(retry="uncertain" if write else "retry", detail=code)
    return InvalidRequest(detail=code)


def reason_for_status(  # noqa: PLR0911
    status: int, *, write: bool, retry_after: Duration | None = None, cause: object = None
) -> AnyReason:
    """The reason for a non-2xx answer."""
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
    """A request that failed before an answer came."""
    return Transport(retry="uncertain" if write else "retry", detail=detail, cause=cause)


def invalid_response(write: bool, detail: str, cause: object = None) -> AnyReason:
    """An answer the adapter cannot read. A write may have landed."""
    if write:
        return Unknown(detail=detail, cause=cause)
    return InvalidResponse(detail=detail, cause=cause)


def chat_error(op: str, reason: AnyReason) -> ChatError:
    """A Slack ``ChatError`` of ``op``."""
    return ChatError(platform=PLATFORM, op=op, reason=reason)


def with_op(op: str, error: ChatError) -> ChatError:
    """``error`` as an error of ``op``."""
    if error.op == op:
        return error
    return ChatError(platform=error.platform, op=op, reason=error.reason)


def file_refused(reason: AnyReason) -> AnyReason:
    """A ``denied`` reason from an upload call, or from the attach of a post
    whose rollback left nothing behind, as a refused file: the same reason
    with detail ``file_refused``, and the reason it replaces as its
    ``cause``. Any other reason is returned as it is."""
    if reason.retry != "denied" or reason.detail == FILE_REFUSED:
        return reason
    if isinstance(reason, (RateLimited, Unknown)):
        return reason
    return copy.replace(reason, detail=FILE_REFUSED, cause=reason)
