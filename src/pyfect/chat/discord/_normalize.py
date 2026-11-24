"""Discord's gateway and REST payloads as chat messages and events: pure, and
reading each payload once, at the boundary, into the fields it uses."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

import pyfect.schema as S
from pyfect._json_value import JsonValue
from pyfect.chat import chat_thread
from pyfect.chat.chat_event import (
    ChatEvent,
    MessageCreated,
    ReactionAdded,
    ReactionRemoved,
    ThreadKind,
)
from pyfect.chat.chat_message import Attachment, Author, ChatMessage, Mention, ReplyTo
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.discord import _json, _mentions
from pyfect.chat.discord._json import Invalid, JsonObject

PLATFORM = "discord"

MESSAGE_TYPES = frozenset({0, 19, 20, 23})
"""The message types that are a message: ``DEFAULT``, ``REPLY``,
``CHAT_INPUT_COMMAND`` and ``CONTEXT_MENU_COMMAND``. Inbound and history both
read it, and a type Discord adds later stays out."""

REPLY = 19
THREAD_STARTER_MESSAGE = 21
"""The thread starter placeholder in a thread started from a message."""

SNOWFLAKE = re.compile(r"[0-9]{1,20}")
"""A Discord id: ASCII digits, at most 20 (a 64-bit number)."""

_DISCORD_EPOCH = 1_420_070_400_000
"""The start of Discord's snowflake clock, in Unix milliseconds."""

_decode_timestamp = S.decode_unknown_option(S.DateTimeUtcFromString)

_MAX_TIMESTAMP_LENGTH = 64
"""An ISO 8601 timestamp is about 32 characters; a longer one is not parsed."""


def thread(channel_id: str) -> ChatThread:
    """The address of a Discord channel, thread or direct: its channel id."""
    return chat_thread.make(PLATFORM, channel_id)


def is_address(address: ChatThread) -> bool:
    """Whether ``address`` is a Discord address."""
    return address.platform == PLATFORM and SNOWFLAKE.fullmatch(address.id) is not None


def kind_of(channel_type: float) -> ThreadKind:
    """Discord's channel type as a ``kind``: 10, 11 and 12 are threads, 1 and
    3 directs, everything else a channel, unknown types included."""
    if channel_type in (10, 11, 12):
        return "thread"
    if channel_type in (1, 3):
        return "direct"
    return "channel"


def is_thread_type(channel_type: float) -> bool:
    return kind_of(channel_type) == "thread"


def parse_timestamp(text: str) -> datetime | None:
    """An ISO 8601 timestamp as a UTC ``datetime``; ``None`` when it is not one."""
    if len(text) > _MAX_TIMESTAMP_LENGTH:
        return None
    found = _decode_timestamp(text)
    return None if found is None else found.value


# --- decoding ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UserFields:
    id: str
    username: str | None
    global_name: str | None
    bot: bool | None


def decode_user(obj: JsonObject) -> UserFields:
    return UserFields(
        id=_json.req_str(obj, "id"),
        username=_json.opt_str(obj, "username"),
        global_name=_json.opt_str(obj, "global_name"),
        bot=_json.opt_bool(obj, "bot"),
    )


def decode_option[A](decode: Callable[[JsonObject], A], raw: object) -> A | None:
    """``decode(raw)``, or ``None`` when ``raw`` is not an object or a field
    has the wrong type."""
    obj = _json.as_object(raw)
    if obj is None:
        return None
    try:
        return decode(obj)
    except Invalid:
        return None


@dataclass(frozen=True, slots=True)
class _AttachmentFields:
    id: str
    filename: str | None
    content_type: str | None
    size: int | None


@dataclass(frozen=True, slots=True)
class ReferenceFields:
    type: float | None
    message_id: str | None
    channel_id: str | None


