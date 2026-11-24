"""Ports of Effect's ``slack/test/normalize.test.ts``, and of ``richText.test.ts`` and
``events.test.ts`` in ``packages/chat/slack/test``: the pure normaliser, the bot's
own messages read back as the Markdown they were posted with, and Events API
deliveries captured from Slack, run through the webhook on their real bytes."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
from collections.abc import Generator
from typing import Any

from _slack_fake import (
    APP_ID,
    BOT_USER_ID,
    CHANNEL,
    FIXTURES,
    TEAM,
    fixture,
    message_envelope,
    unix_now,
)

import pyfect as fx
from pyfect import testing
from pyfect._core import Effect
from pyfect.byte_size import ByteSize
from pyfect.chat.chat_event import (
    ChatEvent,
    MessageCreated,
    ReactionAdded,
    ReactionRemoved,
    StopRequested,
    dedupe_key,
)
from pyfect.chat.chat_message import Attachment, Author, ChatMessage, utf16_slice
from pyfect.chat.chat_test import check_event, check_message, same_message
from pyfect.chat.slack import _webhook, slack_chat
from pyfect.chat.slack._address import Parts
from pyfect.crypto.native import layer_mac
from pyfect.duration import seconds
from pyfect.http import request as http_request
from pyfect.http import server_request
from pyfect.redacted import make as redacted

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]


def check_event_(event: ChatEvent) -> Effect[None, Any]:
    return check_event(event, platform="slack", parse_mention=slack_chat.parse_mention)


def check_message_(message: ChatMessage) -> Effect[None, Any]:
    return check_message(message, platform="slack", parse_mention=slack_chat.parse_mention)


def created(events: list[ChatEvent]) -> MessageCreated:
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, MessageCreated)
    return event


def normalize(message: dict[str, Any], **options: Any) -> MessageCreated:
    return created(
        slack_chat.normalize(
            message_envelope(message, **options), team_id=TEAM, bot_user_id=BOT_USER_ID
        )
    )


def section(elements: list[Any]) -> list[Any]:
    return [
        {"type": "rich_text", "elements": [{"type": "rich_text_section", "elements": elements}]}
    ]


def recorded_messages(name: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = fixture("recorded", name)["calls"]
    for call in calls:
        response: dict[str, Any] = call.get("response") or {}
        found += response.get("messages") or []
    return found


def recorded(name: str, ts: str) -> dict[str, Any]:
    return next(message for message in recorded_messages(name) if message["ts"] == ts)


@testing.effect
def test_without_rich_text_text_is_scanned_outside_code():
    """normalize / without rich_text, text is scanned outside code"""

    @fx.gen
    def program() -> Gen[None]:
        event = normalize(
            {
                "ts": "1794509003.000001",
                "user": "U080YLYB277",
                "text": "hey <@U0CCLMD4S1L> `<@U999>` and <!here>",
            }
        )
        yield from check_event_(event)
        assert [mention.id for mention in event.message.mentions] == [BOT_USER_ID, "here"]
        assert event.message.mentions[0].is_self

    return program


@testing.effect
def test_text_never_adds_a_mention_the_rich_text_block_lacks():
    """normalize / text never adds a mention the rich_text block lacks"""

    @fx.gen
    def program() -> Gen[None]:
        # Block items: literal U1, real U1, real U2, literal bot.
        event = normalize(
            {
                "ts": "1794509003.000002",
                "user": "U080YLYB277",
                "text": f"<@U1AAAA> <@U2BBBB> <@{BOT_USER_ID}>",
                "blocks": section(
                    [
                        {"type": "text", "text": "<@U1AAAA>"},
                        {"type": "user", "user_id": "U1AAAA"},
                        {"type": "text", "text": " "},
                        {"type": "user", "user_id": "U2BBBB"},
                        {"type": "text", "text": f" <@{BOT_USER_ID}>"},
                    ]
                ),
            }
        )
        yield from check_event_(event)
        assert [(m.id, m.is_self, m.start) for m in event.message.mentions] == [
            ("U1AAAA", False, 0),
            ("U2BBBB", False, 10),
        ]

    return program


@testing.effect
def test_a_real_mention_with_no_token_in_text_past_a_literal_ends():
    """normalize / a real mention with no token in text, past a literal, ends"""

    @fx.gen
    def program() -> Gen[None]:
        # Block items: real U1, literal U9, real U2. Text has only U1.
        event = normalize(
            {
                "ts": "1794509003.000004",
                "user": "U080YLYB277",
                "text": "<@U1AAAA>",
                "blocks": section(
                    [
                        {"type": "user", "user_id": "U1AAAA"},
                        {"type": "text", "text": " <@U9ZZZZ> "},
                        {"type": "user", "user_id": "U2BBBB"},
                    ]
                ),
            }
        )
        yield from check_event_(event)
        assert [(m.id, m.start) for m in event.message.mentions] == [("U1AAAA", 0)]

    return program


def test_files_are_attachments_with_an_id_and_no_url() -> None:
    """normalize / files are attachments, with an id and no URL"""
    reply = recorded("file-share", "1794509028.831169")
    assert normalize(reply).message.attachments == (
        Attachment(id="F0CH6RHTMRU", name="fixture.txt", content_type="text/plain", size=51),
    )


def test_a_d_or_mpim_channel_is_a_direct() -> None:
    """normalize / a D or mpim channel is a direct"""
    message = {"ts": "1794509003.000002", "user": "U080YLYB277", "text": "hi"}
    assert normalize(message, channel="D0CCGDG0E75").kind == "direct"
    assert normalize(message, channel="C0GROUP", channel_type="mpim").kind == "direct"


def test_a_bot_messages_author_is_its_bot_id() -> None:
    """normalize / a bot_message's author is its bot_id"""
    event = normalize(
        {
            "ts": "1794509003.000004",
            "subtype": "bot_message",
            "bot_id": "B0WEBHOOK",
            "username": "incoming-webhook",
            "text": "deploy done <@U0CCLMD4S1L>",
        }
    )
    assert event.message.author == Author(
        id="B0WEBHOOK", name="incoming-webhook", is_bot=True, is_self=False
    )


