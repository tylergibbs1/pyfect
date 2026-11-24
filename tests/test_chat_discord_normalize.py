"""Port of Effect's ``packages/chat/discord/test/normalize.test.ts``: the pure
dispatch normaliser over the recorded gateway fixtures."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from _discord_fake import BOT_USER_ID, FIXTURES, GUILD, SCRATCH, TIM, dispatch, events

import pyfect as fx
from pyfect import testing
from pyfect._core import Effect
from pyfect.chat import chat_message
from pyfect.chat.chat_event import ChatEvent, MessageCreated, ReactionAdded
from pyfect.chat.chat_test import check_event
from pyfect.chat.discord import discord_chat
from pyfect.chat.discord.discord_gateway import GatewayDispatch
from pyfect.result import Err, Ok

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]

ROLE = "1570607256838479964"


def normalize(raw: GatewayDispatch | dict[str, Any]) -> tuple[ChatEvent, ...]:
    found = raw if isinstance(raw, GatewayDispatch) else dispatch(raw)
    result = discord_chat.normalize(found, bot_user_id=BOT_USER_ID)
    assert isinstance(result, Ok), "expected events"
    return result.value


def created(raw: GatewayDispatch | dict[str, Any]) -> MessageCreated:
    event, *rest = normalize(raw)
    assert isinstance(event, MessageCreated)
    assert rest == []
    return event


BASE = events("channel-message")[0]


@testing.effect
def test_every_recorded_dispatch_passes_check_event():
    """normalize / every recorded dispatch passes checkEvent"""

    @fx.gen
    def program() -> Gen[None]:
        count = 0
        for file in sorted((FIXTURES / "events").iterdir()):
            for raw in events(file.stem):
                result = discord_chat.normalize(
                    dispatch(raw), bot_user_id=BOT_USER_ID, channel_type=0
                )
                assert isinstance(result, Ok), file.name
                for event in result.value:
                    yield from check_event(
                        event, platform="discord", parse_mention=discord_chat.parse_mention
                    )
                    count += 1
        assert count > 35

    return program


def test_a_message_create_without_channel_type_fails_missing_channel_type() -> None:
    """normalize / a MESSAGE_CREATE without channel_type fails MissingChannelType, then takes it
    from the context"""
    raw = dispatch(events("channel-message-without-channel-type")[0])
    missing = discord_chat.normalize(raw, bot_user_id=BOT_USER_ID)
    assert isinstance(missing, Err)
    assert isinstance(missing.error, discord_chat.MissingChannelType)
    assert missing.error.channel_id == SCRATCH

    def kind(found: GatewayDispatch, channel_type: int) -> str:
        result = discord_chat.normalize(found, bot_user_id=BOT_USER_ID, channel_type=channel_type)
        assert isinstance(result, Ok)
        event = result.value[0]
        assert isinstance(event, MessageCreated)
        return event.kind

    assert [kind(raw, 11), kind(raw, 1)] == ["thread", "direct"]
    # The payload's own type wins over the context.
    assert kind(dispatch(BASE), 11) == "channel"


def test_a_message_with_an_invalid_timestamp_is_dropped_not_thrown() -> None:
    """normalize / a message with an invalid timestamp is dropped, not thrown"""
    assert normalize({"t": BASE["t"], "d": {**BASE["d"], "timestamp": "not a date"}}) == ()


def test_thread_starter_message_and_thread_created_give_no_event() -> None:
    """normalize / THREAD_STARTER_MESSAGE and THREAD_CREATED give no event"""
    dispatches = events("thread-started")
    assert sorted(raw["d"]["type"] for raw in dispatches) == [18, 21, 21]
    for raw in dispatches:
        assert normalize(raw) == ()


def test_a_persons_reply_to_the_bot_is_a_reply_not_a_mention_with_the_ping_on_or_off() -> None:
    """normalize / a person's reply to the bot is a reply, not a mention, with the ping on or off"""
    ping_on, ping_off = [raw for raw in events("reply-ping") if raw["d"]["author"]["id"] == TIM]
    own = next(raw for raw in events("reply-ping") if raw["d"]["author"]["id"] == BOT_USER_ID)

    def author(event: MessageCreated) -> tuple[str, bool, bool]:
        found = event.message.author
        return (found.id, found.is_bot, found.is_self)

    assert author(created(own)) == (BOT_USER_ID, True, True)
    # Discord lists the replied-to bot in mentions when the ping is on, with no token
    # in content.
    assert [user["id"] for user in ping_on["d"]["mentions"]] == [BOT_USER_ID]
    assert ping_off["d"]["mentions"] == []
    for raw in (ping_on, ping_off):
        event = created(raw)
        assert author(event) == (TIM, False, False)
        assert list(event.message.mentions) == []
        assert chat_message.replies_to_self(event.message)
        member = discord_chat.member(event)
        assert member is not None
        assert list(member.roles) == raw["d"]["member"]["roles"]


