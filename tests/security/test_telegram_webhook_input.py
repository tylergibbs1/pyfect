"""Inbound Telegram requests and updates are untrusted. The webhook answers
every request without the secret 401 before reading its body, compares the
secret in constant time, bounds a body in size and nesting, and answers a
malformed one 400, never with a defect; the normaliser reads any JSON
without raising, and its entity handling is linear in the entities, with
UTF-16 offsets."""

from __future__ import annotations

import inspect
import json
from collections.abc import Generator
from typing import Any

import pytest
from _growth import assert_near_linear
from _telegram_fake import BOT_ID, CONTEXT, message_update

import pyfect as fx
from pyfect._core import Effect
from pyfect.byte_size import ByteSize
from pyfect.chat.chat_event import MessageCreated
from pyfect.chat.telegram import _json, _webhook, telegram_chat
from pyfect.chat.telegram._receive import Outcome
from pyfect.exit import is_failure
from pyfect.http import request as http_request
from pyfect.http import server_request
from pyfect.redacted import make as redacted

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]

SECRET = "S" * 40
LIMIT = 64 * 1024
UPDATE = json.dumps(message_update({"text": "hi"})).encode()


def status(body: bytes, header: str | None = SECRET) -> tuple[int, list[object]]:
    """The webhook's status for one request, and what reached ``receive``."""
    received: list[object] = []
    headers = {} if header is None else {_webhook.SECRET_HEADER: header}

    def receive(update: object) -> Effect[Outcome]:
        received.append(update)
        return fx.succeed("accepted")

    client = http_request.post("http://localhost/telegram", headers=headers).body_bytes(
        body, "application/json"
    )
    response = fx.run_blocking(
        _webhook.handle_request(
            server_request.from_client_request(client),
            _webhook.Options(
                secret=SECRET.encode(), max_body_size=ByteSize(LIMIT), receive=receive
            ),
        )
    )
    return response.status, received


def test_an_update_with_the_secret_reaches_receive() -> None:
    assert status(UPDATE) == (200, [json.loads(UPDATE)])


@pytest.mark.parametrize(
    ("name", "header"),
    [
        ("missing", None),
        ("empty", ""),
        ("one character short", SECRET[:-1]),
        ("one character long", SECRET + "S"),
        ("wrong case", SECRET.lower()),
        ("padded", f" {SECRET} "),
        ("non-ASCII", "é" * 40),
        ("lone surrogate", "\ud800" * 40),
    ],
)
def test_a_wrong_or_missing_secret_is_401(name: str, header: str | None) -> None:
    assert status(UPDATE, header) == (401, []), name


def test_a_wrong_secret_is_401_before_the_body_is_read() -> None:
    # A body past the limit would be 413 if it were read.
    assert status(b"x" * (LIMIT + 1), "wrong") == (401, [])


def test_the_secret_is_compared_in_constant_time() -> None:
    source = inspect.getsource(_webhook.handle_request)
    assert "hmac.compare_digest" in source
    assert "== options.secret" not in source


def test_a_body_over_the_limit_is_413() -> None:
    assert status(b" " * (LIMIT + 1)) == (413, [])


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("empty", b""),
        ("not JSON", b"{"),
        ("a string", b'"x"'),
        ("an array", b"[]"),
        ("null", b"null"),
        ("no update_id", b'{"message": {}}'),
        ("a string update_id", b'{"update_id": "1"}'),
        ("a boolean update_id", b'{"update_id": true}'),
        ("nested past the cap", b'{"update_id": 1, "x": ' + b"[" * 100 + b"]" * 100 + b"}"),
        ("NaN", b'{"update_id": NaN}'),
        ("a trailing comma", b'{"update_id": 1,}'),
        ("a BOM-less UTF-16 body", '{"update_id": 1}'.encode("utf-16-le")),
    ],
)
def test_a_body_that_is_not_a_shallow_update_is_400(name: str, body: bytes) -> None:
    assert status(body) == (400, []), name


def test_nesting_inside_strings_does_not_count() -> None:
    body = json.dumps({"update_id": 1, "x": "[" * 200}).encode()
    assert status(body)[0] == 200