def test_drops_other_subtypes_and_other_workspaces() -> None:
    """normalize / drops other subtypes and other workspaces"""
    message = {"ts": "1794509003.000005", "user": "U080YLYB277", "text": "<@U0CCLMD4S1L>"}
    joined = message_envelope({**message, "subtype": "channel_join"})
    assert slack_chat.normalize(joined, team_id=TEAM, bot_user_id=BOT_USER_ID) == []
    other = message_envelope(message, team_id="T0OTHER")
    assert slack_chat.normalize(other, team_id=TEAM, bot_user_id=BOT_USER_ID) == []


def test_drops_the_verification_token_from_raw() -> None:
    """normalize / drops the verification token from raw"""
    event = normalize({"ts": "1794509003.000006", "user": "U080YLYB277", "text": "hi"})
    assert isinstance(event.raw, dict)
    assert "token" not in event.raw


def read(message: dict[str, Any]) -> Effect[ChatMessage, Any]:
    @fx.gen
    def run() -> Gen[ChatMessage]:
        event = created(
            slack_chat.normalize(message_envelope(message), team_id=TEAM, bot_user_id=BOT_USER_ID)
        )
        # Includes that each mention's span parses as its token.
        yield from check_message_(event.message)
        return event.message

    return run


SYNTHETIC: list[dict[str, Any]] = fixture("synthetic", "own-messages")["cases"]


@testing.effect
def test_give_the_markdown_they_were_posted_with_from_recordings():
    """the bot's own messages read back / give the Markdown they were posted with, from
    recordings"""

    @fx.gen
    def program() -> Gen[None]:
        # The fixture posted raw markdown_text with `&lt;not a tag&gt;` typed
        # as entities. Through the adapter the same message is `<not a tag>`.
        mentions_post: str = fixture("recorded", "markdown-mentions")["calls"][0]["request"][
            "markdown_text"
        ]
        cases = [
            (
                "markdown-mentions",
                "1794509003.143939",
                mentions_post.replace("&lt;not a tag&gt;", "<not a tag>", 1),
            ),
            # Two appends.
            (
                "stream",
                "1794509111.134189",
                f"Streaming **part one**. Part two with <@{BOT_USER_ID}>.",
            ),
        ]
        for name, ts, markdown in cases:
            message = recorded(name, ts)
            read_ = yield from read(message)
            assert read_.text == markdown, name
            # Slack's own field stays on raw.
            assert isinstance(read_.raw, dict)
            assert read_.raw["text"] == message["text"], name
        # Slack stored the markdown-mentions text with its fence on one line.
        assert recorded("markdown-mentions", "1794509003.143939")["text"] != mentions_post

    return program


@testing.effect
def test_give_the_markdown_they_were_posted_with_from_synthetic_messages():
    """the bot's own messages read back / give the Markdown they were posted with, from synthetic
    messages"""

    @fx.gen
    def program() -> Gen[None]:
        for case in SYNTHETIC:
            assert (yield from read(case["message"])).text == case["markdown"], case["name"]

    return program


