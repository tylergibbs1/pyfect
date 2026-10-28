"""Ports of Effect's ``sql/SqlError.test.ts``.

Each test's docstring is the Effect test title; the schema roundtrip is
one parametrized test per reason, as Effect's loop makes one per reason.
"""
# pyright: reportPrivateUsage=false

from collections.abc import Callable
from typing import Any

import pytest

from pyfect import schema as S
from pyfect import testing
from pyfect.sql import error as E

_CONSTRAINT = "users_email_key"


def _unique(**args: Any) -> E.UniqueViolation:
    return E.UniqueViolation(constraint=_CONSTRAINT, **args)


_REASONS: list[tuple[str, bool, Callable[..., E.SqlErrorReason]]] = [
    ("ConnectionError", True, E.ConnectionError),
    ("AuthenticationError", False, E.AuthenticationError),
    ("AuthorizationError", False, E.AuthorizationError),
    ("SqlSyntaxError", False, E.SqlSyntaxError),
    ("UniqueViolation", False, _unique),
    ("ConstraintError", False, E.ConstraintError),
    ("DeadlockError", True, E.DeadlockError),
    ("SerializationError", True, E.SerializationError),
    ("LockTimeoutError", True, E.LockTimeoutError),
    ("StatementTimeoutError", True, E.StatementTimeoutError),
    ("UnknownError", False, E.UnknownError),
]


def _assert_unique_violation(reason: E.SqlErrorReason, constraint: str) -> None:
    assert isinstance(reason, E.UniqueViolation)
    assert reason.constraint == constraint


def test_reason_classes_expose_expected_tags_and_retryability():
    """reason classes expose expected tags and retryability"""
    for tag, retryable, make in _REASONS:
        reason = make(cause={"tag": tag}, message=f"{tag} message", operation="execute")
        assert reason._tag == tag
        assert reason.is_retryable is retryable
        assert reason.message == f"{tag} message"
        assert reason.operation == "execute"
        assert reason.cause == {"tag": tag}


def test_delegates_message_cause_and_retryability_for_every_reason_type():
    """delegates message, cause and retryability for every reason type"""
    for tag, retryable, make in _REASONS:
        without_message = make(cause={"tag": f"{tag}-fallback"})
        with_message = make(
            cause={"tag": f"{tag}-custom"}, message=f"{tag} custom", operation="execute"
        )
        with_empty_message = make(cause={"tag": f"{tag}-empty"}, message="")
        fallback = E.SqlError(reason=without_message)
        explicit = E.SqlError(reason=with_message)
        empty = E.SqlError(reason=with_empty_message)

        assert fallback.message == tag
        assert fallback.cause is without_message
        assert fallback.is_retryable is retryable
        assert explicit.message == f"{tag} custom"
        assert explicit.cause is with_message
        assert explicit.is_retryable is retryable
        assert empty.message == tag
        assert empty.cause is with_empty_message
        assert empty.is_retryable is retryable


def test_is_sql_error_only_matches_the_sql_error_wrapper():
    """isSqlError only matches the SqlError wrapper"""
    reason = E.UnknownError(cause=Exception("boom"))
    error = E.SqlError(reason=reason)
    mismatch = E.ResultLengthMismatch(expected=1, actual=0)

    assert E.is_sql_error(error)
    assert not E.is_sql_error(reason)
    assert not E.is_sql_error(mismatch)


def test_is_sql_error_reason_only_matches_reason_values():
    """isSqlErrorReason only matches reason values"""
    reason = E.UnknownError(cause=Exception("boom"))
    error = E.SqlError(reason=reason)

    assert E.is_sql_error_reason(reason)
    assert not E.is_sql_error_reason(error)


def test_constructs_and_recognizes_unique_violation_reasons():
    """constructs and recognizes UniqueViolation reasons"""
    reason = E.UniqueViolation(
        cause={"code": "23505"},
        message="duplicate key value violates unique constraint",
        operation="insert",
        constraint=_CONSTRAINT,
    )

    assert E.is_sql_error_reason(reason)
    assert reason._tag == "UniqueViolation"
    assert reason.is_retryable is False
    assert reason.constraint == _CONSTRAINT


