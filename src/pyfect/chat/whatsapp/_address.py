"""WhatsApp addresses: ``{phoneNumberId}/u/{user}``, where ``user`` is a phone
number in digits or a business-scoped user id (BSUID), and the reserved
``{phoneNumberId}/g/{groupId}``."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pyfect._digits import is_digits
from pyfect.chat import chat_thread
from pyfect.chat.chat_thread import ChatThread

PLATFORM = "whatsapp"

type Kind = Literal["user", "group"]

# The grammar is read from examples, such as ``US.13491208655302741918`` and
# ``US.ENT.11815799212886844830``, not from a specification.
_BSUID = re.compile(r"[A-Z]{2}(?:\.[A-Z0-9]++)++")


@dataclass(frozen=True)
class Parts:
    """The parts of a WhatsApp address. A group address, which is reserved,
    has ``kind`` ``"group"``."""

    phone_number_id: str
    kind: Kind
    id: str


def is_bsuid(id: str) -> bool:
    """Whether ``id`` is a business-scoped user id."""
    return _BSUID.fullmatch(id) is not None


def is_user(id: str) -> bool:
    """A phone number in digits, or a BSUID."""
    return is_digits(id) or is_bsuid(id)


def thread(parts: Parts) -> ChatThread:
    """The address of ``parts``."""
    kind = "u" if parts.kind == "user" else "g"
    return chat_thread.make(PLATFORM, f"{parts.phone_number_id}/{kind}/{parts.id}")


def parts(address: ChatThread) -> Parts | None:
    """The parts of a WhatsApp address, or ``None`` for another platform's
    or a malformed one."""
    if address.platform != PLATFORM:
        return None
    segments = address.id.split("/")
    if len(segments) != 3 or not is_digits(segments[0]) or segments[2] == "":
        return None
    phone_number_id, kind, id = segments
    if kind == "u":
        return Parts(phone_number_id, "user", id) if is_user(id) else None
    if kind == "g":
        return Parts(phone_number_id, "group", id)
    return None
