"""A stubbed Bot Framework for the Teams adapter's tests (Effect's
``chat/teams/test`` helpers): a Connector that keeps the activities the
adapter posts, Entra's token endpoint, and the OpenID metadata and key set
inbound tokens are checked against, signed by a key made per test. Nothing
here reaches the network."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass, field
from typing import Any, TypedDict, cast
from urllib.parse import unquote

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect._core import Effect
from pyfect._url import Url
from pyfect.chat import chat
from pyfect.chat import chat_interaction as ci
from pyfect.chat.chat_event import ChatEvent
from pyfect.chat.chat_handler import ChatHandler
from pyfect.chat.chat_handler import Service as HandlerService
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.teams import teams_chat
from pyfect.crypto.native import layer_digest, layer_mac, layer_signature
from pyfect.http import body as http_body
from pyfect.http import client, router
from pyfect.http import request as http_request
from pyfect.http import response as http_response
from pyfect.http.httpx_client import FollowRedirects
from pyfect.http.request import HttpClientRequest
from pyfect.http.server_request import HttpServerRequest
from pyfect.jose import jwk, jwt
from pyfect.jose.jwk import KeyPair, PrivateKey, SecretJwk
from pyfect.redacted import Redacted
from pyfect.redacted import make as redacted
from pyfect.redacted import value as redacted_value

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]

APP_ID = "00000000-0000-0000-0000-0000000000a1"
TENANT_ID = "00000000-0000-0000-0000-0000000000b2"
SERVICE_URL = "https://smba.trafficmanager.net/emea/"
METADATA_URL = "https://login.botframework.com/v1/.well-known/openidconfiguration"
KEYS_URL = "https://login.botframework.com/v1/.well-known/keys"
CONVERSATION = "19:conformance@thread.tacv2"

INTERACTION_KEY: Redacted[SecretJwk] = redacted(
    {"kty": "oct", "kid": "k1", "k": "BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc"}
)
OTHER_KEY: Redacted[SecretJwk] = redacted(
    {"kty": "oct", "kid": "k2", "k": "CAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"}
)

crypto = layer.merge(layer.merge(layer_mac, layer_digest), layer_signature)


def activity(**overrides: object) -> dict[str, Any]:
    """A message in a direct conversation, as Teams delivers it."""
    return {
        "type": "message",
        "id": "1800000000001",
        "timestamp": "2026-11-15T10:00:00.000Z",
        "serviceUrl": SERVICE_URL,
        "channelId": "msteams",
        "from": {"id": "29:user", "aadObjectId": "user", "name": "User"},
        "recipient": {"id": f"28:{APP_ID}", "name": "Bot"},
        "conversation": {"id": "a:direct", "conversationType": "personal", "tenantId": TENANT_ID},
        "channelData": {"tenant": {"id": TENANT_ID}},
        "text": "hello",
        **overrides,
    }


@dataclass(frozen=True)
class Sent:
    """One request the adapter sent: where, its body, whether redirects were
    on, and its bearer token."""

    method: str
    url: Url
    body: str
    follow_redirects: bool | None
    authorization: str | None


def _text(request: HttpClientRequest) -> str:
    body = request.body
    return body.body.decode("utf-8") if isinstance(body, http_body.Bytes) else ""


@dataclass
class Bot:
    """The stubbed Bot Framework and what was sent to it. ``key_pair`` signs
    inbound tokens; the key set serves its public key endorsed for
    ``msteams``. ``jwks_uri`` is what the metadata names."""

    key_pair: KeyPair | None = None
    jwks_uri: str = KEYS_URL
    endorsements: list[str] = field(default_factory=lambda: ["msteams"])
    sent: list[Sent] = field(default_factory=list[Sent])
    posted: set[str] = field(default_factory=set[str])
    answers: dict[str, Callable[[Sent], tuple[int, object]]] = field(
        default_factory=dict[str, Callable[[Sent], tuple[int, object]]]
    )
    _next: int = 1_700_000_000_000

    def _answer(self, sent: Sent) -> tuple[int, object]:  # noqa: PLR0911
        url = sent.url
        override = self.answers.get(url.href)
        if override is not None:
            return override(sent)
        if url.hostname == "login.microsoftonline.com":
            return 200, {"access_token": "token", "expires_in": 3600, "token_type": "Bearer"}
        if url.href == METADATA_URL:
            return 200, {"jwks_uri": self.jwks_uri}
        if url.href == KEYS_URL:
            assert self.key_pair is not None
            public = {**self.key_pair.public_key, "endorsements": self.endorsements}
            return 200, {"keys": [public]}
        if sent.method == "POST":
            id = str(self._next)
            self._next += 1
            self.posted.add(id)
            return 200, {"id": id}
        if sent.method in ("PUT", "DELETE"):
            id = unquote(url.pathname.rsplit("/", 1)[-1])
            known = id in self.posted
            if sent.method == "DELETE":
                self.posted.discard(id)
            return (200, {}) if known else (404, {"error": {"code": "ActivityNotFound"}})
        if "/members/" in url.pathname:
            return 200, {"id": "29:user", "aadObjectId": "user", "name": "User"}
        return 200, {"members": []}

    @property
    def http(self) -> client.HttpClientService[Any]:
        def send(request: HttpClientRequest, url: Url, _signal: object, fiber: Any) -> Effect[Any]:
            def answer() -> Any:
                sent = Sent(
                    request.method,
                    url,
                    _text(request),
                    fiber.get_ref(FollowRedirects),
                    request.headers.get("authorization"),
                )
                self.sent.append(sent)
                status, body = self._answer(sent)
                # As Fetch does: the response names the URL it came from, query included.
                return http_response.make(
                    request,
                    json.dumps(body),
                    status=status,
                    headers={"content-type": "application/json"},
                    url=url.href,
                )

            return fx.sync(answer)

        return client.make(send)

    @property
    def layer(self) -> layer.Layer[client.HttpClient]:
        return layer.succeed(client.HttpClient, self.http)

    def token(self, claimed: str = SERVICE_URL, **claims: object) -> Effect[str, Any, Any]:
        """A Bot Framework token for the app, valid for ten minutes, signed
        by this bot's key."""
        assert self.key_pair is not None
        pair = self.key_pair

        @fx.gen
        def run() -> Gen[str]:
            key: PrivateKey = yield from jwk.import_private(pair.private_key, "RS256")
            body: dict[str, object] = {
                "iss": "https://api.botframework.com",
                "aud": APP_ID,
                "exp": int(time.time()) + 600,
                "serviceurl": claimed,
                **claims,
            }
            signed = yield from jwt.sign(_CLAIMS, cast("_Claims", body), key, {"kid": "k1"})
            return redacted_value(signed)

        return run


