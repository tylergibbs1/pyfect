"""PostgreSQL failures as ``SqlError`` reasons (Effect's
``@effect/sql-pg`` ``internal/sqlError``).

A server error carries a SQLSTATE; ``classify_sql_state`` maps it to a
reason. ``classify`` reads the SQLSTATE and constraint name of a psycopg
error; a psycopg error without one (a lost or refused connection) is a
``ConnectionError``.
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
    SerializationError,
    SqlError,
    SqlErrorReason,
    SqlSyntaxError,
    StatementTimeoutError,
    UniqueViolation,
    UnknownError,
)

_MAX_CHANNEL_BYTES = 63
CHANNEL_TOO_LONG = "PostgreSQL channel names must not exceed 63 UTF-8 bytes"


def _normalize_constraint(constraint: object) -> str:
    if not isinstance(constraint, str):
        return "unknown"
    normalized = constraint.strip()
    return normalized or "unknown"


_BY_CODE: dict[str, Callable[..., SqlErrorReason]] = {
    "42501": AuthorizationError,
    "40P01": DeadlockError,
    "40001": SerializationError,
    "55P03": LockTimeoutError,
    "57014": StatementTimeoutError,
}

_BY_CLASS: dict[str, Callable[..., SqlErrorReason]] = {
    "08": ConnectionError,
    "28": AuthenticationError,
    "42": SqlSyntaxError,
    "23": ConstraintError,
}


def classify_sql_state(
    code: str | None, constraint: object, *, cause: object, message: str, operation: str
) -> SqlErrorReason:
    """The reason for the SQLSTATE ``code``; ``constraint`` names the
    constraint a unique violation (``23505``) broke."""
    if code is None:
        return UnknownError(cause=cause, message=message, operation=operation)
    if code == "23505":
        return UniqueViolation(
            cause=cause,
            message=message,
            operation=operation,
            constraint=_normalize_constraint(constraint),
        )
    reason = _BY_CODE.get(code) or _BY_CLASS.get(code[:2], UnknownError)
    return reason(cause=cause, message=message, operation=operation)


_AUTHENTICATION_FAILURE = re.compile(
    r"authentication failed|no password supplied|no pg_hba\.conf entry"
)
"""libpq reports a failed startup as text, without its SQLSTATE (``28*``)."""


def classify(cause: BaseException, *, message: str, operation: str) -> SqlErrorReason:
    """The reason for a psycopg error (or any exception)."""
    import psycopg

    if not isinstance(cause, psycopg.Error):
        return UnknownError(cause=cause, message=message, operation=operation)
    code = cause.sqlstate
    if code is None and isinstance(cause, (psycopg.OperationalError, psycopg.InterfaceError)):
        if _AUTHENTICATION_FAILURE.search(str(cause)):
            return AuthenticationError(cause=cause, message=message, operation=operation)
        return ConnectionError(cause=cause, message=message, operation=operation)
    return classify_sql_state(
        code, cause.diag.constraint_name, cause=cause, message=message, operation=operation
    )


def catch(message: str, operation: str) -> Callable[[BaseException], SqlError]:
    """Turns an exception into the ``SqlError`` of ``operation``."""
    return lambda cause: SqlError(reason=classify(cause, message=message, operation=operation))


def connection_error(message: str, operation: str, cause: object | None = None) -> SqlError:
    return SqlError(
        reason=ConnectionError(
            cause=cause if cause is not None else Exception(message),
            message=message,
            operation=operation,
        )
    )


def validate_channel_name(channel: str, operation: str) -> SqlError | None:
    """An error when ``channel`` is longer than PostgreSQL allows."""
    if len(channel.encode("utf-8", "surrogatepass")) <= _MAX_CHANNEL_BYTES:
        return None
    return SqlError(
        reason=UnknownError(
            cause=Exception(CHANNEL_TOO_LONG), message=CHANNEL_TOO_LONG, operation=operation
        )
    )


__all__ = [
    "CHANNEL_TOO_LONG",
    "catch",
    "classify",
    "classify_sql_state",
    "connection_error",
    "validate_channel_name",
]