@dataclass(frozen=True, slots=True)
class MessageFields:
    """What the normaliser reads from a message."""

    id: str
    channel_id: str
    type: float
    content: str | None
    timestamp: datetime
    author: UserFields
    webhook_id: str | None
    channel_type: float | None
    nick: str | None
    mentions: frozenset[str]
    mention_roles: frozenset[str]
    mention_everyone: bool
    attachments: tuple[_AttachmentFields, ...]
    message_reference: ReferenceFields | None
    replied_author: str | None


def _decode_message(obj: JsonObject) -> MessageFields:
    timestamp = parse_timestamp(_json.req_str(obj, "timestamp"))
    if timestamp is None:
        raise Invalid
    member = _json.opt_obj(obj, "member")
    if member is not None:
        _json.opt_str_list(member, "roles")
    reference = _json.opt_obj(obj, "message_reference")
    referenced = _json.opt_obj(obj, "referenced_message")
    referenced_author = None if referenced is None else _json.opt_obj(referenced, "author")
    _json.opt_str(obj, "guild_id")
    return MessageFields(
        id=_json.req_str(obj, "id"),
        channel_id=_json.req_str(obj, "channel_id"),
        type=_json.req_number(obj, "type"),
        content=_json.opt_str(obj, "content"),
        timestamp=timestamp,
        author=decode_user(_json.req_obj(obj, "author")),
        webhook_id=_json.opt_str(obj, "webhook_id"),
        channel_type=_json.opt_number(obj, "channel_type"),
        nick=None if member is None else _json.opt_str(member, "nick"),
        mentions=frozenset(
            _json.req_str(user, "id") for user in _json.objects(_json.opt_list(obj, "mentions"))
        ),
        mention_roles=frozenset(_json.opt_str_list(obj, "mention_roles") or ()),
        mention_everyone=_json.opt_bool(obj, "mention_everyone") is True,
        attachments=tuple(
            _AttachmentFields(
                id=_json.req_str(item, "id"),
                filename=_json.opt_str(item, "filename"),
                content_type=_json.opt_str(item, "content_type"),
                size=_json.opt_int(item, "size"),
            )
            for item in _json.objects(_json.opt_list(obj, "attachments"))
        ),
        message_reference=None
        if reference is None
        else ReferenceFields(
            type=_json.opt_number(reference, "type"),
            message_id=_json.opt_str(reference, "message_id"),
            channel_id=_json.opt_str(reference, "channel_id"),
        ),
        replied_author=None
        if referenced_author is None
        else _json.req_str(referenced_author, "id"),
    )


def decode_message_fields(raw: object) -> MessageFields | None:
    """A message payload's fields; ``None`` when it is not a message payload."""
    return decode_option(_decode_message, raw)


@dataclass(frozen=True, slots=True)
class _ReactionFields:
    user_id: str
    channel_id: str
    message_id: str
    message_author_id: str | None
    emoji_id: str | None
    emoji_name: str | None


def _decode_reaction(obj: JsonObject) -> _ReactionFields:
    member = _json.opt_obj(obj, "member")
    if member is not None:
        _json.opt_str(member, "nick")
        _json.opt_str_list(member, "roles")
    _json.opt_str(obj, "guild_id")
    emoji = _json.req_obj(obj, "emoji")
    return _ReactionFields(
        user_id=_json.req_str(obj, "user_id"),
        channel_id=_json.req_str(obj, "channel_id"),
        message_id=_json.req_str(obj, "message_id"),
        message_author_id=_json.opt_str(obj, "message_author_id"),
        emoji_id=_json.opt_str(emoji, "id"),
        emoji_name=_json.opt_str(emoji, "name"),
    )


# --- messages ------------------------------------------------------------------------


def attachment_id(message_id: str, id: str) -> str:
    """An attachment's id: the message's id and the attachment's, since a
    download reads the message again."""
    return f"{message_id}/{id}"


def parse_attachment_id(id: str) -> tuple[str, str] | None:
    """The message id and attachment id of an attachment's id."""
    parts = id.split("/")
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0], parts[1]
    return None


