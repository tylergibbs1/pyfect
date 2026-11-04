"""MySQL failures as ``SqlError`` reasons (the ``classifyError`` of Effect's
``@effect/sql-mysql2`` ``MysqlClient``).

A server error carries an errno (asyncmy's ``args[0]``); ``classify`` maps
the errnos Effect knows to reasons and every other failure (the client's
own, such as a refused connection) to ``UnknownError``. A duplicate entry
(1062) names its key from a ``constraint`` attribute, else from the
message's ``for key 'name'``.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from pyfect.sql.error import (
    AuthenticationError,
    AuthorizationError,
    ConnectionError,
    ConstraintError,
    DeadlockError,
    LockTimeoutError,
    SqlError,
    SqlErrorReason,
    SqlSyntaxError,
    StatementTimeoutError,
    UniqueViolation,
    UnknownError,
)

_CONNECTION = frozenset({1040, 1042, 1043, 1129, 1130, 1203})
_AUTHORIZATION = frozenset({1044, 1142, 1143, 1227})
_SYNTAX = frozenset({1054, 1064, 1146})
_CONSTRAINT = frozenset({1022, 1048, 1169, 1216, 1217, 1451, 1452, 1557})
_BY_ERRNO: dict[int, Callable[..., SqlErrorReason]] = {
    1045: AuthenticationError,
    1213: DeadlockError,
    1205: LockTimeoutError,
    3024: StatementTimeoutError,
    **dict.fromkeys(_CONNECTION, ConnectionError),
    **dict.fromkeys(_AUTHORIZATION, AuthorizationError),
    **dict.fromkeys(_SYNTAX, SqlSyntaxError),
    **dict.fromkeys(_CONSTRAINT, ConstraintError),
}
_DUPLICATE_ENTRY = 1062
_UNKNOWN_CONSTRAINT = "unknown"
_FOR_KEY = re.compile(r"\bfor key\s+(?:'([^']*)'|`([^`]*)`|([^\s'`]+))", re.IGNORECASE)


def _errno(cause: object) -> int | None:
    """The errno of asyncmy's ``MySQLError(errno, message)``."""
    from asyncmy.errors import MySQLError

    if not isinstance(cause, MySQLError) or not cause.args:
        return None
    errno = cause.args[0]
    return errno if type(errno) is int else None


def _normalize(identifier: object) -> str:
    if not isinstance(identifier, str):
        return _UNKNOWN_CONSTRAINT
    return identifier.strip() or _UNKNOWN_CONSTRAINT


def _constraint_from_message(message: object) -> str:
    if not isinstance(message, str):
        return _UNKNOWN_CONSTRAINT
    found = _FOR_KEY.search(message)
    if found is None:
        return _UNKNOWN_CONSTRAINT
    return _normalize(found.group(1) or found.group(2) or found.group(3))


def duplicate_entry_constraint(cause: BaseException) -> str:
    """The key a duplicate entry broke: the error's ``constraint``
    attribute when it has one, else what its message names."""
    explicit = _normalize(getattr(cause, "constraint", None))
    if explicit != _UNKNOWN_CONSTRAINT:
        return explicit
    message = cause.args[1] if len(cause.args) > 1 else None
    return _constraint_from_message(message)


def classify(cause: object, *, message: str, operation: str) -> SqlErrorReason:
    """The reason for an asyncmy error (or any other cause)."""
    errno = _errno(cause)
    if errno == _DUPLICATE_ENTRY and isinstance(cause, BaseException):
        return UniqueViolation(
            cause=cause,
            message=message,
            operation=operation,
            constraint=duplicate_entry_constraint(cause),
        )
    reason = UnknownError if errno is None else _BY_ERRNO.get(errno, UnknownError)
    return reason(cause=cause, message=message, operation=operation)


def catch(message: str, operation: str) -> Callable[[BaseException], SqlError]:
    """Turns an exception into the ``SqlError`` of ``operation``."""
    return lambda cause: SqlError(reason=classify(cause, message=message, operation=operation))


__all__ = ["catch", "classify", "duplicate_entry_constraint"]
