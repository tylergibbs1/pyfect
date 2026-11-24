"""Inbound Discord data is untrusted. The interactions endpoint answers every
malformed signature, timestamp, body and payload with a 4xx before a handler
sees it, and never with a defect; dispatches, interaction payloads and gateway
frames an attacker shapes decode to nothing rather than a defect or a request
to another route."""

from __future__ import annotations

import json
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from _discord_fake import BOT_USER_ID, SCRATCH, events
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import pyfect as fx
from pyfect._core import Effect
from pyfect._json_value import JsonValue
from pyfect.byte_size import ByteSize
from pyfect.chat.chat_event import MessageCreated
from pyfect.chat.discord import _interactions, _json, _mentions, _webhook, discord_chat
from pyfect.chat.discord._adapter import SendCallback
from pyfect.chat.discord.discord_gateway import GatewayDispatch
from pyfect.chat.discord.discord_rest import path
from pyfect.crypto.native import layer_signature
from pyfect.duration import Duration, seconds
from pyfect.exit import Success
from pyfect.http import request as http_request
from pyfect.http import server_request
from pyfect.result import Ok

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]

KEY = Ed25519PrivateKey.generate()
PUBLIC = KEY.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
OTHER = Ed25519PrivateKey.generate()
LIMIT = 64 * 1024
CLICK = {
    "id": "1570700000000000100",
    "application_id": BOT_USER_ID,
    "type": 3,
    "token": "token",
    "version": 1,
    "channel_id": SCRATCH,
    "member": {"user": {"id": "449108784879763458"}},
    "message": {"id": "1570700000000000001", "channel_id": SCRATCH},
    "data": {"custom_id": "go", "component_type": 2},
}
BODY = json.dumps(CLICK).encode()


def now(offset: int = 0) -> str:
    """A request timestamp: whole seconds since the epoch, from the wall clock
    the signature check reads."""
    return str(int(datetime.now(UTC).timestamp()) + offset)


def sign(timestamp: str, body: bytes, key: Ed25519PrivateKey = KEY) -> str:
    return key.sign(timestamp.encode() + body).hex()


def headers(body: bytes, **overrides: str | None) -> dict[str, str]:
    stamp = overrides.pop("x-signature-timestamp", None) or now()
    found: dict[str, str | None] = {
        "content-type": "application/json",
        "x-signature-timestamp": stamp,
        "x-signature-ed25519": sign(stamp, body),
        **overrides,
    }
    return {key: value for key, value in found.items() if value is not None}


def status(body: bytes, sent: dict[str, str] | None = None) -> tuple[int, list[object]]:
    """The endpoint's status for one request, and what reached the interaction entry."""
    payloads: list[object] = []

    def interaction(payload: object, _: Duration, send: SendCallback) -> Effect[None]:
        payloads.append(payload)
        to = _interactions.answer_to(payload)
        if to is None or _interactions.normalize(payload) is None:
            return fx.void
        return send("ack", to, _interactions.ACK_CALLBACK).or_die()

    @fx.gen
    def run() -> Gen[int]:
        verify = yield from _webhook.make_verifier(PUBLIC).pipe(fx.provide(layer_signature))
        request = http_request.post(
            "http://localhost/discord", headers=headers(body) if sent is None else sent
        ).body_bytes(body, "application/json")
        response = yield from _webhook.handle_request(
            server_request.from_client_request(request),
            _webhook.Options(
                verify=verify,
                interaction=interaction,
                deadline=seconds(2),
                max_body_size=ByteSize(LIMIT),
            ),
        )
        return response.status

    exit = fx.run_blocking_exit(run)
    assert isinstance(exit, Success), exit
    return exit.value, payloads


def test_a_signed_interaction_reaches_the_entry_and_a_ping_is_answered() -> None:
    assert status(BODY) == (200, [CLICK])
    ping = json.dumps({"type": 1, "id": "1", "token": "t"}).encode()
    assert status(ping) == (200, [])


