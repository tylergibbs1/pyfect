"""Bot Framework bearer tokens on inbound requests."""

from __future__ import annotations

import re
from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Never, NotRequired, TypedDict, cast

import pyfect as fx
from pyfect import schema as S
from pyfect._core import Effect
from pyfect._url import Url
from pyfect.chat.teams import _connector, _json
from pyfect.chat.teams._cloud import Cloud
from pyfect.clock import current_time_millis
from pyfect.context import Context
from pyfect.crypto.signature import Signature
from pyfect.exit import Failure, Success
from pyfect.http import request as http_request
from pyfect.http.client import HttpClient
from pyfect.jose import jwks, jwt
from pyfect.jose.jose_error import JoseError, KeySetUnavailable
from pyfect.jose.jwks import Jwks, JwksService
from pyfect.scope import Scope
from pyfect.semaphore import Semaphore

MAX_AUTHORIZATION_LENGTH = 16 * 1024
"""The longest ``Authorization`` header read. Anything longer is refused unread."""

RETRY_AFTER_MILLIS = 30_000
"""How long after a failed metadata or key set fetch the next is tried, so
unauthenticated requests can't drive a fetch each."""

MAX_METADATA_BYTES = 64 * 1024
"""The longest OpenID metadata document read."""

CLOCK_TOLERANCE = "5 minutes"
"""The skew allowed on a token's ``exp`` and ``nbf``."""

_BEARER = re.compile(r"Bearer ([A-Za-z0-9_.-]+)")


class _Claims(TypedDict):
    serviceurl: NotRequired[str]
    serviceUrl: NotRequired[str]


_CLAIMS = S.Struct(_Claims)

type Verdict = Literal["ok", "forbidden", "unavailable"]


@dataclass(frozen=True)
class Activity:
    """What the token is checked against, from the activity's body."""

    service_url: object
    channel_id: object
    tenant_id: str | None


type Verify = Callable[[str | None, Activity], Effect[Verdict]]


def endorsed_for_teams(jwk: Mapping[str, object]) -> bool:
    """Keeps a key only when its ``endorsements`` is an array of strings
    holding ``msteams``. A key without them is dropped: fails closed."""
    endorsements = jwk.get("endorsements")
    return (
        isinstance(endorsements, list)
        and all(isinstance(e, str) for e in endorsements)  # pyright: ignore[reportUnknownVariableType]
        and "msteams" in endorsements
    )


def tenant_of(activity: _json.JsonObject) -> str | None:
    """The tenant of an activity: ``conversation.tenantId``, else ``channelData.tenant.id``."""
    tenant = _json.object_(activity, "conversation")
    value = None if tenant is None else tenant.get("tenantId")
    if isinstance(value, str):
        return value
    found = _json.object_(_json.object_(activity, "channelData"), "tenant")
    value = None if found is None else found.get("id")
    return value if isinstance(value, str) else None


def _none(_error: object) -> None:
    return None


def _read_bounded(stream: Any, max_bytes: int) -> Effect[bytes | None]:
    """The body, or ``None`` once it passes ``max_bytes`` or can't be read.
    Never reads past the limit."""

    def append(body: bytearray, chunk: bytes) -> Effect[bytearray, str]:
        if len(chunk) > max_bytes - len(body):
            return fx.fail("too_large")
        body.extend(chunk)
        return fx.succeed(body)

    return stream.run_fold_effect(bytearray, append).map(bytes).or_else_succeed(_none)


def _jwks_uri(http: _connector.Http, cloud: Cloud) -> Effect[str | None]:
    """The ``jwks_uri`` of the cloud's OpenID metadata, when it is ``https:``
    on the metadata's own host and the default port."""
    metadata_url = Url.parse(cloud.open_id_metadata_url)
    if metadata_url is None:
        return fx.succeed(None)
    host = metadata_url.hostname

    @fx.gen
    def run() -> Generator[Effect[Any, Never, Any], Any, str | None]:
        response = yield from _connector.send(
            http, http_request.get(metadata_url.href), write=False, op="openIdMetadata"
        ).or_else_succeed(_none)
        if response is None or response.status != 200:
            return None
        length = response.headers.get("content-length")
        if length is not None and length.strip().isdigit() and int(length) > MAX_METADATA_BYTES:
            return None
        body = yield from _read_bounded(response.stream, MAX_METADATA_BYTES)
        metadata = (
            None if not body else _json.as_object(_json.parse(body.decode("utf-8", "replace")))
        )
        raw = None if metadata is None else metadata.get("jwks_uri")
        parsed = Url.parse(raw) if isinstance(raw, str) else None
        if parsed is None or parsed.protocol != "https:" or parsed.port or parsed.hostname != host:
            return None
        return parsed.href

    return fx.scoped(run)


