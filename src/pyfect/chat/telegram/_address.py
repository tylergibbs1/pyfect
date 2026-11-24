"""Telegram addresses: ``{chatId}``, or ``{chatId}/{messageThreadId}`` for a
forum topic."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pyfect.chat import chat_thread
from pyfect.chat.chat_thread import ChatThread

PLATFORM = "telegram"

# JavaScript's ``\d`` is ASCII; Python's would take any Unicode digit.
_CHAT_ID = re.compile(r"-?[1-9][0-9]{0,15}")
_TOPIC_ID = re.compile(r"[1-9][0-9]{0,9}")
_NUMERIC_ID = re.compile(r"[1-9][0-9]{0,15}")

EPHEMERAL_PREFIX = "e"
"""The prefix of the label a private answer's message id gets:
``e{ephemeral_message_id}.{date}``."""


@dataclass(frozen=True)
class Parts:
    """The parts of a Telegram address."""

    chat_id: str
    message_thread_id: str | None = None


def thread(chat: str | int, message_thread_id: str | int | None = None) -> ChatThread:
    """The address of a chat, or of a topic in it."""
    id = str(chat) if message_thread_id is None else f"{chat}/{message_thread_id}"
    return chat_thread.make(PLATFORM, id)


def parts(address: ChatThread) -> Parts | None:
    """The parts of a Telegram address, or ``None`` for another platform's or
    a malformed one."""
    if address.platform != PLATFORM:
        return None
    segments = address.id.split("/")
    if len(segments) > 2 or _CHAT_ID.fullmatch(segments[0]) is None:
        return None
    if len(segments) == 1:
        return Parts(segments[0])
    return Parts(segments[0], segments[1]) if _TOPIC_ID.fullmatch(segments[1]) else None


def numeric_id(id: str) -> int | None:
    """A message or user id as Telegram takes it."""
    return int(id) if _NUMERIC_ID.fullmatch(id) else None
