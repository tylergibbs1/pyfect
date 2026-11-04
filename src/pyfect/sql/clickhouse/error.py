"""ClickHouse failures: ``ClickhouseError``, what the server answers a
failed request with, and their ``SqlError`` reasons (the
``classifyError`` of Effect's ``@effect/sql-clickhouse`` ``ClickhouseClient``).

``classify`` reads the cause's numeric ``code``: 516 is an
``AuthenticationError``, 497 an ``AuthorizationError``, 36, 60, 62 and 242
``SqlSyntaxError`` and 159 and 469 ``StatementTimeoutError``; every other
failure (an unknown code, a transport error) is the fallback reason,
``UnknownError`` or, while connecting, ``ConnectionError``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Literal

from pyfect._digits import parse_signed_digits
from pyfect.sql.error import (
    AuthenticationError,
    AuthorizationError,
    ConnectionError,
    SqlError,
    SqlErrorReason,
    SqlSyntaxError,
    StatementTimeoutError,
    UnknownError,
)

# ``@clickhouse/client``'s ``parseError``: the innermost exception's code,
# message and ``(TYPE)``.
_ERROR = re.compile(
    r"(Code|Error): (?P<code>[0-9]+).*Exception: (?P<message>.+?)"
    r"\((?P<type>(?=[A-Z0-9_]*[A-Z]{3})[A-Z0-9_]+)\)",
    re.DOTALL,
)
_SYNTAX = frozenset({36, 60, 62, 242})
_TIMEOUT = frozenset({159, 469})


class ClickhouseError(Exception):
    """An error the server answered with: its ``code`` (``62``) and
    ``type`` (``SYNTAX_ERROR``), or ``None`` for both when the answer was
    not a ClickHouse exception (a proxy's error page)."""

    def __init__(self, message: str, code: int | None = None, type: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.type = type

    def __repr__(self) -> str:
        return f"ClickhouseError({self.message!r}, code={self.code!r}, type={self.type!r})"


def parse_error(text: str) -> ClickhouseError:
    """The error in a failed response's body."""
    found = _ERROR.search(text)
    if found is None:
        return ClickhouseError(text)
    return ClickhouseError(found["message"], int(found["code"]), found["type"])


def _code(cause: object) -> int | None:
    code = getattr(cause, "code", None)
    if isinstance(code, bool):
        return None
    if isinstance(code, int):
        return code
    if isinstance(code, str):
        return parse_signed_digits(code.strip())
    return None


def classify(
    cause: object,
    *,
    message: str,
    operation: str,
    fallback: Literal["connection", "unknown"] = "unknown",
) -> SqlErrorReason:
    """The reason for a failure ``cause`` (see the module)."""
    code = _code(cause)
    if code == 516:
        reason: Callable[..., SqlErrorReason] = AuthenticationError
    elif code == 497:
        reason = AuthorizationError
    elif code in _SYNTAX:
        reason = SqlSyntaxError
    elif code in _TIMEOUT:
        reason = StatementTimeoutError
    else:
        reason = ConnectionError if fallback == "connection" else UnknownError
    return reason(cause=cause, message=message, operation=operation)


def catch(
    message: str, operation: str, fallback: Literal["connection", "unknown"] = "unknown"
) -> Callable[[object], SqlError]:
    """Turns a failure into the ``SqlError`` of ``operation``."""
    return lambda cause: SqlError(
        reason=classify(cause, message=message, operation=operation, fallback=fallback)
    )


__all__ = ["ClickhouseError", "catch", "classify", "parse_error"]
