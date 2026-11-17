"""Ports of Effect's ``packages/effect/test/ai/WorkloadIdentity.test.ts``. Each docstring is
the Effect test title (with its ``describe``). The token endpoint and the API are a mocked
``HttpClient``, as Effect's ``HttpClient.make`` handler; the redirect case runs httpx over a
mock transport, as Effect's runs ``FetchHttpClient`` over a mocked ``fetch``."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

import pyfect as fx
from pyfect import testing
from pyfect.ai import workload_identity
from pyfect.deferred import Deferred
from pyfect.http import client as http_client
from pyfect.http import httpx_client
from pyfect.http import response as http_response
from pyfect.http.client import HttpClientService
from pyfect.http.error import HttpClientError, TransportError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.redacted import Redacted
from pyfect.redacted import make as redact

from ._ai_http import body_json
from ._ai_http import reaches as contains

IDENTITY_TOKEN = "identity.token.signature"
TOKEN_URL = "https://auth.example.com/oauth/token"
API_URL = "https://api.example.com/v1/models"

type Handler = Callable[[HttpClientRequest], fx.Effect[HttpClientResponse, HttpClientError]]


def token_response(request: HttpClientRequest, n: int) -> HttpClientResponse:
    return http_response.make(
        request,
        json.dumps({"access_token": f"access-{n}", "expires_in": 3600}),
        headers={"content-type": "application/json"},
    )


@dataclass
class Http:
    """Effect's ``makeHttp``: the token endpoint answers ``access-<n>`` for the nth exchange
    unless ``token`` is given; the API answers an empty 200 unless ``api`` is."""

    token: Handler | None = None
    api: Handler | None = None
    requests: list[HttpClientRequest] = field(default_factory=list[HttpClientRequest])
    exchanges: int = 0

    @property
    def client(self) -> HttpClientService[HttpClientError]:
        def handle(request: HttpClientRequest) -> fx.Effect[HttpClientResponse, HttpClientError]:
            self.requests.append(request)
            if request.url == TOKEN_URL:
                if self.token is not None:
                    return self.token(request)
                self.exchanges += 1
                return fx.succeed(token_response(request, self.exchanges))
            if self.api is not None:
                return self.api(request)
            return fx.succeed(http_response.make(request, ""))

        return http_client.make(lambda request, _url, _signal, _fiber: handle(request))

    @property
    def authorizations(self) -> list[str | None]:
        return [request.headers.get("authorization") for request in self.requests]


def exchange_request(request: HttpClientRequest, identity_token: str) -> HttpClientRequest:
    return request.body_json_unsafe({"subject_token": identity_token})


def make(
    http: Http, identity_token: fx.Effect[Redacted[str], Any] | None = None
) -> fx.Effect[workload_identity.ClientTransform, Any, Any]:
    transform = workload_identity.make(
        token_url=TOKEN_URL,
        identity_token=fx.succeed(redact(IDENTITY_TOKEN))
        if identity_token is None
        else identity_token,
        exchange_request=exchange_request,
    )
    return transform.pipe(fx.provide_service(http_client.HttpClient, http.client))


def make_client(
    http: Http, identity_token: fx.Effect[Redacted[str], Any] | None = None
) -> fx.Effect[HttpClientService[HttpClientError], Any, Any]:
    return make(http, identity_token).map(lambda transform: transform(http.client))


@testing.effect
def test_exchanges_a_new_identity_token_once_the_access_token_is_about_to_expire():
    """WorkloadIdentity / exchanges a new identity token once the access token is about to expire"""
    identity_tokens = 0

    def next_identity_token() -> Redacted[str]:
        nonlocal identity_tokens
        identity_tokens += 1
        return redact(f"identity-{identity_tokens}")

    http = Http()
    client = yield from make_client(http, fx.sync(next_identity_token))

    yield from client.get(API_URL)
    yield from testing.adjust("3569 seconds")
    yield from client.get(API_URL)
    yield from testing.adjust("1 second")
    yield from client.get(API_URL)

    assert http.authorizations == [
        None,
        "Bearer access-1",
        "Bearer access-1",
        None,
        "Bearer access-2",
    ]
    assert body_json(http.requests[3]) == {"subject_token": "identity-2"}


@testing.effect
def test_discards_only_the_access_token_a_401_rejected_without_replaying_the_request():
    """WorkloadIdentity / discards only the access token a 401 rejected, without replaying the request"""  # noqa: E501
    latch: Deferred[None] = yield from Deferred[None].make()

    def api(request: HttpClientRequest) -> fx.Effect[HttpClientResponse]:
        status = 401 if request.headers.get("authorization") == "Bearer access-1" else 200
        wait = latch.wait() if request.url.endswith("/slow") else fx.void
        return wait.as_(http_response.make(request, None, status=status))

    http = Http(api=api)
    client = yield from make_client(http)

    def status(url: str) -> fx.Effect[int, HttpClientError]:
        return client.get(url).map(lambda response: response.status)

    slow = yield from status(f"{API_URL}/slow").fork(start_immediately=True)
    assert (yield from status(API_URL)) == 401
    assert (yield from status(API_URL)) == 200
    # The late rejection of the first token must not discard the second one.
    yield from latch.succeed(None)
    assert (yield from slow.join()) == 401
    assert (yield from status(API_URL)) == 200

    assert http.authorizations == [
        None,
        "Bearer access-1",
        "Bearer access-1",
        None,
        "Bearer access-2",
        "Bearer access-2",
    ]


@testing.effect
def test_discards_a_rejected_access_token_when_the_client_fails_on_error_statuses():
    """WorkloadIdentity / discards a rejected access token when the client fails on error statuses"""  # noqa: E501

    def api(request: HttpClientRequest) -> fx.Effect[HttpClientResponse]:
        status = 401 if request.headers.get("authorization") == "Bearer access-1" else 200
        return fx.succeed(http_response.make(request, None, status=status))

    http = Http(api=api)
    transform = yield from make(http)
    client = transform(http.client.filter_status_ok())

    yield from client.get(API_URL).flip()
    yield from client.get(API_URL)

    assert http.authorizations == [None, "Bearer access-1", None, "Bearer access-2"]


@testing.effect
def test_redacts_the_identity_token_from_a_rejected_exchange():
    """WorkloadIdentity / redacts the identity token from a rejected exchange"""
    body = json.dumps(
        {"message": f"Authentication failed for {IDENTITY_TOKEN}", IDENTITY_TOKEN: True},
        separators=(",", ":"),
    ).replace(".", "\\u002e")

    def token(request: HttpClientRequest) -> fx.Effect[HttpClientResponse]:
        headers = {"www-authenticate": f'Bearer error_description="{IDENTITY_TOKEN}"'}
        return fx.succeed(http_response.make(request, body, status=401, headers=headers))

    http = Http(token=token)
    client = yield from make_client(http)
    error: HttpClientError = yield from client.get(API_URL).flip()

    response = error.response
    assert response is not None
    assert response.status == 401
    assert response.headers["www-authenticate"] == 'Bearer error_description="<redacted>"'
    assert (yield from response.text) == (
        '{"message":"Authentication failed for <redacted>","<redacted>":true}'
    )
    assert not contains(error, IDENTITY_TOKEN)


class _SocketHangUp(Exception):
    """A transport failure whose cause holds the request, as Effect's ``{ cause: { request } }``."""

    def __init__(self, request: HttpClientRequest) -> None:
        super().__init__("socket hang up")
        self.request = request