def _mentions_of(fields: MessageFields, text: str, bot_user_id: str) -> tuple[Mention, ...]:
    """The mentions in ``content``: a token outside code that Discord says
    resolved, through ``mentions`` for a user, ``mention_roles`` for a role
    and ``mention_everyone`` for ``@everyone`` and ``@here``. A channel token
    has no confirming field, so the token alone counts."""

    def resolved(token: _mentions.Token) -> bool:
        match token.kind:
            case "user":
                return token.id in fields.mentions
            case "role":
                return token.id in fields.mention_roles
            case "broadcast":
                return fields.mention_everyone
            case "channel":
                return True

    found = [token for token in _mentions.tokens(text) if resolved(token)]
    offsets = _mentions.utf16_offsets(text, [p for t in found for p in (t.start, t.end)])
    return tuple(
        Mention(
            kind=token.kind,
            id=token.id,
            start=offsets[2 * i],
            end=offsets[2 * i + 1],
            is_self=token.kind == "user" and token.id == bot_user_id,
        )
        for i, token in enumerate(found)
    )


def message(raw: object, fields: MessageFields, *, bot_user_id: str) -> ChatMessage | None:
    """A message payload, from the gateway or REST, as a ``ChatMessage``;
    ``None`` for a type that is not a message."""
    if fields.type not in MESSAGE_TYPES:
        return None
    text = fields.content or ""
    webhook = _json.non_empty(fields.webhook_id)
    author = fields.author
    name = (
        _json.non_empty(fields.nick)
        or _json.non_empty(author.global_name)
        or _json.non_empty(author.username)
        if webhook is None
        else _json.non_empty(author.username)
    )
    reference = fields.message_reference
    reply_id = (
        _json.non_empty(reference.message_id)
        if fields.type == REPLY and reference is not None and (reference.type or 0) == 0
        else None
    )
    replied = fields.replied_author
    return ChatMessage(
        id=fields.id,
        thread=thread(fields.channel_id),
        author=Author(
            id=webhook or author.id,
            name=name,
            is_bot=webhook is not None or author.bot is True,
            is_self=webhook is None and author.id == bot_user_id,
        ),
        text=text,
        mentions=_mentions_of(fields, text, bot_user_id),
        reply_to=None
        if reply_id is None
        else ReplyTo(
            message_id=reply_id,
            author_id=replied,
            is_self=None if replied is None else replied == bot_user_id,
        ),
        attachments=tuple(
            Attachment(
                id=attachment_id(fields.id, attachment.id),
                name=_json.non_empty(attachment.filename),
                content_type=_json.non_empty(attachment.content_type),
                size=attachment.size,
            )
            for attachment in fields.attachments
        ),
        timestamp=fields.timestamp,
        raw=cast("JsonValue", raw),
    )


def to_message(raw: object, *, bot_user_id: str) -> ChatMessage | None:
    """A message payload as a ``ChatMessage``, or ``None`` when it is not one."""
    fields = decode_message_fields(raw)
    return None if fields is None else message(raw, fields, bot_user_id=bot_user_id)


def emoji_of(emoji_id: str | None, emoji_name: str | None) -> str | None:
    """A reaction's emoji: the Unicode emoji, or ``custom:{name}`` for a guild's own."""
    if _json.non_empty(emoji_id) is None:
        return _json.non_empty(emoji_name)
    return f"custom:{_json.non_empty(emoji_name) or emoji_id}"


# --- dispatches ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Events:
    events: tuple[ChatEvent, ...]


@dataclass(frozen=True, slots=True)
class MissingChannelType:
    channel_id: str


type Normalized = Events | MissingChannelType

_NONE = Events(())


