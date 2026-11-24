"""Inbound Teams requests are untrusted. The messaging endpoint answers every
malformed body, header and token with a 4xx before a handler sees it, and
never with a defect: ``alg: none``, an HMAC token made with the public key,
the wrong issuer or audience, an expired token past the skew, a key not
endorsed for Teams, and a key set that names another host."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from _teams_fake import APP_ID, SERVICE_URL, Gen, activity, crypto, setup

import pyfect as fx
from pyfect import testing


def _segment(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _claims(**overrides: object) -> dict[str, object]:
    return {
        "iss": "https://api.botframework.com",
        "aud": APP_ID,
        "exp": int(time.time()) + 600,
        "serviceurl": SERVICE_URL,
        **overrides,
    }


def _forged(header: dict[str, Any], claims: dict[str, object], key: bytes = b"") -> str:
    signing_input = f"{_segment(header)}.{_segment(claims)}"
    if header.get("alg") == "none":
        return f"{signing_input}."
    tag = hmac.new(key, signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{base64.urlsafe_b64encode(tag).rstrip(b'=').decode()}"


@testing.live
def test_refuses_alg_none_and_an_hmac_token_keyed_with_the_public_key():
    """refuses alg none and an HMAC token keyed with the public key"""

    @fx.gen
    def program() -> Gen[None]:
        endpoint = yield from setup()
        assert endpoint.bot.key_pair is not None
        public = json.dumps(endpoint.bot.key_pair.public_key).encode()
        none = _forged({"alg": "none", "kid": "k1"}, _claims())
        confused = _forged({"alg": "HS256", "kid": "k1"}, _claims(), public)
        for token in (none, confused):
            assert (yield from endpoint.send(activity(), f"Bearer {token}")) == 403
        assert endpoint.events == []

    return fx.scoped(program).pipe(fx.provide(crypto))


@testing.live
def test_refuses_the_wrong_issuer_or_audience_and_a_token_expired_past_the_skew():
    """refuses the wrong issuer or audience, and a token expired past the skew"""

    @fx.gen
    def program() -> Gen[None]:
        endpoint = yield from setup()
        now = int(time.time())
        refused: list[dict[str, object]] = [
            {"iss": "https://sts.windows.net/"},
            {"aud": "another-app"},
            {"exp": now - 6 * 60},
            {"nbf": now + 6 * 60},
        ]
        for claims in refused:
            token = yield from endpoint.bot.token(SERVICE_URL, **claims)
            assert (yield from endpoint.send(activity(), f"Bearer {token}")) == 403, claims
        within = yield from endpoint.bot.token(exp=now - 4 * 60)
        assert (yield from endpoint.send(activity(), f"Bearer {within}")) == 200
        assert len(endpoint.events) == 1

    return fx.scoped(program).pipe(fx.provide(crypto))


@testing.live
def test_refuses_a_key_not_endorsed_for_teams():
    """refuses a key not endorsed for Teams"""

    @fx.gen
    def program() -> Gen[None]:
        endpoint = yield from setup()
        endpoint.bot.endorsements = ["skype"]
        token = yield from endpoint.bot.token()
        assert (yield from endpoint.send(activity(), f"Bearer {token}")) == 403
        assert endpoint.events == []

    return fx.scoped(program).pipe(fx.provide(crypto))


@testing.live
def test_refuses_an_oversized_or_malformed_authorization_header_unread():
    """refuses an oversized or malformed Authorization header unread"""

    @fx.gen
    def program() -> Gen[None]:
        endpoint = yield from setup()
        token = yield from endpoint.bot.token()
        for header in (
            f"bearer {token}",
            f"Bearer  {token}",
            f"Bearer {token} ",
            f"Basic {token}",
            "Bearer " + "a" * 17_000,
        ):
            assert (yield from endpoint.send(activity(), header)) == 403
        # Nothing was fetched for a header refused before the token is read.
        assert endpoint.bot.sent == []

    return fx.scoped(program).pipe(fx.provide(crypto))


@testing.live
def test_refuses_another_channel_a_missing_service_url_and_another_tenant():
    """refuses another channel, a missing serviceUrl and another tenant"""

    @fx.gen
    def program() -> Gen[None]:
        endpoint = yield from setup()
        bearer = yield from endpoint.bearer()
        no_service_url = activity()
        del no_service_url["serviceUrl"]
        for body in (
            activity(channelId="skype"),
            no_service_url,
            activity(conversation={"id": "a:direct"}, channelData={"tenant": {"id": "other"}}),
        ):
            assert (yield from endpoint.send(body, bearer)) == 403
        assert endpoint.events == []

    return fx.scoped(program).pipe(fx.provide(crypto))


@testing.live
def test_answers_400_for_a_body_that_is_not_a_json_object_and_for_deep_nesting():
    """answers 400 for a body that is not a JSON object, and for deep nesting"""

    @fx.gen
    def program() -> Gen[None]:
        endpoint = yield from setup()
        bearer = yield from endpoint.bearer()
        for body in ([activity()], "hello", None, 1):
            assert (yield from endpoint.send(body, bearer)) == 400
        depth = 100_000
        nested = json.dumps(activity())[:-1] + ', "entities": ' + "[" * depth + "]" * depth + "}"
        response = yield from endpoint.exchange_text(nested, bearer)
        assert response.status == 400
        invalid = yield from endpoint.exchange_text('{"type": "message", ', bearer)
        assert invalid.status == 400
        assert endpoint.events == []

    return fx.scoped(program).pipe(fx.provide(crypto))


@testing.live
def test_answers_503_for_a_key_set_on_another_host_or_over_http():
    """answers 503 for a key set on another host or over http"""

    @fx.gen
    def program() -> Gen[None]:
        for uri in (
            "https://evil.example/keys",
            "http://login.botframework.com/v1/.well-known/keys",
            "https://login.botframework.com:8443/v1/.well-known/keys",
        ):
            endpoint = yield from setup(jwks_uri=uri)
            assert (yield from endpoint.send(activity(), (yield from endpoint.bearer()))) == 503
            assert not any(sent.url.href.startswith(uri) for sent in endpoint.bot.sent)

    return fx.scoped(program).pipe(fx.provide(crypto))


@testing.live
def test_tries_the_key_set_again_only_after_a_pause():
    """tries the key set again only after a pause"""

    @fx.gen
    def program() -> Gen[None]:
        endpoint = yield from setup(jwks_uri="not a URL")
        bearer = yield from endpoint.bearer()
        for _ in range(3):
            assert (yield from endpoint.send(activity(), bearer)) == 503
        metadata = [
            sent for sent in endpoint.bot.sent if sent.url.pathname.endswith("configuration")
        ]
        assert len(metadata) == 1

    return fx.scoped(program).pipe(fx.provide(crypto))
