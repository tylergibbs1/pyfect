"""Bot API errors as chat error reasons."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pyfect.chat.chat_error import (
    FILE_REFUSED,
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
from pyfect.chat.telegram import _json
from pyfect.chat.telegram._address import PLATFORM
from pyfect.duration import seconds

CHAT_MIGRATED = "chat_migrated"
"""The detail of a chat that became a supergroup."""


def chat_error(op: str, reason: AnyReason) -> ChatError:
    return ChatError(platform=PLATFORM, op=op, reason=reason)


def with_op(op: str) -> Callable[[ChatError], ChatError]:
    return lambda error: chat_error(op, error.reason)


def unsupported(capability: Capability) -> AnyReason:
    return Unsupported(capability=capability)


def invalid_request(detail: str) -> AnyReason:
    return InvalidRequest(detail=detail)


def not_found(detail: str) -> AnyReason:
    return NotFound(detail=detail)


def too_large(subject: Literal["text", "files"] | None, detail: str) -> AnyReason:
    return TooLarge(subject=subject, detail=detail)


UNAUTHENTICATED_TOKEN: AnyReason = Unauthenticated(detail="invalid_token")
REFUSED_FILE: AnyReason = TooLarge(subject="files", detail=FILE_REFUSED)


@dataclass(frozen=True)
class ApiError:
    """The error Telegram answers with. ``description`` is lowercased and
    only matched, never put in an error: it can quote the message."""

    code: int
    description: str = ""
    retry_after: int | None = None
    migrate_to: int | None = None


def api_error(body: object, status: int) -> ApiError | None:
    """The error in a body that says ``ok: false``."""
    obj = _json.as_object(body)
    if obj is None or obj.get("ok") is not False:
        return None
    description = obj.get("description")
    code = obj.get("error_code")
    return ApiError(
        code=code if isinstance(code, int) and not isinstance(code, bool) else status,
        description=description.lower() if isinstance(description, str) else "",
        retry_after=_json.integer(obj.get("parameters"), "retry_after"),
        migrate_to=_json.integer(obj.get("parameters"), "migrate_to_chat_id"),
    )


def _forbidden(detail: str) -> AnyReason:
    return Forbidden(detail=detail)


def _text_too_large(detail: str) -> AnyReason:
    return too_large("text", detail)


def _refused(_detail: str) -> AnyReason:
    return REFUSED_FILE


# Descriptions that refine a 400 or a 403, matched as substrings, each to a
# fixed detail.
_REFINEMENTS: tuple[tuple[str, Callable[[str], AnyReason], str], ...] = (
    ("message is not modified", invalid_request, "not_modified"),
    ("message to edit not found", not_found, "message_not_found"),
    ("message to delete not found", not_found, "message_not_found"),
    ("message to be replied not found", not_found, "reply_target_not_found"),
    ("message not found", not_found, "message_not_found"),
    ("chat not found", not_found, "chat_not_found"),
    ("thread not found", not_found, "thread_not_found"),
    ("user not found", not_found, "user_not_found"),
    ("participant_id_invalid", not_found, "user_not_found"),
    ("message can't be deleted", _forbidden, "cannot_delete"),
    ("message can't be edited", _forbidden, "cannot_edit"),
    ("not enough rights", _forbidden, "not_enough_rights"),
    ("have no rights", _forbidden, "not_enough_rights"),
    ("bot was blocked", _forbidden, "blocked"),
    ("bot was kicked", _forbidden, "kicked"),
    ("bot is not a member", _forbidden, "not_a_member"),
    ("rich_message_text_too_long", _text_too_large, "message_too_long"),
    ("rich_message_too_large", _text_too_large, "message_too_large"),
    ("rich_message_blocks_too_many", _text_too_large, "too_many_blocks"),
    ("rich_message_depth_invalid", invalid_request, "too_deep"),
    ("rich_message_table_cols_too_many", invalid_request, "too_many_columns"),
    ("rich_message_empty", invalid_request, "empty_message"),
    ("rich_message_markdown_invalid", invalid_request, "invalid_markdown"),
    ("too long", _text_too_large, "message_too_long"),
    ("file is too big", _refused, FILE_REFUSED),
    ("wrong file", _refused, FILE_REFUSED),
)


def reason_for_api_error(  # noqa: PLR0911
    error: ApiError, *, write: bool, cause: object = None
) -> AnyReason:
    """Maps one Telegram error. ``cause`` holds no URL or message text."""
    if error.code == 429:
        retry_after = None if error.retry_after is None else seconds(max(0, error.retry_after))
        return RateLimited(detail="telegram_429", retry_after=retry_after)
    if error.migrate_to is not None:
        return NotFound(detail=CHAT_MIGRATED, cause=cause)
    if error.code in (401, 404):
        return Unauthenticated(detail=f"telegram_{error.code}")
    if error.code >= 500:
        return PlatformUnavailable(
            retry="uncertain" if write else "retry", detail=f"telegram_{error.code}"
        )
    if error.code == 409:
        return invalid_request("conflict")
    if error.code in (400, 403):
        for needle, make, detail in _REFINEMENTS:
            if needle in error.description:
                return make(detail)
        return _forbidden("telegram_403") if error.code == 403 else invalid_request("telegram_400")
    return invalid_request(f"telegram_{error.code}")


def transport(write: bool, detail: str) -> AnyReason:
    """A request that failed before an answer came. No cause: it would hold
    the URL, and the URL holds the token."""
    return Transport(retry="uncertain" if write else "retry", detail=detail)


def invalid_response(write: bool, detail: str) -> AnyReason:
    """An answer the adapter cannot read. A write may have landed."""
    return Unknown(detail=detail) if write else InvalidResponse(detail=detail)