def test_classify_sqlite_error_maps_sqlite_unique_constraint_codes_to_unique_violation():
    """classifySqliteError maps sqlite unique constraint codes to UniqueViolation"""
    by_string = E.classify_sqlite_error(
        {"code": "SQLITE_CONSTRAINT_UNIQUE", "constraint": f" {_CONSTRAINT} "}
    )
    by_numeric_code = E.classify_sqlite_error({"code": 2067, "constraint": _CONSTRAINT})
    by_errno = E.classify_sqlite_error({"errno": 2067, "constraint": _CONSTRAINT})
    by_extended_errno = E.classify_sqlite_error(
        {"code": 19, "errno": 2067, "constraint": _CONSTRAINT}
    )
    unknown = E.classify_sqlite_error({"code": "NOT_SQLITE"})

    _assert_unique_violation(by_string, _CONSTRAINT)
    _assert_unique_violation(by_numeric_code, _CONSTRAINT)
    _assert_unique_violation(by_errno, _CONSTRAINT)
    _assert_unique_violation(by_extended_errno, _CONSTRAINT)
    assert unknown._tag == "UnknownError"


def test_classify_sqlite_error_extracts_sqlite_unique_descriptors_from_messages():
    """classifySqliteError extracts sqlite unique descriptors from messages"""
    reason = E.classify_sqlite_error(
        {"code": "SQLITE_CONSTRAINT_UNIQUE", "message": "UNIQUE constraint failed: users.email"}
    )
    _assert_unique_violation(reason, "users.email")


def test_classify_sqlite_error_prefers_explicit_sqlite_unique_constraint_identifiers():
    """classifySqliteError prefers explicit sqlite unique constraint identifiers"""
    reason = E.classify_sqlite_error(
        {
            "code": "SQLITE_CONSTRAINT_UNIQUE",
            "constraint": " users_email_key ",
            "message": "UNIQUE constraint failed: users.email",
        }
    )
    _assert_unique_violation(reason, "users_email_key")


def test_classify_sqlite_error_falls_back_to_unknown_for_blank_or_missing_unique_identifiers():
    """classifySqliteError falls back to unknown for blank or missing sqlite unique identifiers"""
    blank = E.classify_sqlite_error(
        {
            "code": "SQLITE_CONSTRAINT_UNIQUE",
            "constraint": "   ",
            "message": "UNIQUE constraint failed: users.email",
        }
    )
    missing = E.classify_sqlite_error({"code": "SQLITE_CONSTRAINT_UNIQUE"})
    non_string = E.classify_sqlite_error({"code": "SQLITE_CONSTRAINT_UNIQUE", "constraint": 123})
    malformed_message = E.classify_sqlite_error(
        {
            "code": "SQLITE_CONSTRAINT_UNIQUE",
            "message": {"text": "UNIQUE constraint failed: users.email"},
        }
    )

    _assert_unique_violation(blank, "unknown")
    _assert_unique_violation(missing, "unknown")
    _assert_unique_violation(non_string, "unknown")
    _assert_unique_violation(malformed_message, "unknown")


def test_classify_sqlite_error_keeps_generic_sqlite_constraints_as_constraint_error():
    """classifySqliteError keeps generic sqlite constraints as ConstraintError"""
    for cause in (
        {"code": "SQLITE_CONSTRAINT"},
        {"code": 19},
        {"errno": 19},
        {"code": "SQLITE_CONSTRAINT_PRIMARYKEY"},
        {"code": 1555},
    ):
        assert E.classify_sqlite_error(cause)._tag == "ConstraintError"


@pytest.mark.parametrize(("tag", "retryable", "make"), _REASONS, ids=[r[0] for r in _REASONS])
@testing.effect
def test_schema_roundtrip_for_sql_error_wrapping(
    tag: str, retryable: bool, make: Callable[..., E.SqlErrorReason]
):
    """schema roundtrip for SqlError wrapping ${reasonCase.tag}"""
    cause = {"tag": tag}
    error = E.SqlError(reason=make(cause=cause, message=f"{tag} message", operation="execute"))

    encoded = yield from S.encode_effect(E.SqlError)(error)
    decoded = yield from S.decode_effect(E.SqlError)(encoded)

    assert decoded._tag == "SqlError"
    assert decoded.reason._tag == tag
    assert decoded.reason.message == f"{tag} message"
    assert decoded.reason.operation == "execute"
    assert decoded.reason.cause == cause
    assert decoded.message == f"{tag} message"
    assert decoded.is_retryable is retryable
    assert decoded.cause is decoded.reason
    if isinstance(decoded.reason, E.UniqueViolation):
        assert decoded.reason.constraint == _CONSTRAINT
