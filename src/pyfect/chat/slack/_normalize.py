"""Slack payloads as chat messages and events."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime, timedelta
from typing import cast

from pyfect._json_value import JsonValue
from pyfect.chat.chat_event import (
    ChatEvent,
    MessageCreated,
    ReactionAdded,
    ReactionRemoved,
    StopRequested,
    ThreadKind,
)
from pyfect.chat.chat_message import Attachment, Author, ChatMessage
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.slack import _emoji, _json, _mentions, _rich_text
from pyfect.chat.slack._address import Parts, is_direct_channel, thread
from pyfect.chat.slack._json import JsonObject

MESSAGE_SUBTYPES = frozenset({"file_share", "thread_broadcast", "bot_message", "me_message"})
"""The message subtypes that count as a message, for inbound events and for
every read path alike. Anything else is rejected, so a subtype Slack adds
later stays out until someone decides about it."""

TS = re.compile(r"[0-9]+\.[0-9]+")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_SAFE_INTEGER = 2**53 - 1


def from_seconds(value: float) -> datetime | None:
    """The instant ``value``, a count of seconds since the epoch, to the millisecond;
    ``None`` past what a ``datetime`` holds."""
    try:
        return _EPOCH + timedelta(milliseconds=math.floor(value * 1000))
    except (OverflowError, ValueError):
        return None


def timestamp(ts: str) -> datetime | None:
    """When a Slack ``ts`` was sent."""
    return from_seconds(float(ts))


def _author_name(message: JsonObject) -> str | None:
    profile = _json.object_(message, "user_profile")
    return (
        _json.string(profile, "display_name")
        or _json.string(profile, "real_name")
        or _json.string(profile, "name")
        or _json.string(_json.object_(message, "bot_profile"), "name")
        or _json.string(message, "username")
    )


def _attachments(message: JsonObject) -> tuple[Attachment, ...]:
    out: list[Attachment] = []
    for file in _json.as_list(message.get("files")):
        id = _json.string(file, "id")
        if id is None:
            continue
        size = _json.number(file, "size")
        whole = size is not None and size.is_integer() and 0 <= size <= _SAFE_INTEGER
        out.append(
            Attachment(
                id=id,
                name=_json.string(file, "name"),
                content_type=_json.string(file, "mimetype"),
                size=int(size) if whole and size is not None else None,
            )
        )
    return tuple(out)


def message(raw: object, *, team: str, channel: str, bot_user_id: str) -> ChatMessage | None:
    """A Slack message payload as a ``ChatMessage``, from an event or any
    read path. ``None`` when it is not a message: a subtype off the list, or
    no author.

    - The address is the channel when ``thread_ts`` is missing or equal to
      ``ts``, and the thread otherwise.
    - A ``bot_message`` has ``bot_id`` and no ``user``: ``author.id`` is the
      ``bot_id``, with ``is_bot`` true.
    - ``text`` is Slack's field as stored, except for a message the bot
      itself wrote that has a ``rich_text`` block: its ``text`` is rendered
      from the blocks as Markdown, and its mentions are the mention elements
      outside code. Slack's field stays on ``raw``.
    """
    obj = _json.as_object(raw)
    if obj is None:
        return None
    subtype = _json.string(obj, "subtype")
    if subtype is not None and subtype not in MESSAGE_SUBTYPES:
        return None
    ts = _json.string(obj, "ts")
    sent = None if ts is None or TS.fullmatch(ts) is None else timestamp(ts)
    if ts is None or sent is None:
        return None
    user = _json.string(obj, "user")
    bot_id = _json.string(obj, "bot_id")
    author_id = user or bot_id
    if author_id is None:
        return None
    thread_ts = _json.string(obj, "thread_ts")
    is_self = user is not None and user == bot_user_id
    blocks = obj.get("blocks")
    rendered = (
        _rich_text.render(_json.as_list(blocks), bot_user_id)
        if is_self and _rich_text.has_rich_text(blocks)
        else None
    )
    stored = obj.get("text")
    text = rendered.text if rendered is not None else stored if isinstance(stored, str) else ""
    return ChatMessage(
        id=ts,
        thread=thread(Parts(team, channel, None if thread_ts in (None, ts) else thread_ts)),
        author=Author(
            id=author_id,
            name=_author_name(obj),
            is_bot=bot_id is not None or subtype == "bot_message" or user == bot_user_id,
            is_self=is_self,
        ),
        text=text,
        mentions=tuple(_mentions.extract(text, blocks, bot_user_id))
        if rendered is None
        else rendered.mentions,
        attachments=_attachments(obj),
        timestamp=sent,
        raw=cast("JsonValue", raw),
    )


def _kind_of(address: ChatThread, channel: str, channel_type: str | None) -> ThreadKind:
    if len(address.id.split("/")) == 3:
        return "thread"
    if channel_type in ("im", "mpim") or is_direct_channel(channel):
        return "direct"
    return "channel"


def _for_workspace(envelope: JsonObject, team_id: str) -> bool:
    if envelope.get("team_id") == team_id:
        return True
    return any(
        _json.any_string(authorization, "team_id") == team_id
        for authorization in _json.as_list(envelope.get("authorizations"))
    )


def _envelope_raw(envelope: JsonObject) -> JsonValue:
    """The envelope as ``raw``, without the deprecated verification
    ``token``."""
    return cast("JsonValue", {key: value for key, value in envelope.items() if key != "token"})


def emoji(name: str) -> str:
    """An emoji name as Slack writes it, as Unicode, or ``custom:{name}``."""
    return _emoji.from_name(name) or f"custom:{name}"


def normalize(envelope: object, *, team_id: str, bot_user_id: str) -> list[ChatEvent]:  # noqa: PLR0911
    """The events in an ``event_callback`` envelope."""
    obj = _json.as_object(envelope)
    if obj is None or obj.get("type") != "event_callback" or not _for_workspace(obj, team_id):
        return []
    event = _json.as_object(obj.get("event"))
    if event is None:
        return []
    raw = _envelope_raw(obj)
    team = team_id
    kind = event.get("type")
    if kind in ("message", "app_mention"):
        if kind == "app_mention" and "edited" in event:
            return []
        channel = _json.string(event, "channel")
        if channel is None:
            return []
        normalized = message(event, team=team, channel=channel, bot_user_id=bot_user_id)
        if normalized is None:
            return []
        return [
            MessageCreated(
                thread=normalized.thread,
                kind=_kind_of(normalized.thread, channel, _json.string(event, "channel_type")),
                message=normalized,
                raw=raw,
            )
        ]
    if kind in ("reaction_added", "reaction_removed"):
        item = _json.as_object(event.get("item"))
        if item is None or item.get("type") != "message":
            return []
        channel = _json.string(item, "channel")
        message_id = _json.string(item, "ts")
        user_id = _json.string(event, "user")
        name = _json.string(event, "reaction")
        if channel is None or message_id is None or user_id is None or name is None:
            return []
        event_ts = _json.string(event, "event_ts")
        when = None if event_ts is None or TS.fullmatch(event_ts) is None else timestamp(event_ts)
        reaction = ReactionAdded if kind == "reaction_added" else ReactionRemoved
        return [
            reaction(
                thread=thread(Parts(team, channel)),
                message_id=message_id,
                message_author_id=_json.string(event, "item_user"),
                user_id=user_id,
                emoji=emoji(name),
                timestamp=when,
                raw=raw,
            )
        ]
    if kind == "agent_session_stopped":
        channel = _json.string(event, "channel")
        thread_ts = _json.string(event, "thread_ts")
        user_id = _json.string(event, "user")
        id = _json.string(event, "event_ts")
        if channel is None or thread_ts is None or user_id is None or id is None:
            return []
        streams = event.get("streaming_message_ts")
        message_ids = (
            tuple(ts for ts in _json.as_list(streams) if isinstance(ts, str) and ts)
            if _json.is_list(streams)
            else (streams,)
            if isinstance(streams, str) and streams
            else ()
        )
        return [
            StopRequested(
                thread=thread(Parts(team, channel, thread_ts)),
                id=id,
                user_id=user_id,
                message_ids=message_ids,
                raw=raw,
            )
        ]
    return []