class _Claims(TypedDict, total=False):
    iss: str
    aud: str
    exp: int
    nbf: int
    serviceurl: str


_CLAIMS = S.Struct(_Claims)


def make_bot(**options: Any) -> Effect[Bot, Any, Any]:
    """A bot with a fresh RS256 key pair, kid ``k1``."""
    return jwk.generate_key_pair("RS256", kid="k1").map(lambda pair: Bot(key_pair=pair, **options))


def teams_layer(bot: Bot, **options: Any) -> layer.Layer[Any, Any, Any]:
    """``Chat``, ``Registry`` and the Teams adapter over the stub, with the
    crypto it needs."""
    return (
        teams_chat.layer(
            app_id=APP_ID, tenant_id=TENANT_ID, credentials=redacted("secret"), **options
        )
        .pipe(layer.provide_merge(chat.layer))
        .pipe(layer.provide(bot.layer))
        .pipe(layer.provide(crypto))
    )


_sequence = [0]


def user_posts(at: ChatThread, text: str) -> Effect[ChatEvent]:
    """A user's message in ``at``, through the public normaliser."""

    def make() -> ChatEvent:
        parts = teams_chat.parts(at)
        id = str(1_800_000_000_000 + _sequence[0])
        _sequence[0] += 1
        events = teams_chat.normalize(
            activity(
                id=id,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                serviceUrl="https://smba.trafficmanager.net/teams",
                conversation={
                    "id": CONVERSATION if parts is None else parts.conversation_id,
                    "conversationType": "channel",
                    "tenantId": TENANT_ID,
                },
                textFormat="plain",
                text=text,
            ),
            app_id=APP_ID,
        )
        return events[0]

    return fx.sync(make)


def json_of(text: str) -> Mapping[str, Any]:
    return cast("Mapping[str, Any]", json.loads(text))


@dataclass
class Endpoint:
    bot: Bot
    http: client.HttpClientService[Any]
    events: list[ChatEvent]

    def exchange(self, body: object, authorization: str | None = None) -> Effect[Any, Any]:
        return self.exchange_text(json.dumps(body), authorization)

    def exchange_text(self, text: str, authorization: str | None = None) -> Effect[Any, Any]:
        headers = {} if authorization is None else {"authorization": authorization}
        return self.http.post(
            "http://localhost/api/messages",
            body=http_request.post("http://x").body_text(text, "application/json").body,
            headers=headers,
        )

    def send(self, body: object, authorization: str | None = None) -> Effect[int, Any]:
        return self.exchange(body, authorization).map(lambda response: response.status)

    def bearer(self, claimed: str | None = None) -> Effect[str, Any, Any]:
        token = self.bot.token() if claimed is None else self.bot.token(claimed)
        return token.map(lambda value: f"Bearer {value}")


def _read_first(http_effect: Effect[Any, Any, Any]) -> Effect[Any, Any, Any]:
    return (
        HttpServerRequest().flat_map(lambda request: request.bytes_).or_die().and_then(http_effect)
    )


def setup(
    *,
    jwks_uri: str = KEYS_URL,
    teams: dict[str, Any] | None = None,
    interactions: ci.HandlerService | None = None,
    max_body_bytes: int = 1024 * 1024,
    read_first: bool = False,
) -> Effect[Endpoint, Any, Any]:
    @fx.gen
    def run() -> Gen[Endpoint]:
        bot = yield from make_bot(jwks_uri=jwks_uri)
        events: list[ChatEvent] = []
        handler = HandlerService(lambda event: fx.sync(lambda: events.append(event)))
        app = teams_chat.layer_webhook(path="/api/messages", max_body_bytes=max_body_bytes)
        if read_first:
            app = layer.merge(app, router.middleware(_read_first, global_=True))
        services = layer.succeed(ChatHandler, handler)
        if interactions is not None:
            services = layer.merge(services, layer.succeed(ci.Handler, interactions))
        app = (
            app.pipe(layer.provide(teams_layer(bot, **(teams or {}))))
            .pipe(layer.provide(services))
            .pipe(layer.provide(layer.merge(bot.layer, crypto)))
        )
        http = yield from router.in_memory_client(app)
        return Endpoint(bot, http, events)

    return run