@testing.effect
def test_preserve_a_trailing_parenthesis_in_a_named_link_destination():
    """the bot's own messages read back / preserve a trailing parenthesis in a named link
    destination"""

    @fx.gen
    def program() -> Gen[None]:
        message = yield from read(
            {
                "user": BOT_USER_ID,
                "ts": "1794600000.000103",
                "text": "draft",
                "blocks": section(
                    [
                        {
                            "type": "link",
                            "text": "draft",
                            "url": "https://example.test/drafts/closing)",
                        }
                    ]
                ),
            }
        )
        assert message.text == "[draft](https://example.test/drafts/closing\\))"

    return program


@testing.effect
def test_someone_elses_message_keeps_slacks_text():
    """the bot's own messages read back / someone else's message keeps Slack's text"""

    @fx.gen
    def program() -> Gen[None]:
        message = next(c for c in SYNTHETIC if c["name"].startswith("Markdown characters"))[
            "message"
        ]
        rest = {k: v for k, v in message.items() if k not in ("app_id", "bot_id")}
        read_ = yield from read({**rest, "user": "U080YLYB277"})
        assert read_.text == message["text"]

    return program


# Captured deliveries, signed here with a test secret: the capture never logs
# Slack's signature.
SECRET = "captured-delivery-test-secret"
CASES = sorted(path.stem for path in (FIXTURES / "events").glob("*.json"))


def captured(name: str) -> list[dict[str, Any]]:
    return fixture("events", name)["deliveries"]


def deliver(delivery: dict[str, Any]) -> Effect[list[ChatEvent], Any]:
    """One delivery through the webhook, with its captured content type."""

    @fx.gen
    def run() -> Gen[list[ChatEvent]]:
        timestamp = unix_now()
        body: str = delivery["body"]
        digest = hmac.new(SECRET.encode(), f"v0:{timestamp}:{body}".encode(), hashlib.sha256)
        client_request = http_request.post(
            "http://localhost/slack/events",
            headers={
                "content-type": delivery["headers"]["content-type"],
                "x-slack-request-timestamp": timestamp,
                "x-slack-signature": "v0=" + digest.hexdigest(),
            },
        ).body_text(body, delivery["headers"]["content-type"])
        events: list[ChatEvent] = []
        verify = yield from _webhook.make_verifier(redacted(SECRET)).pipe(fx.provide(layer_mac))
        response = yield from _webhook.handle_request(
            server_request.from_client_request(client_request),
            _webhook.Options(
                verify=verify,
                app_id=APP_ID,
                team_id=TEAM,
                bot_user_id=fx.succeed(BOT_USER_ID),
                handle=lambda event: fx.sync(lambda: events.append(event)),
                deadline=seconds(2),
                max_body_size=ByteSize(1024 * 1024),
            ),
        )
        assert response.status == 200
        return events

    return run


def deliveries(name: str) -> Effect[list[list[ChatEvent]], Any]:
    """The events of every delivery of a case, in delivery order."""
    return fx.for_each(captured(name), deliver)


def parts_of(event: ChatEvent) -> Parts:
    parts = slack_chat.parts(event.thread)
    assert parts is not None
    return parts


def mentions(event: MessageCreated) -> list[tuple[str, bool, str]]:
    return [
        (m.id, m.is_self, utf16_slice(event.message.text, m.start, m.end))
        for m in event.message.mentions
    ]


def self_mention(label: str = "") -> list[tuple[str, bool, str]]:
    return [(BOT_USER_ID, True, f"<@{BOT_USER_ID}{label}>")]


@testing.live
def test_every_delivery_passes_the_webhook_and_normalises_as_slack_chat_normalize_does():
    """captured Events API deliveries / every delivery passes the webhook and normalises as
    SlackChat.normalize does"""

    @fx.gen
    def program() -> Gen[None]:
        for name in CASES:
            for delivery in captured(name):
                events = yield from deliver(delivery)
                expected = slack_chat.normalize(
                    json.loads(delivery["body"]), team_id=TEAM, bot_user_id=BOT_USER_ID
                )
                assert events == expected, name
                for event in events:
                    yield from check_event_(event)

    return program


@testing.live
def test_a_thread_reply_and_a_thread_broadcast_belong_to_the_roots_thread():
    """captured Events API deliveries / a thread reply and a thread_broadcast belong to the root's
    thread"""

    @fx.gen
    def program() -> Gen[None]:
        root = created((yield from deliveries("thread-root"))[0]).message.id
        reply = created((yield from deliveries("thread-reply"))[0])
        assert parts_of(reply) == Parts(TEAM, CHANNEL, root)
        # Slack sent a message_changed for the broadcast before the broadcast itself.
        _, broadcast = yield from deliveries("thread-broadcast")
        assert parts_of(created(broadcast)) == Parts(TEAM, CHANNEL, root)

    return program


