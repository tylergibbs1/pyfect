"""Inbound WhatsApp requests are untrusted. The webhook answers every malformed
signature, body and envelope with a 4xx before a handler sees it, and never
with a defect; the subscription check compares the verify token in constant
time; a body is bounded in size and in nesting; and the normaliser reads any
JSON without raising."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Generator
from typing import Any

import pytest
from _whatsapp_fake import BSUID, PHONE_NUMBER_ID, inbound

import pyfect as fx
from pyfect._core import Effect
from pyfect.byte_size import ByteSize
from pyfect.chat.chat_event import ChatEvent
from pyfect.chat.whatsapp import _json, _webhook, whatsapp_chat
from pyfect.crypto.native import layer_mac
from pyfect.duration import seconds
from pyfect.exit import Success
from pyfect.http import request as http_request
from pyfect.http import server_request
from pyfect.redacted import make as redacted

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]

SECRET = "security-test-app-secret"
LIMIT = 64 * 1024
MESSAGE = json.dumps(inbound({"type": "text", "text": {"body": "hi"}})).encode()


def sign(body: bytes, key: str = SECRET) -> str:
    return "sha256=" + hmac.new(key.encode(), body, hashlib.sha256).hexdigest()


def status(body: bytes, signature: str | None) -> tuple[int, list[ChatEvent]]:
    """The webhook's status for one request, and what reached the handler."""
    events: list[ChatEvent] = []
    headers = {} if signature is None else {"x-hub-signature-256": signature}

    @fx.gen
    def run() -> Gen[int]:
        verify = yield from _webhook.make_verifier(redacted(SECRET)).pipe(fx.provide(layer_mac))
        client = http_request.post("http://localhost/whatsapp", headers=headers).body_bytes(
            body, "application/json"
        )
        response = yield from _webhook.handle_request(
            server_request.from_client_request(client),
            _webhook.Options(
                verify=verify,
                normalize=lambda envelope: whatsapp_chat.normalize(
                    envelope, phone_number_id=PHONE_NUMBER_ID
                ),
                handle=lambda event: fx.sync(lambda: events.append(event)),
                on_update=None,
                deadline=seconds(4),
                max_body_size=ByteSize(LIMIT),
            ),
        )
        return response.status

    exit = fx.run_blocking_exit(run)
    assert isinstance(exit, Success), exit
    return exit.value, events


def test_a_signed_delivery_reaches_the_handler() -> None:
    code, events = status(MESSAGE, sign(MESSAGE))
    assert code == 200
    assert len(events) == 1


@pytest.mark.parametrize(
    ("name", "signature"),
    [
        ("missing", None),
        ("empty", ""),
        ("no prefix", hmac.new(SECRET.encode(), MESSAGE, hashlib.sha256).hexdigest()),
        ("sha1 prefix", "sha1=" + hmac.new(SECRET.encode(), MESSAGE, hashlib.sha1).hexdigest()),
        ("wrong key", sign(MESSAGE, "other-secret")),
        ("odd hex", sign(MESSAGE)[:-1]),
        ("not hex", "sha256=" + "zz" * 32),
        ("truncated", sign(MESSAGE)[:20]),
        ("uppercase prefix", sign(MESSAGE).replace("sha256", "SHA256")),
        ("trailing newline", sign(MESSAGE) + "\n"),
        ("huge", "sha256=" + "00" * 100_000),
        ("non-ASCII digits", "sha256=" + "\u0661" * 64),
    ],
)
def test_a_bad_or_missing_signature_is_401(name: str, signature: str | None) -> None:
    code, events = status(MESSAGE, signature)
    assert (code, events) == (401, []), name


def test_a_body_over_the_limit_is_413_before_the_signature_is_checked() -> None:
    body = b'{"object":"whatsapp_business_account","x":"' + b"a" * LIMIT + b'"}'
    assert status(body, None) == (413, [])
    assert status(body, sign(body)) == (413, [])


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("empty", b""),
        ("not JSON", b"{not json"),
        ("an array", b"[]"),
        ("a string", b'"whatsapp_business_account"'),
        ("NaN", b'{"object":NaN}'),
        ("deep arrays", b'{"a":' + b"[" * 65 + b"]" * 65 + b"}"),
        ("deep objects", b'{"a":' + b'{"a":' * 70 + b"1" + b"}" * 70 + b"}"),
        ("a huge integer", b'{"object":1' + b"0" * 5000 + b"}"),
    ],
)
def test_a_signed_body_that_is_not_a_shallow_json_object_is_400(name: str, body: bytes) -> None:
    assert status(body, sign(body)) == (400, []), name


def test_invalid_utf8_is_replaced_as_effects_decoder_does_and_reaches_no_handler() -> None:
    body = b'{"object":"\xff\xfe"}'
    assert status(body, sign(body)) == (200, [])