@testing.effect
def test_keeps_only_the_redacted_messages_of_a_transport_failure():
    """WorkloadIdentity / keeps only the redacted messages of a transport failure"""

    def token(request: HttpClientRequest) -> fx.Effect[Any, HttpClientError]:
        reason = TransportError(
            request, cause=_SocketHangUp(request), description=f"failed to send {IDENTITY_TOKEN}"
        )
        return fx.fail(HttpClientError(reason))

    http = Http(token=token)
    client = yield from make_client(http)
    error: HttpClientError = yield from client.get(API_URL).flip()

    assert error.reason.tag == "TransportError"
    assert "failed to send <redacted>: socket hang up" in error.message
    assert not contains(error, IDENTITY_TOKEN)


@testing.effect
def test_fails_with_the_identity_token_source_failure_as_the_cause_without_an_exchange():
    """WorkloadIdentity / fails with the identity token source failure as the cause, without an exchange"""  # noqa: E501
    cause = FileNotFoundError("ENOENT")
    http = Http()

    client = yield from make_client(http, fx.fail(cause))
    error: HttpClientError = yield from client.get(API_URL).flip()

    assert error.reason.tag == "EncodeError"
    assert error.reason.cause is cause
    assert http.requests == []


@testing.effect
def test_does_not_follow_a_redirect_of_the_exchange():
    """WorkloadIdentity / does not follow a redirect of the exchange: Effect checks that
    ``fetch`` is called with ``redirect: "manual"``; here an httpx client made to follow
    redirects sends the exchange alone, so the identity token never reaches the target."""
    sent: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if str(request.url) == TOKEN_URL:
            return httpx.Response(307, headers={"location": "https://example.com"})
        return httpx.Response(200, json={"access_token": "stolen", "expires_in": 3600})

    @fx.gen
    def program():
        transform = yield from workload_identity.make(
            token_url=TOKEN_URL,
            identity_token=fx.succeed(redact(IDENTITY_TOKEN)),
            exchange_request=exchange_request,
        )
        client = transform((yield from http_client.HttpClient()))
        return (yield from client.get(API_URL).flip())

    layer = httpx_client.layer_with(transport=httpx.MockTransport(transport), follow_redirects=True)
    error: HttpClientError = yield from program.pipe(fx.provide(layer))

    assert [str(request.url) for request in sent] == [TOKEN_URL]
    assert error.reason.tag == "TransportError"
    assert not contains(error, IDENTITY_TOKEN)
