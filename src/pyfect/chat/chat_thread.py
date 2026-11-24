"""Addresses for chat threads (Effect's ``effect/chat/ChatThread``).

A ``ChatThread`` names a channel, a thread or a direct conversation on one
platform. The address does not say which of the three it is:
``MessageCreated.kind`` and ``Chat.get_thread`` do. The ``id`` is opaque to
the core and owned by the platform's adapter: Slack's is
``{team}/{channel}`` or ``{team}/{channel}/{thread_ts}``.
"""

from __future__ import annotations

from pyfect import schema as S
from pyfect._core import Effect
from pyfect.effect import fail, succeed
from pyfect.option import Some
from pyfect.schema import transformation as T
from pyfect.schema._options import ParseOptions
from pyfect.schema.issue import InvalidValue, Issue


class ChatThread(S.Class, identifier="ChatThread"):
    """The address messages go to: a channel, a thread or a direct
    conversation on one platform."""

    platform: str
    id: str


def make(platform: str, id: str) -> ChatThread:
    """The address ``id`` on ``platform``."""
    return ChatThread(platform=platform, id=id)


def equals(self: ChatThread, that: ChatThread) -> bool:
    """Whether two addresses name the same platform and id."""
    return self.platform == that.platform and self.id == that.id


def to_string(thread: ChatThread) -> str:
    """``{platform}:{id}``, for session keys, entity ids and URLs. The format
    is frozen, because consumers persist it."""
    return f"{thread.platform}:{thread.id}"


def from_string(value: str) -> ChatThread | None:
    """The address a ``{platform}:{id}`` string names: the platform is
    everything before the first ``:``, so an id may hold ``:``. ``None``
    when either part is empty."""
    index = value.find(":")
    if index <= 0 or index == len(value) - 1:
        return None
    return make(value[:index], value[index + 1 :])


def _decode(value: str, options: ParseOptions) -> Effect[ChatThread, Issue]:
    thread = from_string(value)
    if thread is None:
        return fail(InvalidValue({"expected": "a {platform}:{id} string"}, Some(value)))
    return succeed(thread)


def _encode(thread: ChatThread, options: ParseOptions) -> Effect[str, Issue]:
    return succeed(to_string(thread))


FROM_STRING: S.DecodeToSchema[ChatThread, str] = S.String.pipe(
    S.decode_to(S.to_type(ChatThread), T.transform_effect(decode=_decode, encode=_encode))
)
"""Decodes a ``{platform}:{id}`` string into a ``ChatThread`` and encodes it
back. The string format is frozen."""

__all__ = ["FROM_STRING", "ChatThread", "equals", "from_string", "make", "to_string"]
