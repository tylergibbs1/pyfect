"""Inbound Slack requests are untrusted. The Events API and Interactivity
routes answer every malformed signature, timestamp, body and payload with a
4xx before a handler sees it, and never with a defect, and the rich text an
attacker controls renders in bounded time and size."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable, Generator
from typing import Any

import pytest
from _slack_fake import APP_ID, BOT_USER_ID, TEAM, message_envelope, unix_now

import pyfect as fx
from pyfect._core import Effect
from pyfect.byte_size import ByteSize
from pyfect.chat.chat_event import ChatEvent, MessageCreated
from pyfect.chat.slack import _webhook, slack_chat
from pyfect.chat.slack._interactions import Body
from pyfect.crypto.native import layer_mac
from pyfect.duration import Duration, seconds
from pyfect.exit import Success
from pyfect.http import request as http_request
from pyfect.http import server_request
from pyfect.redacted import make as redacted

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]

SECRET = "security-test-signing-secret"
LIMIT = 64 * 1024
EVENT = json.dumps(
    message_envelope({"ts": "1794509003.000001", "user": "U080YLYB277", "text": "hi"})
)


def sign(timestamp: str, body: bytes, key: str = SECRET) -> str:
    digest = hmac.new(key.encode(), f"v0:{timestamp}:".encode() + body, hashlib.sha256)
    return "v0=" + digest.hexdigest()


def now() -> str:
    return unix_now()


def headers(body: bytes, **overrides: str | None) -> dict[str, str]:
    stamp = now()
    found: dict[str, str | None] = {
        "content-type": "application/json",
        "x-slack-request-timestamp": stamp,
        "x-slack-signature": sign(stamp, body),
        **overrides,
    }
    return {key: value for key, value in found.items() if value is not None}


def _request(body: bytes, sent: dict[str, str]) -> server_request.ServerRequest:
    client = http_request.post("http://localhost/slack", headers=sent).body_bytes(
        body, sent.get("content-type", "application/octet-stream")
    )
    return server_request.from_client_request(client)


def events_status(body: bytes, sent: dict[str, str] | None = None) -> tuple[int, list[ChatEvent]]:
    """The Events API route's status for one request, and what reached the handler."""
    events: list[ChatEvent] = []

    @fx.gen
    def run() -> Gen[int]:
        verify = yield from _webhook.make_verifier(redacted(SECRET)).pipe(fx.provide(layer_mac))
        response = yield from _webhook.handle_request(
            _request(body, headers(body) if sent is None else sent),
            _webhook.Options(
                verify=verify,
                app_id=APP_ID,
                team_id=TEAM,
                bot_user_id=fx.succeed(BOT_USER_ID),
                handle=lambda event: fx.sync(lambda: events.append(event)),
                deadline=seconds(5),
                max_body_size=ByteSize(LIMIT),
            ),
        )
        return response.status

    exit = fx.run_blocking_exit(run)
    assert isinstance(exit, Success), exit
    return exit.value, events


def interactivity_status(
    body: bytes, sent: dict[str, str] | None = None
) -> tuple[int, list[object]]:
    """The Interactivity route's status for one request, and what reached the handler."""
    payloads: list[object] = []

    def interaction(payload: object, _: Duration) -> Effect[Body]:
        return fx.sync(lambda: payloads.append(payload)).as_(None)

    @fx.gen
    def run() -> Gen[int]:
        verify = yield from _webhook.make_verifier(redacted(SECRET)).pipe(fx.provide(layer_mac))
        form_headers = headers(body, **{"content-type": "application/x-www-form-urlencoded"})
        response = yield from _webhook.handle_interactivity(
            _request(body, form_headers if sent is None else sent),
            _webhook.InteractivityOptions(
                verify=verify,
                app_id=APP_ID,
                interaction=interaction,
                deadline=seconds(5),
                max_body_size=ByteSize(LIMIT),
            ),
        )
        return response.status

    exit = fx.run_blocking_exit(run)
    assert isinstance(exit, Success), exit
    return exit.value, payloads


def test_a_signed_event_reaches_the_handler() -> None:
    status, events = events_status(EVENT.encode())
    assert status == 200
    assert [type(event) for event in events] == [MessageCreated]


BODY = EVENT.encode()


def _valid(timestamp: str) -> str:
    """The right signature's hex for ``timestamp``, which each case below breaks."""
    return sign(timestamp, BODY)[3:]


