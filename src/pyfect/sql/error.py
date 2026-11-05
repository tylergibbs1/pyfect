"""The errors of SQL clients (Effect's ``effect/sql/SqlError``).

Every database failure is one ``SqlError`` whose ``reason`` says what kind
of failure it was; match a reason with ``catch_reason``::

    insert.pipe(
        fx.catch_reason(SqlError, UniqueViolation, lambda reason, _e: fx.succeed(None))
    )

Each reason carries the driver's ``cause``, an optional ``message`` and the
``operation`` that failed, and says whether retrying can help
(``is_retryable``). The classes are schema classes, so an ``SqlError``
encodes to JSON and back; a ``cause`` that is an exception is written as
``{"name", "message"}`` and read back as that mapping.

``classify_sqlite_error`` turns an SQLite error (a ``sqlite3.Error``, or
any value with Node's ``code`` / ``errno`` / ``constraint`` / ``message``
properties) into its reason.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from typing import TypeIs

from pyfect import schema as S
from pyfect.errors import with_cause

_CAUSE = S.Union(S.Json, S.Defect(), S.Unknown)
"""Any cause: JSON values as they are, exceptions as ``{"name", "message"}``,
anything else unchanged (Effect's ``Schema.Defect()``, which keeps every
value)."""


class _Reason(S.TaggedError):
    cause: object = S.field(_CAUSE)
    message: str | None = None
    operation: str | None = None

    @property
    def is_retryable(self) -> bool:
        return False

    def __str__(self) -> str:
        return with_cause(self.message or self._tag, self.cause)


class ConnectionError(_Reason, tag="ConnectionError"):
    """The database could not be reached, or the connection broke."""

    @property
    def is_retryable(self) -> bool:
        return True


class AuthenticationError(_Reason, tag="AuthenticationError"):
    """The credentials were rejected."""


class AuthorizationError(_Reason, tag="AuthorizationError"):
    """The user may not do this."""


class SqlSyntaxError(_Reason, tag="SqlSyntaxError"):
    """The statement is not valid SQL for the database."""


class UniqueViolation(_Reason, tag="UniqueViolation"):
    """A unique constraint (``constraint``, or ``"unknown"``) was violated."""

    constraint: str


class ConstraintError(_Reason, tag="ConstraintError"):
    """Another constraint (foreign key, not null, check, ...) was violated."""


class DeadlockError(_Reason, tag="DeadlockError"):
    """The database broke a deadlock by failing this statement."""

    @property
    def is_retryable(self) -> bool:
        return True


class SerializationError(_Reason, tag="SerializationError"):
    """A serializable transaction could not be ordered with another."""

    @property
    def is_retryable(self) -> bool:
        return True


class LockTimeoutError(_Reason, tag="LockTimeoutError"):
    """A lock was not granted in time (SQLite's ``SQLITE_BUSY``)."""

    @property
    def is_retryable(self) -> bool:
        return True


class StatementTimeoutError(_Reason, tag="StatementTimeoutError"):
    """The statement ran longer than the database allows."""

    @property
    def is_retryable(self) -> bool:
        return True


class UnknownError(_Reason, tag="UnknownError"):
    """Any other failure."""


type SqlErrorReason = (
    ConnectionError
    | AuthenticationError
    | AuthorizationError
    | SqlSyntaxError
    | UniqueViolation
    | ConstraintError
    | DeadlockError
    | SerializationError
    | LockTimeoutError
    | StatementTimeoutError
    | UnknownError
)

SQL_ERROR_REASON = S.Union(
    ConnectionError,
    AuthenticationError,
    AuthorizationError,
    SqlSyntaxError,
    UniqueViolation,
    ConstraintError,
    DeadlockError,
    SerializationError,
    LockTimeoutError,
    StatementTimeoutError,
    UnknownError,
)
"""The schema of every reason (Effect's ``SqlErrorReason`` schema)."""


class SqlError(S.TaggedError):
    """A database failure; ``reason`` says which kind. Its ``cause`` (and
    ``__cause__``) is the reason; its ``message`` is the reason's, or the
    reason's tag when that has none."""

    reason: SqlErrorReason = S.field(SQL_ERROR_REASON)

    def __post_init__(self) -> None:
        self.__cause__ = self.reason

    @property
    def cause(self) -> SqlErrorReason:
        return self.reason

    @property
    def message(self) -> str:
        return self.reason.message or self.reason._tag

    @property
    def is_retryable(self) -> bool:
        return self.reason.is_retryable


class ResultLengthMismatch(S.TaggedError):
    """A resolver's query returned ``actual`` rows for ``expected``
    requests."""

    expected: int = S.field(S.Natural)
    actual: int = S.field(S.Natural)

    @property
    def message(self) -> str:
        return f"Expected {self.expected} results but got {self.actual}"


def is_sql_error(u: object) -> TypeIs[SqlError]:
    return isinstance(u, SqlError)


def is_sql_error_reason(u: object) -> TypeIs[SqlErrorReason]:
    return isinstance(u, _Reason)


# --- SQLite ------------------------------------------------------------------

_UNKNOWN_CONSTRAINT = "unknown"
_SQLITE_CONSTRAINT_UNIQUE = "SQLITE_CONSTRAINT_UNIQUE"
_SQLITE_CONSTRAINT_UNIQUE_CODE = 2067
_UNIQUE_PREFIX = "UNIQUE constraint failed:"


def _prop(cause: object, name: str) -> object:
    """``cause``'s property ``name``: a mapping key or an attribute."""
    if isinstance(cause, Mapping):
        return cause.get(name)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    return getattr(cause, name, None)


def _code(cause: object) -> str | int | None:
    code = _prop(cause, "sqlite_errorname" if isinstance(cause, sqlite3.Error) else "code")
    return code if isinstance(code, str | int) and not isinstance(code, bool) else None


def _errno(cause: object) -> object:
    # ``sqlite3`` sets the codes only on errors from the library itself.
    return _prop(cause, "sqlite_errorcode" if isinstance(cause, sqlite3.Error) else "errno")


def _numeric_code(cause: object) -> int | None:
    code = _code(cause)
    if isinstance(code, int):
        return code
    errno = _errno(cause)
    return errno if isinstance(errno, int) and not isinstance(errno, bool) else None


def _matches_numeric(cause: object, expected: int) -> bool:
    return _code(cause) == expected or _errno(cause) == expected


def _matches_code(code: str, expected: str) -> bool:
    return code == expected or code.startswith(expected + "_")


def _normalize_constraint(identifier: object) -> str:
    if not isinstance(identifier, str):
        return _UNKNOWN_CONSTRAINT
    trimmed = identifier.strip()
    return trimmed or _UNKNOWN_CONSTRAINT


def _unique_constraint(cause: object) -> str:
    constraint = _prop(cause, "constraint")
    if constraint is not None:
        return _normalize_constraint(constraint)
    message = str(cause) if isinstance(cause, sqlite3.Error) else _prop(cause, "message")
    if not isinstance(message, str):
        return _UNKNOWN_CONSTRAINT
    index = message.find(_UNIQUE_PREFIX)
    if index == -1:
        return _UNKNOWN_CONSTRAINT
    return _normalize_constraint(message[index + len(_UNIQUE_PREFIX) :])


type _MakeReason = Callable[..., SqlErrorReason]

_BY_CODE: tuple[tuple[tuple[str, ...], _MakeReason], ...] = (
    (("SQLITE_AUTH",), AuthenticationError),
    (("SQLITE_PERM",), AuthorizationError),
    (("SQLITE_CONSTRAINT",), ConstraintError),
    (("SQLITE_BUSY", "SQLITE_LOCKED"), LockTimeoutError),
    (("SQLITE_CANTOPEN",), ConnectionError),
)

_BY_PRIMARY_CODE: Mapping[int, _MakeReason] = {
    23: AuthenticationError,
    3: AuthorizationError,
    19: ConstraintError,
    5: LockTimeoutError,
    6: LockTimeoutError,
    14: ConnectionError,
}


def classify_sqlite_error(
    cause: object, *, message: str | None = None, operation: str | None = None
) -> SqlErrorReason:
    """The reason for an SQLite failure, from its result code: the name
    (``"SQLITE_BUSY"``, ...) when there is one, else the number (extended
    codes are reduced to their primary code). A unique violation reads its
    constraint from ``constraint`` or the message."""
    code = _code(cause)
    if code == _SQLITE_CONSTRAINT_UNIQUE or _matches_numeric(cause, _SQLITE_CONSTRAINT_UNIQUE_CODE):
        return UniqueViolation(
            cause=cause, message=message, operation=operation, constraint=_unique_constraint(cause)
        )
    if isinstance(code, str):
        for prefixes, reason in _BY_CODE:
            if any(_matches_code(code, prefix) for prefix in prefixes):
                return reason(cause=cause, message=message, operation=operation)
    numeric = _numeric_code(cause)
    if numeric is not None:
        reason = _BY_PRIMARY_CODE.get(numeric & 0xFF, UnknownError)
        return reason(cause=cause, message=message, operation=operation)
    return UnknownError(cause=cause, message=message, operation=operation)


__all__ = [
    "SQL_ERROR_REASON",
    "AuthenticationError",
    "AuthorizationError",
    "ConnectionError",
    "ConstraintError",
    "DeadlockError",
    "LockTimeoutError",
    "ResultLengthMismatch",
    "SerializationError",
    "SqlError",
    "SqlErrorReason",
    "SqlSyntaxError",
    "StatementTimeoutError",
    "UniqueViolation",
    "UnknownError",
    "classify_sqlite_error",
    "is_sql_error",
    "is_sql_error_reason",
]
