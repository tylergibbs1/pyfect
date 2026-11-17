"""The Amazon Bedrock Runtime Converse API client (Effect's
``AmazonBedrockClient``).

``layer(...)`` provides ``AmazonBedrockClient`` over the ``HttpClient``
service, signing each request with AWS Signature Version 4 on the ``Digest``
and ``Mac`` services the caller provides (``pyfect.crypto.native``'s layers,
or the Web Crypto ones), or sending a Bedrock API key as a bearer token::

    client = yield from AmazonBedrockClient()
    response = yield from client.converse({"modelId": model, "messages": [...]})

The client authenticates with, in this order: ``api_key`` (a Bedrock API
key); ``credentials``, an effect run before every request (wrap a credential
provider in it; cache it with ``cached_with_ttl`` to avoid resolving on every
request); ``access_key_id`` and ``secret_access_key`` with an optional
``session_token``. Without any of them every request fails with an
``AuthenticationError`` of kind ``MissingKey``. Every failure is an
``AiError``; an exception frame in a stream (a ``throttlingException``,
...) fails the stream with the reason its REST counterpart has.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Never, Self, final
from urllib.parse import quote

import pyfect as fx
from pyfect import byte_size
from pyfect import layer as L
from pyfect import stream as St
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._service_copy import replaced
from pyfect.ai import _provider as P
from pyfect.ai.ai_error import AiError, AuthenticationError, InternalProviderError
from pyfect.ai.amazon_bedrock import _event_stream as ES
from pyfect.ai.amazon_bedrock import schema as W
from pyfect.ai.amazon_bedrock._errors import (
    ERRORS,
    SECRET_HEADERS,
    map_event_stream_error,
    map_stream_exception,
)
from pyfect.ai.amazon_bedrock._errors import make as make_error
from pyfect.ai.amazon_bedrock._sigv4 import Signer, SigningCredentials, sign
from pyfect.ai.amazon_bedrock.config import AmazonBedrockConfig, ClientTransform
from pyfect.byte_size import ByteSize
from pyfect.config import Config, ConfigError
from pyfect.config import redacted as config_redacted
from pyfect.config import string as config_string
from pyfect.context import Reference, Tag
from pyfect.crypto.digest import Digest, DigestService
from pyfect.crypto.mac import Mac, MacService
from pyfect.http import request as http_request
from pyfect.http import response as http_response
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.http.headers import CurrentRedactedNames
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value
from pyfect.result import Err, Ok
from pyfect.stream import Stream

DEFAULT_REGION = "us-east-1"
_redacted = P.with_redacted_headers(SECRET_HEADERS)


@dataclass(frozen=True)
class Credentials:
    """AWS credentials; an empty ``session_token`` is sent as none."""

    access_key_id: str
    secret_access_key: str
    session_token: str | None = None


@final
class Service:
    """The client: an authenticated ``HttpClient`` for the Bedrock Runtime
    operations it does not model, and the Converse calls. ``make`` builds
    it; ``Service(client, converse, converse_stream)`` makes one of two
    functions (a test double, say)."""

    __slots__ = ("_converse", "_converse_stream", "client")

    client: HttpClientService[HttpClientError | AiError]
    """The underlying client with the base URL and authentication; resolving
    the credentials can fail with an ``AiError``."""

    def __replace__(self, **changes: Any) -> Self:
        """A copy with ``changes`` to the constructor's arguments (``copy.replace``)."""
        return replaced(self, changes)

    def __init__(
        self,
        client: HttpClientService[HttpClientError | AiError],
        converse: Callable[[W.ConverseRequest], Effect[W.ConverseResponse, AiError]],
        converse_stream: Callable[[W.ConverseRequest], Stream[W.ConverseStreamEvent, AiError]],
    ) -> None:
        self.client = client
        self._converse = converse
        self._converse_stream = converse_stream

    def converse(self, request: W.ConverseRequest) -> Effect[W.ConverseResponse, AiError]:
        """The Converse operation: ``modelId`` names the model in the URL,
        the other fields are the body; an ``AmazonBedrockConfig`` in context
        transforms the client for this call."""
        return self._converse(request)

    def converse_stream(self, request: W.ConverseRequest) -> Stream[W.ConverseStreamEvent, AiError]:
        """The ConverseStream operation's decoded events."""
        return self._converse_stream(request)