# Each signature is made when its test runs, over the timestamp the request
# carries, so a case fails only for what it changes.
_BAD_SIGNATURES: dict[str, Callable[[str], str | None]] = {
    "missing": lambda _: None,
    "empty": lambda _: "",
    "another key": lambda stamp: sign(stamp, BODY, "other-secret"),
    "another version": lambda stamp: "v1=" + _valid(stamp),
    "no prefix": _valid,
    "non-hex": lambda _: "v0=" + "zz" * 32,
    "odd length": lambda stamp: "v0=" + _valid(stamp)[:-1],
    "spaced hex": lambda stamp: "v0=" + " ".join(_valid(stamp)[i : i + 2] for i in range(0, 64, 2)),
    "a trailing newline": lambda stamp: "v0=" + _valid(stamp) + "\n",
    "full-width digits": lambda _: "v0=" + "\uff10" * 64,
    "truncated": lambda stamp: "v0=" + _valid(stamp)[:32],
    "prefix only": lambda _: "v0=",
}


@pytest.mark.parametrize("name", list(_BAD_SIGNATURES))
def test_a_bad_or_missing_signature_is_401(name: str) -> None:
    stamp = now()
    signature = _BAD_SIGNATURES[name](stamp)
    sent = headers(BODY, **{"x-slack-request-timestamp": stamp, "x-slack-signature": signature})
    status, events = events_status(BODY, sent)
    assert (status, events) == (401, []), name


def _signed_at(timestamp: str) -> dict[str, str]:
    return headers(
        BODY, **{"x-slack-request-timestamp": timestamp, "x-slack-signature": sign(timestamp, BODY)}
    )


# Each timestamp is made when its test runs, so time spent before (collection,
# a busy machine) cannot move it back inside the window.
_BAD_TIMESTAMPS: dict[str, Callable[[], str]] = {
    "six minutes old": lambda: unix_now(-6 * 60),
    "six minutes ahead": lambda: unix_now(6 * 60),
    "zero": lambda: "0",
    "twenty digits": lambda: "9" * 20,
    "past twenty digits": lambda: "9" * 4_000,
    "negative": lambda: "-" + now(),
    "plus sign": lambda: "+" + now(),
    "spaced": lambda: " " + now(),
    "fractional": lambda: now() + ".5",
    "non-digit": lambda: now() + "a",
    "Arabic-Indic digits": lambda: now().translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")),
    "underscore": lambda: now()[:4] + "_" + now()[4:],
    "empty": lambda: "",
}


@pytest.mark.parametrize("name", list(_BAD_TIMESTAMPS))
def test_a_timestamp_past_the_skew_or_not_whole_ascii_seconds_is_401(name: str) -> None:
    # Signed correctly over the bad timestamp: only the timestamp check can refuse it.
    status, events = events_status(BODY, _signed_at(_BAD_TIMESTAMPS[name]()))
    assert (status, events) == (401, []), name


def test_a_missing_timestamp_is_401() -> None:
    status, _ = events_status(BODY, headers(BODY, **{"x-slack-request-timestamp": None}))
    assert status == 401


def test_a_body_over_the_limit_is_413_before_the_signature_is_checked() -> None:
    big = b"x" * (LIMIT + 1)
    assert events_status(big, {})[0] == 413
    assert events_status(big)[0] == 413
    assert interactivity_status(big, {})[0] == 413
    assert events_status(b"x" * LIMIT, {})[0] == 401


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("not JSON", b"{"),
        ("empty", b""),
        ("an array", b"[]"),
        ("a string", b'"event_callback"'),
        ("NaN", b"NaN"),
        ("Infinity in an object", b'{"type": "event_callback", "x": Infinity}'),
        ("deep nesting", b"[" * 2000 + b"]" * 2000),
        ("invalid UTF-8", b'{"type": "\xff\xfe"'),
        ("a trailing comma", b'{"type": "event_callback",}'),
        ("a duplicate key's second value would be event_callback", b'{"type": 1, "type": 2}'),
    ],
)
def test_a_signed_body_that_is_not_a_json_object_is_400_or_dropped(name: str, body: bytes) -> None:
    status, events = events_status(body)
    assert status in (400, 200), name
    assert events == [], name