def normalize(  # noqa: PLR0911
    t: str, d: object, *, bot_user_id: str, channel_type: float | None = None
) -> Normalized:
    """One gateway dispatch as events, or the channel whose type is missing."""
    raw = cast("JsonValue", d)
    match t:
        case "MESSAGE_CREATE":
            fields = decode_message_fields(d)
            # The channel id becomes the thread's address: one that is not a snowflake
            # is not Discord's.
            if (
                fields is None
                or fields.type not in MESSAGE_TYPES
                or SNOWFLAKE.fullmatch(fields.channel_id) is None
            ):
                return _NONE
            found_type = fields.channel_type if fields.channel_type is not None else channel_type
            if found_type is None:
                return MissingChannelType(fields.channel_id)
            created = message(d, fields, bot_user_id=bot_user_id)
            if created is None:
                return _NONE
            return Events(
                (
                    MessageCreated(
                        thread=created.thread,
                        kind=kind_of(found_type),
                        message=created,
                        raw=raw,
                    ),
                )
            )
        case "MESSAGE_REACTION_ADD" | "MESSAGE_REACTION_REMOVE":
            reaction = decode_option(_decode_reaction, d)
            emoji = None if reaction is None else emoji_of(reaction.emoji_id, reaction.emoji_name)
            if (
                reaction is None
                or emoji is None
                or SNOWFLAKE.fullmatch(reaction.channel_id) is None
            ):
                return _NONE
            event_type = ReactionAdded if t == "MESSAGE_REACTION_ADD" else ReactionRemoved
            return Events(
                (
                    event_type(
                        thread=thread(reaction.channel_id),
                        message_id=reaction.message_id,
                        message_author_id=_json.non_empty(reaction.message_author_id),
                        user_id=reaction.user_id,
                        emoji=emoji,
                        raw=raw,
                    ),
                )
            )
        case _:
            return _NONE


HANDLED = frozenset({"MESSAGE_CREATE", "MESSAGE_REACTION_ADD", "MESSAGE_REACTION_REMOVE"})
"""The dispatches ``normalize`` reads."""


# --- accessors -----------------------------------------------------------------------


def guild_id_of(raw: object) -> str | None:
    guild = _json.string_field(raw, "guild_id")
    return guild or None


@dataclass(frozen=True, slots=True)
class Member:
    """The member on a message's or added reaction's ``raw``."""

    guild_id: str
    roles: tuple[str, ...]
    nick: str | None = None


def member_of(raw: object) -> Member | None:
    guild_id = guild_id_of(raw)
    obj = _json.as_object(raw)
    member = None if obj is None else _json.as_object(obj.get("member"))
    if guild_id is None or member is None:
        return None
    roles = tuple(role for role in _json.as_list(member.get("roles")) if isinstance(role, str))
    nick = member.get("nick")
    return Member(guild_id, roles, nick if isinstance(nick, str) and nick else None)


# --- snowflakes ----------------------------------------------------------------------


def snowflake_millis(id: str) -> int:
    """When a snowflake was made, in Unix milliseconds. ``id`` matches ``SNOWFLAKE``."""
    return (int(id) >> 22) + _DISCORD_EPOCH


def snowflake_time(id: str) -> datetime | None:
    """When a snowflake was made; ``None`` for an id that is not one."""
    if SNOWFLAKE.fullmatch(id) is None:
        return None
    try:
        return datetime.fromtimestamp(snowflake_millis(id) / 1000, UTC)
    except (OverflowError, ValueError, OSError):
        return None


def compare_ids(a: str, b: str) -> Literal[-1, 0, 1]:
    """Orders two snowflakes: by number, and two ids that are not both
    snowflakes by length, then text."""
    if SNOWFLAKE.fullmatch(a) is not None and SNOWFLAKE.fullmatch(b) is not None:
        x, y = int(a), int(b)
        return -1 if x < y else 1 if x > y else 0
    ka, kb = (len(a), a), (len(b), b)
    return -1 if ka < kb else 1 if ka > kb else 0