_BAD_SIGNATURES: dict[str, Callable[[str], str | None]] = {
    "missing": lambda _: None,
    "empty": lambda _: "",
    "another key": lambda stamp: sign(stamp, BODY, OTHER),
    "over another timestamp": lambda stamp: sign(str(int(stamp) - 1), BODY),
    "non-hex": lambda _: "zz" * 64,
    "odd length": lambda stamp: sign(stamp, BODY)[:-1],
    "truncated": lambda stamp: sign(stamp, BODY)[:64],
    "spaced hex": lambda stamp: " ".join(sign(stamp, BODY)[i : i + 2] for i in range(0, 128, 2)),
    "a trailing newline": lambda stamp: sign(stamp, BODY) + "\n",
    "full-width digits": lambda _: "\uff10" * 128,
    "all zeros": lambda _: "0" * 128,
    "too long": lambda stamp: sign(stamp, BODY) * 100,
}


@pytest.mark.parametrize("name", list(_BAD_SIGNATURES))
def test_a_bad_or_missing_signature_is_401(name: str) -> None:
    stamp = now()
    signature = _BAD_SIGNATURES[name](stamp)
    sent = headers(BODY, **{"x-signature-timestamp": stamp, "x-signature-ed25519": signature})
    assert status(BODY, sent) == (401, []), name


_BAD_TIMESTAMPS: dict[str, Callable[[], str]] = {
    "six minutes old": lambda: now(-6 * 60),
    "six minutes ahead": lambda: now(6 * 60),
    "zero": lambda: "0",
    "twenty digits": lambda: "9" * 20,
    "past twenty digits": lambda: "9" * 4_000,
    "negative": lambda: "-" + now(),
    "plus sign": lambda: "+" + now(),
    "spaced": lambda: " " + now(),
    "fractional": lambda: now() + ".5",
    "non-digit": lambda: now() + "a",
    "Arabic-Indic digits": lambda: now().translate(
        str.maketrans("0123456789", "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669")
    ),
    "underscore": lambda: now()[:4] + "_" + now()[4:],
}


@pytest.mark.parametrize("name", list(_BAD_TIMESTAMPS))
def test_a_timestamp_past_the_skew_or_not_whole_ascii_seconds_is_401(name: str) -> None:
    # Signed correctly over the bad timestamp: only the timestamp check can refuse it.
    stamp = _BAD_TIMESTAMPS[name]()
    sent = {
        "content-type": "application/json",
        "x-signature-timestamp": stamp,
        "x-signature-ed25519": sign(stamp, BODY),
    }
    assert status(BODY, sent) == (401, []), name


def test_a_body_over_the_limit_is_413_before_the_signature_is_checked() -> None:
    big = b"x" * (LIMIT + 1)
    assert status(big, {})[0] == 413
    assert status(big)[0] == 413
    assert status(b"x" * LIMIT, {})[0] == 401


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("not JSON", b"{"),
        ("empty", b""),
        ("an array", b"[]"),
        ("a string", b'"ping"'),
        ("null", b"null"),
        ("NaN", b"NaN"),
        ("deep nesting", b"[" * 2000 + b"]" * 2000),
        ("an object nested deep", b'{"a":' * 100 + b"1" + b"}" * 100),
        ("invalid UTF-8", b'{"type": "\xff\xfe"'),
        ("a trailing comma", b'{"type": 1,}'),
    ],
)
def test_a_signed_body_that_is_not_a_json_object_is_400(name: str, body: bytes) -> None:
    assert status(body) == (400, []), name


def test_a_signed_payload_the_adapter_cant_answer_is_204() -> None:
    # The entry runs and sends nothing: an unknown type, a token that is not URL-safe.
    for payload in ({**CLICK, "type": 99}, {**CLICK, "token": "../../users/@me"}):
        body = json.dumps(payload).encode()
        assert status(body)[0] == 204


def test_the_public_key_is_checked_when_the_layer_is_made() -> None:
    for key in ("", "zz" * 32, PUBLIC.hex()[:-1], PUBLIC.hex() + "00", " " + PUBLIC.hex()[1:]):
        with pytest.raises(ValueError, match="public_key"):
            discord_chat.layer_interactions(path="/discord", public_key=key)


# --- the REST client's paths -----------------------------------------------------------


@pytest.mark.parametrize("segment", ["", ".", ".."])
def test_a_dot_or_empty_path_segment_raises(segment: str) -> None:
    with pytest.raises(ValueError, match="path segment"):
        path("channels", segment, "messages")


def test_a_path_segment_is_percent_encoded() -> None:
    assert path("channels", "1/../../users", "messages") == "/channels/1%2F..%2F..%2Fusers/messages"
    assert path("interactions", "1", "a?b#c") == "/interactions/1/a%3Fb%23c"


