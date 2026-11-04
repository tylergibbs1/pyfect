"""SQL Server failures as ``SqlError`` reasons (the ``classifyError`` of
Effect's ``@effect/sql-mssql`` ``MssqlClient``).

A server error carries its error ``number`` (pytds's errors do);
``classify`` maps the numbers Effect knows to reasons, and any other
failure to ``UnknownError`` (``ConnectionError`` when connecting). A
duplicate key (2601 / 2627) names its constraint from a ``constraint``
attribute, else from the message's ``unique index '...'`` /
``constraint '...'``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Literal

from pyfect.sql.error import (
    AuthenticationError,
    AuthorizationError,
    ConnectionError,
    ConstraintError,
    DeadlockError,
    LockTimeoutError,
    SerializationError,
    SqlError,
    SqlErrorReason,
    SqlSyntaxError,
    UniqueViolation,
    UnknownError,
)

_BY_NUMBER: dict[int, Callable[..., SqlErrorReason]] = {
    **dict.fromkeys((233, 10054), ConnectionError),
    **dict.fromkeys((4060, 18452, 18456), AuthenticationError),
    **dict.fromkeys((229, 230, 262, 297, 300), AuthorizationError),
    **dict.fromkeys((102, 207, 208, 2714), SqlSyntaxError),
    **dict.fromkeys((515, 547), ConstraintError),
    1205: DeadlockError,
    3960: SerializationError,
    1222: LockTimeoutError,
}
_UNIQUE_INDEX = 2601
_UNIQUE_CONSTRAINT = 2627
_UNKNOWN_CONSTRAINT = "unknown"
_CONSTRAINT_NAME = re.compile(r"\bconstraint\s+'([^']*)'", re.IGNORECASE)
_INDEX_NAME = re.compile(r"\bunique index\s+'([^']*)'", re.IGNORECASE)

type Fallback = Literal["connection", "unknown"]


def error_number(cause: object) -> int | None:
    """The server's error number of ``cause``, if it has one."""
    number = getattr(cause, "number", None)
    return number if type(number) is int else None


def _normalize(identifier: object) -> str:
    if not isinstance(identifier, str):
        return _UNKNOWN_CONSTRAINT
    return identifier.strip() or _UNKNOWN_CONSTRAINT


def _message(cause: object) -> object:
    if hasattr(cause, "message"):
        return getattr(cause, "message")  # noqa: B009 - any object's message
    return str(cause) if isinstance(cause, BaseException) else None


def unique_constraint(number: int, cause: object) -> str:
    """The constraint a duplicate key broke: ``cause.constraint`` when it
    has one, else what its message names."""
    explicit = _normalize(getattr(cause, "constraint", None))
    if explicit != _UNKNOWN_CONSTRAINT:
        return explicit
    message = _message(cause)
    if not isinstance(message, str):
        return _UNKNOWN_CONSTRAINT
    pattern = _CONSTRAINT_NAME if number == _UNIQUE_CONSTRAINT else _INDEX_NAME
    found = pattern.search(message)
    return _UNKNOWN_CONSTRAINT if found is None else _normalize(found.group(1))


def classify(
    cause: object, *, message: str, operation: str, fallback: Fallback = "unknown"
) -> SqlErrorReason:
    """The reason for a driver error (or any other cause)."""
    number = error_number(cause)
    if number in (_UNIQUE_INDEX, _UNIQUE_CONSTRAINT):
        return UniqueViolation(
            cause=cause,
            message=message,
            operation=operation,
            constraint=unique_constraint(number, cause),
        )
    reason = None if number is None else _BY_NUMBER.get(number)
    if reason is None:
        reason = ConnectionError if fallback == "connection" else UnknownError
    return reason(cause=cause, message=message, operation=operation)


def catch(
    message: str, operation: str, fallback: Fallback = "unknown"
) -> Callable[[BaseException], SqlError]:
    """Turns an exception into the ``SqlError`` of ``operation``."""
    return lambda cause: SqlError(
        reason=classify(cause, message=message, operation=operation, fallback=fallback)
    )


__all__ = ["catch", "classify", "error_number", "unique_constraint"]
