"""``teams_chat.normalize``: where a message is addressed, its mentions in
UTF-16 offsets, reactions, and the bounded scan for mention tokens."""

from __future__ import annotations

from typing import Any

from _teams_fake import APP_ID, activity

from pyfect.chat.chat_event import MessageCreated, ReactionAdded, ReactionRemoved
from pyfect.chat.chat_message import Mention
from pyfect.chat.teams import _normalize, teams_chat


def _mention(token: str, id: str = "29:u", **mentioned: object) -> dict[str, Any]:
    return {"type": "mention", "text": token, "mentioned": {"id": id, **mentioned}}


def _message(**overrides: object) -> MessageCreated:
    [event] = teams_chat.normalize(activity(**overrides), app_id=APP_ID)
    assert isinstance(event, MessageCreated)
    return event


def test_a_channel_post_is_addressed_to_the_channel_and_a_reply_to_its_thread():
    """a channel post is addressed to the channel, and a reply to its thread"""
    channel = "19:abc@thread.tacv2"
    post = _message(
        id="123", conversation={"id": f"{channel};messageid=123", "conversationType": "channel"}
    )
    assert (post.thread, post.kind) == (teams_chat.thread(channel), "channel")
    reply = _message(
        id="456", conversation={"id": f"{channel};messageid=123", "conversationType": "channel"}
    )
    assert (reply.thread, reply.kind) == (teams_chat.thread(f"{channel};messageid=123"), "thread")
    direct = _message()
    assert direct.kind == "direct"


def test_locates_mentions_in_utf16_units_in_order_and_skips_one_not_in_the_text():
    """locates mentions in UTF-16 units, in order, and skips one not in the text"""
    created = _message(
        text="\U0001f600 <at>Bot</at> and <at>Ann</at>",
        entities=[
            _mention("<at>Bot</at>", f"28:{APP_ID}"),
            _mention("<at>Gone</at>", "29:gone"),
            _mention("<at>Ann</at>", "29:ann", aadObjectId="ann"),
            {"type": "clientInfo", "locale": "en-US"},
        ],
    )
    assert created.message.mentions == (
        Mention(kind="user", id=f"28:{APP_ID}", start=3, end=15, is_self=True),
        Mention(kind="user", id="ann", start=20, end=32, is_self=False),
    )


def test_stops_locating_mentions_past_the_scan_budget():
    """stops locating mentions past the scan budget"""
    text = "x" * 100 + "<at>u</at>"
    missing = [_mention(f"<at>{index}</at>") for index in range(_normalize.SCAN_FACTOR * 2)]
    created = _message(text=text, entities=[*missing, _mention("<at>u</at>")])
    assert created.message.mentions == ()
    within = _message(text=text, entities=[*missing[:10], _mention("<at>u</at>")])
    assert [mention.start for mention in within.message.mentions] == [100]


def test_reactions_are_emoji_for_the_six_documented_types_and_custom_otherwise():
    """reactions are emoji for the six documented types, and custom otherwise"""
    events = teams_chat.normalize(
        activity(
            type="messageReaction",
            replyToId="1800000000000",
            reactionsAdded=[{"type": "like"}, {"type": "1f4af_hundredpointssymbol"}],
            reactionsRemoved=[{"type": "heart"}],
        ),
        app_id=APP_ID,
    )
    reactions = [event for event in events if isinstance(event, ReactionAdded | ReactionRemoved)]
    assert len(reactions) == len(events)
    assert [(type(event), event.emoji) for event in reactions] == [
        (ReactionAdded, "\U0001f44d"),
        (ReactionAdded, "custom:1f4af_hundredpointssymbol"),
        (ReactionRemoved, "❤️"),
    ]


def test_a_targeted_message_a_card_submit_and_a_message_without_a_date_give_no_event():
    """a targeted message, a card submit and a message without a date give no event"""
    for body in (
        activity(recipient={"id": f"28:{APP_ID}", "isTargeted": True}),
        activity(value={"effect": "token"}),
        activity(timestamp="not a date"),
        activity(type="conversationUpdate"),
        [activity()],
    ):
        assert teams_chat.normalize(body, app_id=APP_ID) == []


def test_parse_mention_reads_no_id_from_the_tag():
    """parseMention reads no id from the tag"""
    assert teams_chat.parse_mention("<at>Ann</at>") is None
