"""Ports of Effect's ``http/HttpStatus.test.ts``. Each test's docstring is
the Effect test title."""

from pyfect.http.status import from_literal


def test_from_literal_returns_the_numeric_status_code() -> None:
    """fromLiteral returns the numeric status code"""
    assert from_literal("Continue") == 100
    assert from_literal("OK") == 200
    assert from_literal("Ok") == 200
    assert from_literal("Created") == 201
    assert from_literal("MovedPermanently") == 301
    assert from_literal("Conflict") == 409
    assert from_literal("InternalServerError") == 500
    assert from_literal("NetworkAuthenticationRequired") == 511
