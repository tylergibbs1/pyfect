"""Ports of Effect's ``sql-pg/test/SqlErrorClassification.test.ts``
(``describe("PostgreSQL SQLSTATE classification")``).

``queryFailureReason`` reads ``code`` and ``constraint`` off the cause, as
the test's helper does; ``classify`` (psycopg errors) is pinned in
``tests/test_sql_pg.py``.
"""
# pyright: reportPrivateUsage=false

from collections.abc import Mapping

import pytest

pytest.importorskip("psycopg")

from pyfect.sql.error import SqlErrorReason, UniqueViolation
from pyfect.sql.pg.error import classify_sql_state


def _reason(cause: Mapping[str, object]) -> SqlErrorReason:
    code = cause.get("code")
    return classify_sql_state(
        code if isinstance(code, str) else None,
        cause.get("constraint"),
        cause=cause,
        message="Failed to execute statement",
        operation="query",
    )


def _assert_unique_violation(reason: SqlErrorReason, constraint: str) -> None:
    assert isinstance(reason, UniqueViolation)
    assert reason.constraint == constraint


def test_checks_42501_before_generic_42():
    """checks 42501 before generic 42*"""
    assert _reason({"code": "42501"})._tag == "AuthorizationError"
    assert _reason({"code": "42P01"})._tag == "SqlSyntaxError"


def test_falls_back_to_unknown_error_for_unmapped_sqlstate():
    """falls back to UnknownError for unmapped SQLSTATE"""
    assert _reason({"code": "ZZZZZ"})._tag == "UnknownError"


def test_classifies_23505_as_unique_violation_and_trims_the_constraint_name():
    """classifies 23505 as UniqueViolation and trims the constraint name"""
    _assert_unique_violation(
        _reason({"code": "23505", "constraint": "  users_email_key  "}), "users_email_key"
    )


def test_uses_unknown_for_missing_non_string_or_blank_unique_violation_constraints():
    """uses unknown for missing, non-string, or blank unique violation constraints"""
    _assert_unique_violation(_reason({"code": "23505"}), "unknown")
    _assert_unique_violation(_reason({"code": "23505", "constraint": 123}), "unknown")
    _assert_unique_violation(_reason({"code": "23505", "constraint": "   "}), "unknown")


def test_keeps_non_unique_integrity_constraints_classified_as_constraint_error():
    """keeps non-unique integrity constraints classified as ConstraintError"""
    reason = _reason({"code": "23503", "constraint": "orders_user_id_fkey"})
    assert reason._tag == "ConstraintError"