def test_nesting_inside_strings_does_not_count() -> None:
    envelope = inbound({"type": "text", "text": {"body": "[" * 5000 + "{" * 5000}})
    body = json.dumps(envelope).encode()
    code, events = status(body, sign(body))
    assert code == 200
    assert len(events) == 1


_FOREIGN: list[object] = [
    {"object": "page", "entry": []},
    {"object": "whatsapp_business_account", "entry": "x"},
    {"object": "whatsapp_business_account", "entry": [{"changes": [None, 1, "x", []]}]},
    inbound({"type": "text", "text": {"body": "hi"}}, phone_number_id="999"),
]


@pytest.mark.parametrize("envelope", _FOREIGN)
def test_an_envelope_for_another_object_or_number_or_of_the_wrong_shape_reaches_no_handler(
    envelope: object,
) -> None:
    body = json.dumps(envelope).encode()
    assert status(body, sign(body)) == (200, [])


def _verification(query: str) -> int:
    request = server_request.from_client_request(
        http_request.get(f"http://localhost/whatsapp?{query}")
    )
    return _webhook.handle_verification(request, redacted("verify-token")).status


@pytest.mark.parametrize(
    "query",
    [
        "",
        "hub.mode=subscribe&hub.challenge=1",
        "hub.mode=subscribe&hub.verify_token=verify-toke&hub.challenge=1",
        "hub.mode=subscribe&hub.verify_token=verify-token%00&hub.challenge=1",
        "hub.mode=unsubscribe&hub.verify_token=verify-token&hub.challenge=1",
        "hub.mode=subscribe&hub.verify_token=verify-token",
        "hub.mode=subscribe&hub.verify_token=%FF%FE&hub.challenge=1",
        "hub.mode=subscribe&hub.verify_token=é&hub.challenge=1",
    ],
)
def test_a_subscription_check_without_the_verify_token_is_403(query: str) -> None:
    assert _verification(query) == 403


def test_a_subscription_check_with_the_verify_token_echoes_the_challenge() -> None:
    assert _verification("hub.mode=subscribe&hub.verify_token=verify-token&hub.challenge=7") == 200


def test_the_verify_token_is_compared_in_constant_time() -> None:
    # A token compared with ``==`` would leak its prefix through timing; the
    # check goes through ``hmac.compare_digest``.
    import inspect

    assert "compare_digest" in inspect.getsource(_webhook.handle_verification)


_ODD_VALUES: list[object] = [None, True, 0, -1, 1e308, "", "x", [], {}, [None], {"a": None}]


@pytest.mark.parametrize("value", _ODD_VALUES)
def test_any_json_in_any_field_normalises_without_raising(value: object) -> None:
    fields = [
        "from",
        "from_user_id",
        "id",
        "timestamp",
        "type",
        "text",
        "reaction",
        "interactive",
        "context",
        "image",
        "document",
        "system",
        "group_id",
    ]
    for name in fields:
        for type_ in ("text", "reaction", "interactive", "image", "system", name):
            envelope = inbound({"type": type_, name: value})
            whatsapp_chat.normalize(envelope, phone_number_id=PHONE_NUMBER_ID)
    for key in ("contacts", "metadata", "messages", "statuses"):
        envelope = inbound({"type": "text"})
        envelope["entry"][0]["changes"][0]["value"][key] = value
        whatsapp_chat.normalize(envelope, phone_number_id=PHONE_NUMBER_ID)
    status_item = {"id": "w", "status": "failed", "recipient_user_id": BSUID, "errors": value}
    whatsapp_chat.normalize(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": PHONE_NUMBER_ID},
                                "statuses": [status_item, {**status_item, "timestamp": value}],
                            },
                        }
                    ]
                }
            ],
        },
        phone_number_id=PHONE_NUMBER_ID,
    )


@pytest.mark.parametrize("timestamp", ["9" * 15, "1e300", "-1", "1" * 400, "NaN", "Infinity"])
def test_an_out_of_range_timestamp_is_no_timestamp_not_a_defect(timestamp: str) -> None:
    [event] = whatsapp_chat.normalize(
        inbound({"type": "text", "text": {"body": "hi"}, "timestamp": timestamp}),
        phone_number_id=PHONE_NUMBER_ID,
    )
    assert type(event).__name__ == "MessageCreated"


def test_the_depth_check_is_linear_on_unterminated_strings() -> None:
    # A quote-escape run never ends a string: matched whole, not once per quote.
    assert _json.parse(b'"\\"' * 200_000) is None
    assert _json.parse(b"[" * 200_000) is None
    assert _json.parse(b"[" * _json.MAX_DEPTH + b"]" * _json.MAX_DEPTH) is not None
