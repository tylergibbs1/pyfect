"""Ports of Effect's ``sql-mysql2/test/SqlErrorClassification.test.ts``
(``describe("MysqlClient SqlError classification")``).

As in Effect, the driver is replaced (``asyncmy.connect`` raises, where
Effect mocks ``mysql2``'s pool) and ``make`` fails with the reason of its
connection check. A cause is asyncmy's ``MySQLError(errno, message)``:
Effect's ``sqlMessage`` / ``message`` are its message, and a ``constraint``
attribute stands for Effect's ``constraint`` property.
"""

from typing import Any

import pytest

pytest.importorskip("asyncmy")

import asyncmy
from asyncmy.errors import MySQLError

import pyfect as fx
from pyfect.reactivity import layer as reactivity_layer
from pyfect.sql import mysql
from pyfect.sql.error import SqlErrorReason, UniqueViolation


def _error(errno: object, message: object = "failed", **attributes: object) -> MySQLError:
    error = MySQLError(errno, message)
    for name, value in attributes.items():
        setattr(error, name, value)
    return error


def _connect_failure_reason(monkeypatch: pytest.MonkeyPatch, cause: MySQLError) -> SqlErrorReason:
    async def connect(**_options: Any) -> Any:
        raise cause

    monkeypatch.setattr(asyncmy, "connect", connect)
    failed = fx.scoped(mysql.make(mysql.MysqlClientConfig())).flip().or_die()
    error = fx.run_blocking(failed.pipe(fx.provide(reactivity_layer)))
    assert error.reason.message == "MysqlClient: Failed to connect"
    assert error.reason.operation == "connect"
    assert error.reason.cause is cause
    return error.reason


def _assert_unique_violation(reason: SqlErrorReason, constraint: str) -> None:
    assert isinstance(reason, UniqueViolation)
    assert reason.constraint == constraint


def test_maps_representative_errno_codes_to_reasons(monkeypatch: pytest.MonkeyPatch):
    """maps representative errno codes to reasons"""
    cases = [
        (1040, "ConnectionError"),
        (1045, "AuthenticationError"),
        (1142, "AuthorizationError"),
        (1064, "SqlSyntaxError"),
        (1062, "UniqueViolation"),
        (1048, "ConstraintError"),
        (1213, "DeadlockError"),
        (1205, "LockTimeoutError"),
        (3024, "StatementTimeoutError"),
    ]
    for errno, expected in cases:
        assert type(_connect_failure_reason(monkeypatch, _error(errno))).__name__ == expected


def test_falls_back_to_unknown_error_for_unmapped_errno(monkeypatch: pytest.MonkeyPatch):
    """falls back to UnknownError for unmapped errno"""
    assert type(_connect_failure_reason(monkeypatch, _error(9999))).__name__ == "UnknownError"


def test_classifies_duplicate_entry_errno_1062_as_unique_violation(
    monkeypatch: pytest.MonkeyPatch,
):
    """classifies duplicate-entry errno 1062 as UniqueViolation"""
    _assert_unique_violation(_connect_failure_reason(monkeypatch, _error(1062)), "unknown")


def test_extracts_duplicate_entry_constraints_from_structured_fields_and_common_messages(
    monkeypatch: pytest.MonkeyPatch,
):
    """extracts duplicate-entry constraints from structured fields and common messages"""
    explicit = _error(
        1062,
        "Duplicate entry 'user@example.com' for key 'ignored_key'",
        constraint="  users_email_key  ",
    )
    _assert_unique_violation(_connect_failure_reason(monkeypatch, explicit), "users_email_key")
    single_quoted = _error(1062, "Duplicate entry 'user@example.com' for key 'users_email_key'")
    _assert_unique_violation(_connect_failure_reason(monkeypatch, single_quoted), "users_email_key")
    backtick_quoted = _error(1062, "Duplicate entry '1' for key `PRIMARY`")
    _assert_unique_violation(_connect_failure_reason(monkeypatch, backtick_quoted), "PRIMARY")
    unquoted = _error(1062, "Duplicate entry 'user@example.com' for key users_email_key")
    _assert_unique_violation(_connect_failure_reason(monkeypatch, unquoted), "users_email_key")


def test_uses_unknown_for_blank_missing_malformed_or_non_string_duplicate_entry_metadata(
    monkeypatch: pytest.MonkeyPatch,
):
    """uses unknown for blank, missing, malformed, or non-string duplicate-entry metadata"""
    missing = MySQLError(1062)
    _assert_unique_violation(_connect_failure_reason(monkeypatch, missing), "unknown")
    blank = _error(1062, "Duplicate entry 'user@example.com' for key '   '", constraint="   ")
    _assert_unique_violation(_connect_failure_reason(monkeypatch, blank), "unknown")
    malformed = _error(1062, "Duplicate entry 'user@example.com'")
    _assert_unique_violation(_connect_failure_reason(monkeypatch, malformed), "unknown")
    non_string = _error(
        1062, {"text": "Duplicate entry 'user@example.com' for key 'users_email_key'"}
    )
    _assert_unique_violation(_connect_failure_reason(monkeypatch, non_string), "unknown")


def test_keeps_non_unique_constraint_errno_values_classified_as_constraint_error(
    monkeypatch: pytest.MonkeyPatch,
):
    """keeps non-unique constraint errno values classified as ConstraintError"""
    assert type(_connect_failure_reason(monkeypatch, _error(1452))).__name__ == "ConstraintError"


def test_client_errors_without_a_server_errno_are_unknown(monkeypatch: pytest.MonkeyPatch):
    """(pyfect) a refused connection (asyncmy's client errno 2003) is not
    one of Effect's errnos, so it is an UnknownError, as mysql2's
    ``ECONNREFUSED`` is in Effect"""
    refused = _error(2003, "Can't connect to MySQL server on 'localhost'")
    assert type(_connect_failure_reason(monkeypatch, refused)).__name__ == "UnknownError"
    assert (
        type(_connect_failure_reason(monkeypatch, _error("not an errno"))).__name__
        == "UnknownError"
    )
