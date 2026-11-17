"""What the Amazon Bedrock ports share (Effect's ``ai/amazon-bedrock/test/utils.ts``
and the helpers of its test files): ``application/vnd.amazon.eventstream`` frames with
their CRC-32 checksums, a mocked ``HttpClient`` with the crypto services, and a SigV4
verifier that recomputes a signature the way the service does."""

from __future__ import annotations

import hashlib
import hmac as std_hmac
import json
import re
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import pyfect as fx
from pyfect import layer as L
from pyfect import stream as St
from pyfect.crypto import digest, mac, secure_random
from pyfect.http import response as http_response
from pyfect.http import url as http_url
from pyfect.http.body import Bytes
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.result import Ok

from ._ai_http import Handler, MockHttp

MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
ENCODED_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1%3A0"
ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

WEB_CRYPTO = L.merge(
    digest.layer_web_crypto, mac.layer_web_crypto.pipe(L.provide(secure_random.layer_web_crypto))
)
"""The ``Digest`` and ``Mac`` services the client signs with."""


def encode_raw_frame(
    headers: bytes,
    payload: bytes,
    *,
    total_length: int | None = None,
    prelude_crc: int | None = None,
    message_crc: int | None = None,
) -> bytes:
    """A frame around an encoded headers block; the overrides corrupt it."""
    length = 12 + len(headers) + len(payload) + 4
    prelude = (total_length if total_length is not None else length).to_bytes(4) + len(
        headers
    ).to_bytes(4)
    prelude += (prelude_crc if prelude_crc is not None else zlib.crc32(prelude)).to_bytes(4)
    message = prelude + headers + payload
    return message + (message_crc if message_crc is not None else zlib.crc32(message)).to_bytes(4)


def _headers(headers: Mapping[str, str]) -> bytes:
    out = b""
    for name, value in headers.items():
        name_bytes, value_bytes = name.encode(), value.encode()
        out += bytes([len(name_bytes)]) + name_bytes + bytes([7])
        out += len(value_bytes).to_bytes(2) + value_bytes
    return out


def encode_frame(headers: Mapping[str, str], payload: bytes, **overrides: int) -> bytes:
    return encode_raw_frame(_headers(headers), payload, **overrides)


def event_frame(event_type: str, payload: object, **overrides: int) -> bytes:
    headers = {
        ":message-type": "event",
        ":event-type": event_type,
        ":content-type": "application/json",
    }
    return encode_frame(headers, json.dumps(payload).encode(), **overrides)


def exception_frame(exception_type: str, payload: object) -> bytes:
    headers = {
        ":message-type": "exception",
        ":exception-type": exception_type,
        ":content-type": "application/json",
    }
    return encode_frame(headers, json.dumps(payload).encode())


def text_reply_frames(text: str) -> list[bytes]:
    return [
        event_frame("messageStart", {"role": "assistant"}),
        event_frame("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": text}}),
        event_frame("contentBlockStop", {"contentBlockIndex": 0}),
        event_frame("messageStop", {"stopReason": "end_turn"}),
        event_frame(
            "metadata",
            {
                "usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15},
                "metrics": {"latencyMs": 123},
            },
        ),
    ]


def json_response(
    request: HttpClientRequest, body: object, status: int = 200, error_type: str | None = None
) -> HttpClientResponse:
    headers = {"content-type": "application/json"}
    if error_type is not None:
        headers["x-amzn-errortype"] = (
            f"{error_type}:http://internal.amazon.com/coral/com.amazon.bedrock/"
        )
    return http_response.make(request, json.dumps(body), status=status, headers=headers)


def event_stream_response(
    request: HttpClientRequest, chunks: Sequence[bytes]
) -> HttpClientResponse:
    return http_response.make(
        request,
        St.from_iterable(chunks),
        headers={"content-type": "application/vnd.amazon.eventstream"},
    )


def respond(answer: Callable[[HttpClientRequest], HttpClientResponse]) -> MockHttp:
    handler: Handler = lambda request: fx.succeed(answer(request))  # noqa: E731
    return MockHttp(handler)


def with_crypto(mock: MockHttp) -> L.Layer[Any]:
    """The mocked transport with the Web Crypto ``Digest`` and ``Mac``."""
    return L.merge(mock.layer, WEB_CRYPTO)


def body_json(request: HttpClientRequest) -> Any:
    body = request.body
    assert isinstance(body, Bytes)
    return json.loads(body.body)


def _rfc3986(value: str) -> str:
    return quote(value, safe="-_.~")


def _hmac(key: bytes, data: str) -> bytes:
    return std_hmac.new(key, data.encode(), hashlib.sha256).digest()


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Signature:
    access_key_id: str
    date: str
    region: str
    service: str
    signed_headers: list[str]
    actual: str
    expected: str


_AUTHORIZATION = re.compile(
    r"^AWS4-HMAC-SHA256 Credential=([^/]+)/(\d{8})/([^/]+)/([^/]+)/aws4_request, "
    r"SignedHeaders=([^,]+), Signature=([0-9a-f]{64})$"
)


def verify_sig_v4(request: HttpClientRequest, secret: str) -> Signature:
    """The signature of ``request`` recomputed from the request as sent, so one the service
    would reject fails here too. Canonical URI segments are encoded once more because the
    path is already percent-encoded (Bedrock is not S3)."""
    authorization = request.headers.get("authorization", "")
    match = _AUTHORIZATION.match(authorization)
    assert match is not None, f"Not a SigV4 authorization header: {authorization}"
    access_key_id, date, region, service, signed_list, actual = match.groups()
    signed_headers = signed_list.split(";")
    # The transport appends `url_params` to `url` when it sends the request.
    made = http_url.make(request.url, request.url_params, None)
    assert isinstance(made, Ok)
    url = made.value
    canonical_query = "&".join(
        sorted(f"{_rfc3986(key)}={_rfc3986(value)}" for key, value in url.search_params)
    )
    body = request.body.body if isinstance(request.body, Bytes) else b""
    host = urlsplit(url.href).netloc
    canonical_headers = "".join(
        f"{name}:{host if name == 'host' else request.headers.get(name, '').strip()}\n"
        for name in signed_headers
    )
    canonical_request = "\n".join(
        (
            request.method,
            "/".join(_rfc3986(segment) for segment in url.pathname.split("/")),
            canonical_query,
            canonical_headers,
            signed_list,
            _sha256_hex(body),
        )
    )
    scope = f"{date}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        (
            "AWS4-HMAC-SHA256",
            request.headers.get("x-amz-date", ""),
            scope,
            _sha256_hex(canonical_request.encode()),
        )
    )
    key = _hmac(f"AWS4{secret}".encode(), date)
    for part in (region, service, "aws4_request"):
        key = _hmac(key, part)
    expected = _hmac(key, string_to_sign).hex()
    return Signature(access_key_id, date, region, service, signed_headers, actual, expected)