class AmazonBedrockClient(Tag[Service], key="@effect/ai-amazon-bedrock/AmazonBedrockClient"):
    """The Amazon Bedrock client."""


@dataclass(frozen=True)
class _Bearer:
    api_key: Redacted[str]


@dataclass(frozen=True)
class _SigV4:
    credentials: SigningCredentials


type _RequestCredentials = _Bearer | _SigV4


class _CurrentRequestCredentials(
    Reference[_RequestCredentials | None],
    key="@effect/ai-amazon-bedrock/AmazonBedrockClient/CurrentRequestCredentials",
):
    """The credentials of the request in flight. They are resolved before
    ``execute`` and provided around it, so a resolution failure is not an
    ``HttpClientError`` a retry policy would retry, and every retry inside
    ``execute`` signs again with them."""

    @classmethod
    def default(cls) -> _RequestCredentials | None:
        return None


def _missing_key(method: str, description: str) -> AiError:
    return make_error(method, AuthenticationError(kind="MissingKey", description=description))


def _sig_v4(access_key_id: str, secret_access_key: str, session_token: str | None) -> _SigV4:
    token = None if session_token == "" else session_token
    return _SigV4(SigningCredentials(access_key_id, secret_access_key, token))


type _Resolve = Callable[[str], Effect[_RequestCredentials, AiError]]


def _resolve_credentials(
    *,
    api_key: Redacted[str] | None,
    credentials: Effect[Credentials, AiError] | None,
    access_key_id: str | None,
    secret_access_key: Redacted[str] | None,
    session_token: Redacted[str] | None,
) -> _Resolve:
    if api_key is not None:
        bearer: Effect[_RequestCredentials, AiError] = fx.succeed(_Bearer(api_key))
        return lambda _method: bearer
    if credentials is not None:
        resolve = credentials

        def check(method: str, found: Credentials) -> Effect[_RequestCredentials, AiError]:
            if found.access_key_id == "" or found.secret_access_key == "":
                return fx.fail(
                    _missing_key(
                        method,
                        "The credentials effect returned an empty access key ID "
                        "or secret access key",
                    )
                )
            return fx.succeed(
                _sig_v4(found.access_key_id, found.secret_access_key, found.session_token)
            )

        return lambda method: resolve.flat_map(lambda found: check(method, found))
    if access_key_id is not None and secret_access_key is not None:
        static: Effect[_RequestCredentials, AiError] = fx.succeed(
            _sig_v4(
                access_key_id,
                redacted_value(secret_access_key),
                None if session_token is None else redacted_value(session_token),
            )
        )
        return lambda _method: static
    return lambda method: fx.fail(
        _missing_key(
            method,
            "AmazonBedrockClient has no credentials: set `api_key`, `credentials`, "
            "or `access_key_id` with `secret_access_key`",
        )
    )


def _authenticate(signer: Signer) -> Callable[[HttpClientRequest], Effect[HttpClientRequest]]:
    def authenticate(request: HttpClientRequest) -> Effect[HttpClientRequest]:
        def with_credentials(found: _RequestCredentials | None) -> Effect[HttpClientRequest]:
            match found:
                case _Bearer(api_key):
                    return fx.succeed(request.bearer_token(api_key))
                case _SigV4(credentials):
                    return sign(request, signer, credentials)
                case None:
                    return fx.die(
                        RuntimeError(
                            "AmazonBedrockClient sent a request without resolving its credentials"
                        )
                    )

        return _CurrentRequestCredentials().flat_map(with_credentials)

    return authenticate


def _encode_uri_component(text: str) -> str:
    return quote(text, safe="-_.!~*'()")


