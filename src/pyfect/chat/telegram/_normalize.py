"""Telegram updates as chat events (Effect's ``internal/normalize.ts``).

Entity offsets and lengths are UTF-16 code units, as are ``Mention``
offsets, so they pass through unchanged. The text is measured once, and an
``@username`` entity is compared only when its length is the bot's: a
message of many overlapping entities costs what its entities cost, never
their lengths times the text's.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from pyfect._json_value import JsonValue
from pyfect.chat.chat_event import ChatEvent, MessageCreated, ThreadKind
from pyfect.chat.chat_message import (
    Attachment,
    Author,
    ChatMessage,
    Mention,
    ReplyTo,
    utf16_length,
)
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.telegram import _address
from pyfect.chat.telegram._json import JsonObject, as_list, as_object, integer, object_, string

type Environment = Literal["production", "test"]

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_COMMAND = re.compile(r"/([A-Za-z0-9_-]{1,32})(?:@([A-Za-z0-9_]+))?")


@dataclass(frozen=True)
class Context:
    """What normalising needs to know about the bot. ``bot_username`` is
    without ``@``, from ``getMe``."""

    bot_id: str
    bot_username: str | None = None
    environment: Environment = "production"


def raw(value: object) -> JsonValue:
    """Parsed JSON, which is a ``JsonValue``, as one."""
    return cast("JsonValue", value)


def timestamp(seconds: int) -> datetime | None:
    """Telegram's seconds as a time, or ``None`` past what a ``datetime``
    holds (Effect's ``DateTime.makeUnsafe`` throws there)."""
    try:
        return _EPOCH + timedelta(seconds=seconds)
    except OverflowError:
        return None


def is_excluded(message: JsonObject) -> bool:
    """Whether a message belongs to a context this version leaves out: a
    business connection, a channel's direct messages chat, or guest mode."""
    chat = object_(message, "chat")
    return (
        "business_connection_id" in message
        or "guest_query_id" in message
        or "guest_bot_caller_user" in message
        or "guest_bot_caller_chat" in message
        or "direct_messages_topic" in message
        or (chat is not None and chat.get("is_direct_messages") is True)
    )


def is_ephemeral(message: JsonObject) -> bool:
    """A private answer or input: ``message_id`` 0 with an
    ``ephemeral_message_id``."""
    return (
        integer(message, "message_id") == 0 and integer(message, "ephemeral_message_id") is not None
    )


@dataclass(frozen=True)
class At:
    thread: ChatThread
    kind: ThreadKind


def thread_of(message: JsonObject) -> At | None:
    """The address and kind of the chat a message is in."""
    chat = object_(message, "chat")
    chat_id = integer(chat, "id")
    if chat is None or chat_id is None:
        return None
    topic = (
        integer(message, "message_thread_id") if message.get("is_topic_message") is True else None
    )
    if topic is not None:
        return At(_address.thread(chat_id, topic), "thread")
    return At(_address.thread(chat_id), "direct" if chat.get("type") == "private" else "channel")


def message_id_of(message: JsonObject) -> str | None:
    """A message's id as events carry it: the real id, or
    ``e{ephemeral_message_id}.{date}`` for a private one."""
    id = integer(message, "message_id")
    if id is None:
        return None
    if id != 0:
        return str(id)
    ephemeral = integer(message, "ephemeral_message_id")
    if ephemeral is None:
        return None
    return f"{_address.EPHEMERAL_PREFIX}{ephemeral}.{integer(message, 'date') or 0}"


def full_name(value: object) -> str:
    """A user's or private chat's first and last name, ``""`` without
    either."""
    return " ".join(
        part
        for part in (string(value, "first_name"), string(value, "last_name"))
        if part is not None
    )


def display_name(user: JsonObject) -> str | None:
    """A user's full name, else their username."""
    return full_name(user) or string(user, "username")


def _author_of(message: JsonObject, context: Context) -> Author | None:
    sender_chat = object_(message, "sender_chat")
    sender_chat_id = integer(sender_chat, "id")
    if sender_chat is not None and sender_chat_id is not None:
        return Author(
            id=str(sender_chat_id),
            name=string(sender_chat, "title"),
            is_bot=False,
            is_self=False,
        )
    sender = object_(message, "from")
    sender_id = integer(sender, "id")
    if sender is None or sender_id is None:
        return None
    return Author(
        id=str(sender_id),
        name=display_name(sender),
        is_bot=sender.get("is_bot") is True,
        is_self=str(sender_id) == context.bot_id,
    )


class _Units:
    """A text's UTF-16 code units, encoded once for the slices entities
    need."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._encoded: bytes | None = None
        self.length = utf16_length(text)

    def slice(self, start: int, end: int) -> str:
        if self._encoded is None:
            self._encoded = self._text.encode("utf-16-le", "surrogatepass")
        return self._encoded[start * 2 : end * 2].decode("utf-16-le", "surrogatepass")


def _mentions_of(text: str, entities: Sequence[object], context: Context) -> tuple[Mention, ...]:
    mentions: list[Mention] = []
    me = None if context.bot_username is None else context.bot_username.lower()
    units = _Units(text)
    for entity in entities:
        obj = as_object(entity)
        if obj is None:
            continue
        start = integer(obj, "offset")
        length = integer(obj, "length")
        if start is None or length is None or start < 0 or start + length > units.length:
            continue
        end = start + length
        if obj.get("type") == "text_mention":
            user = integer(object_(obj, "user"), "id")
            if user is not None:
                mentions.append(
                    Mention(
                        kind="user",
                        id=str(user),
                        start=start,
                        end=end,
                        is_self=str(user) == context.bot_id,
                    )
                )
        elif (
            obj.get("type") == "mention"
            and me is not None
            and length - 1 == utf16_length(me)
            and units.slice(start + 1, end).lower() == me
        ):
            mentions.append(
                Mention(kind="user", id=context.bot_id, start=start, end=end, is_self=True)
            )
    return tuple(mentions)


def _attachments_of(message: JsonObject) -> tuple[Attachment, ...]:
    out: list[Attachment] = []

    def add(file: JsonObject | None) -> None:
        id = string(file, "file_id")
        if id is None:
            return
        out.append(
            Attachment(
                id=id,
                name=string(file, "file_name"),
                content_type=string(file, "mime_type"),
                size=integer(file, "file_size"),
            )
        )

    # An animation comes with a copy of itself as ``document``, for older clients.
    animation = object_(message, "animation")
    add(animation if animation is not None else object_(message, "document"))
    for key in ("audio", "video", "voice"):
        add(object_(message, key))
    largest: JsonObject | None = None
    best = 0
    for size in as_list(message.get("photo")):
        obj = as_object(size)
        if obj is None:
            continue
        area = (integer(obj, "width") or 0) * (integer(obj, "height") or 0)
        if largest is None or area > best:
            largest, best = obj, area
    add(largest)
    return tuple(out)


def _reply_to_of(message: JsonObject, context: Context) -> ReplyTo | None:
    reply = object_(message, "reply_to_message")
    id = integer(reply, "message_id")
    if reply is None or id is None or id == 0:
        return None
    # A message in a topic replies to the topic's creation message, which is not a reply.
    if message.get("is_topic_message") is True and (
        id == integer(message, "message_thread_id") or "forum_topic_created" in reply
    ):
        return None
    author = integer(object_(reply, "from"), "id")
    if author is None:
        return ReplyTo(message_id=str(id))
    return ReplyTo(message_id=str(id), author_id=str(author), is_self=str(author) == context.bot_id)


def message_of(update: object) -> JsonObject | None:
    """The message of an update that carries one: ``message`` or
    ``channel_post``."""
    message = object_(update, "message")
    return message if message is not None else object_(update, "channel_post")


def text_of(message: JsonObject) -> tuple[str, list[object]]:
    """The text of a message, verbatim, and its entities."""
    text = string(message, "text")
    if text is not None:
        return text, as_list(message.get("entities"))
    return string(message, "caption") or "", as_list(message.get("caption_entities"))


type Created = MessageCreated | Literal["none", "invalid"]


def message_created(update: JsonObject, context: Context) -> Created:
    """The ``MessageCreated`` of an update's message, ``"none"`` for one that
    gives none, and ``"invalid"`` for a message that should give one and
    can't be read."""
    message = message_of(update)
    if message is None or is_excluded(message) or integer(message, "message_id") == 0:
        return "none"
    text, entities = text_of(message)
    attachments = _attachments_of(message)
    if text == "" and not attachments and "rich_message" not in message:
        return "none"
    at = thread_of(message)
    id = message_id_of(message)
    author = _author_of(message, context)
    date = integer(message, "date")
    when = None if date is None else timestamp(date)
    if at is None or id is None or author is None or when is None:
        return "invalid"
    return MessageCreated(
        thread=at.thread,
        kind=at.kind,
        message=ChatMessage(
            id=id,
            thread=at.thread,
            author=author,
            text=text,
            mentions=_mentions_of(text, entities, context),
            reply_to=_reply_to_of(message, context),
            attachments=attachments,
            timestamp=when,
            raw=raw(message),
        ),
        raw=raw(update),
    )


@dataclass(frozen=True)
class Command:
    """A command typed as a message: its lowercased name and what follows."""

    id: str
    text: str


def command_of(message: JsonObject, context: Context) -> Command | None:
    """The command a message holds: its first entity is a ``bot_command`` at
    offset 0, naming this bot or no bot.

    The entity's length is in UTF-16 units. The command pattern is ASCII, so
    when it matches, those units are the first ``length`` characters, and
    when the text has another character within them, it fails as it does in
    JavaScript."""
    text, entities = text_of(message)
    first = as_object(entities[0]) if entities else None
    if first is None or first.get("type") != "bot_command" or integer(first, "offset") != 0:
        return None
    length = integer(first, "length")
    if length is None or not 2 <= length <= utf16_length(text):
        return None
    match = _COMMAND.fullmatch(text, 0, length)
    if match is None:
        return None
    named = match[2]
    username = context.bot_username
    if named is not None and (username is None or named.lower() != username.lower()):
        return None
    rest = text[length:]
    if rest.startswith((" ", "\n")):
        rest = rest[1:]
    return Command(match[1].lower(), rest)


def _date_of(update: object) -> int:
    """The date of an update's message or callback message, 0 without one."""
    date = integer(message_of(update), "date")
    if date is not None:
        return date
    return integer(object_(object_(update, "callback_query"), "message"), "date") or 0


def delivery_id(update: object, *, bot_id: str, environment: Environment) -> str | None:
    """The delivery id of an update: ``{botId}.{update_id}.{date}``, with
    ``test.`` in front in the test environment."""
    id = integer(update, "update_id")
    if id is None:
        return None
    return f"{'test.' if environment == 'test' else ''}{bot_id}.{id}.{_date_of(update)}"


def normalize(update: object, context: Context) -> list[ChatEvent]:
    """The events of an update, as ``telegram_chat.normalize`` gives them."""
    obj = as_object(update)
    if obj is None:
        return []
    event = message_created(obj, context)
    return [] if isinstance(event, str) else [event]
