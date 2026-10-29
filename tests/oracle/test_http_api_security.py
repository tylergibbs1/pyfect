"""Ports of Effect's ``httpapi/HttpApiSecurity.test.ts``.

Each test's docstring is the Effect test title.
"""

import base64
from typing import Never

import pyfect as fx
from pyfect import effect, redacted
from pyfect.http import request as client_request
from pyfect.http.headers import Headers
from pyfect.http.server_request import HttpServerRequest, ParsedSearchParams
from pyfect.http.web import WebRequest
from pyfect.http.web_handler import request_from_web
from pyfect.http_api import builder, security
from pyfect.http_api.security import Credentials


def _decode_with[A](
    headers: Headers | dict[str, str],
    eff: fx.Effect[A, Never, HttpServerRequest | ParsedSearchParams],
) -> A:
    request = request_from_web(WebRequest("http://localhost/", headers=dict(headers)))
    return fx.run_sync(
        eff.pipe(effect.provide_service(HttpServerRequest, request)).pipe(
            effect.provide_service(ParsedSearchParams, {})
        )
    )


def _decode(authorization: str, sec: security.Http) -> str:
    return redacted.value(
        _decode_with({"authorization": authorization}, builder.security_decode(sec))
    )


def _decode_basic(authorization: str) -> Credentials:
    return _decode_with({"authorization": authorization}, builder.security_decode(security.basic))


def test_decodes_a_bearer_token_without_a_leading_space() -> None:
    """decodes a bearer token without a leading space"""
    headers = client_request.get("http://localhost/").bearer_token("abc123").headers
    credential = _decode_with(headers, builder.security_decode(security.bearer))
    assert redacted.value(credential) == "abc123"


def test_decodes_a_custom_http_scheme_without_a_leading_space() -> None:
    """decodes a custom http scheme without a leading space"""
    assert _decode("Token abc123", security.http(scheme="Token")) == "abc123"


def test_matches_http_schemes_case_insensitively() -> None:
    """matches HTTP schemes case-insensitively"""
    assert _decode("bEaReR abc123", security.bearer) == "abc123"


def test_accepts_multiple_spaces_before_http_credentials() -> None:
    """accepts multiple spaces before HTTP credentials"""
    assert _decode("Bearer   abc123", security.bearer) == "abc123"


def test_rejects_mismatched_and_malformed_http_schemes() -> None:
    """rejects mismatched and malformed HTTP schemes"""
    assert _decode("Basic abc123", security.bearer) == ""
    assert _decode("Bearerabc123", security.bearer) == ""


def test_decodes_basic_credentials_using_the_first_colon_separator() -> None:
    """decodes Basic credentials using the first colon separator"""
    encoded = base64.b64encode(b"alice:secret:with:colons").decode()
    credential = _decode_basic(f"Basic {encoded}")
    assert credential.username == "alice"
    assert redacted.value(credential.password) == "secret:with:colons"


def test_rejects_basic_credentials_from_a_different_scheme() -> None:
    """rejects Basic credentials from a different scheme"""
    encoded = base64.b64encode(b"alice:secret").decode()
    credential = _decode_basic(f"Bearer {encoded}")
    assert credential.username == ""
    assert redacted.value(credential.password) == ""