def _decode_frame(
    frame: ES.Frame,
) -> Effect[W.ConverseStreamEvent | None, Any]:
    match frame.headers.get(":message-type"):
        case "event":
            event_type = frame.headers.get(":event-type")
            if event_type is None:
                return fx.succeed(None)
            return ES.parse_json_payload(frame).flat_map(
                lambda payload: W.decode_converse_stream_event({event_type: payload})
            )
        case "exception":
            exception_type = frame.headers.get(":exception-type", "unknown exception")
            return (
                ES.parse_json_payload(frame)
                .flat_map(W.decode_converse_stream_exception)
                .flat_map(
                    lambda exception: fx.fail(
                        map_stream_exception(
                            exception_type, exception.get("message"), "converseStream"
                        )
                    )
                )
            )
        case "error":
            code = frame.headers.get(":error-code", "unknown")
            message = frame.headers.get(":error-message", "no error message provided")
            return fx.fail(
                make_error(
                    "converseStream",
                    InternalProviderError(
                        description=f"Event stream error frame [{code}]: {message}"
                    ),
                )
            )
        case _:
            return fx.succeed(None)


def _stream_failure(error: object) -> Stream[Never, AiError]:
    if isinstance(error, ES.EventStreamError):
        return St.fail(map_event_stream_error(error, "converseStream"))
    return St.from_effect(ERRORS.catch("converseStream")(error))


def make(
    *,
    region: str | None = None,
    api_url: str | None = None,
    access_key_id: str | None = None,
    secret_access_key: Redacted[str] | None = None,
    session_token: Redacted[str] | None = None,
    api_key: Redacted[str] | None = None,
    credentials: Effect[Credentials, AiError] | None = None,
    transform_client: ClientTransform | None = None,
    max_response_bytes: byte_size.Input | None = None,
) -> Effect[Service, Never, HttpClient | Digest | Mac]:
    """An Amazon Bedrock client over the ``HttpClient`` service, signing
    with the ``Digest`` and ``Mac`` services in context (required however
    it authenticates, though an ``api_key`` client never calls them; a
    ``CryptoError`` of ``Mac`` is a defect). Requests go to ``api_url``
    (``https://bedrock-runtime.<region>.amazonaws.com``, ``region``
    defaulting to ``us-east-1``); ``transform_client`` changes the
    underlying client (and so does an ``AmazonBedrockConfig``, per call). A
    response body larger than ``max_response_bytes`` (256 MiB) fails the
    call."""
    if credentials is not None:
        require_effect(credentials, "credentials")
    resolved_region = P.or_default(region, DEFAULT_REGION)
    base_url = P.or_default(api_url, f"https://bedrock-runtime.{resolved_region}.amazonaws.com")
    limit: ByteSize = P.response_limit(max_response_bytes)
    resolve = _resolve_credentials(
        api_key=api_key,
        credentials=credentials,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        session_token=session_token,
    )

    def with_credentials[A, E](method: str, effect: Effect[A, E]) -> Effect[A, E | AiError]:
        return resolve(method).flat_map(
            lambda found: effect.pipe(fx.provide_service(_CurrentRequestCredentials, found))
        )

    def build(
        base: HttpClientService[HttpClientError], digest: DigestService, mac: MacService
    ) -> Service:
        prepared = base.map_request(
            lambda request: request.prepend_url(base_url).accept_json()
        ).map_request_effect(_authenticate(Signer(resolved_region, digest, mac)))
        http_client = prepared if transform_client is None else transform_client(prepared)

        def send(
            requesting: Effect[HttpClientRequest, Any, Any],
        ) -> Effect[HttpClientResponse, HttpClientError | AiError]:
            sending: Effect[HttpClientResponse, Any, Any] = requesting.flat_map(
                lambda request: with_credentials("execute", http_client.execute(request))
            )
            return sending.pipe(_redacted)

        exposed: HttpClientService[HttpClientError | AiError] = HttpClientService(send, fx.succeed)
        client_ok = P.limit_responses(http_client, limit).filter_status_ok()

        def execute(
            operation: str, method: str, request: W.ConverseRequest
        ) -> Effect[HttpClientResponse, HttpClientError | AiError]:
            body = {key: value for key, value in request.items() if key != "modelId"}
            path = f"/model/{_encode_uri_component(request['modelId'])}/{operation}"
            sending = P.resolve_client(AmazonBedrockConfig, client_ok).flat_map(
                lambda client: client.execute(http_request.post(path).body_json_unsafe(body))
            )
            return with_credentials(method, sending)

        def converse(request: W.ConverseRequest) -> Effect[W.ConverseResponse, AiError]:
            sent: Effect[W.ConverseResponse, Any] = execute(
                "converse", "converse", request
            ).flat_map(lambda response: response.json.flat_map(W.decode_converse_response))
            return sent.catch_all(ERRORS.catch("converse")).pipe(_redacted)

        def converse_stream(request: W.ConverseRequest) -> Stream[W.ConverseStreamEvent, AiError]:
            frames = ES.decode(
                http_response.stream(execute("converse-stream", "converseStream", request))
            )
            events: Stream[W.ConverseStreamEvent, Any] = frames.map_effect(
                _decode_frame
            ).filter_map(lambda event: Err(None) if event is None else Ok(event))
            return events.catch_all(_stream_failure).update_service(
                CurrentRedactedNames, lambda names: (*names, *SECRET_HEADERS)
            )

        return Service(exposed, converse, converse_stream)

    return fx.all(HttpClient(), Digest(), Mac()).map(lambda found: build(*found)).pipe(_redacted)


