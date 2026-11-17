"""Ports of Effect's ``packages/ai/amazon-bedrock/test/AmazonBedrockClient.test.ts``.
Each docstring is the Effect test title (with its ``describe``). Responses are recorded
JSON or event-stream frames answered by a mocked ``HttpClient``; signatures are checked by
recomputing them as the service does (``_bedrock.verify_sig_v4``)."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
import hashlib
import hmac
from typing import Any

import pytest

import pyfect as fx
from pyfect import config_provider, testing
from pyfect import layer as L
from pyfect import stream as St
from pyfect.ai import ai_error as E
from pyfect.ai.amazon_bedrock import _sigv4, client
from pyfect.ai.amazon_bedrock import schema as W
from pyfect.crypto import digest, mac, secure_random
from pyfect.crypto.digest import DigestService
from pyfect.crypto.mac import MacService
from pyfect.http import body as http_body
from pyfect.http import client as http_client
from pyfect.http import request as http_request
from pyfect.http import url_params
from pyfect.redacted import make as redact

from ._ai_http import recording_tracer, stringify_error
from ._bedrock import (
    ACCESS_KEY_ID,
    ENCODED_MODEL_ID,
    MODEL_ID,
    SECRET_ACCESS_KEY,
    WEB_CRYPTO,
    encode_frame,
    encode_raw_frame,
    event_frame,
    event_stream_response,
    exception_frame,
    json_response,
    respond,
    text_reply_frames,
    verify_sig_v4,
    with_crypto,
)

PAYLOAD: W.ConverseRequest = {
    "modelId": MODEL_ID,
    "messages": [{"role": "user", "content": [{"text": "Hello"}]}],
}

CONVERSE_BODY = {
    "output": {"message": {"role": "assistant", "content": [{"text": "Hi"}]}},
    "stopReason": "end_turn",
    "usage": {"inputTokens": 7, "outputTokens": 3, "totalTokens": 10},
    "metrics": {"latencyMs": 42},
}

STATIC_KEYS = client.layer(
    region="us-east-1", access_key_id=ACCESS_KEY_ID, secret_access_key=redact(SECRET_ACCESS_KEY)
)


def converse() -> fx.Effect[W.ConverseResponse, E.AiError, client.AmazonBedrockClient]:
    return client.AmazonBedrockClient().flat_map(lambda c: c.converse(PAYLOAD))


def converse_stream() -> fx.Effect[list[W.ConverseStreamEvent], E.AiError, Any]:
    return St.unwrap(
        client.AmazonBedrockClient().map(lambda c: c.converse_stream(PAYLOAD))
    ).run_collect()


def converse_ok():
    return respond(lambda request: json_response(request, CONVERSE_BODY))


@testing.effect
def test_signs_with_sig_v4():
    """AmazonBedrockClient / authentication / signs requests with SigV4 from static keys using
    the Effect clock"""
    http = converse_ok()
    response = (
        yield from converse().pipe(fx.provide(STATIC_KEYS)).pipe(fx.provide(with_crypto(http)))
    )
    assert response["stopReason"] == "end_turn"
    request = http.requests[0]
    assert request.method == "POST"
    assert request.url == (
        f"https://bedrock-runtime.us-east-1.amazonaws.com/model/{ENCODED_MODEL_ID}/converse"
    )
    # The TestClock starts at the Unix epoch.
    assert request.headers["x-amz-date"] == "19700101T000000Z"
    signature = verify_sig_v4(request, SECRET_ACCESS_KEY)
    assert signature.access_key_id == ACCESS_KEY_ID
    assert signature.date == "19700101"
    assert signature.region == "us-east-1"
    assert signature.service == "bedrock"
    assert "host" in signature.signed_headers
    assert "x-amz-date" in signature.signed_headers
    assert signature.actual == signature.expected


@testing.effect
def test_signs_session_token():
    """AmazonBedrockClient / authentication / signs the session token when one is configured"""
    http = converse_ok()
    layer = client.layer(
        region="us-east-1",
        access_key_id=ACCESS_KEY_ID,
        secret_access_key=redact(SECRET_ACCESS_KEY),
        session_token=redact("session-token"),
    )
    yield from converse().pipe(fx.provide(layer)).pipe(fx.provide(with_crypto(http)))
    request = http.requests[0]
    assert request.headers["x-amz-security-token"] == "session-token"
    signature = verify_sig_v4(request, SECRET_ACCESS_KEY)
    assert "x-amz-security-token" in signature.signed_headers
    assert signature.actual == signature.expected


@testing.effect
def test_signs_with_caller_crypto():
    """AmazonBedrockClient / authentication / signs with the Digest and Mac services the caller
    provides"""
    http = converse_ok()
    calls = {"digest": 0, "hmac": 0}

    def digest_hex(_algorithm: digest.Algorithm, data: Any) -> fx.Effect[str]:
        def run() -> str:
            calls["digest"] += 1
            return hashlib.sha256(bytes(data)).hexdigest()

        return fx.sync(run)

    def node_hmac(_hash: str, key: bytes, data: bytes) -> bytes:
        calls["hmac"] += 1
        return hmac.new(key, data, hashlib.sha256).digest()

    crypto = L.merge(
        L.succeed(
            digest.Digest,
            DigestService(
                digest=lambda _a, _d: fx.die(RuntimeError("unused")), digest_hex=digest_hex
            ),
        ),
        mac.layer_web_crypto_with(hmac=node_hmac).pipe(L.provide(secure_random.layer_web_crypto)),
    )
    yield from (
        converse()
        .pipe(fx.provide(STATIC_KEYS))
        .pipe(fx.provide(crypto))
        .pipe(fx.provide(http.layer))
    )
    signature = verify_sig_v4(http.requests[0], SECRET_ACCESS_KEY)
    assert signature.actual == signature.expected
    assert calls["digest"] > 0
    assert calls["hmac"] > 0


def _dies(*_args: Any) -> Any:
    return fx.die(RuntimeError("unexpected crypto call"))


@testing.effect
def test_api_key_without_crypto_calls():
    """AmazonBedrockClient / authentication / authenticates with an API key without calling
    Digest or Mac"""
    http = converse_ok()
    unused = L.merge(
        L.succeed(digest.Digest, DigestService(digest=_dies, digest_hex=_dies)),
        L.succeed(mac.Mac, MacService(generate_key=_dies, sign=_dies, verify=_dies)),
    )
    yield from (
        converse()
        .pipe(fx.provide(client.layer(api_key=redact("bedrock-api-key"))))
        .pipe(fx.provide(unused))
        .pipe(fx.provide(http.layer))
    )
    assert http.requests[0].headers["authorization"] == "Bearer bedrock-api-key"


@testing.effect
def test_api_key_bearer_and_api_url():
    """AmazonBedrockClient / authentication / sends a Bedrock API key as a bearer token and
    honours apiUrl"""
    http = converse_ok()
    layer = client.layer(api_key=redact("bedrock-api-key"), api_url="https://bedrock.example.test")
    yield from converse().pipe(fx.provide(layer)).pipe(fx.provide(with_crypto(http)))
    request = http.requests[0]
    assert request.url == f"https://bedrock.example.test/model/{ENCODED_MODEL_ID}/converse"
    assert request.headers["authorization"] == "Bearer bedrock-api-key"
    assert "x-amz-date" not in request.headers


@testing.effect
def test_direct_requests_authenticated():
    """AmazonBedrockClient / authentication / authenticates direct requests through the exposed
    client"""
    http = respond(lambda request: json_response(request, {"ok": True}))
    yield from (
        client.AmazonBedrockClient()
        .flat_map(lambda c: c.client.post(f"/model/{ENCODED_MODEL_ID}/invoke"))
        .pipe(fx.provide(STATIC_KEYS))
        .pipe(fx.provide(with_crypto(http)))
    )
    request = http.requests[0]
    assert request.url == (
        f"https://bedrock-runtime.us-east-1.amazonaws.com/model/{ENCODED_MODEL_ID}/invoke"
    )
    signature = verify_sig_v4(request, SECRET_ACCESS_KEY)
    assert signature.access_key_id == ACCESS_KEY_ID
    assert signature.actual == signature.expected


@testing.effect
def test_signs_direct_query():
    """AmazonBedrockClient / authentication / signs the query of a direct request built from
    urlParams"""
    http = respond(lambda request: json_response(request, {"ok": True}))
    yield from (
        client.AmazonBedrockClient()
        .flat_map(lambda c: c.client.get("/async-invoke", url_params={"maxResults": 1}))
        .pipe(fx.provide(STATIC_KEYS))
        .pipe(fx.provide(with_crypto(http)))
    )
    request = http.requests[0]
    assert url_params.to_string(request.url_params) == "maxResults=1"
    signature = verify_sig_v4(request, SECRET_ACCESS_KEY)
    assert signature.actual == signature.expected


@testing.effect
def test_redacts_session_token_in_tracing():
    """AmazonBedrockClient / authentication / redacts the session token in the header tracing
    of a direct request"""
    tracer, spans = recording_tracer()
    http = respond(lambda request: json_response(request, {"ok": True}))
    layer = client.layer(
        region="us-east-1",
        access_key_id=ACCESS_KEY_ID,
        secret_access_key=redact(SECRET_ACCESS_KEY),
        session_token=redact("session-token"),
    ).pipe(L.provide(with_crypto(http)))
    yield from (
        client.AmazonBedrockClient()
        .flat_map(lambda c: c.client.get("/async-invoke"))
        .pipe(fx.provide(layer))
        .pipe(fx.provide_service(http_client.TracerHeaderFilter, lambda _name, _phase: True))
        .with_tracer(tracer)
    )
    span = next(s for s in spans if s.attributes.get("http.request.method") == "GET")
    assert span.attributes["http.request.header.x-amz-security-token"] == "<redacted>"


@testing.effect
def test_resolves_credentials_every_request():
    """AmazonBedrockClient / authentication / resolves the credentials effect on every request"""
    http = converse_ok()
    calls = [0]

    def resolve() -> client.Credentials:
        calls[0] += 1
        return client.Credentials(f"AKIA{calls[0]}", SECRET_ACCESS_KEY, f"token-{calls[0]}")

    layer = client.layer(region="us-east-1", credentials=fx.sync(resolve))
    yield from converse().pipe(fx.provide(layer)).pipe(fx.provide(with_crypto(http)))
    yield from converse().pipe(fx.provide(layer)).pipe(fx.provide(with_crypto(http)))
    assert [verify_sig_v4(r, SECRET_ACCESS_KEY).access_key_id for r in http.requests] == [
        "AKIA1",
        "AKIA2",
    ]
    assert [r.headers["x-amz-security-token"] for r in http.requests] == ["token-1", "token-2"]


@testing.effect
def test_credentials_effect_error():
    """AmazonBedrockClient / authentication / fails with the error of the credentials effect"""
    http = converse_ok()
    vault_down = E.AiError(
        module="Vault",
        method="credentials",
        reason=E.AuthenticationError(kind="Unknown", description="vault is down"),
    )
    layer = client.layer(region="us-east-1", credentials=fx.fail(vault_down))
    error = yield from converse().pipe(fx.provide(layer)).pipe(fx.provide(with_crypto(http))).flip()
    assert isinstance(error.reason, E.AuthenticationError)
    assert error.reason.kind == "Unknown"
    assert error.reason.description == "vault is down"
    assert http.requests == []


@testing.effect
def test_missing_key():
    """AmazonBedrockClient / authentication / fails with MissingKey when no credentials are
    configured"""
    http = converse_ok()
    error = yield from (
        converse()
        .pipe(fx.provide(client.layer(region="us-east-1")))
        .pipe(fx.provide(with_crypto(http)))
        .flip()
    )
    assert isinstance(error.reason, E.AuthenticationError)
    assert error.reason.kind == "MissingKey"
    assert http.requests == []


@testing.effect
def test_error_context_without_credentials():
    """AmazonBedrockClient / authentication / omits request credentials from error context"""
    http = respond(
        lambda request: json_response(
            request, {"message": "Malformed input request"}, 400, "ValidationException"
        )
    )
    layer = client.layer(
        region="us-east-1",
        access_key_id=ACCESS_KEY_ID,
        secret_access_key=redact(SECRET_ACCESS_KEY),
        session_token=redact("session-token"),
    )
    error = yield from converse().pipe(fx.provide(layer)).pipe(fx.provide(with_crypto(http))).flip()
    assert isinstance(error.reason, E.InvalidRequestError)
    assert error.reason.http is not None
    assert "request" not in error.reason.http
    serialized = stringify_error(error)
    assert ACCESS_KEY_ID not in serialized
    assert SECRET_ACCESS_KEY not in serialized
    assert "session-token" not in serialized


@testing.effect
def test_layer_config_aws_keys():
    """AmazonBedrockClient / layerConfig / reads the AWS keys and region from the environment"""
    http = converse_ok()
    provider = config_provider.from_env(
        {
            "AWS_REGION": "eu-west-1",
            "AWS_ACCESS_KEY_ID": ACCESS_KEY_ID,
            "AWS_SECRET_ACCESS_KEY": SECRET_ACCESS_KEY,
            "AWS_SESSION_TOKEN": "session-token",
        }
    )
    yield from (
        converse()
        .pipe(fx.provide(client.layer_config()))
        .pipe(fx.provide(config_provider.layer(provider)))
        .pipe(fx.provide(with_crypto(http)))
    )
    request = http.requests[0]
    assert request.url == (
        f"https://bedrock-runtime.eu-west-1.amazonaws.com/model/{ENCODED_MODEL_ID}/converse"
    )
    assert request.headers["x-amz-security-token"] == "session-token"
    signature = verify_sig_v4(request, SECRET_ACCESS_KEY)
    assert signature.access_key_id == ACCESS_KEY_ID
    assert signature.region == "eu-west-1"
    assert signature.actual == signature.expected


@testing.effect
def test_layer_config_api_key():
    """AmazonBedrockClient / layerConfig / reads a Bedrock API key from the environment"""
    http = converse_ok()
    provider = config_provider.from_env(
        {"AWS_REGION": "eu-west-1", "AWS_BEARER_TOKEN_BEDROCK": "bedrock-api-key"}
    )
    yield from (
        converse()
        .pipe(fx.provide(client.layer_config()))
        .pipe(fx.provide(config_provider.layer(provider)))
        .pipe(fx.provide(with_crypto(http)))
    )
    assert http.requests[0].headers["authorization"] == "Bearer bedrock-api-key"


_ERROR_CASES: list[tuple[int, str, type[E.AiErrorReason], str | None]] = [
    (400, "ValidationException", E.InvalidRequestError, None),
    (404, "ResourceNotFoundException", E.InvalidRequestError, None),
    (400, "ServiceQuotaExceededException", E.QuotaExhaustedError, None),
    (403, "AccessDeniedException", E.AuthenticationError, "InsufficientPermissions"),
    (403, "ExpiredTokenException", E.AuthenticationError, "ExpiredKey"),
    (403, "UnrecognizedClientException", E.AuthenticationError, "InvalidKey"),
    (403, "InvalidSignatureException", E.AuthenticationError, "InvalidKey"),
    (429, "ThrottlingException", E.RateLimitError, None),
    (500, "InternalServerException", E.InternalProviderError, None),
    (503, "ServiceUnavailableException", E.InternalProviderError, None),
]


@pytest.mark.parametrize(
    ("status", "error_type", "reason", "kind"),
    _ERROR_CASES,
    ids=[f"maps {s} {t} to {r.__name__}" for s, t, r, _ in _ERROR_CASES],
)
@testing.effect
def test_error_mapping(status: int, error_type: str, reason: type[Any], kind: str | None):
    """AmazonBedrockClient / error mapping / maps each status and exception type to its reason"""
    http = respond(
        lambda request: json_response(request, {"message": "provider message"}, status, error_type)
    )
    error = (
        yield from converse()
        .pipe(fx.provide(STATIC_KEYS))
        .pipe(fx.provide(with_crypto(http)))
        .flip()
    )
    assert isinstance(error, E.AiError)
    assert isinstance(error.reason, reason)
    if kind is not None:
        assert isinstance(error.reason, E.AuthenticationError)
        assert error.reason.kind == kind
    description = getattr(error.reason, "description", None)
    if hasattr(error.reason, "description"):
        assert "provider message" in (description or "")


@testing.effect
def test_converse_preserves_unmodelled():
    """AmazonBedrockClient / converse / preserves response fields and content blocks it does
    not model"""
    body = {
        **CONVERSE_BODY,
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": "Hi"}, {"citationsContent": {"content": [{"text": "cited"}]}}],
            }
        },
        "additionalModelResponseFields": {"stop_sequence": None},
    }
    http = respond(lambda request: json_response(request, body))
    response = (
        yield from converse().pipe(fx.provide(STATIC_KEYS)).pipe(fx.provide(with_crypto(http)))
    )
    assert response["output"]["message"]["content"][1] == {
        "citationsContent": {"content": [{"text": "cited"}]}
    }
    raw: dict[str, Any] = dict(response)
    assert raw["additionalModelResponseFields"] == {"stop_sequence": None}


def _stream_events(chunks: list[bytes]):
    http = respond(lambda request: event_stream_response(request, chunks))
    return http, converse_stream().pipe(fx.provide(STATIC_KEYS)).pipe(fx.provide(with_crypto(http)))


@testing.effect
def test_stream_preserves_unmodelled_fields():
    """AmazonBedrockClient / converseStream / preserves fields of known events and nested
    structs it does not model"""
    _http, events = _stream_events(
        [
            event_frame("messageStart", {"role": "assistant"})
            + event_frame(
                "messageStop",
                {
                    "stopReason": "stop_sequence",
                    "additionalModelResponseFields": {"stop_sequence": "END"},
                },
            )
            + event_frame(
                "metadata",
                {
                    "usage": {
                        "inputTokens": 1,
                        "outputTokens": 1,
                        "totalTokens": 2,
                        "cacheDetails": {"tier": "default"},
                    },
                    "metrics": {"latencyMs": 1},
                },
            )
        ]
    )
    found = yield from events
    assert found[1] == {
        "messageStop": {
            "stopReason": "stop_sequence",
            "additionalModelResponseFields": {"stop_sequence": "END"},
        }
    }
    metadata: dict[str, Any] = dict(found[2])
    assert metadata["metadata"]["usage"]["cacheDetails"] == {"tier": "default"}


@testing.effect
def test_stream_preserves_unknown_event():
    """AmazonBedrockClient / converseStream / preserves an event it does not model"""
    _http, events = _stream_events(
        [
            event_frame("messageStart", {"role": "assistant"})
            + event_frame("someFutureEvent", {"detail": 1})
            + event_frame("messageStop", {"stopReason": "end_turn"})
        ]
    )
    found = yield from events
    assert [next(iter(event)) for event in found] == [
        "messageStart",
        "someFutureEvent",
        "messageStop",
    ]
    assert found[1] == {"someFutureEvent": {"detail": 1}}


@testing.effect
def test_stream_frames_split_across_chunks():
    """AmazonBedrockClient / converseStream / decodes event frames split across chunks"""
    data = b"".join(text_reply_frames("Hello"))
    http, events = _stream_events([data[:20], data[20:95], data[95:]])
    found = yield from events
    assert http.requests[0].url == (
        f"https://bedrock-runtime.us-east-1.amazonaws.com/model/{ENCODED_MODEL_ID}/converse-stream"
    )
    assert [next(iter(event)) for event in found] == [
        "messageStart",
        "contentBlockDelta",
        "contentBlockStop",
        "messageStop",
        "metadata",
    ]
    delta: dict[str, Any] = dict(found[1])
    assert delta["contentBlockDelta"]["delta"] == {"text": "Hello"}


@testing.effect
def test_stream_exception_frame():
    """AmazonBedrockClient / converseStream / fails with the mapped error for an exception
    frame"""
    _http, events = _stream_events(
        [
            event_frame("messageStart", {"role": "assistant"})
            + exception_frame("throttlingException", {"message": "Too many requests"})
        ]
    )
    error = yield from events.flip()
    assert isinstance(error.reason, E.RateLimitError)


_MALFORMED: list[tuple[str, bytes]] = [
    (
        "a frame whose message CRC does not match",
        event_frame("messageStart", {"role": "assistant"}, message_crc=0),
    ),
    (
        "a frame whose prelude CRC does not match",
        event_frame("messageStart", {"role": "assistant"}, prelude_crc=0),
    ),
    (
        "a frame shorter than the 16 byte minimum",
        event_frame("messageStart", {"role": "assistant"}, total_length=0),
    ),
    (
        "a frame cut off before its declared length",
        event_frame("messageStart", {"role": "assistant"})[:24],
    ),
    ("a CRC-valid frame whose headers block is cut off", encode_raw_frame(bytes([255]), b"{}")),
    (
        "a payload that is not JSON",
        encode_frame(
            {
                ":message-type": "event",
                ":event-type": "messageStart",
                ":content-type": "application/json",
            },
            b"{not json",
        ),
    ),
]


@pytest.mark.parametrize(
    "data", [data for _, data in _MALFORMED], ids=[label for label, _ in _MALFORMED]
)
@testing.effect
def test_stream_rejects_malformed(data: bytes):
    """AmazonBedrockClient / converseStream / rejects each malformed frame with
    InvalidResponseError"""
    _http, events = _stream_events([data])
    error = yield from events.flip()
    assert isinstance(error, E.AiError)
    assert isinstance(error.reason, E.InvalidResponseError)


@testing.effect
def test_signature_matches_effect():
    """The signature Effect 4.1.4's ``internal/sigv4.ts`` gives the same request at the same
    time (computed with Node against the Effect checkout): a query to sort and encode, a
    path segment to encode twice, a non-ASCII body and a session token."""
    yield from testing.set_time(1700000000123)
    request = http_request.post(
        "https://bedrock-runtime.us-east-1.amazonaws.com/model/a%3Ab/converse",
        url_params={"b c": "x*y", "a": "1"},
    ).set_body(
        http_body.json_unsafe({"messages": [{"role": "user", "content": [{"text": "Hi é"}]}]})
    )
    signed = yield from _sign(request).pipe(fx.provide(WEB_CRYPTO))
    assert signed.headers["authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKID/20231114/us-east-1/bedrock/aws4_request, "
        "SignedHeaders=content-type;host;x-amz-date;x-amz-security-token, "
        "Signature=40c7357e7f6136205f47989e705e2b48984b1c11f6bc3f93b2d8b8c59d585d25"
    )


def _sign(request: http_request.HttpClientRequest):
    @fx.gen
    def run():
        signer = _sigv4.Signer("us-east-1", (yield from digest.Digest()), (yield from mac.Mac()))
        credentials = _sigv4.SigningCredentials("AKID", "SECRET", "tok")
        return (yield from _sigv4.sign(request, signer, credentials))

    return run