def test_the_depth_check_is_linear_on_unterminated_strings() -> None:
    def make(n: int):
        value = b'"\\"' * (n // 3)
        return lambda: _json.parse(value)

    assert_near_linear(make, 40_000)


@pytest.mark.parametrize("secret", ["short", "x" * 31, "x" * 257, "x" * 31 + "!", "é" * 32])
def test_a_secret_outside_telegrams_rule_is_refused_when_the_layer_is_built(secret: str) -> None:
    exit = fx.run_blocking(_webhook.secret_token("layerWebhook", redacted(secret)).exit())
    assert is_failure(exit)


_ODD_VALUES: list[object] = [
    None,
    True,
    0,
    -1,
    2**64,
    1e308,
    -0.0,
    "",
    "x",
    [],
    [None],
    {},
    {"id": None},
]


@pytest.mark.parametrize("value", _ODD_VALUES)
def test_any_json_in_any_field_normalises_without_raising(value: object) -> None:
    base = message_update({"text": "hi"})
    message = base["message"]
    for key in [
        "message_id",
        "date",
        "chat",
        "from",
        "sender_chat",
        "text",
        "entities",
        "caption",
        "caption_entities",
        "reply_to_message",
        "photo",
        "document",
        "animation",
        "message_thread_id",
        "is_topic_message",
    ]:
        update = {**base, "message": {**message, key: value}}
        telegram_chat.normalize(update, CONTEXT)
        telegram_chat.normalize_interaction(update, CONTEXT)
        telegram_chat.delivery_key(update, bot_id=BOT_ID)
    for update in [value, {"update_id": value}, {"update_id": 1, "message": value}]:
        telegram_chat.normalize(update, CONTEXT)
        telegram_chat.normalize_interaction(update, CONTEXT)
        telegram_chat.delivery_key(update, bot_id=BOT_ID)
    telegram_chat.normalize_interaction(
        {"update_id": 1, "callback_query": {"id": "q", "data": value, "message": value}}, CONTEXT
    )


@pytest.mark.parametrize("date", [10**15, -(10**15), 2**63, 1e300])
def test_an_out_of_range_date_gives_no_event_not_a_defect(date: object) -> None:
    update = message_update({"text": "hi", "date": date})
    assert telegram_chat.normalize(update, CONTEXT) == []


@pytest.mark.parametrize(
    "entity",
    [
        {"type": "mention", "offset": -1, "length": 11},
        {"type": "mention", "offset": 0, "length": 1000},
        {"type": "mention", "offset": 2**60, "length": 2**60},
        {"type": "mention", "offset": 1.5, "length": 11},
        {"type": "text_mention", "offset": 0, "length": 2, "user": {"id": "1"}},
    ],
)
def test_an_entity_outside_the_text_is_no_mention(entity: dict[str, object]) -> None:
    [event] = telegram_chat.normalize(
        message_update({"text": "@effect_bot", "entities": [entity]}), CONTEXT
    )
    assert isinstance(event, MessageCreated)
    assert event.message.mentions == ()


def test_entity_offsets_are_utf16_units() -> None:
    # Each emoji is two UTF-16 units.
    text = "😀😀 @effect_bot"
    [event] = telegram_chat.normalize(
        message_update(
            {"text": text, "entities": [{"type": "mention", "offset": 5, "length": 11}]}
        ),
        CONTEXT,
    )
    assert isinstance(event, MessageCreated)
    [mention] = event.message.mentions
    assert (mention.start, mention.end, mention.is_self) == (5, 16, True)


def test_a_command_entity_over_non_ascii_text_is_no_command() -> None:
    # Two UTF-16 units of "/é" would cover the slash and the letter, which the
    # command pattern refuses, as Telegram's JavaScript reading does.
    update = message_update(
        {"text": "/é", "entities": [{"type": "bot_command", "offset": 0, "length": 2}]}
    )
    assert telegram_chat.normalize_interaction(update, CONTEXT) is None


def test_mentions_are_linear_in_many_overlapping_entities() -> None:
    def make(n: int):
        text = "@effect_bot " + "x" * n
        entities = [{"type": "mention", "offset": 0, "length": n} for _ in range(n // 10)]
        update = message_update({"text": text, "entities": entities})
        return lambda: telegram_chat.normalize(update, CONTEXT)

    assert_near_linear(make, 4000)
