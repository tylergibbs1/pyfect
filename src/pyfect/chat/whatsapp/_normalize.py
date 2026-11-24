"""A webhook delivery's JSON as chat events, clicks and updates: pure, and
never raising on what Meta (or anyone) sends."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime, timedelta
from typing import cast

from pyfect._json_value import JsonValue
from pyfect.chat.chat_event import MessageCreated, ReactionAdded
from pyfect.chat.chat_interaction import ButtonClicked, SelectChanged
from pyfect.chat.chat_message import Attachment, Author, ChatMessage, ReplyTo
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.whatsapp import _address, _json
from pyfect.chat.whatsapp._actions import parse_wire_id
from pyfect.chat.whatsapp._address import Parts
from pyfect.chat.whatsapp._errors import GraphError, reason_for_graph_error
from pyfect.chat.whatsapp._json import JsonObject
from pyfect.chat.whatsapp.whatsapp_update import (
    Alias,
    AliasStatus,
    Status,
    StatusValue,
    UserIdChanged,
    WhatsAppUpdate,
)

type Inbound = MessageCreated | ReactionAdded | ButtonClicked | SelectChanged | WhatsAppUpdate
"""What one webhook delivery holds, in order: messages and reactions, clicks,
and updates."""

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_NOT_DIGITS = re.compile(r"[^0-9]")
_SECONDS = re.compile(r"[0-9]{1,15}(?:\.[0-9]{1,9})?")
"""Seconds as Meta sends them; fifteen digits is past any date."""
_MEDIA = ("image", "video", "audio", "document", "sticker")
_STATUSES: frozenset[str] = frozenset({"sent", "delivered", "read", "failed"})


def _raw(value: object) -> JsonValue:
    """Parsed JSON, which is a ``JsonValue``, as one."""
    return cast("JsonValue", value)


def _digits(phone: str) -> str:
    """A phone number without its formatting: Meta may show
    ``display_phone_number`` with ``+``, spaces or dashes."""
    return _NOT_DIGITS.sub("", phone)


def _timestamp(value: str | None) -> datetime | None:
    """Meta's seconds as a time, or ``None`` for anything else, also past
    what a ``datetime`` holds."""
    if value is None or _SECONDS.fullmatch(value) is None:
        return None
    try:
        return _EPOCH + timedelta(milliseconds=math.floor(float(value) * 1000))
    except OverflowError:
        return None


def _user_thread(phone_number_id: str, user: str) -> ChatThread:
    return _address.thread(Parts(phone_number_id, "user", user))


def is_group_message(message: object) -> bool:
    """Whether a message is from a group, which the adapter does not support
    yet."""
    obj = _json.as_object(message)
    return obj is not None and (
        obj.get("group_id") is not None
        or _json.string(_json.object_(obj, "context"), "group_id") is not None
    )


def group_messages(envelope: object) -> int:
    """How many messages and statuses of a delivery are from groups."""
    count = 0
    obj = _json.as_object(envelope)
    if obj is None:
        return count
    for entry in _json.as_list(obj.get("entry")):
        entry_obj = _json.as_object(entry)
        for change in _json.as_list(None if entry_obj is None else entry_obj.get("changes")):
            value = _json.object_(change, "value")
            if value is None:
                continue
            count += sum(
                1 for message in _json.as_list(value.get("messages")) if is_group_message(message)
            )
            count += sum(
                1
                for status in _json.as_list(value.get("statuses"))
                if (status_obj := _json.as_object(status)) is not None
                and status_obj.get("recipient_type") == "group"
            )
    return count


class _Contacts:
    """A change's contacts, indexed once: Effect searches the list once per
    message, which is quadratic in a batch of many messages and contacts."""

    def __init__(self, value: JsonObject) -> None:
        self.all = [
            c for contact in _json.as_list(value.get("contacts")) if (c := _json.as_object(contact))
        ]
        self._by_user_id: dict[object, int] = {}
        self._by_phone: dict[object, int] = {}
        for index, contact in enumerate(self.all):
            self._by_user_id.setdefault(_hashable(contact.get("user_id")), index)
            self._by_phone.setdefault(_hashable(contact.get("wa_id")), index)

    def sender(self, user_id: str | None, phone: str | None) -> JsonObject | None:
        """The first contact naming the sender's BSUID or phone number, else
        the first contact, as Effect's ``find`` with its fallback."""
        found = [
            index
            for index in (
                None if user_id is None else self._by_user_id.get(user_id),
                None if phone is None else self._by_phone.get(phone),
            )
            if index is not None
        ]
        if found:
            return self.all[min(found)]
        return self.all[0] if self.all else None


