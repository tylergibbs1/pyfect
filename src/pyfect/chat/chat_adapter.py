"""What a chat platform adapter implements (Effect's ``effect/chat/ChatAdapter``).

An adapter is a set of ``Ops`` plus a static ``Descriptor`` of what the
platform supports. Adapters register in the ``Registry``, which ``Chat``
routes through by ``thread.platform``.

- Every op exists on every platform. Where the platform has no equivalent
  the op fails with ``Unsupported``, naming the capability.
- A post notifies nobody unless asked: mentions in Markdown do not notify.
- Length is checked before the call, with ``check_message_length``, in the
  unit the descriptor's ``measure`` counts.
- Adapters retry ``"retry"`` failures with ``retry_safe`` and never retry
  ``"uncertain"`` ones.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Never, Protocol, overload

import pyfect as fx
from pyfect._core import Effect
from pyfect._json_value import JsonValue
from pyfect.chat.chat_error import Capability, ChatError, TooLarge
from pyfect.chat.chat_event import ThreadKind
from pyfect.chat.chat_message import Attachment, ChatMessage, ReplyTo
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.chat_ui import Action
from pyfect.context import Reference, Tag
from pyfect.duration import Duration, millis
from pyfect.layer import Layer
from pyfect.layer import effect_discard as _layer_effect_discard
from pyfect.scope import Scope
from pyfect.stream import Stream

if TYPE_CHECKING:
    from pyfect.chat.chat_interaction import Defer

type Measure = Callable[[str, Sequence[Action]], int]
"""What a Markdown string costs, with the ``actions`` its message carries:
pure, an upper bound of what the adapter sends, subadditive, ASCII letters
at one each, and ``measure(md, ()) == measure(md)``."""


@dataclass(frozen=True, kw_only=True)
class Limits:
    """A platform's limits, each in the platform's own unit.

    - ``message_length`` is the limit for one message, less any fixed
      overhead the text does not carry.
    - ``min_write_interval`` is the default floor between two writes to one
      thread, for streamed and multi-part posts.
    - ``stream_length`` / ``stream_age`` apply to native streams only;
      ``stream_length`` is never more than ``message_length``.
    - ``actions_per_message`` and ``action_data_length`` are there exactly
      with ``buttons``, ``modal_metadata_length`` and ``modal_fields`` with
      ``modals``, ``follow_up_age`` with ``commands``.
    """

    message_length: int
    files_per_message: int
    upload_bytes: int
    min_write_interval: Duration
    stream_length: int | None = None
    stream_age: Duration | None = None
    actions_per_message: int | None = None
    action_data_length: int | None = None
    modal_metadata_length: int | None = None
    modal_fields: int | None = None
    follow_up_age: Duration | None = None


@dataclass(frozen=True, kw_only=True)
class Descriptor:
    """Static description of a platform: its capabilities and limits,
    readable without a call. An op whose capability is missing fails
    ``Unsupported``. ``measure`` gives what Markdown (and a message's
    ``actions``) costs against ``limits.message_length`` and
    ``limits.stream_length``."""

    platform: str
    capabilities: frozenset[Capability]
    measure: Measure
    limits: Limits


@dataclass(frozen=True)
class File:
    """A file to upload with a post."""

    name: str
    content_type: str
    content: bytes


@dataclass(frozen=True)
class Posted:
    """The message a successful post created."""

    id: str
    thread: ChatThread
    timestamp: datetime


@dataclass(frozen=True, kw_only=True)
class ThreadInfo:
    """What the platform says about an address."""

    thread: ChatThread
    kind: ThreadKind
    name: str | None = None
    topic: str | None = None
    parent: ChatThread | None = None
    created_at: datetime | None = None
    raw: JsonValue = None


@dataclass(frozen=True, kw_only=True)
class User:
    """A user as the platform reports them. ``name`` is the guild nick when
    ``in_`` was given and the platform has one; ``raw`` is the platform's
    own record, for what the model has no field for."""

    id: str
    name: str
    is_bot: bool
    is_self: bool
    raw: JsonValue


type Direction = Literal["backward", "forward"]


@dataclass(frozen=True)
class AppendResult:
    """What a native append did: ``"open"`` added the text apart from its
    last ``held`` characters (code points), ``"stopped"`` added nothing because a
    user stopped the stream, ``"closed"`` added nothing because it is closed
    or expired."""

    state: Literal["open", "stopped", "closed"]
    held: int


class Ops(Protocol):
    """The operations of one platform; ``Chat`` has the same ops, routed by
    ``thread.platform``.

    - ``post`` takes standard Markdown that must fit
      ``limits.message_length``: it never splits or truncates, and fails
      ``TooLarge`` without calling the platform. Mentions notify nobody, and
      no link preview shows unless the adapter's scoped options ask.
    - ``fetch_message`` fails ``NotFound`` for a message that is gone.
    - ``history`` pages lazily: ``"backward"`` runs newest to oldest,
      ``"forward"`` oldest to newest, and ``from_`` is exclusive. A thread's
      oldest message is its opener, the one message not addressed to the
      thread.
    - ``download`` fails ``TooLarge`` as soon as more than ``max_bytes``
      arrive, and streams.
    - ``start_thread`` is get-or-create: the thread under ``message_id``.
    - ``opener`` is the message a thread hangs off; ``None`` for a channel
      or direct address, or when it was deleted.
    - ``actions`` are a flat list of elements beside the Markdown. An
      ``edit`` replaces the whole message, so one without ``actions``
      removes them.
    - ``follow_up`` sends the answer a command's ``Defer`` promised. It is
      never retried, takes no files, and fails ``NotFound`` with detail
      ``interaction_expired`` past ``limits.follow_up_age``.
    """

    def post(
        self,
        thread: ChatThread,
        *,
        markdown: str,
        reply_to: ReplyTo | None = None,
        files: Sequence[File] = (),
        actions: Sequence[Action] = (),
    ) -> Effect[Posted, ChatError]: ...

    def edit(
        self, thread: ChatThread, message_id: str, *, markdown: str, actions: Sequence[Action] = ()
    ) -> Effect[None, ChatError]: ...

    def delete(self, thread: ChatThread, message_id: str) -> Effect[None, ChatError]: ...

    def fetch_message(
        self, thread: ChatThread, message_id: str
    ) -> Effect[ChatMessage, ChatError]: ...

    def history(
        self, thread: ChatThread, *, direction: Direction, from_: str | None = None
    ) -> Stream[ChatMessage, ChatError]: ...

    def download(
        self, thread: ChatThread, attachment: Attachment, *, max_bytes: int
    ) -> Stream[bytes, ChatError]: ...

    def start_thread(
        self, thread: ChatThread, message_id: str, *, name: str | None = None
    ) -> Effect[ChatThread, ChatError]: ...

    def get_thread(self, thread: ChatThread) -> Effect[ThreadInfo, ChatError]: ...

    def opener(self, thread: ChatThread) -> Effect[ChatMessage | None, ChatError]: ...

    def get_user(self, id: str, *, in_: ChatThread | None = None) -> Effect[User, ChatError]: ...

    def follow_up(
        self, deferred: Defer, *, markdown: str, actions: Sequence[Action] = ()
    ) -> Effect[None, ChatError]: ...


class NativeStream(Protocol):
    """A platform's native streaming of one message, used by
    ``chat_markdown.stream`` when present. Adapter-facing, not on ``Chat``.

    - ``start`` fails ``Unsupported`` when the platform refuses the feature
      for this thread or recipient; the caller then posts and edits. It
      sends all of ``markdown``.
    - ``append`` is never retried by the adapter. ``held`` counts the
      trailing characters it could not send yet (an unclosed ``<``, a high
      surrogate); the caller sends them again at the front of the next
      append. ``flush`` holds nothing back. ``TooLarge`` means nothing was
      added and the stream is still open.
    - ``stop`` closes the stream; ``stopped`` says whether a user had
      clicked stop. On a closed stream it gives ``False``.
    - ``continues`` names the previous part's message, so per-reply state
      such as a rate limit's backoff carries over a rotation.
    """

    def start(
        self,
        thread: ChatThread,
        *,
        markdown: str,
        reply_to: ReplyTo | None = None,
        recipient: str | None = None,
        continues: str | None = None,
    ) -> Effect[Posted, ChatError]: ...

    def append(
        self, thread: ChatThread, message_id: str, markdown: str, *, flush: bool = False
    ) -> Effect[AppendResult, ChatError]: ...

    def stop(
        self, thread: ChatThread, message_id: str, *, end: Literal["done", "rotating"]
    ) -> Effect[bool, ChatError]: ...


class ChatAdapter(Ops, Protocol):
    """What an adapter builds: the platform's ops, its descriptor and, when
    the platform has one, its native stream."""

    @property
    def descriptor(self) -> Descriptor: ...

    @property
    def native_stream(self) -> NativeStream | None: ...


class RegistryService(Protocol):
    """Holds the adapters by platform. ``get`` fails ``NoAdapter`` for a
    platform with none; registering a second adapter for a platform
    replaces the first."""

    def register(self, adapter: ChatAdapter) -> Effect[None]: ...

    def get(self, platform: str) -> Effect[ChatAdapter, ChatError]: ...

    @property
    def descriptors(self) -> Effect[tuple[Descriptor, ...]]: ...


class Registry(Tag[RegistryService], key="effect/chat/ChatAdapter/Registry"):
    """The adapters by platform; ``Chat.layer`` provides it."""


class RetriesDisabled(Reference[bool], key="effect/chat/Chat/RetriesDisabled"):
    """Set by ``chat.without_retries``: adapter calls make one attempt."""

    @classmethod
    def default(cls) -> bool:
        return False


@overload
def layer[E = Never](adapter: Effect[ChatAdapter, E, Scope]) -> Layer[Never, E, Registry]: ...
@overload
def layer[E, R](adapter: Effect[ChatAdapter, E, Scope | R]) -> Layer[Never, E, R | Registry]: ...
def layer[E, R](adapter: Effect[ChatAdapter, E, Scope | R]) -> Layer[Never, E, R | Registry]:
    """The layer that registers ``adapter`` in the ``Registry``. A platform
    that is off is a layer left out."""

    @fx.gen
    def register():
        registry = yield from Registry()
        made = yield from adapter
        yield from registry.register(made)

    return _layer_effect_discard(register)


def check_message_length(
    descriptor: Descriptor, op: str, markdown: str, actions: Sequence[Action] = ()
) -> Effect[None, ChatError]:
    """Fails ``TooLarge`` when ``markdown`` (with its ``actions``) does not
    fit ``limits.message_length``, measured with the descriptor's
    ``measure``. Pass the string the adapter is about to send, after
    escaping."""
    if descriptor.measure(markdown, actions) <= descriptor.limits.message_length:
        return fx.void
    return fx.fail(
        ChatError(
            platform=descriptor.platform,
            op=op,
            reason=TooLarge(subject="text", detail="message_too_long"),
        )
    )


_MAX_RETRIES = 3
_BASE_DELAY = millis(500)


def _retrying[A, R](effect: Effect[A, ChatError, R], attempt: int) -> Effect[A, ChatError, R]:
    return effect.catch_if(
        lambda error: error.retry == "retry" and attempt < _MAX_RETRIES,
        lambda error: fx.sleep(
            error.retry_after if error.retry_after is not None else _BASE_DELAY.times(2**attempt)
        ).and_then(fx.suspend(lambda: _retrying(effect, attempt + 1))),
    )


def retry_safe[A, R](effect: Effect[A, ChatError, R]) -> Effect[A, ChatError, R]:
    """Retries an adapter request with the shared policy: only ``"retry"``
    failures, up to three times, after the error's ``retry_after`` or an
    exponential backoff from 500 milliseconds. Inside
    ``chat.without_retries`` the request runs once."""
    return RetriesDisabled().flat_map(lambda disabled: effect if disabled else _retrying(effect, 0))


__all__ = [
    "AppendResult",
    "ChatAdapter",
    "ChatError",
    "Descriptor",
    "Direction",
    "File",
    "Limits",
    "Measure",
    "NativeStream",
    "Ops",
    "Posted",
    "Registry",
    "RegistryService",
    "RetriesDisabled",
    "ThreadInfo",
    "User",
    "check_message_length",
    "layer",
    "retry_safe",
]
