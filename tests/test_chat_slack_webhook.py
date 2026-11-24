"""Port of Effect's ``packages/chat/slack/test/webhook.test.ts``: the Events API
route checks Slack's ``v0`` signature before anything else, bounds the body
and the whole request, and answers so Slack retries what it should."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable, Generator
from typing import Any, Never

from _slack_fake import APP_ID, AUTH_TEST, BOT_USER_ID, TEAM, Fake, message_envelope, unix_now

import pyfect as fx
from pyfect import layer, testing
from pyfect._core import Effect
from pyfect.byte_size import ByteSize
from pyfect.chat import chat
from pyfect.chat.chat_error import ChatError, PlatformUnavailable
from pyfect.chat.chat_event import ChatEvent
from pyfect.chat.chat_handler import ChatHandler, NotAccepted
from pyfect.chat.chat_handler import Service as HandlerService
from pyfect.chat.slack import _webhook, slack_chat
from pyfect.crypto import mac as _mac
from pyfect.crypto.crypto_error import CryptoError, InvalidKey
from pyfect.crypto.native import layer_mac
from pyfect.duration import Duration, millis, seconds
from pyfect.http import body as http_body
from pyfect.http import request as http_request
from pyfect.http import router, server_request
from pyfect.http.server_request import ServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.redacted import make as redacted

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]

SECRET = "8f742231b10e8888abcd99yyyzzz85a5"
MESSAGE = message_envelope(
    {"ts": "1794509003.000001", "user": "U080YLYB277", "text": "hi <@U0CCLMD4S1L>"}
)
UNAVAILABLE = ChatError(
    platform="slack", op="auth.test", reason=PlatformUnavailable(retry="retry", detail="http_503")
)


def sign(timestamp: str, body: str, key: str = SECRET) -> str:
    digest = hmac.new(key.encode(), f"v0:{timestamp}:{body}".encode(), hashlib.sha256)
    return "v0=" + digest.hexdigest()


def now() -> str:
    return unix_now()


def signed_headers(body: str, *, timestamp: str | None = None, key: str = SECRET) -> dict[str, str]:
    stamp = now() if timestamp is None else timestamp
    return {
        "content-type": "application/json",
        "x-slack-request-timestamp": stamp,
        "x-slack-signature": sign(stamp, body, key),
    }


def request(body: str, headers: dict[str, str] | None = None) -> ServerRequest:
    client_request = http_request.post(
        "http://localhost/slack/events",
        headers=signed_headers(body) if headers is None else headers,
    ).body_text(body, "application/json")
    return server_request.from_client_request(client_request)


BOT: Effect[str, ChatError] = fx.succeed(BOT_USER_ID)
TWO_SECONDS = seconds(2)
ONE_MIB = ByteSize(1024 * 1024)


def _record(events: list[ChatEvent]) -> Callable[[ChatEvent], Effect[None, NotAccepted]]:
    return lambda event: fx.sync(lambda: events.append(event))


def handle(
    web: ServerRequest,
    *,
    bot_user_id: Effect[str, ChatError] = BOT,
    on_event: Callable[[ChatEvent], Effect[None, NotAccepted]] | None = None,
    deadline: Duration = TWO_SECONDS,
    max_body_size: ByteSize = ONE_MIB,
) -> Effect[tuple[int, HttpServerResponse, list[ChatEvent]], Any]:
    @fx.gen
    def run() -> Gen[tuple[int, HttpServerResponse, list[ChatEvent]]]:
        verify = yield from _webhook.make_verifier(redacted(SECRET)).pipe(fx.provide(layer_mac))
        events: list[ChatEvent] = []
        response = yield from _webhook.handle_request(
            web,
            _webhook.Options(
                verify=verify,
                app_id=APP_ID,
                team_id=TEAM,
                bot_user_id=bot_user_id,
                handle=_record(events) if on_event is None else on_event,
                deadline=deadline,
                max_body_size=max_body_size,
            ),
        )
        return response.status, response, events

    return run


@testing.live
def test_rejects_a_bad_stale_or_missing_signature():
    """webhook / rejects a bad, stale or missing signature"""

    @fx.gen
    def program() -> Gen[None]:
        body = json.dumps(MESSAGE)
        wrong_key = yield from handle(request(body, signed_headers(body, key="other")))
        assert wrong_key[0] == 401
        stale = unix_now(-6 * 60)
        old = yield from handle(request(body, signed_headers(body, timestamp=stale)))
        assert old[0] == 401
        unsigned = yield from handle(request(body, {}))
        assert unsigned[0] == 401
        malformed = {**signed_headers(body), "x-slack-signature": "v0=gg"}
        assert (yield from handle(request(body, malformed)))[0] == 401
        assert len(wrong_key[2]) + len(old[2]) + len(unsigned[2]) == 0

    return program


@testing.live
def test_413_past_the_body_limit_also_for_a_body_read_earlier_under_a_larger_limit():
    """webhook / 413 past the body limit, also for a body read earlier under a larger limit"""

    @fx.gen
    def program() -> Gen[None]:
        limit = ByteSize(100)
        big = yield from handle(request("x" * 101), max_body_size=limit)
        assert big[0] == 413
        # Middleware read this signed event first; the request caches what it read.
        cached = request(json.dumps(MESSAGE))
        assert len((yield from cached.bytes_)) > 100
        result = yield from handle(cached, max_body_size=limit)
        assert (result[0], len(result[2])) == (413, 0)

    return program


@testing.live
def test_answers_url_verification_with_its_challenge():
    """webhook / answers url_verification with its challenge"""

    @fx.gen
    def program() -> Gen[None]:
        challenge = "3eZbrw1aBm2rZgRNFdxV2595E9CY3gmdALWMmHkvFXO7tYXAYM8P"
        body = json.dumps({"token": "t", "challenge": challenge, "type": "url_verification"})
        status, response, _ = yield from handle(request(body))
        assert status == 200
        assert isinstance(response.body, http_body.Bytes)
        assert response.body.body.decode() == challenge

    return program


@testing.live
def test_drops_another_apps_event_with_200():
    """webhook / drops another app's event with 200"""

    @fx.gen
    def program() -> Gen[None]:
        status, _, events = yield from handle(
            request(json.dumps({**MESSAGE, "api_app_id": "A0OTHER"}))
        )
        assert status == 200
        assert events == []

    return program


