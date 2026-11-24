"""What WhatsApp reports beside messages (Effect's ``@effect/chat-whatsapp/WhatsAppUpdate``):
delivery statuses, a user's changed id, and the link between a phone number and
a business-scoped user id. They go to the ``on_update`` of
``whatsapp_chat.layer_webhook`` and ``WhatsAppChatService.receive``, not to the
``ChatHandler``."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from pyfect import schema as S
from pyfect._json_value import JsonValue
from pyfect.chat.chat_error import CHAT_ERROR_REASON, AnyReason
from pyfect.chat.chat_thread import ChatThread

type StatusValue = Literal["sent", "delivered", "read", "failed"]
type AliasStatus = Literal["sent", "delivered", "read"]
type Change = Literal["user_changed_number", "user_changed_user_id"]


class Status(S.TaggedClass, tag="Status", identifier="WhatsAppUpdate.Status"):
    """The status of a message the business sent.

    - ``thread`` is the recipient's address, with the business-scoped user id
      when the status carries one and the phone number when it does not.
    - ``message_id`` is the id ``post`` gave. A ``failed`` status has the
      ``reason`` for Meta's error, mapped as a refused call is.
    - ``phone`` and ``user_id`` are the recipient's phone number and
      business-scoped user id, each when the status carries it.
    - ``raw`` is the change's ``metadata`` and the one status.
    """

    thread: ChatThread
    message_id: str = S.field(S.String, key="messageId")
    status: StatusValue = S.field(S.Literals("sent", "delivered", "read", "failed"))
    timestamp: datetime | None = S.field(S.NullOr(S.DateTimeUtc), default=None)
    reason: AnyReason | None = S.field(S.NullOr(CHAT_ERROR_REASON), default=None)
    phone: str | None = None
    user_id: str | None = S.field(S.NullOr(S.String), default=None, key="userId")
    raw: JsonValue


class UserIdChanged(S.TaggedClass, tag="UserIdChanged", identifier="WhatsAppUpdate.UserIdChanged"):
    """A user's changed phone number or business-scoped user id, from a
    ``system`` message.

    - ``thread`` is the user's new address. A thread kept under the old one no
      longer receives messages from the user.
    - ``id`` is the system message's id. ``change`` is Meta's ``type``:
      ``user_changed_number`` or ``user_changed_user_id``.
    - ``user_id``, ``previous_user_id`` and ``phone`` are there when Meta
      sends them. ``previous_phone`` is the system message's ``from``.
    """

    thread: ChatThread
    id: str
    change: Change = S.field(S.Literals("user_changed_number", "user_changed_user_id"))
    user_id: str | None = S.field(S.NullOr(S.String), default=None, key="userId")
    previous_user_id: str | None = S.field(S.NullOr(S.String), default=None, key="previousUserId")
    phone: str | None = None
    previous_phone: str | None = S.field(S.NullOr(S.String), default=None, key="previousPhone")
    timestamp: datetime | None = S.field(S.NullOr(S.DateTimeUtc), default=None)
    raw: JsonValue


class Alias(S.TaggedClass, tag="Alias", identifier="WhatsAppUpdate.Alias"):
    """A phone number and a business-scoped user id that name one user.

    - Given for every ``sent``, ``delivered`` or ``read`` status that carries
      both, beside the ``Status``. Nothing is remembered between batches, so
      the same pair comes again and again.
    - A message posted to a phone number address reports back with the user's
      business-scoped id, which is how a consumer learns that the inbound
      address and the phone number address are one user. The adapter never
      rewrites an address.
    """

    thread: ChatThread
    phone: str
    user_id: str = S.field(S.String, key="userId")
    message_id: str = S.field(S.String, key="messageId")
    status: AliasStatus = S.field(S.Literals("sent", "delivered", "read"))
    raw: JsonValue


type WhatsAppUpdate = Status | UserIdChanged | Alias
"""Any update."""

WHATSAPP_UPDATE: S.Bottom[WhatsAppUpdate] = cast(
    "S.Bottom[WhatsAppUpdate]",
    S.Union(Status, UserIdChanged, Alias).annotate(identifier="WhatsAppUpdate"),
)
"""The schema of any update."""

__all__ = [
    "WHATSAPP_UPDATE",
    "Alias",
    "AliasStatus",
    "Change",
    "Status",
    "StatusValue",
    "UserIdChanged",
    "WhatsAppUpdate",
]