MENTION_CASES: list[tuple[str, list[dict[str, Any]]]] = [
    (
        "Fixture: <@!",
        [{"kind": "user", "id": BOT_USER_ID, "is_self": True, "token": f"<@!{BOT_USER_ID}>"}],
    ),
    (
        "Fixture: <@1564742987727118426> and",
        [
            {"kind": "user", "id": BOT_USER_ID, "is_self": True, "token": f"<@{BOT_USER_ID}>"},
            {"kind": "role", "id": ROLE, "is_self": False, "token": f"<@&{ROLE}>"},
            {"kind": "channel", "id": SCRATCH, "is_self": False, "token": f"<#{SCRATCH}>"},
        ],
    ),
    (
        "Fixture: @everyone that",
        [{"kind": "broadcast", "id": "everyone", "is_self": False, "token": "@everyone"}],
    ),
    # Posted without the ping, so Discord did not resolve it.
    ("Fixture: @everyone with parse", []),
]


def _mentions_of(event: MessageCreated) -> list[dict[str, Any]]:
    """Each mention with its token, sliced by its UTF-16 offsets."""
    units = event.message.text.encode("utf-16-le")
    return [
        {
            "kind": mention.kind,
            "id": mention.id,
            "is_self": mention.is_self,
            "token": units[mention.start * 2 : mention.end * 2].decode("utf-16-le"),
        }
        for mention in event.message.mentions
    ]


@pytest.mark.parametrize(("prefix", "expected"), MENTION_CASES, ids=[c[0] for c in MENTION_CASES])
def test_mentions(prefix: str, expected: list[dict[str, Any]]) -> None:
    """normalize / mentions / {prefix}"""
    found = [raw for raw in events("mentions") if str(raw["d"]["content"]).startswith(prefix)]
    assert len(found) == 1, prefix
    assert _mentions_of(created(found[0])) == expected


def test_a_token_in_code_or_escaped_is_not_a_mention() -> None:
    """normalize / mentions / a token in code or escaped is not a mention"""
    event = created(
        {
            "t": BASE["t"],
            "d": {
                **BASE["d"],
                "content": "<@1> `<@2>` ``<@3>`` ```\n<@4>\n``` \\<@5> <@6>",
                "mentions": [{"id": id} for id in ["1", "2", "3", "4", "5", "6"]],
            },
        }
    )
    assert [mention.id for mention in event.message.mentions] == ["1", "6"]


def test_reactions_give_the_emoji_custom_ones_by_name_and_the_messages_author_when_added() -> None:
    """normalize / reactions give the emoji, custom ones by name, and the message's author when
    added"""
    found = [normalize(raw)[0] for raw in events("reactions")]
    assert [
        [event.emoji, event.message_author_id]
        if isinstance(event, ReactionAdded)
        else [type(event).__name__]
        for event in found[:4]
    ] == [
        ["\U0001f44d", BOT_USER_ID],
        ["\U0001f44d\U0001f3fd", BOT_USER_ID],
        ["custom:effectchat", BOT_USER_ID],
        ["ReactionRemoved"],
    ]
    assert discord_chat.guild_id(found[0]) == GUILD