@testing.live
def test_503_so_slack_retries_no_bot_user_not_accepted_past_the_deadline():
    """webhook / 503 so Slack retries: no bot user, NotAccepted, past the deadline"""

    @fx.gen
    def program() -> Gen[None]:
        body = json.dumps(MESSAGE)
        no_bot = yield from handle(request(body), bot_user_id=fx.fail(UNAVAILABLE))
        refused = yield from handle(request(body), on_event=lambda _: fx.fail(NotAccepted()))
        slow = yield from handle(request(body), on_event=lambda _: fx.never, deadline=millis(20))
        assert [no_bot[0], refused[0], slow[0]] == [503, 503, 503]
        assert no_bot[2] == []

    return program


@testing.live
def test_the_deadline_covers_the_bot_user_lookup():
    """webhook / the deadline covers the bot user lookup"""

    @fx.gen
    def program() -> Gen[None]:
        slow_bot = yield from handle(
            request(json.dumps(MESSAGE)), bot_user_id=fx.never, deadline=millis(20)
        )
        assert slow_bot[0] == 503
        assert slow_bot[2] == []

    return program


def _app(
    mac: layer.Layer[Any], events: list[ChatEvent], fake: Fake, **options: Any
) -> layer.Layer[Any]:
    handler = HandlerService(lambda event: fx.sync(lambda: events.append(event)))
    return (
        slack_chat.layer_webhook(
            path="/slack/events", signing_secret=redacted(SECRET), app_id=APP_ID, **options
        )
        .pipe(
            layer.provide(
                slack_chat.layer(bot_token=redacted("xoxb-test"), team_id=TEAM)
                .pipe(layer.provide(chat.layer))
                .pipe(layer.provide(fake.layer))
            )
        )
        .pipe(layer.provide(layer.merge(mac, layer.succeed(ChatHandler, handler))))
    )


@testing.effect
def test_layer_webhook_bounds_a_request_whose_body_never_finishes():
    """webhook / layerWebhook bounds a request whose body never finishes"""

    @fx.gen
    def program() -> Gen[None]:
        events: list[ChatEvent] = []
        app = _app(layer_mac, events, Fake({"auth.test": AUTH_TEST}), deadline="2 seconds")
        http = yield from router.in_memory_client(app)
        sent = http.post(
            "http://localhost/slack/events",
            body=http_request.post("http://localhost").body_stream(fx.stream.never).body,
            headers={"x-slack-request-timestamp": "0", "x-slack-signature": "v0=" + "0" * 64},
        )
        fiber = yield from sent.fork()
        yield from testing.adjust("2 seconds")
        response = yield from fiber.join()
        assert response.status == 503
        assert events == []

    return fx.scoped(program)


def _unused(*_: object) -> Effect[Never, CryptoError]:
    return fx.die("unused")


@testing.live
def test_layer_webhook_uses_the_supplied_mac_and_fails_closed_on_crypto_errors():
    """webhook / layerWebhook uses the supplied Mac and fails closed on crypto errors"""
    events: list[ChatEvent] = []
    failing = [False]

    def verify(key: _mac.Key[Any], tag: object, data: object) -> Effect[bool, CryptoError]:
        assert key.algorithm is _mac.hmac_sha256
        if failing[0]:
            return fx.fail(
                CryptoError(
                    module="Mac", method="verify", reason=InvalidKey(description="test failure")
                )
            )
        return fx.succeed(True)

    mac = layer.succeed(
        _mac.Mac,
        _mac.MacService(
            generate_key=_unused,
            sign=_unused,
            verify=verify,
        ),
    )

    @fx.gen
    def program() -> Gen[None]:
        http = yield from router.in_memory_client(_app(mac, events, Fake({"auth.test": AUTH_TEST})))
        body = json.dumps(MESSAGE)
        headers = {**signed_headers(body), "x-slack-signature": "v0=abcd"}

        def send() -> Effect[Any, Any]:
            return http.post(
                "http://localhost/slack/events",
                body=http_request.post("http://x").body_text(body, "application/json").body,
                headers=headers,
            )

        response = yield from send()
        failing[0] = True
        assert (yield from send()).status == 401
        assert response.status == 200
        assert len(events) == 1

    return fx.scoped(program)