def _hashable(value: object) -> object:
    return value if isinstance(value, str) else None


def _from_system(  # noqa: PLR0917
    contacts: _Contacts,
    metadata: JsonObject,
    phone_number_id: str,
    message: JsonObject,
    id: str,
    at: datetime | None,
) -> list[Inbound]:
    """A changed phone number or BSUID, addressed by the user's new id."""
    system = _json.object_(message, "system")
    change = _json.string(system, "type")
    if change not in ("user_changed_number", "user_changed_user_id"):
        return []
    user_id = _json.string(system, "user_id")
    phone = _json.string(system, "wa_id")
    next_id = user_id if user_id is not None else phone
    if next_id is None or not _address.is_user(next_id):
        return []
    raw = _raw({"metadata": metadata, "contacts": contacts.all, "messages": [message]})
    return [
        UserIdChanged(
            thread=_user_thread(phone_number_id, next_id),
            id=id,
            change=change,
            user_id=user_id,
            previous_user_id=_json.string(system, "previous_user_id"),
            phone=phone,
            previous_phone=_json.string(message, "from"),
            timestamp=at,
            raw=raw,
        )
    ]


def _from_message(  # noqa: PLR0911
    contacts: _Contacts, metadata: JsonObject, phone_number_id: str, message: object
) -> list[Inbound]:
    obj = _json.as_object(message)
    if obj is None or is_group_message(obj):
        return []
    id = _json.string(obj, "id")
    at = _timestamp(_json.string(obj, "timestamp"))
    type_ = _json.string(obj, "type")
    # A changed BSUID can arrive with no sender at all: the new id is only in `system`.
    if type_ == "system":
        return [] if id is None else _from_system(contacts, metadata, phone_number_id, obj, id, at)
    sender = _json.string(obj, "from")
    sender_user_id = _json.string(obj, "from_user_id")
    contact = contacts.sender(sender_user_id, sender)
    user = sender_user_id or _json.string(contact, "user_id") or sender
    if id is None or user is None or not _address.is_user(user):
        return []
    thread = _user_thread(phone_number_id, user)
    raw = _raw(
        {"metadata": metadata, "contacts": [] if contact is None else [contact], "messages": [obj]}
    )
    if type_ == "reaction":
        reaction = _json.object_(obj, "reaction")
        emoji = _json.string(reaction, "emoji")
        message_id = _json.string(reaction, "message_id")
        # An empty emoji is a removed reaction, which is dropped.
        if emoji is None or message_id is None:
            return []
        return [
            ReactionAdded(
                thread=thread,
                message_id=message_id,
                user_id=user,
                emoji=emoji,
                timestamp=at,
                raw=raw,
            )
        ]
    if type_ == "interactive":
        interactive = _json.object_(obj, "interactive")
        reply = _json.object_(interactive, "button_reply") or _json.object_(
            interactive, "list_reply"
        )
        wire = _json.string(reply, "id")
        parsed = None if wire is None else parse_wire_id(wire)
        message_id = _json.string(_json.object_(obj, "context"), "id")
        if parsed is None or message_id is None:
            return []
        if parsed.kind == "select":
            return [
                SelectChanged(
                    id=parsed.id,
                    value=parsed.value or "",
                    thread=thread,
                    message_id=message_id,
                    user_id=user,
                    raw=raw,
                )
            ]
        return [
            ButtonClicked(
                id=parsed.id,
                value=parsed.value,
                thread=thread,
                message_id=message_id,
                user_id=user,
                raw=raw,
            )
        ]
    if type_ in ("unsupported", "request_welcome"):
        return []
    attachments: list[Attachment] = []
    text = (
        _json.string(_json.object_(obj, "text"), "body")
        or _json.string(_json.object_(obj, "button"), "text")
        or ""
    )
    for kind in _MEDIA:
        item = _json.object_(obj, kind)
        media_id = _json.string(item, "id")
        if media_id is None:
            continue
        attachments.append(
            Attachment(
                id=media_id,
                name=_json.string(item, "filename"),
                content_type=_json.string(item, "mime_type"),
            )
        )
        text = _json.string(item, "caption") or text
    context = _json.object_(obj, "context")
    reply_id = _json.string(context, "id")
    quoted = _json.string(context, "from")
    business = _json.string(metadata, "display_phone_number") or ""
    reply_to = (
        None
        if reply_id is None
        else ReplyTo(
            message_id=reply_id,
            is_self=None if quoted is None else _digits(quoted) == _digits(business),
        )
    )
    chat_message = ChatMessage(
        id=id,
        thread=thread,
        author=Author(
            id=user,
            name=_json.string(_json.object_(contact, "profile"), "name"),
            is_bot=False,
            is_self=False,
        ),
        text=text,
        mentions=(),
        reply_to=reply_to,
        attachments=tuple(attachments),
        timestamp=_EPOCH if at is None else at,
        raw=_raw(obj),
    )
    return [MessageCreated(thread=thread, kind="direct", message=chat_message, raw=raw)]


