"""Ports of Effect's ``sql-mssql/test/SqlErrorClassification.test.ts``.

Each test's docstring is the Effect test title. Effect's ``vi.mock("tedious")``
is ``_mssql_fake``: the client's ``SELECT 1`` succeeds, then the statement
under test raises an error with the given ``number`` / ``message`` /
``constraint`` properties.
"""

from typing import Any

import pytest

pytest.importorskip("pytds")

import pyfect as fx
from pyfect.reactivity import layer as reactivity_layer
from pyfect.sql import mssql
from pyfect.sql.error import SqlError, SqlErrorReason, UniqueViolation

from . import _mssql_fake


def _query_failure_reason(monkeypatch: pytest.MonkeyPatch, **cause: Any) -> SqlErrorReason:
    fake = _mssql_fake.install(monkeypatch)
    fake.request_causes = [None, _mssql_fake.ServerError(**cause)]

    def body():
        client = yield from mssql.make(mssql.MssqlClientConfig(server="localhost"))
        error = yield from client("SELECT 1").flip()
        assert isinstance(error, SqlError)
        return error.reason

    return fx.run_sync(fx.scoped(fx.gen(body)).pipe(fx.provide(reactivity_layer)).or_die())


def _tag(monkeypatch: pytest.MonkeyPatch, number: int) -> str:
    return type(_query_failure_reason(monkeypatch, number=number)).__name__


def _assert_unique_violation(reason: SqlErrorReason, constraint: str) -> None:
    assert isinstance(reason, UniqueViolation)
    assert reason.constraint == constraint


def test_maps_representative_error_numbers_to_reasons(monkeypatch: pytest.MonkeyPatch):
    """maps representative error numbers to reasons"""
    cases = [
        (233, "ConnectionError"),
        (18456, "AuthenticationError"),
        (229, "AuthorizationError"),
        (102, "SqlSyntaxError"),
        (2601, "UniqueViolation"),
        (2627, "UniqueViolation"),
        (547, "ConstraintError"),
        (1205, "DeadlockError"),
        (3960, "SerializationError"),
        (1222, "LockTimeoutError"),
    ]
    for number, expected_tag in cases:
        assert _tag(monkeypatch, number) == expected_tag


def test_falls_back_to_unknown_error_for_unmapped_error_numbers(monkeypatch: pytest.MonkeyPatch):
    """falls back to UnknownError for unmapped error numbers"""
    assert _tag(monkeypatch, 99999) == "UnknownError"


def test_classifies_2601_as_unique_violation_and_extracts_the_unique_index(
    monkeypatch: pytest.MonkeyPatch,
):
    """classifies duplicate-key number 2601 as UniqueViolation and extracts the unique index"""
    reason = _query_failure_reason(
        monkeypatch,
        number=2601,
        message="Cannot insert duplicate key row in object 'dbo.Users' with unique index "
        "'IX_Users_Email'. The duplicate key value is (user@example.com).",
    )
    _assert_unique_violation(reason, "IX_Users_Email")


def test_classifies_2627_as_unique_violation_and_extracts_the_constraint(
    monkeypatch: pytest.MonkeyPatch,
):
    """classifies constraint number 2627 as UniqueViolation and extracts the constraint"""
    reason = _query_failure_reason(
        monkeypatch,
        number=2627,
        message="Violation of UNIQUE KEY constraint 'UQ_Users_Email'. Cannot insert duplicate "
        "key in object 'dbo.Users'. The duplicate key value is (user@example.com).",
    )
    _assert_unique_violation(reason, "UQ_Users_Email")


def test_prefers_structured_constraints_and_trims_whitespace(monkeypatch: pytest.MonkeyPatch):
    """prefers structured constraints and trims whitespace"""
    reason = _query_failure_reason(
        monkeypatch,
        number=2601,
        constraint="  IX_Structured_Email  ",
        message="Cannot insert duplicate key row in object 'dbo.Users' with unique index "
        "'IX_Users_Email'. The duplicate key value is (user@example.com).",
    )
    _assert_unique_violation(reason, "IX_Structured_Email")


def test_uses_unknown_for_blank_missing_malformed_or_non_string_metadata(
    monkeypatch: pytest.MonkeyPatch,
):
    """uses unknown for blank, missing, malformed, or non-string unique violation metadata"""
    missing = _query_failure_reason(monkeypatch, number=2601)
    _assert_unique_violation(missing, "unknown")

    blank = _query_failure_reason(
        monkeypatch,
        number=2627,
        constraint="   ",
        message="Violation of UNIQUE KEY constraint '   '. Cannot insert duplicate key in "
        "object 'dbo.Users'.",
    )
    _assert_unique_violation(blank, "unknown")

    malformed = _query_failure_reason(
        monkeypatch,
        number=2601,
        message="Cannot insert duplicate key row in object 'dbo.Users'.",
    )
    _assert_unique_violation(malformed, "unknown")

    non_string = _query_failure_reason(
        monkeypatch,
        number=2627,
        constraint=2627,
        message={"text": "Violation of UNIQUE KEY constraint 'UQ_Users_Email'."},
    )
    _assert_unique_violation(non_string, "unknown")


def test_keeps_non_unique_constraint_number_547_classified_as_constraint_error(
    monkeypatch: pytest.MonkeyPatch,
):
    """keeps non-unique constraint number 547 classified as ConstraintError"""
    assert _tag(monkeypatch, 547) == "ConstraintError"
