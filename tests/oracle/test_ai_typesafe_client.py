"""Ports of Effect's ``packages/ai/typesafe/test/TypeSafeClient.test.ts``.
Each docstring is the Effect test title (with its ``describe``); the
HTTP-date ``Retry-After`` pair is one parametrized test. Responses are
answered by a mocked ``HttpClient``."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

import pyfect as fx
from pyfect import config, config_provider, testing
from pyfect import duration as fx_duration
from pyfect.ai import ai_error as E
from pyfect.ai._provider import ClientTransform
from pyfect.ai.typesafe import client
from pyfect.ai.typesafe import config as typesafe_config
from pyfect.ai.typesafe import schema as W
from pyfect.http import error as http_error
from pyfect.http import request as http_request
from pyfect.http.client import HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.redacted import make as redact

from ._ai_http import MockHttp, body_json, mock_json, refuse_transport, stringify_error

REQUEST: W.SystemOneRequest = {
    "state": "My card was charged twice.",
    "model": "jev-latest",
    "questions": {
        "urgent": {
            "type": "noul",
            "instructions": "The message conveys urgency",
            "criteria": {"false": "No time pressure", "true": "Needs action now"},
        }
    },
}

BODY = {
    "model": "jev-latest",
    "answers": {"urgent": {"type": "noul", "noul": 0.99}},
    "usage": {"input_tokens": 360, "output_tokens": 39},
}

_KEY = redact("test-key")


def provided[A](
    effect: fx.Effect[A, Any, Any], mock: MockHttp | None = None, **options: Any
) -> fx.Effect[A, Any, Any]:
    options.setdefault("api_key", _KEY)
    return effect.pipe(fx.provide(client.layer(**options))).pipe(
        fx.provide((mock or mock_json(BODY)).layer)
    )


def set_header(name: str, value: str) -> ClientTransform:
    return lambda c: c.map_request(lambda r: r.set_header(name, value))


def status_of(http: E.HttpContext | None) -> int | None:
    assert http is not None
    response = http.get("response")
    return None if response is None else response["status"]


def system_one() -> fx.Effect[W.SystemOneResponse, E.AiError, client.TypeSafeClient]:
    return client.TypeSafeClient().flat_map(lambda c: c.system_one(REQUEST))


def failure(mock: MockHttp) -> fx.Effect[E.AiError, Any, Any]:
    return provided(system_one().flip(), mock)


# make -------------------------------------------------------------------------------------


@testing.effect
def test_bearer_token():
    """TypeSafeClient / make / sets Bearer token from apiKey"""
    mock = mock_json(BODY)
    yield from provided(system_one(), mock, api_key=redact("ts-test-12345"))
    assert mock.requests[0].headers["authorization"] == "Bearer ts-test-12345"


@testing.effect
def test_posts_systemone():
    """TypeSafeClient / make / posts systemone requests to the default URL as JSON"""
    mock = mock_json(BODY)
    response = yield from provided(system_one(), mock)
    request = mock.requests[0]
    assert request.method == "POST"
    assert request.url == "https://api.typesafe.ai/v1/systemone"
    assert request.headers["content-type"] == "application/json"
    assert body_json(request) == REQUEST
    assert response["model"] == "jev-latest"
    assert response.get("usage") == {"input_tokens": 360, "output_tokens": 39}


@pytest.mark.parametrize(
    ("extra", "header"),
    [
        pytest.param({}, None, id="text-only requests"),
        pytest.param(
            {"assets": {"image-0-abc": {"format": "png", "data_base64": "iVBORw0KGgo="}}},
            "true",
            id="image assets",
        ),
        pytest.param(
            {"questions": {"mug": {"type": "box", "instructions": "the mug"}}},
            "true",
            id="a box question",
        ),
    ],
)
@testing.effect
def test_images_header(extra: dict[str, Any], header: str | None):
    """TypeSafeClient / make / sets the images header for text-only requests / image assets /
    a box question"""
    mock = mock_json(BODY)
    payload: W.SystemOneRequest = {**REQUEST, **extra}  # pyright: ignore[reportAssignmentType]
    yield from provided(client.TypeSafeClient().flat_map(lambda c: c.system_one(payload)), mock)
    assert mock.requests[0].headers.get("typesafe-danger-zone-images") == header


@testing.effect
def test_custom_api_url():
    """TypeSafeClient / make / uses custom apiUrl when provided"""
    mock = mock_json(BODY)
    yield from provided(system_one(), mock, api_url="https://custom.api.com/v2")
    assert mock.requests[0].url == "https://custom.api.com/v2/systemone"


@testing.effect
def test_lists_models():
    """TypeSafeClient / make / lists models from the models endpoint"""
    models = [{"name": "jev-1.13.0", "description": "Jev 1.13", "release_date": "2026-08-01"}]
    mock = mock_json({"models": models})
    response = yield from provided(
        client.TypeSafeClient().flat_map(lambda c: c.list_models()), mock
    )
    assert mock.requests[0].method == "GET"
    assert mock.requests[0].url == "https://api.typesafe.ai/v1/models"
    assert list(response["models"]) == models


@testing.effect
def test_transform_client_option():
    """TypeSafeClient / make / applies transformClient option"""
    applied: list[bool] = []

    def transform(c: Any) -> Any:
        applied.append(True)
        return c

    yield from provided(system_one(), transform_client=transform)
    assert applied == [True]


@testing.effect
def test_client_field():
    """TypeSafeClient / make / exposes transformed HttpClient via client field"""
    mock = mock_json(BODY)
    yield from provided(
        client.TypeSafeClient().flat_map(
            lambda c: c.http_client.execute(http_request.get("/models"))
        ),
        mock,
        transform_client=set_header("x-client-field", "enabled"),
    )
    request = mock.requests[0]
    assert request.url == "https://api.typesafe.ai/v1/models"
    assert request.headers["authorization"] == "Bearer test-key"
    assert request.headers["x-client-field"] == "enabled"


@testing.effect
def test_config_transform_after_options():
    """TypeSafeClient / make / applies TypeSafeConfig transformClient after options
    transformClient"""
    applied: list[str] = []

    def options_transform(c: HttpClientService[HttpClientError]) -> Any:
        applied.append("options")
        return set_header("x-typesafe-transform", "options")(c)

    def config_transform(c: HttpClientService[HttpClientError]) -> Any:
        applied.append("config")
        return set_header("x-typesafe-transform", "config")(c)

    mock = mock_json(BODY)
    yield from provided(
        client.TypeSafeClient().flat_map(
            lambda c: c.system_one(REQUEST).pipe(
                typesafe_config.with_client_transform(config_transform)
            )
        ),
        mock,
        transform_client=options_transform,
    )
    assert applied == ["options", "config"]
    assert mock.requests[0].headers["x-typesafe-transform"] == "config"


# layer ------------------------------------------------------------------------------------


@testing.effect
def test_layer_creates_service():
    """TypeSafeClient / layer / creates working service"""
    found = yield from provided(client.TypeSafeClient().map(lambda c: c.http_client))
    assert found is not None


@testing.effect
def test_layer_config():
    """TypeSafeClient / layer / layerConfig loads from Config"""
    mock = mock_json(BODY)
    provider = config_provider.from_env(
        {"MY_API_KEY": "ts-config-key", "MY_API_URL": "https://config.api.com/v1"}
    )
    layer = client.layer_config(
        api_key=config.redacted("MY_API_KEY"), api_url=config.string("MY_API_URL")
    )
    yield from (
        system_one()
        .pipe(fx.provide(layer))
        .pipe(fx.provide(mock.layer))
        .pipe(fx.provide(config_provider.layer(provider)))
    )
    assert mock.requests[0].headers["authorization"] == "Bearer ts-config-key"
    assert mock.requests[0].url == "https://config.api.com/v1/systemone"


@testing.effect
def test_layer_config_default_key():
    """TypeSafeClient / layer / layerConfig defaults to TYPESAFE_API_KEY"""
    mock = mock_json(BODY)
    provider = config_provider.from_env({"TYPESAFE_API_KEY": "ts-env-key"})
    yield from (
        system_one()
        .pipe(fx.provide(client.layer_config()))
        .pipe(fx.provide(mock.layer))
        .pipe(fx.provide(config_provider.layer(provider)))
    )
    assert mock.requests[0].headers["authorization"] == "Bearer ts-env-key"
    assert mock.requests[0].url == "https://api.typesafe.ai/v1/systemone"


# request behavior -------------------------------------------------------------------------


@testing.effect
def test_redacts_authorization():
    """TypeSafeClient / request behavior / redacts the authorization header in AI error
    context"""
    mock = mock_json({"message": "questions must not be empty"}, status=422)
    error = yield from provided(system_one().flip(), mock, api_key=redact("secret-key"))
    reason = error.reason
    assert isinstance(reason, E.InvalidRequestError)
    assert reason.http is not None
    assert "secret-key" not in stringify_error(error)
    assert status_of(reason.http) == 422


# error mapping ----------------------------------------------------------------------------


@testing.effect
def test_409_unknown():
    """TypeSafeClient / error mapping / maps undocumented 409 status to the generic UnknownError
    fallback"""
    error = yield from failure(mock_json({"message": "Conflict"}, status=409))
    reason = error.reason
    assert isinstance(reason, E.UnknownError)
    assert status_of(reason.http) == 409
    assert "Conflict" in (reason.description or "")


@testing.effect
def test_429_metadata():
    """TypeSafeClient / error mapping / retains 429 diagnostics in provider metadata"""
    body = {"message": "Slow down", "code": "rate_limit_exceeded", "type": "requests"}
    mock = mock_json(body, status=429, headers={"x-typesafe-request-id": "req_typesafe_429"})
    error = yield from failure(mock)
    reason = error.reason
    assert isinstance(reason, E.RateLimitError)
    assert reason.metadata["typesafe"] == {
        "requestId": "req_typesafe_429",
        "errorCode": "rate_limit_exceeded",
        "errorType": "requests",
    }
    assert status_of(reason.http) == 429


@pytest.mark.parametrize(
    ("date", "expected"),
    [("Fri, 18 Sep 2026 12:00:30 GMT", 30), ("Fri, 18 Sep 2026 11:59:30 GMT", 0)],
    ids=["future", "past"],
)
@testing.effect
def test_http_date_retry_after(date: str, expected: float):
    """TypeSafeClient / error mapping / HTTP-date Retry-After / honors a future / past HTTP-date
    Retry-After"""
    yield from testing.set_time(datetime(2026, 9, 18, 12, tzinfo=UTC).timestamp() * 1000)
    mock = mock_json({"message": "Rate limit exceeded"}, status=429, headers={"retry-after": date})
    error = yield from failure(mock)
    reason = error.reason
    assert isinstance(reason, E.RateLimitError)
    assert reason.retry_after == fx_duration.seconds(expected)


@testing.effect
def test_transport_error():
    """TypeSafeClient / error mapping / maps TransportError to NetworkError reason"""
    failures: list[http_error.HttpClientError] = []
    error = (
        yield from client.make(api_key=_KEY)
        .flat_map(lambda c: c.system_one(REQUEST).flip())
        .pipe(fx.provide(MockHttp(refuse_transport(failures, ConnectionRefusedError())).layer))
    )
    assert error.module == "TypeSafeClient"
    assert error.method == "systemOne"
    assert isinstance(error.reason, E.NetworkError)
    assert error.reason.cause is failures[0]


@testing.effect
def test_400():
    """TypeSafeClient / error mapping / maps 400 status to InvalidRequestError reason"""
    error = yield from failure(mock_json({"message": "Bad request"}, status=400))
    assert error.module == "TypeSafeClient"
    assert error.method == "systemOne"
    assert isinstance(error.reason, E.InvalidRequestError)


@testing.effect
def test_401():
    """TypeSafeClient / error mapping / maps 401 status to AuthenticationError reason"""
    mock = mock_json(
        {"message": "Invalid API key"},
        status=401,
        headers={"x-typesafe-request-id": "req_typesafe"},
    )
    reason = (yield from failure(mock)).reason
    assert isinstance(reason, E.AuthenticationError)
    assert reason.kind == "InvalidKey"
    assert "Invalid API key" in (reason.description or "")
    assert "req_typesafe" in (reason.description or "")


@testing.effect
def test_403():
    """TypeSafeClient / error mapping / maps 403 status to AuthenticationError with
    InsufficientPermissions"""
    reason = (yield from failure(mock_json({"message": "Access denied"}, status=403))).reason
    assert isinstance(reason, E.AuthenticationError)
    assert reason.kind == "InsufficientPermissions"


@testing.effect
def test_404():
    """TypeSafeClient / error mapping / maps 404 status to InvalidRequestError reason"""
    reason = (yield from failure(mock_json({"message": "Not found"}, status=404))).reason
    assert isinstance(reason, E.InvalidRequestError)


@testing.effect
def test_422():
    """TypeSafeClient / error mapping / maps 422 status to InvalidRequestError reason with the
    message"""
    body = {"message": "criteria must contain at least two levels"}
    reason = (yield from failure(mock_json(body, status=422))).reason
    assert isinstance(reason, E.InvalidRequestError)
    assert "criteria must contain at least two levels" in (reason.description or "")


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        pytest.param({"retry-after": "2"}, fx_duration.seconds(2), id="seconds"),
        pytest.param(
            {"retry-after-ms": "1500"},
            fx_duration.millis(1500),
            id="maps 429 status to RateLimitError honoring retry-after-ms",
        ),
        pytest.param({}, None, id="none"),
    ],
)
@testing.effect
def test_429_retry_after(headers: dict[str, str], expected: fx_duration.Duration | None):
    """TypeSafeClient / error mapping / maps 429 status to RateLimitError honoring Retry-After
    seconds / honoring retry-after-ms / maps 429 status without retry headers to RateLimitError
    without retryAfter"""
    mock = mock_json({"message": "Rate limit exceeded"}, status=429, headers=headers)
    reason = (yield from failure(mock)).reason
    assert isinstance(reason, E.RateLimitError)
    assert reason.retry_after == expected


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        pytest.param(
            {"retry-after-ms": "0", "retry-after": "5"}, fx_duration.zero, id="zero-ms-wins"
        ),
        pytest.param(
            {"retry-after-ms": "-1", "retry-after": "2"}, fx_duration.seconds(2), id="negative-ms"
        ),
        pytest.param(
            {"retry-after-ms": "soon", "retry-after": "2"}, fx_duration.seconds(2), id="invalid-ms"
        ),
    ],
)
@testing.effect
def test_retry_after_ms_precedence(headers: dict[str, str], expected: fx_duration.Duration):
    """A non-negative retry-after-ms, 0 included, wins over Retry-After; any other value
    falls back to it (Python only: Effect's nonNegative)."""
    mock = mock_json({"message": "Rate limit exceeded"}, status=429, headers=headers)
    reason = (yield from failure(mock)).reason
    assert isinstance(reason, E.RateLimitError)
    assert reason.retry_after == expected


@pytest.mark.parametrize(
    "status",
    [
        pytest.param(529, id="maps 529 status to InternalProviderError reason"),
        pytest.param(500, id="maps 500 status to InternalProviderError reason"),
    ],
)
@testing.effect
def test_5xx(status: int):
    """TypeSafeClient / error mapping / maps 529 / 500 status to InternalProviderError reason"""
    reason = (yield from failure(mock_json({"message": "Overloaded"}, status=status))).reason
    assert isinstance(reason, E.InternalProviderError)
    assert status_of(reason.http) == status


@testing.effect
def test_malformed_success_body():
    """TypeSafeClient / error mapping / maps a malformed success body to a non-retryable
    InvalidResponseError reason"""
    body = {"model": "jev-latest", "answers": {"urgent": {"type": "noul"}}}
    error = yield from failure(mock_json(body))
    assert error.method == "systemOne"
    assert isinstance(error.reason, E.InvalidResponseError)
    assert not error.is_retryable


@testing.effect
def test_list_models_failure():
    """TypeSafeClient / error mapping / maps listModels failures with the listModels method"""
    mock = mock_json({"message": "Invalid API key"}, status=401)
    error = yield from provided(
        client.TypeSafeClient().flat_map(lambda c: c.list_models()).flip(), mock
    )
    assert error.module == "TypeSafeClient"
    assert error.method == "listModels"
    assert isinstance(error.reason, E.AuthenticationError)