def _from_status(metadata: JsonObject, phone_number_id: str, status: object) -> list[Inbound]:
    obj = _json.as_object(status)
    if obj is None or obj.get("recipient_type") == "group":
        return []
    message_id = _json.string(obj, "id")
    value = _json.string(obj, "status")
    phone = _json.string(obj, "recipient_id")
    user_id = _json.string(obj, "recipient_user_id")
    user = user_id if user_id is not None else phone
    if message_id is None or value not in _STATUSES or user is None or not _address.is_user(user):
        return []
    status_value: StatusValue = value  # pyright: ignore[reportAssignmentType]
    thread = _user_thread(phone_number_id, user)
    raw = _raw({"metadata": metadata, "statuses": [obj]})
    error = next(
        (e for item in _json.as_list(obj.get("errors")) if (e := _json.as_object(item))), None
    )
    code = _json.code(error)
    out: list[Inbound] = [
        Status(
            thread=thread,
            message_id=message_id,
            status=status_value,
            timestamp=_timestamp(_json.string(obj, "timestamp")),
            reason=reason_for_graph_error(GraphError(code), write=False, cause=error)
            if status_value == "failed" and code is not None and error is not None
            else None,
            phone=phone,
            user_id=user_id,
            raw=raw,
        )
    ]
    if status_value != "failed" and phone is not None and user_id is not None:
        alias_status: AliasStatus = status_value
        out.append(
            Alias(
                thread=thread,
                phone=phone,
                user_id=user_id,
                message_id=message_id,
                status=alias_status,
                raw=raw,
            )
        )
    return out


def normalize(envelope: object, *, phone_number_id: str) -> list[Inbound]:
    """What a delivery holds, in order. A change for another phone number,
    and a group message, give nothing."""
    out: list[Inbound] = []
    obj = _json.as_object(envelope)
    if obj is None or obj.get("object") != "whatsapp_business_account":
        return out
    for entry in _json.as_list(obj.get("entry")):
        entry_obj = _json.as_object(entry)
        for change in _json.as_list(None if entry_obj is None else entry_obj.get("changes")):
            change_obj = _json.as_object(change)
            if change_obj is None or change_obj.get("field") != "messages":
                continue
            value = _json.object_(change_obj, "value")
            metadata = _json.object_(value, "metadata")
            if (
                value is None
                or metadata is None
                or _json.string(metadata, "phone_number_id") != phone_number_id
            ):
                continue
            contacts = _Contacts(value)
            for message in _json.as_list(value.get("messages")):
                out.extend(_from_message(contacts, metadata, phone_number_id, message))
            for status in _json.as_list(value.get("statuses")):
                out.extend(_from_status(metadata, phone_number_id, status))
    return out
