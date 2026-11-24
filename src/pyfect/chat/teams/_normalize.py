"""Verified Bot Framework activities as chat events."""

from __future__ import annotations

from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from pyfect._js_date import parse as js_date_parse
from pyfect._json_value import JsonValue
from pyfect.chat.chat_event import (
    ChatEvent,
    MessageCreated,
    ReactionAdded,
    ReactionRemoved,
    ThreadKind,
)
from pyfect.chat.chat_message import Attachment, Author, ChatMessage, Mention, MentionKind
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.teams import _address, _download, _json
from pyfect.chat.teams._json import JsonObject


@dataclass(frozen=True, kw_only=True)
class Context:
    """What normalising needs from the layer: the bot's app id, and the
    cloud's hosts for classifying attachments."""

    app_id: str
    connector_hosts: AbstractSet[str]
    file_host_suffixes: Sequence[str]


def bot_id(app_id: str) -> str:
    """The bot's own Connector id."""
    return f"28:{app_id}"


def user_id(account: object) -> str | None:
    """The public id of a user: the Entra object id for a person, the
    Connector id (``29:…``, ``28:…``) for a bot or anyone without one."""
    return _json.string(account, "aadObjectId") or _json.string(account, "id")


def is_targeted(activity: JsonObject) -> bool:
    """Whether the activity was sent to the bot alone, as a targeted message:
    ``recipient.isTargeted``."""
    recipient = _json.object_(activity, "recipient")
    return recipient is not None and recipient.get("isTargeted") is True


@dataclass(frozen=True)
class Located:
    thread: ChatThread
    kind: ThreadKind


def locate(
    conversation_id: str | None, message_id: str | None, conversation_type: str | None = None
) -> Located | None:
    """Where a message lives, and what kind of address it is. A channel
    post's conversation names the post itself as its reply chain root: such
    a post is addressed to the channel, and is the opener of the thread
    under it."""
    if conversation_id is None:
        return None
    parts = _address.parts(_address.thread(conversation_id))
    if parts is None:
        return None
    if parts.root is not None and parts.root == message_id:
        return Located(_address.thread(parts.base), "channel")
    kind: ThreadKind = (
        "thread"
        if parts.root is not None
        else "direct"
        if conversation_type == "personal"
        else "channel"
    )
    return Located(_address.thread(conversation_id), kind)


def thread_of(activity: JsonObject) -> Located | None:
    """Where an activity's message lives."""
    conversation = _json.object_(activity, "conversation")
    return locate(
        _json.string(conversation, "id"),
        _json.string(activity, "id"),
        _json.string(conversation, "conversationType"),
    )


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MAX_TIMESTAMP_LENGTH = 64
"""Longer than any date Teams writes; a longer ``timestamp`` is no date."""


def timestamp(activity: JsonObject) -> datetime | None:
    """The activity's ``timestamp``, read as ``new Date(text)`` reads it."""
    value = _json.string(activity, "timestamp")
    if value is None or len(value) > _MAX_TIMESTAMP_LENGTH:
        return None
    millis = js_date_parse(value)
    if millis is None:
        return None
    try:
        return _EPOCH + timedelta(milliseconds=millis)
    except OverflowError:
        return None


def _mention_kind(mentioned: JsonObject, conversation_id: str) -> MentionKind:
    if _json.string(mentioned, "type") == "tag":
        return "role"
    id = _json.string(mentioned, "id") or ""
    if id == _address.base_conversation(conversation_id) or id.startswith("19:"):
        return "channel"
    return "user"


SCAN_FACTOR = 64
"""How many times the text's length locating mentions may scan. A found
token moves the scan on, so only tokens that are not in the text spend it;
past it, the remaining entities are left out, as unfound ones are."""


