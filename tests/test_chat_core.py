"""Ports of Effect's ``test/chat/Chat.test.ts``, ``test/chat/ChatError.test.ts``
and ``test/chat/ChatEvent.test.ts``: the chat service routes by platform and
traces each call; errors keep their cause out of what they print; a stop's
dedupe key ignores the streams it names."""

from __future__ import annotations

import copy
import json
from collections.abc import Generator
from typing import Any

import pyfect as fx
import pyfect.schema as S
from pyfect import layer, testing
from pyfect._core import Effect
from pyfect.chat import chat_event, chat_test, chat_thread
from pyfect.chat.chat import Chat
from pyfect.chat.chat_error import (
    AnyReason,
    ChatError,
    Forbidden,
    InvalidRequest,
    InvalidResponse,
    NoAdapter,
    NotFound,
    PlatformUnavailable,
    RateLimited,
    TooLarge,
    Transport,
    Unauthenticated,
    Unknown,
    Unsupported,
)
from pyfect.chat.chat_event import StopRequested
from pyfect.chat.chat_test import ChatTest
from pyfect.duration import seconds
from pyfect.tracer import NativeSpan, SpanRequest, Tracer

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]


def _recording() -> tuple[Tracer, list[NativeSpan]]:
    spans: list[NativeSpan] = []

    def make(request: SpanRequest) -> NativeSpan:
        span = NativeSpan(request)
        spans.append(span)
        return span

    return Tracer(make), spans


# --- Chat ----------------------------------------------------------------------------


@testing.effect
def test_routes_each_address_to_its_platforms_adapter():
    """Chat / routes each address to its platform's adapter"""

    @fx.gen
    def program() -> Gen[None]:
        chat = yield from Chat()
        test = yield from ChatTest()
        b = yield from test.make_thread()
        yield from chat.post(b, markdown="to b")
        missing = yield from chat.post(chat_thread.make("c", "x"), markdown="nowhere").flip()
        assert missing.reason._tag == "NoAdapter"  # pyright: ignore[reportPrivateUsage]
        assert [m.text for m in (yield from test.messages(b))] == ["to b"]

    return program.pipe(
        fx.provide(layer.merge(chat_test.layer(platform="a"), chat_test.layer(platform="b")))
    )


@testing.effect
def test_sets_only_platform_op_error_reason_and_retry_value_on_its_spans():
    """Chat / sets only platform, op, error reason and retry value on its spans"""

    @fx.gen
    def program() -> Gen[None]:
        tracer, spans = _recording()
        chat = yield from Chat()
        test = yield from ChatTest()
        thread = yield from test.make_thread()

        @fx.gen
        def calls() -> Gen[None]:
            posted = yield from chat.post(thread, markdown="hello")
            yield from chat.fetch_message(thread, posted.id + "0").exit()

        yield from calls.with_tracer(tracer)
        assert [(span.name, dict(span.attributes)) for span in spans] == [
            ("Chat.post", {"chat.platform": "test", "chat.op": "post"}),
            (
                "Chat.fetchMessage",
                {
                    "chat.platform": "test",
                    "chat.op": "fetchMessage",
                    "chat.error.reason": "NotFound",
                    "chat.error.retry": "denied",
                },
            ),
        ]

    return program.pipe(fx.provide(chat_test.layer()))


# --- ChatError -----------------------------------------------------------------------

_CAUSE = Exception("https://example.com/files/secret.txt")

REASONS: tuple[AnyReason, ...] = (
    RateLimited(retry_after=seconds(3), detail="ratelimited", cause=_CAUSE),
    Unsupported(capability="edit", detail="no_edit", cause=_CAUSE),
    Transport(retry="uncertain", detail="timeout", cause=_CAUSE),
    PlatformUnavailable(retry="retry", detail="503", cause=_CAUSE),
    NoAdapter(detail="none", cause=_CAUSE),
    Unauthenticated(detail="invalid_auth", cause=_CAUSE),
    Forbidden(detail="not_in_channel", cause=_CAUSE),
    NotFound(detail="channel_not_found", cause=_CAUSE),
    TooLarge(detail="msg_too_long", cause=_CAUSE),
    InvalidRequest(detail="invalid_blocks", cause=_CAUSE),
    InvalidResponse(detail="bad_json", cause=_CAUSE),
    Unknown(detail="unknown", cause=_CAUSE),
)


def test_fixes_the_retry_value_per_reason():
    """ChatError / fixes the retry value per reason"""
    assert [reason.retry for reason in REASONS] == [
        "retry",
        "denied",
        "uncertain",
        "retry",
        "denied",
        "denied",
        "denied",
        "denied",
        "denied",
        "denied",
        "denied",
        "uncertain",
    ]


@testing.effect
def test_round_trips_every_reason_through_its_schema_cause_included():
    """ChatError / round-trips every reason through its Schema, cause included"""
    codec = S.to_codec_json(ChatError)
    for reason in REASONS:
        error = ChatError(platform="slack", op="post", reason=reason)
        decoded = yield from S.decode_effect(codec)((yield from S.encode_effect(codec)(error)))
        assert decoded.reason._tag == reason._tag  # pyright: ignore[reportPrivateUsage]
        assert decoded.reason.detail == reason.detail
        assert decoded.retry == error.retry
        assert isinstance(decoded.reason.cause, Exception)
        assert str(decoded.reason.cause) == str(_CAUSE)


def test_leaves_cause_out_of_to_json_and_message():
    """ChatError / leaves cause out of toJSON and message"""
    for reason in REASONS:
        error = ChatError(platform="slack", op="post", reason=reason)
        assert "secret" not in json.dumps(error.to_json())
        assert "secret" not in json.dumps(reason.to_json())
        assert "secret" not in error.message
        assert "secret" not in str(error)


def test_delegates_retry_after_to_the_reason():
    """ChatError / delegates retryAfter to the reason"""
    error = ChatError(platform="slack", op="post", reason=REASONS[0])
    assert error.retry_after == seconds(3)


# --- ChatEvent -----------------------------------------------------------------------


def test_dedupe_key_is_stop_thread_id():
    """ChatEvent / StopRequested / dedupeKey is stop/{thread}/{id}"""
    event = StopRequested(
        thread=chat_thread.make("slack", "T1/C1/1794454017.568519"),
        id="1794454026.522466",
        user_id="U1",
        message_ids=("1794454017.726189",),
        raw={"event": {"type": "agent_session_stopped"}},
    )
    assert chat_event.dedupe_key(event) == "stop/slack:T1/C1/1794454017.568519/1794454026.522466"
    # A redelivery has the same key, whatever streams it lists.
    assert chat_event.dedupe_key(copy.replace(event, message_ids=())) == chat_event.dedupe_key(
        event
    )