@pytest.mark.parametrize(
    "token",
    ["", ".", "..", "...", "a/b", "a b", "a%2Fb", "x" * 1001, "\u0661", "a\nb", "<redacted>"],
)
def test_an_interaction_token_that_is_not_url_safe_gets_no_answer(token: str) -> None:
    assert _interactions.answer_to({**CLICK, "token": token}) is None
    assert _interactions.follow_up_to({**CLICK, "token": token}) is None


@pytest.mark.parametrize("id", ["", "..", "1/2", "1" * 21, "\u0661\u0662", "-1", "1e5"])
def test_an_interaction_id_that_is_not_a_snowflake_gets_no_answer(id: str) -> None:
    assert _interactions.answer_to({**CLICK, "id": id}) is None


# --- dispatches and interaction payloads -----------------------------------------------

BASE = events("channel-message")[0]


def _normalize(d: object) -> tuple[Any, ...]:
    result = discord_chat.normalize(
        GatewayDispatch(t="MESSAGE_CREATE", d=cast("JsonValue", d)),
        bot_user_id=BOT_USER_ID,
        channel_type=0,
    )
    assert isinstance(result, Ok)
    return result.value


@pytest.mark.parametrize(
    "value", [None, True, 1, 1e308, "x", [], {}, 10**400, -1, "9" * 5000, float("nan")]
)
@pytest.mark.parametrize("field", ["id", "channel_id", "author", "content", "timestamp", "type"])
def test_a_message_field_of_the_wrong_type_drops_the_message(field: str, value: object) -> None:
    found = _normalize({**BASE["d"], field: value})
    assert all(isinstance(event, MessageCreated) for event in found)


@pytest.mark.parametrize("channel_id", ["../1", "1/2", "", "\u0661", "1" * 21])
def test_a_message_whose_channel_is_not_a_snowflake_gives_no_event(channel_id: str) -> None:
    assert _normalize({**BASE["d"], "channel_id": channel_id}) == ()


@pytest.mark.parametrize("channel_id", ["../1", "1/2", "", "\u0661", "1" * 21])
def test_an_interaction_whose_channel_is_not_a_snowflake_is_none(channel_id: str) -> None:
    message = {"id": "1570700000000000001", "channel_id": channel_id}
    raw = {**CLICK, "channel_id": channel_id, "message": message}
    assert discord_chat.normalize_interaction(raw) is None


def test_deeply_nested_payloads_are_not_a_defect() -> None:
    nested: object = "x"
    for _ in range(5000):
        nested = {"a": nested}
    assert _normalize({**BASE["d"], "referenced_message": nested}) is not None
    assert discord_chat.normalize_interaction({**CLICK, "data": nested}) is None


def test_json_past_the_depth_cap_is_refused_in_linear_time() -> None:
    assert _json.parse("[" * (_json.MAX_DEPTH + 1) + "]" * (_json.MAX_DEPTH + 1)) is None
    assert _json.parse("[" * _json.MAX_DEPTH + "]" * _json.MAX_DEPTH) is not None
    # Brackets inside strings do not count.
    assert _json.parse(json.dumps(["[" * 10_000])) == ["[" * 10_000]
    assert _json.nesting_depth('"\\"[[[" [') == 1


@pytest.mark.parametrize(
    "text", ["<@\u0661\u0662>", "<@\uff11\uff12>", "<@!>", "<@&>", "<#>", "<@1", "@everyone2"]
)
def test_a_mention_token_with_non_ascii_digits_or_no_id_is_not_a_mention(text: str) -> None:
    assert discord_chat.parse_mention(text) is None


def test_mention_offsets_count_utf16_units_past_astral_characters() -> None:
    text = "\U0001f600 <@1> \U0001f600\U0001f600 <@2>"
    tokens = _mentions.tokens(text)
    starts = _mentions.utf16_offsets(text, [token.start for token in tokens])
    units = text.encode("utf-16-le")
    assert [units[s * 2 : s * 2 + 8].decode("utf-16-le") for s in starts] == ["<@1>", "<@2>"]


def test_a_fence_that_closes_inside_a_long_run_still_scans_as_effect_does() -> None:
    # A fence opens at the run's first three backticks and closes at the next three,
    # here inside the same run; the scan resumes in the run, which it measures once.
    text = "`" * 7 + "<@7>``` <@8>"
    assert [token.id for token in _mentions.tokens(text)] == ["7", "8"]
