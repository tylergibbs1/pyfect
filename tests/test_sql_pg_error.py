"""``pyfect.sql.pg.error.classify``: psycopg errors to reasons."""
# pyright: reportPrivateUsage=false

import pytest

pytest.importorskip("psycopg")

import psycopg

from pyfect.sql.pg.error import classify


def _reason(error: BaseException, operation: str = "query") -> str:
    return classify(error, message="m", operation=operation)._tag


def test_server_errors_are_classified_by_sqlstate():
    assert _reason(psycopg.errors.UniqueViolation("dup")) == "UniqueViolation"
    assert _reason(psycopg.errors.QueryCanceled("cancelled")) == "StatementTimeoutError"


def test_a_lost_connection_without_sqlstate_is_a_connection_error():
    assert _reason(psycopg.OperationalError("server closed the connection")) == "ConnectionError"


@pytest.mark.parametrize(
    "text",
    [
        'connection failed: connection to server at "127.0.0.1", port 5432 failed: '
        'FATAL:  password authentication failed for user "postgres"',
        "connection failed: fe_sendauth: no password supplied",
        'connection failed: FATAL:  no pg_hba.conf entry for host "10.0.0.1", user "x"',
    ],
)
def test_authentication_failures_at_connect_are_authentication_errors(text: str):
    """libpq reports startup failures as text only, without a SQLSTATE."""
    assert _reason(psycopg.OperationalError(text), "connect") == "AuthenticationError"


def test_other_connect_failures_are_connection_errors():
    error = psycopg.OperationalError("connection failed: Connection refused")
    assert _reason(error, "connect") == "ConnectionError"
