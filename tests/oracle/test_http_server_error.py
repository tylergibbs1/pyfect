"""Ports of Effect's ``http/HttpServerError.test.ts``. Each test's
docstring is the Effect test title; a response carried by a defect is
``Die(UnhandledError(response))``."""

from typing import Any

import pyfect as fx
from pyfect import effect
from pyfect.cause import UnhandledError
from pyfect.cause import die as die_cause
from pyfect.cause import fail as fail_cause
from pyfect.http import server_response
from pyfect.http.server_error import (
    HttpServerError,
    InternalError,
    RequestParseError,
    ResponseError,
    RouteNotFound,
    ServeError,
    cause_response_stripped,
    is_http_server_error,
)
from pyfect.http.server_request import ServerRequest
from pyfect.http.server_respondable import to_response
from pyfect.http.url_params import CurrentRedactedNames
from pyfect.http.web import WebRequest
from pyfect.http.web_handler import request_from_web


def _request(method: str, url: str) -> ServerRequest:
    return request_from_web(WebRequest(url, method=method))


def test_formats_request_reason_messages() -> None:
    """formats request reason messages"""
    request = _request("POST", "http://example.com/widgets")
    parse_error = RequestParseError(request, "invalid body")
    assert parse_error.message == "RequestParseError (POST /widgets): invalid body"
    assert RouteNotFound(request).message == "RouteNotFound (POST /widgets)"


def test_redacts_query_params_using_the_current_redacted_names() -> None:
    """redacts query params using the current redacted names"""
    request = _request("GET", "http://example.com/widgets?token=token-secret&sig=sig-visible")
    message = fx.run_sync(
        effect.sync(lambda: RouteNotFound(request).message).pipe(
            effect.provide_service(CurrentRedactedNames, ("token",))
        )
    )
    assert message == "RouteNotFound (GET /widgets?token=REDACTED&sig=sig-visible)"


def test_formats_response_reason_messages() -> None:
    """formats response reason messages"""
    request = _request("GET", "http://example.com/tea")
    error = ResponseError(request, server_response.empty(status=418), "short and stout")
    assert error.message == "ResponseError (418 GET /tea): short and stout"


def test_delegates_message_and_accessors() -> None:
    """delegates message and accessors"""
    request = _request("GET", "http://example.com/ok")
    response = server_response.empty(status=503)
    reason = ResponseError(request, response)
    error = HttpServerError(reason)
    assert error.message == reason.message
    assert error.request is request
    assert error.response is response
    assert error.reason is reason


def test_forwards_the_reason_cause() -> None:
    """forwards the reason cause"""
    request = _request("GET", "http://example.com/boom")
    cause = RuntimeError("boom")
    reason = InternalError(request, cause=cause)
    error = HttpServerError(reason)
    assert reason.cause is cause
    assert error.cause is cause


def test_maps_reasons_to_status_codes() -> None:
    """maps reasons to status codes"""
    request = _request("GET", "http://example.com/status")
    response = server_response.empty(status=418)
    cases: list[tuple[Any, int]] = [
        (RequestParseError(request), 400),
        (RouteNotFound(request), 404),
        (InternalError(request), 500),
        (ResponseError(request, response), 500),
        (HttpServerError(RequestParseError(request)), 400),
    ]
    for respondable, status in cases:
        assert fx.run_sync(to_response(respondable)).status == status


def test_matches_wrapper_only() -> None:
    """matches wrapper only"""
    request = _request("GET", "http://example.com/check")
    assert is_http_server_error(HttpServerError(RouteNotFound(request)))
    assert not is_http_server_error(RouteNotFound(request))
    assert not is_http_server_error(ServeError(RuntimeError("boom")))
    assert not is_http_server_error({"_tag": "HttpServerError"})


def test_returns_none_cause_for_response_defects() -> None:
    """returns none cause for response defects"""
    response = server_response.empty(status=418)
    out, cause = cause_response_stripped(die_cause(UnhandledError(response)))
    assert out is response
    assert cause is None


def test_returns_some_cause_for_non_response_failures() -> None:
    """returns some cause for non-response failures"""
    request = _request("GET", "http://example.com/fail")
    out, cause = cause_response_stripped(fail_cause(RouteNotFound(request)))
    assert out.status == 500
    assert cause is not None