class _KeySet:
    """The key set, made on first use. A failed fetch is not tried again for
    ``RETRY_AFTER_MILLIS``."""

    def __init__(self, http: _connector.Http, cloud: Cloud, scope: Any) -> None:
        self._http = http
        self._cloud = cloud
        self._scope = scope
        self._lock = Semaphore(1)
        self._keys: JwksService | None = None
        self._failed_at = float("-inf")

    def _make(self) -> Effect[JwksService | None]:
        def remote(url: str | None) -> Effect[JwksService | None]:
            if url is None:
                return fx.succeed(None)
            return (
                jwks.make_remote(url, filter=endorsed_for_teams)
                .pipe(fx.provide_service(Scope, self._scope))
                .pipe(fx.provide_service(HttpClient, self._http))
                .option()
                .map(lambda made: None if made is None else made.value)
            )

        return _jwks_uri(self._http, self._cloud).flat_map(remote)

    def get(self) -> Effect[JwksService | None]:
        @fx.gen
        def run() -> Generator[Effect[Any, Never, Any], Any, JwksService | None]:
            if self._keys is not None:
                return self._keys
            now = yield from current_time_millis()
            if now - self._failed_at < RETRY_AFTER_MILLIS:
                return None
            made = yield from self._make()
            if made is None:
                self._failed_at = now
            self._keys = made
            return made

        return self._lock.with_permits(run)


def _bearer(authorization: str | None) -> str | None:
    if authorization is None or len(authorization) > MAX_AUTHORIZATION_LENGTH:
        return None
    match = _BEARER.fullmatch(authorization)
    return None if match is None else match.group(1)


def _is_unavailable(exit: Failure[Any]) -> bool:
    found = exit.cause.find_error()
    error = getattr(found, "value", None)
    return isinstance(error, JoseError) and isinstance(error.reason, KeySetUnavailable)


def _claims_match(claims: _Claims, activity: Activity, tenant_id: str) -> bool:
    claimed = claims.get("serviceurl", claims.get("serviceUrl"))
    return (
        isinstance(activity.service_url, str)
        and claimed == activity.service_url
        and activity.channel_id == "msteams"
        and activity.tenant_id == tenant_id
    )


def make_verifier(*, cloud: Cloud, app_id: str, tenant_id: str) -> Effect[Verify, Any, Any]:
    """Checks a Bot Framework bearer token: RS256 with a key endorsed for
    ``msteams`` from the cloud's key set, the cloud's issuer, the app id as
    audience, five minutes of skew and a required ``exp``. Then the
    ``serviceurl`` claim must equal the activity's ``serviceUrl``, its
    ``channelId`` must be ``msteams`` and its tenant the configured one.

    The key set is found lazily from the cloud's OpenID metadata, whose
    ``jwks_uri`` must be ``https:`` on the metadata's own host. Neither
    fetch follows a redirect, and the metadata is read to at most 64 KiB.
    Metadata or a key set that can't be read is ``unavailable``, so the
    webhook answers 503 and Teams retries; every other failure is
    ``forbidden``."""

    @fx.gen
    def build() -> Generator[Effect[Any, Any, Any], Any, Verify]:
        http = _connector.without_redirects((yield from HttpClient()))
        key_set = _KeySet(http, cloud, (yield from Scope()))
        context = Context.make(Signature, (yield from Signature()))

        def check(token: str, keys: JwksService, activity: Activity) -> Effect[Verdict]:
            def verdict(exit: Any) -> Verdict:
                if isinstance(exit, Failure):
                    return (
                        "unavailable"
                        if _is_unavailable(cast("Failure[Any]", exit))
                        else "forbidden"
                    )
                claims: _Claims = cast("Success[Any]", exit).value.claims
                return "ok" if _claims_match(claims, activity, tenant_id) else "forbidden"

            return (
                jwt.verify_with_key_set(
                    _CLAIMS,
                    token,
                    algorithms=["RS256"],
                    issuer=cloud.issuer,
                    audience=app_id,
                    clock_tolerance=CLOCK_TOLERANCE,
                    required_claims=["exp"],
                )
                .pipe(fx.provide_service(Jwks, keys))
                .pipe(fx.provide_context(context))
                .exit()
                .map(verdict)
            )

        def verify(authorization: str | None, activity: Activity) -> Effect[Verdict]:
            token = _bearer(authorization)
            if token is None:
                return fx.succeed("forbidden")
            return key_set.get().flat_map(
                lambda keys: (
                    fx.succeed("unavailable") if keys is None else check(token, keys, activity)
                )
            )

        return verify

    return build
