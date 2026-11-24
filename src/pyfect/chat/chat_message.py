"""Messages read from a chat platform (Effect's ``effect/chat/ChatMessage``).

A ``ChatMessage`` has the same shape on every read path: inbound events,
``Chat.fetch_message`` and ``Chat.history``. Its ``text`` is the platform's
own content string, verbatim, and its mentions are data with offsets into
that text. ``text`` is a different format from outbound Markdown and cannot
be posted back as is.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pyfect import schema as S
from pyfect._json_value import JsonValue
from pyfect.chat.chat_thread import ChatThread


class Author(S.Class, identifier="ChatMessage.Author"):
    """The author of a message. ``name`` is whatever the payload carries,
    with no lookup. Other bots' messages have ``is_bot``; ``is_self`` marks
    the bot's own."""

    id: str
    name: str | None = None
    is_bot: bool = S.field(S.Boolean, key="isBot")
    is_self: bool = S.field(S.Boolean, key="isSelf")


type MentionKind = Literal["user", "role", "channel", "broadcast"]


class Mention(S.Class, identifier="ChatMessage.Mention"):
    """A mention inside a message's text. ``start`` and ``end`` are offsets
    into ``ChatMessage.text`` in UTF-16 code units, as in Effect, so
    ``utf16_slice(text, start, end)`` is the platform's own token. ``id`` is
    the platform id, or ``here``, ``channel`` or ``everyone`` for a
    broadcast."""

    kind: MentionKind
    id: str
    start: int
    end: int
    is_self: bool = S.field(S.Boolean, key="isSelf")


class Attachment(S.Class, identifier="ChatMessage.Attachment"):
    """A file attached to a message. It never carries a URL:
    ``Chat.download`` resolves the id again."""

    id: str
    name: str | None = None
    content_type: str | None = S.field(S.NullOr(S.String), default=None, key="contentType")
    size: int | None = None


class ReplyTo(S.Class, identifier="ChatMessage.ReplyTo"):
    """The message a message replies to. ``author_id`` is there when the
    platform says who wrote it; ``is_self`` says whether that is the bot. A
    write reads ``message_id`` only."""

    message_id: str = S.field(S.String, key="messageId")
    author_id: str | None = S.field(S.NullOr(S.String), default=None, key="authorId")
    is_self: bool | None = S.field(S.NullOr(S.Boolean), default=None, key="isSelf")


class ChatMessage(S.Class, identifier="ChatMessage"):
    """A message read from a chat platform.

    - ``thread`` is the address it was posted to, the same on every read
      path. A message a thread hangs off stays in the parent:
      ``Chat.start_thread(message.thread, message.id)`` leads to its thread.
    - ``text`` is the platform's content verbatim, mention tokens and code
      fences in place, except that Slack renders the bot's own ``rich_text``
      blocks as Markdown.
    - ``raw`` is the platform's message payload as JSON.
    """

    id: str
    thread: ChatThread
    author: Author
    text: str
    mentions: tuple[Mention, ...]
    reply_to: ReplyTo | None = S.field(S.NullOr(ReplyTo), default=None, key="replyTo")
    attachments: tuple[Attachment, ...]
    timestamp: datetime = S.field(S.DateTimeUtc)
    raw: JsonValue


def mentions_self(message: ChatMessage) -> bool:
    """Whether the message mentions the bot. A reply to the bot is not a
    mention (see ``replies_to_self``)."""
    return any(mention.is_self for mention in message.mentions)


def replies_to_self(message: ChatMessage) -> bool:
    """Whether the message replies to one of the bot's own messages. False
    when the platform does not say who wrote the message replied to; a Slack
    thread reply carries no ``reply_to``."""
    return message.reply_to is not None and message.reply_to.is_self is True


def utf16_slice(text: str, start: int, end: int) -> str:
    """``text[start:end]`` with ``start`` and ``end`` in UTF-16 code units,
    the unit of ``Mention`` offsets."""
    encoded = text.encode("utf-16-le", "surrogatepass")
    return encoded[start * 2 : end * 2].decode("utf-16-le", "surrogatepass")


def utf16_length(text: str) -> int:
    """How many UTF-16 code units ``text`` takes (JavaScript's ``length``)."""
    return len(text) + sum(1 for c in text if ord(c) > 0xFFFF)


__all__ = [
    "Attachment",
    "Author",
    "ChatMessage",
    "Mention",
    "MentionKind",
    "ReplyTo",
    "mentions_self",
    "replies_to_self",
    "utf16_length",
    "utf16_slice",
]
