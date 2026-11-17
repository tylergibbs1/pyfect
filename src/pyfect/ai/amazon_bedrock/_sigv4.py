"""AWS Signature Version 4 for the Bedrock Runtime service (Effect's
``internal/sigv4.ts``), with SHA-256 and HMAC from the ``Digest`` and ``Mac``
services the caller provides."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote

import pyfect as fx
from pyfect import clock
from pyfect._core import Effect
from pyfect._js import text_encode, to_iso_string, trim
from pyfect._text_keys import key_bytes
from pyfect.crypto import digest as D
from pyfect.crypto import mac as M
from pyfect.http import body as B
from pyfect.http import url as U
from pyfect.http.request import HttpClientRequest
from pyfect.result import Err

_SERVICE = "bedrock"
_WHITESPACE = re.compile(r"\s+")
_AMZ_DATE_DROPPED = re.compile(r"[-:]|\.\d{3}")


@dataclass(frozen=True)
class SigningCredentials:
    """The keys a request is signed with."""

    access_key_id: str
    secret_access_key: str
    session_token: str | None


@dataclass(frozen=True)
class Signer:
    """What signing needs besides the credentials: the region and the
    crypto services."""

    region: str
    digest: D.DigestService
    mac: M.MacService


def _rfc3986(value: str) -> str:
    """Percent-encoding as SigV4 requires: ``encodeURIComponent`` with
    ``!'()*`` encoded too."""
    return quote(value, safe="-_.~")


def _amz_date(millis: float) -> str:
    """``YYYYMMDD'T'HHMMSS'Z'``, the SigV4 timestamp."""
    iso = to_iso_string(datetime.fromtimestamp(millis / 1000, UTC))
    return _AMZ_DATE_DROPPED.sub("", iso)


def _body_bytes(body: B.HttpBody) -> Effect[bytes]:
    match body:
        case B.Empty():
            return fx.succeed(b"")
        case B.Bytes():
            return fx.succeed(body.body)
        case B.Raw(body=str() as text):
            return fx.succeed(text_encode(text))
        case B.Raw(body=bytes() | bytearray() as data):
            return fx.succeed(bytes(data))
        case _:
            pass
    return fx.die(
        RuntimeError(f"AmazonBedrockClient cannot sign a request with a body of type '{body.tag}'")
    )


def sign(
    request: HttpClientRequest, signer: Signer, credentials: SigningCredentials
) -> Effect[HttpClientRequest]:
    """``request`` with the ``authorization``, ``x-amz-date`` and, with a
    session token, ``x-amz-security-token`` headers. The signed headers are
    ``host``, ``x-amz-date``, ``content-type`` when present and
    ``x-amz-security-token`` when present. The canonical URI and query come
    from the URL the transport sends (``url`` with ``url_params``); path
    segments are encoded a second time, as the service does for every API
    but S3. The time comes from the ``Clock``."""

    def hmac(key: bytes, data: str) -> Effect[bytes]:
        # Signing keys are never empty, so a `CryptoError` means the `Mac`
        # service has no HMAC-SHA-256: a defect.
        return (
            M.key(M.hmac_sha256, key)
            .flat_map(lambda made: signer.mac.sign(made, key_bytes(data)))
            .or_die()
        )

    @fx.gen
    def run():
        amz_date = _amz_date((yield from clock.current_time_millis()))
        date = amz_date[:8]
        made = U.make(request.url, request.url_params, None)
        if isinstance(made, Err):
            # The transport fails the request with an `InvalidUrlError` before sending it.
            return request
        url = made.value
        amz_headers = {"x-amz-date": amz_date}
        if credentials.session_token is not None:
            amz_headers["x-amz-security-token"] = credentials.session_token
        headers = {"host": url.host, **amz_headers}
        content_type = request.headers.get("content-type")
        if content_type is not None:
            headers["content-type"] = _WHITESPACE.sub(" ", trim(content_type))
        names = sorted(headers)
        canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in names)
        signed_headers = ";".join(names)
        canonical_uri = "/".join(_rfc3986(segment) for segment in url.pathname.split("/"))
        canonical_query = "&".join(
            f"{key}={value}"
            for key, value in sorted(
                (_rfc3986(key), _rfc3986(value)) for key, value in url.search_params
            )
        )
        body = yield from _body_bytes(request.body)
        payload_hash = yield from signer.digest.digest_hex(D.sha256, body)
        canonical_request = "\n".join(
            (
                request.method,
                canonical_uri,
                canonical_query,
                canonical_headers,
                signed_headers,
                payload_hash,
            )
        )
        scope = f"{date}/{signer.region}/{_SERVICE}/aws4_request"
        request_hash = yield from signer.digest.digest_hex(D.sha256, key_bytes(canonical_request))
        string_to_sign = "\n".join(("AWS4-HMAC-SHA256", amz_date, scope, request_hash))
        key = yield from hmac(key_bytes(f"AWS4{credentials.secret_access_key}"), date)
        key = yield from hmac(key, signer.region)
        key = yield from hmac(key, _SERVICE)
        key = yield from hmac(key, "aws4_request")
        signature = (yield from hmac(key, string_to_sign)).hex()
        authorization = (
            f"AWS4-HMAC-SHA256 Credential={credentials.access_key_id}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return request.set_headers({"authorization": authorization, **amz_headers})

    return run