def test_a_url_verification_without_a_string_challenge_is_400() -> None:
    for challenge in (None, 1, ["x"], {"x": 1}):
        body = json.dumps({"type": "url_verification", "challenge": challenge}).encode()
        assert events_status(body)[0] == 400, challenge


def test_an_envelope_for_another_app_or_workspace_reaches_no_handler() -> None:
    envelope = json.loads(EVENT)
    # A shared channel's envelope names the workspace in ``authorizations``.
    other_workspace = {
        "team_id": "T0OTHER",
        "authorizations": [{"team_id": "T0OTHER", "user_id": "U0", "is_bot": True}],
    }
    for changed in ({"api_app_id": "A0OTHER"}, other_workspace, {"type": "app_rate_limited"}):
        status, events = events_status(json.dumps({**envelope, **changed}).encode())
        assert (status, events) == (200, []), changed


def form(**fields: str) -> bytes:
    from urllib.parse import urlencode

    return urlencode(fields).encode()


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("no fields", b""),
        ("no payload and no command", form(text="hi")),
        ("a payload that is not JSON", form(payload="{")),
        ("a payload that is an array", form(payload="[]")),
        ("a payload that is null", form(payload="null")),
        ("a payload with NaN", form(payload='{"api_app_id": NaN}')),
        ("a payload nested deep", form(payload="[" * 2000 + "]" * 2000)),
        ("bad percent escapes", b"payload=%zz%7"),
        ("invalid UTF-8", b"payload=%ff%fe"),
        ("raw JSON, not a form", json.dumps({"api_app_id": APP_ID}).encode()),
    ],
)
def test_a_signed_form_without_a_payload_object_or_a_command_is_400(name: str, body: bytes) -> None:
    status, payloads = interactivity_status(body)
    assert (status, payloads) == (400, []), name


def test_a_repeated_payload_field_keeps_its_first_value() -> None:
    body = (
        form(payload=json.dumps({"api_app_id": APP_ID, "n": 1}))
        + b"&"
        + form(payload=json.dumps({"api_app_id": APP_ID, "n": 2}))
    )
    status, payloads = interactivity_status(body)
    assert status == 200
    assert [p["n"] for p in payloads if isinstance(p, dict)] == [1]


def test_an_interactivity_payload_for_another_app_or_with_a_bad_signature_reaches_no_handler() -> (
    None
):
    other = form(payload=json.dumps({"api_app_id": "A0OTHER"}))
    assert interactivity_status(other) == (200, [])
    mine = form(payload=json.dumps({"api_app_id": APP_ID}))
    bad = headers(
        mine, **{"content-type": "application/x-www-form-urlencoded", "x-slack-signature": "v0=00"}
    )
    assert interactivity_status(mine, bad) == (401, [])


def _list_message(indent: object, offset: object) -> dict[str, Any]:
    return {
        "ts": "1794509003.000002",
        "user": BOT_USER_ID,
        "text": "x",
        "blocks": [
            {
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_list",
                        "style": "ordered",
                        "indent": indent,
                        "offset": offset,
                        "elements": [
                            {
                                "type": "rich_text_section",
                                "elements": [{"type": "text", "text": "a"}],
                            }
                        ],
                    }
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    "value",
    [10**12, 10**400, -(10**12), 1e308, -1e308, 2**53 + 1, 0.5, "9" * 5000, None, True, [], {}],
)
def test_an_adversarial_rich_text_indent_or_offset_renders_small(value: object) -> None:
    # The bot's own message reads back from its rich_text block, so the
    # block's numbers are peer input that sizes the text.
    message = _list_message(value, value)
    events = slack_chat.normalize(message_envelope(message), team_id=TEAM, bot_user_id=BOT_USER_ID)
    [event] = events
    assert isinstance(event, MessageCreated)
    assert len(event.message.text) < 200, event.message.text


def test_deeply_nested_rich_text_is_not_a_defect() -> None:
    element: dict[str, Any] = {"type": "text", "text": "a"}
    for _ in range(5000):
        element = {"type": "rich_text_section", "elements": [element]}
    message = {
        "ts": "1794509003.000003",
        "user": BOT_USER_ID,
        "text": "a",
        "blocks": [{"type": "rich_text", "elements": [element]}],
    }
    events = slack_chat.normalize(message_envelope(message), team_id=TEAM, bot_user_id=BOT_USER_ID)
    assert len(events) == 1
