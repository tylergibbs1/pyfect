"""JSON Web Key Sets (Effect's ``effect/jose/Jwks``): the ``Jwks`` service
that resolves a token's verification key::

    program.pipe(provide(jwks.layer_local(key_set)))
    program.pipe(provide(jwks.layer_remote(url="https://issuer.example/jwks.json")))

A key matches when its family and curve fit the algorithm, its ``kid`` is
the token's (when the token names one), and its ``alg``, ``use`` and
``key_ops`` allow verifying with it. Keys of other families or curves are
read and ignored; private and symmetric members fail the whole set.

The remote key set is fetched over HTTPS through ``HttpClient``, kept for
``time_to_live``, and refetched early when a token names an unknown key,
at most once per ``cooldown``. A failed fetch is retried after
``cooldown``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Never, NotRequired, TypedDict, cast

from pyfect import schema as S
from pyfect._catch import catch_tag
from pyfect._core import Effect, Restore, uninterruptible_mask
from pyfect._url import Url
from pyfect.clock import current_time_millis
from pyfect.context import Tag
from pyfect.deferred import Deferred
from pyfect.duration import Input as DurationInput
from pyfect.duration import from_millis
from pyfect.effect import fail, from_exit, gen, succeed, suspend, sync
from pyfect.exit import Exit, Failure, Success
from pyfect.exit import fail as fail_exit
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.jose._compact import fail as fail_reason
from pyfect.jose._compact import invalid_argument, millis, parse_json_object
from pyfect.jose.jose_error import AmbiguousKey, JoseError, KeyNotFound, KeySetUnavailable
from pyfect.jose.jwk import (
    AsymmetricAlgorithm,
    PublicJwk,
    PublicJwkSchema,
    PublicKey,
    import_public,
)
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.scope import CloseableScope, Scope, scoped

if TYPE_CHECKING:
    from pyfect.jose.jws import ProtectedHeader


class _UnsupportedJwk(TypedDict):
    kty: str
    crv: NotRequired[str]
    d: NotRequired[Never]
    p: NotRequired[Never]
    q: NotRequired[Never]
    dp: NotRequired[Never]
    dq: NotRequired[Never]
    qi: NotRequired[Never]
    oth: NotRequired[Never]
    k: NotRequired[Never]


def _is_unsupported(jwk: Mapping[str, object]) -> bool:
    kty, crv = jwk.get("kty"), jwk.get("crv")
    return (
        kty not in ("oct", "RSA")
        and (kty != "EC" or (crv is not None and crv not in ("P-256", "P-384", "P-521")))
        and (kty != "OKP" or (crv is not None and crv != "Ed25519"))
    )


# Any other key family or curve, with any other members. Private and
# symmetric members, including RSA factors, are still rejected.
_UnsupportedJwkSchema = S.StructWithRest(
    S.Struct(
        _UnsupportedJwk, **{name: S.Never for name in ("d", "p", "q", "dp", "dq", "qi", "oth", "k")}
    ),
    S.Record(S.String, S.Unknown),
).check(S.make_filter(_is_unsupported))


class KeySet(TypedDict):
    """A JWK Set document: supported public keys and any other key types."""

    keys: Sequence[PublicJwk | Mapping[str, object]]


KeySetSchema = S.Struct(KeySet, keys=S.Array(S.Union(PublicJwkSchema, _UnsupportedJwkSchema)))


@dataclass(frozen=True, slots=True)
class Selection:
    """What to resolve: the algorithm, the token's ``kid``, and the header
    a custom resolver may read."""

    algorithm: AsymmetricAlgorithm
    kid: str | None = None
    protected_header: ProtectedHeader | None = None


@dataclass(frozen=True, slots=True)
class JwksService:
    resolve: Callable[[Selection], Effect[PublicKey, JoseError]]


class Jwks(Tag[JwksService], key="effect/jose/Jwks"):
    """Resolves the public key that verifies a token."""


_KEY_TYPES: dict[AsymmetricAlgorithm, tuple[str, str | None]] = {
    "RS256": ("RSA", None),
    "RS384": ("RSA", None),
    "RS512": ("RSA", None),
    "PS256": ("RSA", None),
    "PS384": ("RSA", None),
    "PS512": ("RSA", None),
    "ES256": ("EC", "P-256"),
    "ES384": ("EC", "P-384"),
    "ES512": ("EC", "P-521"),
    "EdDSA": ("OKP", "Ed25519"),
}

_is_public_jwk = S.is_(PublicJwkSchema)


@dataclass(eq=False, slots=True)
class _Entry:
    """A selectable JWK and its imports, one per algorithm; dropped with the
    key set it came from."""

    jwk: PublicJwk
    imported: dict[AsymmetricAlgorithm, PublicKey] = field(
        default_factory=dict[AsymmetricAlgorithm, PublicKey]
    )


def _supported_keys(key_set: KeySet) -> list[_Entry]:
    """The keys that can ever be selected, found once per key set."""
    return [_Entry(jwk) for jwk in key_set["keys"] if _is_public_jwk(jwk)]


def _candidates(entries: Sequence[_Entry], selection: Selection) -> list[_Entry]:
    kty, crv = _KEY_TYPES[selection.algorithm]

    def matches(jwk: Mapping[str, object]) -> bool:
        key_ops = jwk.get("key_ops")
        return (
            jwk.get("kty") == kty
            and jwk.get("crv") == crv
            and (selection.kid is None or jwk.get("kid") == selection.kid)
            and jwk.get("alg") in (None, selection.algorithm)
            and jwk.get("use") in (None, "sig")
            and (key_ops is None or "verify" in cast("Sequence[str]", key_ops))
        )

    return [entry for entry in entries if matches(cast("Mapping[str, object]", entry.jwk))]


def _import_key(
    found: Sequence[_Entry], algorithm: AsymmetricAlgorithm
) -> Effect[PublicKey, JoseError]:
    if len(found) == 0:
        return fail_reason(KeyNotFound())
    if len(found) > 1:
        return fail_reason(AmbiguousKey())
    entry = found[0]
    cached = entry.imported.get(algorithm)
    if cached is not None:
        return succeed(cached)
    return import_public(entry.jwk, algorithm).tap(
        lambda key: sync(lambda: entry.imported.__setitem__(algorithm, key))
    )


def make_local(key_set: KeySet) -> Effect[JwksService]:
    """A ``Jwks`` service over a fixed key set."""

    def build() -> JwksService:
        keys = _supported_keys(key_set)
        return JwksService(
            lambda selection: _import_key(_candidates(keys, selection), selection.algorithm)
        )

    return sync(build)


def layer_local(key_set: KeySet) -> Layer[Jwks]:
    return layer_effect(Jwks, make_local(key_set))


@dataclass(frozen=True, slots=True)
class _Snapshot:
    keys: list[_Entry]
    expires_at: float


def _unavailable(description: str, cause: object = None) -> JoseError:
    return JoseError(KeySetUnavailable(description, cause))


def _positive_integer(name: str, value: int) -> Effect[int, JoseError]:
    if type(value) is int and 0 < value <= 2**53 - 1:
        return succeed(value)
    return invalid_argument(f"{name} must be a positive integer")


def _positive_millis(name: str, input: DurationInput) -> Effect[float, JoseError]:
    return millis(name, input).flat_map(
        lambda value: succeed(value) if value > 0 else invalid_argument(f"{name} must be positive")
    )


def _read_url(input: str) -> Effect[Url, JoseError]:
    url = Url.parse(input)
    if (
        url is not None
        and url.protocol == "https:"
        and url.username == ""
        and url.password == ""
        and url.hash == ""
    ):
        return succeed(url)
    return invalid_argument("url must be an HTTPS URL without credentials or a fragment")


@dataclass(frozen=True, slots=True)
class _Options:
    href: str
    time_to_live: float
    cooldown: float
    timeout: float
    max_response_bytes: int
    max_keys: int


class _Remote:
    """A remote key set's cache, its one pending fetch, and its cooldown."""

    __slots__ = (
        "_cache",
        "_client",
        "_closed",
        "_closed_exit",
        "_last_attempt",
        "_last_failed",
        "_options",
        "_pending",
        "_scope",
    )

    def __init__(
        self,
        options: _Options,
        client: HttpClientService[HttpClientError, Scope],
        scope: CloseableScope,
    ) -> None:
        self._options = options
        self._client = client
        self._scope = scope
        self._cache: _Snapshot | None = None
        self._pending: Deferred[_Snapshot, JoseError] | None = None
        self._last_attempt = float("-inf")
        self._last_failed = False
        self._closed = False
        self._closed_exit: Exit[Never, JoseError] = fail_exit(
            _unavailable("The key set scope is closed")
        )

    def close(self) -> None:
        self._closed = True
        if self._pending is not None:
            self._pending.done_unsafe(self._closed_exit)

    def _append(self, body: bytearray, chunk: bytes) -> Effect[bytearray, JoseError]:
        limit = self._options.max_response_bytes
        if len(chunk) > limit - len(body):
            return fail(_unavailable(f"The key set response exceeds {limit} bytes"))
        body.extend(chunk)
        return succeed(body)

    def _fetch(self) -> Effect[_Snapshot, JoseError]:
        options = self._options

        @gen
        def body():
            response = yield from self._client.get(
                options.href, headers={"accept": "application/json"}
            )
            if response.status != 200:
                description = f"The key set endpoint responded with status {response.status}"
                return (yield from fail(_unavailable(description)))
            if response.url != options.href:
                return (yield from fail(_unavailable("The key set response came from another URL")))
            document = yield from response.stream.run_fold_effect(bytearray, self._append)
            key_set = yield from S.decode_unknown_effect(KeySetSchema)(
                parse_json_object(bytes(document))
            ).map_error(lambda cause: _unavailable("The key set document is invalid", cause))
            if len(key_set["keys"]) > options.max_keys:
                description = f"The key set has more than {options.max_keys} keys"
                return (yield from fail(_unavailable(description)))
            now = yield from current_time_millis()
            return _Snapshot(_supported_keys(key_set), now + options.time_to_live)

        return (
            scoped(body)
            .pipe(
                catch_tag(
                    HttpClientError,
                    lambda cause: fail(_unavailable("The key set request failed", cause)),
                )
            )
            .timeout_or_else(
                from_millis(options.timeout),
                lambda: fail(_unavailable("The key set request timed out")),
            )
        )

    def _settle(
        self, result: Deferred[_Snapshot, JoseError], exit: Exit[_Snapshot, JoseError]
    ) -> None:
        self._pending = None
        self._last_failed = isinstance(exit, Failure)
        if isinstance(exit, Success):
            self._cache = exit.value
        closed = isinstance(exit, Failure) and exit.cause.has_interrupts_only
        result.done_unsafe(self._closed_exit if closed else exit)

    def _refresh(
        self, now: float, stale: _Snapshot | None = None
    ) -> Effect[_Snapshot | None, JoseError]:
        """``None`` while cooling down, which applies only to unknown-key
        refetches (``stale`` lacked the key) and retries after a failure."""

        def start(restore: Restore) -> Effect[_Snapshot | None, JoseError]:
            if self._closed:
                return from_exit(self._closed_exit)
            cache, pending = self._cache, self._pending
            if cache is not None and cache is not stale and cache.expires_at > now:
                return succeed(cache)
            if pending is not None:
                return restore(pending.wait())
            cooling = now - self._last_attempt < self._options.cooldown
            if (stale is not None or self._last_failed) and cooling:
                return succeed(None)
            self._last_attempt = now
            result = Deferred[_Snapshot, JoseError]()
            self._pending = result
            return (
                self._fetch()
                .on_exit(lambda exit: sync(lambda: self._settle(result, exit)))
                .fork_in(self._scope)
                .flat_map(lambda _fiber: restore(result.wait()))
            )

        return uninterruptible_mask(lambda restore: suspend(lambda: start(restore)))

    def _resolve_at(self, now: float, selection: Selection) -> Effect[PublicKey, JoseError]:
        if self._closed:
            return from_exit(self._closed_exit)

        def lookup(snapshot: _Snapshot) -> Effect[PublicKey, JoseError]:
            return _import_key(_candidates(snapshot.keys, selection), selection.algorithm)

        current = self._cache
        if current is not None and current.expires_at > now:
            found = _candidates(current.keys, selection)
            if found:
                return _import_key(found, selection.algorithm)
            # An unknown key may have been rotated in. Refetch, unless cooling down.
            return self._refresh(now, current).flat_map(
                lambda snapshot: (
                    fail_reason(KeyNotFound()) if snapshot is None else lookup(snapshot)
                )
            )
        return self._refresh(now).flat_map(
            lambda snapshot: (
                fail(_unavailable("The key set is cooling down after a failed fetch"))
                if snapshot is None
                else lookup(snapshot)
            )
        )

    def resolve(self, selection: Selection) -> Effect[PublicKey, JoseError]:
        return current_time_millis().flat_map(lambda now: self._resolve_at(now, selection))