class _Utf16:
    """Code point offsets into ``text`` as UTF-16 offsets, read in
    increasing order, each in time linear in the distance moved."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._ascii = text.isascii()
        self._at = 0
        self._extra = 0

    def offset(self, at: int) -> int:
        if self._ascii:
            return at
        self._extra += sum(1 for char in self._text[self._at : at] if ord(char) > 0xFFFF)
        self._at = at
        return at + self._extra


def _mentions(activity: JsonObject, text: str, self_id: str) -> tuple[Mention, ...]:
    """The mention entities, in order, located in ``text`` by their ``<at>``
    text. An entity whose text is not found is left out."""
    entities = _json.as_list(activity.get("entities"))
    if entities is None:
        return ()
    conversation_id = _json.string(_json.object_(activity, "conversation"), "id") or ""
    out: list[Mention] = []
    offsets = _Utf16(text)
    budget = SCAN_FACTOR * (len(text) + 1)
    missing: set[str] = set()
    start_from = 0
    for entity in entities:
        record = _json.as_object(entity)
        if record is None or record.get("type") != "mention":
            continue
        mentioned = _json.object_(record, "mentioned")
        token = _json.string(record, "text")
        id = user_id(mentioned)
        if mentioned is None or token is None or id is None or token in missing:
            continue
        if budget <= 0:
            break
        start = text.find(token, start_from)
        budget -= (len(text) if start == -1 else start + len(token)) - start_from
        if start == -1:
            missing.add(token)
            continue
        start_from = start + len(token)
        out.append(
            Mention(
                kind=_mention_kind(mentioned, conversation_id),
                id=id,
                start=offsets.offset(start),
                end=offsets.offset(start_from),
                is_self=_json.string(mentioned, "id") == self_id,
            )
        )
    return tuple(out)


def _attachments(activity: JsonObject, context: Context) -> tuple[Attachment, ...]:
    attachments = _json.as_list(activity.get("attachments"))
    service_url = _json.string(activity, "serviceUrl")
    if attachments is None or service_url is None:
        return ()
    conversation_type = _json.string(_json.object_(activity, "conversation"), "conversationType")
    out: list[Attachment] = []
    for attachment in attachments:
        record = _json.as_object(attachment)
        if record is not None and record.get("contentType") == "text/html":
            continue
        classified = _download.classify(
            attachment,
            service_url=service_url,
            conversation_type=conversation_type,
            connector_hosts=context.connector_hosts,
            file_host_suffixes=context.file_host_suffixes,
        )
        if classified is not None:
            out.append(classified)
    return tuple(out)


def message(activity: JsonObject, context: Context) -> ChatMessage | None:
    """A ``message`` activity as a ``ChatMessage``.

    - ``text`` is Teams' ``text`` as delivered, with ``<at>…</at>`` for each
      mention, which is where ``mentions`` point.
    - The author id follows ``user_id``. ``raw`` keeps the Connector id.
    """
    id = _json.string(activity, "id")
    sender = _json.object_(activity, "from")
    author = user_id(sender)
    at = thread_of(activity)
    sent = timestamp(activity)
    if id is None or author is None or at is None or sent is None:
        return None
    self_id = bot_id(context.app_id)
    connector_id = _json.string(sender, "id") or ""
    text = activity.get("text")
    text = text if isinstance(text, str) else ""
    return ChatMessage(
        id=id,
        thread=at.thread,
        author=Author(
            id=author,
            name=_json.string(sender, "name"),
            is_bot=connector_id.startswith("28:"),
            is_self=connector_id == self_id,
        ),
        text=text,
        mentions=_mentions(activity, text, self_id),
        attachments=_attachments(activity, context),
        timestamp=sent,
        raw=cast("JsonValue", activity),
    )


_REACTION_EMOJI = {
    "like": "\U0001f44d",
    "heart": "❤️",
    "laugh": "\U0001f606",
    "surprised": "\U0001f62e",
    "sad": "\U0001f622",
    "angry": "\U0001f621",
}


def emoji(type: str) -> str:
    """A Teams reaction type as an emoji: the six documented types as
    Unicode, any other as ``custom:{type}``."""
    return _REACTION_EMOJI.get(type, f"custom:{type}")


def _reactions(activity: JsonObject) -> list[ChatEvent]:
    message_id = _json.string(activity, "replyToId")
    user = user_id(_json.object_(activity, "from"))
    at = thread_of(activity)
    if message_id is None or user is None or at is None:
        return []
    sent = timestamp(activity)
    raw = cast("JsonValue", activity)
    out: list[ChatEvent] = []
    for key, added in (("reactionsAdded", True), ("reactionsRemoved", False)):
        for reaction in _json.as_list(activity.get(key)) or []:
            type = _json.string(reaction, "type")
            if type is None:
                continue
            event = ReactionAdded if added else ReactionRemoved
            out.append(
                event(
                    thread=at.thread,
                    message_id=message_id,
                    user_id=user,
                    emoji=emoji(type),
                    timestamp=sent,
                    raw=raw,
                )
            )
    return out


def normalize(activity: object, context: Context) -> list[ChatEvent]:
    """A verified, untargeted activity as zero or more events. A ``message``
    carrying a card submit (``value``) is an interaction, not a message, and
    gives none here."""
    record = _json.as_object(activity)
    if record is None or is_targeted(record):
        return []
    match record.get("type"):
        case "message":
            if "value" in record:
                return []
            at = thread_of(record)
            created = message(record, context)
            if at is None or created is None:
                return []
            return [
                MessageCreated(
                    thread=at.thread, kind=at.kind, message=created, raw=cast("JsonValue", record)
                )
            ]
        case "messageReaction":
            return _reactions(record)
        case _:
            return []