def layer(
    *,
    region: str | None = None,
    api_url: str | None = None,
    access_key_id: str | None = None,
    secret_access_key: Redacted[str] | None = None,
    session_token: Redacted[str] | None = None,
    api_key: Redacted[str] | None = None,
    credentials: Effect[Credentials, AiError] | None = None,
    transform_client: ClientTransform | None = None,
    max_response_bytes: byte_size.Input | None = None,
) -> L.Layer[AmazonBedrockClient, Never, HttpClient | Digest | Mac]:
    """``AmazonBedrockClient`` from these options (see ``make``)."""
    return L.effect(
        AmazonBedrockClient,
        make(
            region=region,
            api_url=api_url,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            session_token=session_token,
            api_key=api_key,
            credentials=credentials,
            transform_client=transform_client,
            max_response_bytes=max_response_bytes,
        ),
    )


def layer_config(
    *,
    region: Config[str | None] | None = None,
    api_url: Config[str | None] | None = None,
    access_key_id: Config[str | None] | None = None,
    secret_access_key: Config[Redacted[str] | None] | None = None,
    session_token: Config[Redacted[str] | None] | None = None,
    api_key: Config[Redacted[str] | None] | None = None,
    credentials: Effect[Credentials, AiError] | None = None,
    transform_client: ClientTransform | None = None,
    max_response_bytes: byte_size.Input | None = None,
) -> L.Layer[AmazonBedrockClient, ConfigError, HttpClient | Digest | Mac]:
    """``AmazonBedrockClient`` with its settings read from ``Config``. Each
    defaults to the variable the AWS tools read: ``AWS_REGION``,
    ``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY``, ``AWS_SESSION_TOKEN``
    and, for a Bedrock API key, ``AWS_BEARER_TOKEN_BEDROCK``; all are
    optional (see ``make`` for which wins when several are set)."""

    if credentials is not None:
        require_effect(credentials, "credentials")

    @fx.gen
    def built():
        return (
            yield from make(
                region=(yield from region or config_string("AWS_REGION").with_default(None)),
                api_url=(yield from P.optional_config(api_url)),
                access_key_id=(
                    yield from access_key_id
                    or config_string("AWS_ACCESS_KEY_ID").with_default(None)
                ),
                secret_access_key=(
                    yield from secret_access_key
                    or config_redacted("AWS_SECRET_ACCESS_KEY").with_default(None)
                ),
                session_token=(
                    yield from session_token
                    or config_redacted("AWS_SESSION_TOKEN").with_default(None)
                ),
                api_key=(
                    yield from api_key
                    or config_redacted("AWS_BEARER_TOKEN_BEDROCK").with_default(None)
                ),
                credentials=credentials,
                transform_client=transform_client,
                max_response_bytes=max_response_bytes,
            )
        )

    return L.effect(AmazonBedrockClient, built)


__all__ = [
    "DEFAULT_REGION",
    "AiError",
    "AmazonBedrockClient",
    "Credentials",
    "Service",
    "layer",
    "layer_config",
    "make",
]