def make_remote(
    url: str,
    *,
    time_to_live: DurationInput = "10 minutes",
    cooldown: DurationInput = "30 seconds",
    timeout: DurationInput = "5 seconds",
    max_response_bytes: int = 131072,
    max_keys: int = 64,
) -> Effect[JwksService, JoseError, HttpClient | Scope]:
    """A ``Jwks`` service over the key set at the HTTPS ``url``, fetched on
    first use. Fetches run in the current scope and stop when it closes.

    ``time_to_live`` is how long a fetched set is used (default 10
    minutes); ``cooldown`` the least time between refetches for unknown
    keys and retries after a failure (30 seconds); ``timeout`` bounds each
    fetch (5 seconds); ``max_response_bytes`` (128 KiB) and ``max_keys``
    (64) bound the document."""

    @gen
    def body():
        options = _Options(
            href=(yield from _read_url(url)).href,
            time_to_live=(yield from _positive_millis("timeToLive", time_to_live)),
            cooldown=(yield from millis("cooldown", cooldown)),
            timeout=(yield from _positive_millis("timeout", timeout)),
            max_response_bytes=(
                yield from _positive_integer("maxResponseBytes", max_response_bytes)
            ),
            max_keys=(yield from _positive_integer("maxKeys", max_keys)),
        )
        client = (yield from HttpClient()).with_scope()
        scope = yield from Scope()
        remote = _Remote(options, client, scope)
        yield from scope.add_finalizer(lambda _exit: sync(remote.close))
        return JwksService(remote.resolve)

    return body


def layer_remote(
    url: str,
    *,
    time_to_live: DurationInput = "10 minutes",
    cooldown: DurationInput = "30 seconds",
    timeout: DurationInput = "5 seconds",
    max_response_bytes: int = 131072,
    max_keys: int = 64,
) -> Layer[Jwks, JoseError, HttpClient]:
    """``make_remote`` as a layer; fetches stop when the layer's scope closes."""
    return layer_effect(
        Jwks,
        make_remote(
            url,
            time_to_live=time_to_live,
            cooldown=cooldown,
            timeout=timeout,
            max_response_bytes=max_response_bytes,
            max_keys=max_keys,
        ),
    )


__all__ = [
    "JoseError",
    "Jwks",
    "JwksService",
    "KeySet",
    "KeySetSchema",
    "Selection",
    "layer_local",
    "layer_remote",
    "make_local",
    "make_remote",
]
