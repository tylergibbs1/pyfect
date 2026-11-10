"""``str()`` of an HTTP client error names its cause when it has no description.

Effect's message is ``Transport error (POST http://.../jobs)`` and says nothing of
why; ``message`` keeps that shape (tests/oracle/test_http_client.py), but ``str()``,
what a log line or ``f"{error}"`` shows, adds the cause (docs/PARITY.md)."""

import pytest

from pyfect.http import error as http_error
from pyfect.http import request as req
from pyfect.http.error import HttpClientError, HttpClientErrorReason
from pyfect.http.headers import Headers
from pyfect.http.response import HttpClientResponse
from pyfect.stream import succeed as succeed_stream

REQUEST = req.post("http://test/jobs")
RESPONSE = HttpClientResponse(REQUEST, 500, Headers(), succeed_stream(b""))


class Released(Exception):
    pass


CAUSE = Released("the HTTP client is closed")
URL = "POST http://test/jobs"


def reasons(cause: object, description: str | None) -> list[HttpClientErrorReason]:
    """One of every reason: a new reason class fails test_every_reason_is_covered."""
    return [
        http_error.TransportError(REQUEST, cause, description),
        http_error.EncodeError(REQUEST, cause, description),
        http_error.InvalidUrlError(REQUEST, cause, description),
        http_error.StatusCodeError(REQUEST, RESPONSE, cause, description),
        http_error.DecodeError(REQUEST, RESPONSE, cause, description),
        http_error.EmptyBodyError(REQUEST, RESPONSE, cause, description),
    ]


def test_every_reason_is_covered():
    covered = {type(r) for r in reasons(None, None)}
    declared = {getattr(http_error, name) for name in http_error.__all__}
    reason_classes = {c for c in declared if isinstance(c, type) and issubclass(c, Exception)} - {
        HttpClientError,
        http_error.HttpClientErrorSchema,
    }
    assert covered == reason_classes


def test_transport_error_str_names_its_cause():
    error = HttpClientError(http_error.TransportError(REQUEST, CAUSE))
    assert error.message == f"Transport error ({URL})"
    assert str(error) == f"Transport error ({URL}): Released: the HTTP client is closed"


@pytest.mark.parametrize("reason", reasons(CAUSE, None), ids=lambda r: type(r).__name__)
def test_str_names_the_cause_without_a_description(reason: HttpClientErrorReason):
    assert str(reason) == f"{reason.message}: Released: the HTTP client is closed"
    assert str(HttpClientError(reason)) == str(reason)


@pytest.mark.parametrize("reason", reasons(CAUSE, "it broke"), ids=lambda r: type(r).__name__)
def test_a_description_already_explains(reason: HttpClientErrorReason):
    assert str(reason) == reason.message
    assert "it broke" in str(reason)


@pytest.mark.parametrize("reason", reasons(None, None), ids=lambda r: type(r).__name__)
def test_no_cause_no_suffix(reason: HttpClientErrorReason):
    assert str(HttpClientError(reason)) == reason.message


def test_a_cause_that_is_not_an_exception_is_shown_with_repr():
    error = HttpClientError(http_error.TransportError(REQUEST, {"code": 7}))
    assert str(error) == f"Transport error ({URL}): {{'code': 7}}"
