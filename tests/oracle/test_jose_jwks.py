"""Ports of Effect's ``jose/Jwks.test.ts``."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, cast

import httpx

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.deferred import Deferred
from pyfect.exit import Failure, void
from pyfect.http import httpx_client
from pyfect.http import response as http_response
from pyfect.http.client import HttpClient, layer_test
from pyfect.http.error import HttpClientError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.jose import jwk, jwks
from pyfect.jose.jose_error import JoseError
from pyfect.jose.jwk import PublicJwk
from pyfect.jose.jwks import Jwks, KeySet, Selection
from pyfect.layer import Layer, provide
from pyfect.scope import CloseableScope

from ._jose import (
    ES256_JWK,
    ES256_PUBLIC_JWK,
    HS256_JWK,
    RS256_PUBLIC_JWK,
    assert_reason,
    layer,
)

EC = cast("PublicJwk", {**ES256_PUBLIC_JWK, "kid": "ec"})
RSA = cast("PublicJwk", {**RS256_PUBLIC_JWK, "kid": "rsa", "alg": "RS256"})
URL = "https://issuer.example/keys"


@testing.effect
def test_selects_a_unique_local_key_by_algorithm_kid_and_metadata():
    """selects a unique local key by algorithm, kid, and metadata"""

    @fx.gen
    def program():
        pair = yield from jwk.generate_key_pair("ES384", kid="ec")
        ec384 = cast("PublicJwk", {k: v for k, v in pair.public_key.items() if k != "alg"})
        key_set: KeySet = {
            "keys": [
                EC,
                ec384,
                RSA,
                # Unsupported families and curves are tolerated but never selected.
                {"kty": "EC", "crv": "P-224", "x": "x", "y": "y", "kid": "ec"},
                {"kty": "OKP", "crv": "X25519", "x": "x"},
            ]
        }
        assert S.is_(jwks.KeySetSchema)(key_set)
        resolver = yield from jwks.make_local(key_set)

        key = yield from resolver.resolve(Selection("ES256", "ec"))
        assert key.kid == "ec"
        assert key.jwk == EC
        assert (yield from resolver.resolve(Selection("ES384", "ec"))).jwk == ec384
        assert (yield from resolver.resolve(Selection("RS256"))).kid == "rsa"

        # Declared ``alg`` excludes the key from other algorithms of its family.
        assert_reason(
            (yield from resolver.resolve(Selection("PS256", "rsa")).flip()), "KeyNotFound"
        )
        assert_reason((yield from resolver.resolve(Selection("EdDSA")).flip()), "KeyNotFound")
        assert_reason(
            (yield from resolver.resolve(Selection("ES256", "missing")).flip()), "KeyNotFound"
        )

        ambiguous = yield from jwks.make_local(
            {"keys": [EC, cast("PublicJwk", {**EC, "kid": "ec2"})]}
        )
        assert_reason((yield from ambiguous.resolve(Selection("ES256")).flip()), "AmbiguousKey")
        assert (yield from ambiguous.resolve(Selection("ES256", "ec2"))).kid == "ec2"

        # Private or symmetric material is never a public key set.
        assert not S.is_(jwks.KeySetSchema)({"keys": [ES256_JWK]})
        assert not S.is_(jwks.KeySetSchema)({"keys": [HS256_JWK]})

    return program.pipe(fx.provide(layer))


type Handler = Callable[[HttpClientRequest], fx.Effect[HttpClientResponse, HttpClientError]]


def serve(
    handler: Callable[[HttpClientRequest], fx.Effect[HttpClientResponse]],
) -> Layer[HttpClient]:
    """An ``HttpClient`` answering every request with ``handler``."""
    return layer_test(handler)


def ok(request: HttpClientRequest, document: object, **options: Any) -> HttpClientResponse:
    return http_response.make(request, json.dumps(document), **options)


@testing.effect
def test_caches_remote_key_sets_coalesces_concurrent_refreshes_and_refreshes_once_for_unknown_kids():  # noqa: E501
    """caches remote key sets, coalesces concurrent refreshes, and refreshes once for unknown kids"""  # noqa: E501
    requests = 0
    document: object = {"keys": [EC]}

    @fx.gen
    def program():
        nonlocal document
        entered = yield from Deferred[None].make()
        release = yield from Deferred[None].make()

        def handler(request: HttpClientRequest) -> fx.Effect[HttpClientResponse]:
            @fx.gen
            def respond():
                nonlocal requests
                requests += 1
                yield from entered.succeed(None)
                yield from release.wait()
                return ok(request, document)

            return respond

        context = (
            yield from jwks.layer_remote(URL, time_to_live="100 millis", cooldown="10 millis")
            .pipe(provide(serve(handler)))
            .build()
        )
        keys = context.get(Jwks)

        # A cold cache admits one request for any number of concurrent callers.
        concurrent = yield from fx.for_each(
            range(12), lambda _: keys.resolve(Selection("ES256", "ec")), concurrency=12
        ).fork()
        yield from entered.wait()
        yield from release.succeed(None)
        assert len((yield from concurrent.join())) == 12
        assert requests == 1

        # An unknown kid refreshes at most once per cooldown, so a flood of
        # unknown kids cannot drive a request per token.
        assert_reason(
            (yield from keys.resolve(Selection("ES256", "rotated")).flip()), "KeyNotFound"
        )
        assert_reason(
            (yield from keys.resolve(Selection("ES256", "rotated")).flip()), "KeyNotFound"
        )
        assert requests == 1

        document = {"keys": [{**EC, "kid": "rotated"}]}
        yield from testing.adjust("11 millis")
        assert (yield from keys.resolve(Selection("ES256", "rotated"))).kid == "rotated"
        assert requests == 2

        # Within the TTL the cache answers without a request.
        yield from testing.adjust("50 millis")
        assert (yield from keys.resolve(Selection("ES256", "rotated"))).kid == "rotated"
        assert requests == 2

        # After the TTL a bad document fails every caller until the cooldown passes.
        document = {"keys": [ES256_JWK]}
        yield from testing.adjust("51 millis")
        assert_reason(
            (yield from keys.resolve(Selection("ES256", "rotated")).flip()), "KeySetUnavailable"
        )
        assert_reason(
            (yield from keys.resolve(Selection("ES256", "rotated")).flip()), "KeySetUnavailable"
        )
        assert requests == 3

        # Once the cooldown passes, a good document recovers.
        document = {"keys": [{**EC, "kid": "rotated"}]}
        yield from testing.adjust("11 millis")
        assert (yield from keys.resolve(Selection("ES256", "rotated"))).kid == "rotated"
        assert requests == 4

    return program.pipe(fx.provide(layer))


@testing.effect
def test_refetches_an_expired_key_set_at_once_when_time_to_live_is_shorter_than_cooldown():
    """refetches an expired key set at once when timeToLive is shorter than cooldown"""
    requests = 0
    status = 500

    def handler(request: HttpClientRequest) -> fx.Effect[HttpClientResponse]:
        def respond() -> HttpClientResponse:
            nonlocal requests
            requests += 1
            return ok(request, {"keys": [EC]}, status=status)

        return fx.sync(respond)

    context = (
        yield from jwks.layer_remote(URL, time_to_live="10 seconds", cooldown="30 seconds")
        .pipe(provide(serve(handler)))
        .build()
    )
    keys = context.get(Jwks)

    # A failed fetch still cools down.
    assert_reason((yield from keys.resolve(Selection("ES256", "ec")).flip()), "KeySetUnavailable")
    status = 200
    yield from testing.adjust("5 seconds")
    assert_reason((yield from keys.resolve(Selection("ES256", "ec")).flip()), "KeySetUnavailable")
    assert requests == 1
    yield from testing.adjust("30 seconds")
    yield from keys.resolve(Selection("ES256", "ec"))
    assert requests == 2

    # A set that expired after a successful fetch is refetched without waiting for the cooldown.
    yield from testing.adjust("15 seconds")
    assert (yield from keys.resolve(Selection("ES256", "ec"))).kid == "ec"
    assert requests == 3

    # Unknown kids still refetch at most once per cooldown.
    assert_reason((yield from keys.resolve(Selection("ES256", "unknown")).flip()), "KeyNotFound")
    assert requests == 3


def _resolve_with(
    client: Layer[HttpClient], url: str = URL, **options: Any
) -> fx.Effect[JoseError, Any, Any]:
    return (
        jwks.layer_remote(url, **options)
        .pipe(provide(client))
        .build()
        .flat_map(lambda context: context.get(Jwks).resolve(Selection("ES256")))
        .flip()
    )


@testing.effect
def test_accepts_only_a_200_document_from_the_configured_https_url():
    """accepts only a 200 document from the configured HTTPS URL"""

    @fx.gen
    def program():
        empty = serve(lambda request: fx.succeed(http_response.make(request, "{}")))
        for bad in (
            "http://issuer.example/keys",
            "https://user:pw@issuer.example/keys",
            "https://issuer.example/keys#frag",
        ):
            assert_reason((yield from _resolve_with(empty, bad)), "InvalidArgument")

        # A client that follows redirects answers from another origin; the body is discarded.
        followed = 0

        def redirect(request: HttpClientRequest) -> fx.Effect[HttpClientResponse]:
            def respond() -> HttpClientResponse:
                nonlocal followed
                followed += 1
                return ok(request, {"keys": [EC]}, url="https://attacker.example/keys")

            return fx.sync(respond)

        assert_reason((yield from _resolve_with(serve(redirect))), "KeySetUnavailable")
        assert followed == 1

        # A client configured not to follow redirects (httpx's default, as
        # ``redirect: "manual"`` for fetch) sends no request past the first
        # hop and keeps its other options. This transport answers like a
        # server redirecting to an internal address.
        sent: list[httpx.Request] = []

        def transport(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            if str(request.url) == URL:
                return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})
            return httpx.Response(200, json={"keys": [EC]})

        configured = httpx_client.layer_with(
            transport=httpx.MockTransport(transport),
            follow_redirects=False,
            headers={"authorization": "Bearer configured"},
        )
        assert_reason((yield from _resolve_with(configured)), "KeySetUnavailable")
        assert [str(request.url) for request in sent] == [URL]
        assert sent[0].headers["authorization"] == "Bearer configured"
        assert sent[0].headers["accept"] == "application/json"

        # A redirect status is a failed response, not a hop.
        moved = serve(
            lambda request: fx.succeed(
                http_response.make(
                    request, None, status=302, headers={"location": "https://attacker.example/keys"}
                )
            )
        )
        assert_reason((yield from _resolve_with(moved)), "KeySetUnavailable")
        failing = serve(lambda request: fx.succeed(http_response.make(request, "{}", status=500)))
        assert_reason((yield from _resolve_with(failing)), "KeySetUnavailable")

        # Response bounds.
        two = serve(lambda request: fx.succeed(ok(request, {"keys": [EC, {**EC, "kid": "ec2"}]})))
        assert_reason((yield from _resolve_with(two, max_response_bytes=40)), "KeySetUnavailable")
        assert_reason((yield from _resolve_with(two, max_keys=1)), "KeySetUnavailable")
        not_json = serve(lambda request: fx.succeed(http_response.make(request, "not json")))
        assert_reason((yield from _resolve_with(not_json)), "KeySetUnavailable")

    return program.pipe(fx.provide(layer))


@testing.effect
def test_times_out_refreshes_and_interrupts_in_flight_requests_when_the_layer_scope_closes():
    """times out refreshes and interrupts in-flight requests when the layer scope closes"""
    interrupted = 0
    started: Deferred[None] = Deferred()

    def handler(_request: HttpClientRequest) -> fx.Effect[HttpClientResponse]:
        def count() -> None:
            nonlocal interrupted
            interrupted += 1

        return started.succeed(None).flat_map(lambda _: fx.never).on_interrupt(fx.sync(count))

    @fx.gen
    def program():
        nonlocal started
        scope = yield from fx.acquire_release(
            fx.sync(CloseableScope), lambda scope, _exit: scope.close(void)
        )
        context = yield from (
            jwks.layer_remote(URL, timeout="10 millis", cooldown="1 millis")
            .pipe(provide(serve(handler)))
            .build_with_scope(scope)
        )
        keys = context.get(Jwks)

        first = yield from keys.resolve(Selection("ES256")).flip().fork()
        yield from started.wait()
        yield from testing.adjust("10 millis")
        assert_reason((yield from first.join()), "KeySetUnavailable")
        assert interrupted == 1

        yield from testing.adjust("2 millis")
        started = Deferred()
        second = yield from keys.resolve(Selection("ES256")).fork()
        yield from started.wait()
        yield from scope.close(void)
        assert isinstance((yield from second.await_exit()), Failure)
        assert interrupted == 2
        assert_reason((yield from keys.resolve(Selection("ES256")).flip()), "KeySetUnavailable")

    return program.pipe(fx.provide(layer))


@testing.effect
def test_imports_each_resolved_key_for_the_selected_algorithm():
    """imports each resolved key for the selected algorithm"""
    rsa = cast("PublicJwk", {**RS256_PUBLIC_JWK, "kid": "rsa"})
    resolver = yield from jwks.make_local({"keys": [rsa]})
    rs = yield from resolver.resolve(Selection("RS256", "rsa"))
    ps = yield from resolver.resolve(Selection("PS256", "rsa"))
    assert rs.algorithm == "RS256"
    assert ps.algorithm == "PS256"
    assert ps.jwk == rsa
