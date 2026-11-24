"""Inbound events from a chat platform (Effect's ``effect/chat/ChatEvent``).

Adapters deliver a ``ChatEvent`` to the consumer's ``ChatHandler``.
Delivery is at-least-once: ``dedupe_key`` gives two deliveries of one event
the same key, and the library keeps no seen-store. The union is open:
later releases add members, so a ``match`` over it needs a ``case _``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from pyfect import schema as S
from pyfect._json_value import JsonValue
from pyfect.chat import chat_thread
from pyfect.chat.chat_message import ChatMessage
from pyfect.chat.chat_thread import ChatThread

type ThreadKind = Literal["channel", "thread", "direct"]
"""What an address turned out to be."""

THREAD_KIND = S.Literals("channel", "thread", "direct")


class MessageCreated(S.TaggedClass, tag="MessageCreated", identifier="ChatEvent.MessageCreated"):
    """A message that arrived in a thread. ``thread`` equals
    ``message.thread``; ``raw`` is the delivery envelope (the message
    payload is ``message.raw``)."""

    thread: ChatThread
    kind: ThreadKind = S.field(THREAD_KIND)
    message: ChatMessage
    raw: JsonValue


class _Reaction(S.TaggedClass):
    thread: ChatThread
    message_id: str = S.field(S.String, key="messageId")
    message_author_id: str | None = S.field(S.NullOr(S.String), default=None, key="messageAuthorId")
    user_id: str = S.field(S.String, key="userId")
    emoji: str
    timestamp: datetime | None = S.field(S.NullOr(S.DateTimeUtc), default=None)
    raw: JsonValue


class ReactionAdded(_Reaction, tag="ReactionAdded", identifier="ChatEvent.ReactionAdded"):
    """A reaction a user added to a message.

    - ``thread`` is where the platform says it happened: on Slack the
      channel, even for a message in a thread.
    - ``emoji`` is a Unicode emoji, or ``custom:{name}`` for one the
      adapter's table does not know.
    - ``message_author_id`` and ``timestamp`` are ``None`` when the platform
      does not send them.
    """


class ReactionRemoved(_Reaction, tag="ReactionRemoved", identifier="ChatEvent.ReactionRemoved"):
    """A reaction a user removed from a message; the fields mean what they
    mean on ``ReactionAdded``."""


class StopRequested(S.TaggedClass, tag="StopRequested", identifier="ChatEvent.StopRequested"):
    """A user asking the bot to stop working in a thread, as Slack's stop
    button does.

    - Nothing has been stopped: the thread's streams keep taking text until
      the consumer ends them.
    - ``message_ids`` holds the streams the platform named. An empty list
      does not mean none is open: Slack names the stream only on the first
      click in a thread.
    - ``id`` is the platform's id for the request (Slack's ``event_ts``).
    """

    thread: ChatThread
    id: str
    user_id: str = S.field(S.String, key="userId")
    message_ids: tuple[str, ...] = S.field(S.Array(S.String), key="messageIds")
    raw: JsonValue


type ChatEvent = MessageCreated | ReactionAdded | ReactionRemoved | StopRequested
"""An inbound chat event."""

CHAT_EVENT: S.Bottom[ChatEvent] = cast(
    "S.Bottom[ChatEvent]",
    S.Union(MessageCreated, ReactionAdded, ReactionRemoved, StopRequested).annotate(
        identifier="ChatEvent"
    ),
)
"""The schema of an inbound chat event."""


def dedupe_key(event: ChatEvent) -> str:
    """The key two deliveries of one event share: ``message/{thread}/{id}``,
    ``reaction/{message_id}/{user_id}/{emoji}/{added|removed}`` or
    ``stop/{thread}/{id}``, with a thread in its ``{platform}:{id}`` form.
    Slack's ``message`` and ``app_mention`` for one message share a key."""
    match event:
        case MessageCreated():
            return f"message/{chat_thread.to_string(event.message.thread)}/{event.message.id}"
        case ReactionAdded():
            return f"reaction/{event.message_id}/{event.user_id}/{event.emoji}/added"
        case ReactionRemoved():
            return f"reaction/{event.message_id}/{event.user_id}/{event.emoji}/removed"
        case StopRequested():
            return f"stop/{chat_thread.to_string(event.thread)}/{event.id}"


__all__ = [
    "CHAT_EVENT",
    "THREAD_KIND",
    "ChatEvent",
    "MessageCreated",
    "ReactionAdded",
    "ReactionRemoved",
    "StopRequested",
    "ThreadKind",
    "dedupe_key",
]