@testing.live
def test_a_mention_only_in_code_a_block_kit_section_or_an_attachment_is_not_reported():
    """captured Events API deliveries / a mention only in code, a Block Kit section or an attachment
    is not reported"""

    @fx.gen
    def program() -> Gen[None]:
        for name in ["code-only-mention", "block-kit-mention", "attachment-mention"]:
            event = created((yield from deliveries(name))[0])
            assert event.message.mentions == (), name

    return program


def pairs_of(name: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """The ``message`` and ``app_mention`` deliveries of one message, matched by ts."""
    bodies = [json.loads(delivery["body"]) for delivery in captured(name)]
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for mention in bodies:
        if mention["event"]["type"] != "app_mention" or "edited" in mention["event"]:
            continue
        message = [
            body
            for body in bodies
            if body["event"]["type"] == "message"
            and body["event"].get("ts") == mention["event"]["ts"]
            and "hidden" not in body["event"]
        ]
        assert len(message) == 1, name
        pairs.append((message[0], mention))
    return pairs


@testing.live
def test_each_message_and_app_mention_pair_normalises_to_the_same_event():
    """captured deliveries for messages a person typed / each message and app_mention pair
    normalises to the same event"""
    found: list[str] = []
    for name in CASES:
        for message, mention in pairs_of(name):
            from_message = created(
                slack_chat.normalize(message, team_id=TEAM, bot_user_id=BOT_USER_ID)
            )
            from_mention = created(
                slack_chat.normalize(mention, team_id=TEAM, bot_user_id=BOT_USER_ID)
            )
            assert dedupe_key(from_message) == dedupe_key(from_mention), name
            assert same_message(from_message.message, from_mention.message), name
            assert copy.replace(from_message.message, raw=None) == copy.replace(
                from_mention.message, raw=None
            ), name
            assert from_message.thread == from_mention.thread, name
            label = "|janitor2" if message["event"].get("subtype") == "me_message" else ""
            assert mentions(from_message) == self_mention(label)
            found.append(name)
    assert sorted(found) == [
        "human-edit-keeps-mention",
        "human-edit-removes-mention",
        "human-file-mention",
        "human-me-message",
        "human-mention",
        "human-thread-broadcast",
    ]
    return fx.void


@testing.live
def test_an_edit_gives_nothing_including_the_app_mention_slack_sends_when_it_adds_a_mention():
    """captured deliveries for messages a person typed / an edit gives nothing, including the
    app_mention Slack sends when it adds a mention"""

    @fx.gen
    def program() -> Gen[None]:
        original, changed, mention = yield from deliveries("human-edit-adds-mention")
        assert created(original).message.mentions == ()
        assert changed == []
        assert mention == []

    return program


@testing.live
def test_reactions_with_a_skin_tone_and_a_custom_emoji():
    """captured deliveries for messages a person typed / reactions, with a skin tone and a custom
    emoji"""

    @fx.gen
    def program() -> Gen[None]:
        root = created((yield from deliveries("human-plain"))[0]).message.id
        reactions: list[ReactionAdded | ReactionRemoved] = []
        for events in (yield from deliveries("human-reactions")):
            assert len(events) == 1
            event = events[0]
            assert isinstance(event, ReactionAdded | ReactionRemoved)
            assert event.message_id == root
            reactions.append(event)
        assert [(type(event).__name__, event.emoji) for event in reactions] == [
            ("ReactionAdded", "👍"),
            ("ReactionRemoved", "👍"),
            ("ReactionAdded", "👍🏼"),
            ("ReactionRemoved", "👍🏼"),
            ("ReactionAdded", "custom:effect"),
            ("ReactionRemoved", "custom:effect"),
        ]
        assert len({dedupe_key(event) for event in reactions}) == 6

    return program


@testing.live
def test_only_the_first_click_on_stop_names_the_open_stream():
    """captured deliveries for stops / only the first click on Stop names the open stream"""

    @fx.gen
    def program() -> Gen[None]:
        results = yield from deliveries("stop-stream")
        root = created(results[0]).message.id
        stream = created(results[2])
        assert stream.message.text == ""
        stops = [
            event for events in results for event in events if isinstance(event, StopRequested)
        ]
        assert [stop.message_ids for stop in stops] == [(stream.message.id,), (), ()]
        for stop in stops:
            assert parts_of(stop) == Parts(TEAM, CHANNEL, root)
        # Each click is its own request.
        assert len({dedupe_key(stop) for stop in stops}) == 3

    return program
