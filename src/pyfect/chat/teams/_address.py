"""Teams addresses: the Bot Framework conversation id as it is. A channel
thread is the channel's id followed by ``;messageid={root}``."""

from __future__ import annotations

from dataclasses import dataclass

from pyfect._digits import is_digits
from pyfect.chat import chat_thread
from pyfect.chat.chat_event import ThreadKind
from pyfect.chat.chat_thread import ChatThread

PLATFORM = "teams"

MAX_ID_LENGTH = 256
"""The longest id the adapter puts in a request: a conversation, message,
user or tenant id. A longer one fails ``InvalidRequest`` before the call."""

_REPLY_CHAIN = ";messageid="
_CHANNEL_SUFFIXES = ("@thread.tacv2", "@thread.skype")


@dataclass(frozen=True)
class Parts:
    """The parts of a Teams address: ``conversation_id`` as the Connector
    takes it, ``base`` without a reply chain suffix, and ``root``, the root
    message of a channel thread."""

    conversation_id: str
    base: str
    root: str | None = None


def thread(conversation_id: str) -> ChatThread:
    """The address of a conversation."""
    return chat_thread.make(PLATFORM, conversation_id)


def is_root(text: str) -> bool:
    """Whether ``text`` is a message id that can root a reply chain: ASCII digits."""
    return is_digits(text)


def parts(address: ChatThread) -> Parts | None:
    """The parts of a Teams address, or ``None`` for another platform's or a malformed one."""
    id = address.id
    if address.platform != PLATFORM or not 0 < len(id) <= MAX_ID_LENGTH:
        return None
    at = id.find(_REPLY_CHAIN)
    if at == -1:
        return Parts(id, id)
    base, root = id[:at], id[at + len(_REPLY_CHAIN) :]
    if not base or not is_root(root):
        return None
    return Parts(id, base, root)


def base_conversation(conversation_id: str) -> str:
    """The conversation id without its reply chain suffix."""
    at = conversation_id.find(_REPLY_CHAIN)
    return conversation_id if at == -1 else conversation_id[:at]


def thread_of(base: str, root: str) -> ChatThread:
    """The thread under ``root`` in the channel ``base``."""
    return thread(f"{base}{_REPLY_CHAIN}{root}")


def is_direct(conversation_id: str) -> bool:
    """A personal chat: a one-to-one conversation with the bot."""
    return conversation_id.startswith("a:")


def is_channel(conversation_id: str) -> bool:
    """A team channel, as opposed to a group or personal chat."""
    return base_conversation(conversation_id).endswith(_CHANNEL_SUFFIXES)


def kind(conversation_id: str) -> ThreadKind:
    """The kind of address ``conversation_id`` is."""
    if _REPLY_CHAIN in conversation_id:
        return "thread"
    return "direct" if is_direct(conversation_id) else "channel"
