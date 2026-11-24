"""The routed outbound chat service (Effect's ``effect/chat/Chat``).

``Chat`` has the ops of every registered adapter and routes each call by
the address's platform. ``chat.layer`` provides the router and an empty
``Registry``; adapter layers stack on top with ``layer.provide_merge``, and
a platform that is off is a layer left out::

    @fx.gen
    def program():
        chat = yield from Chat()
        posted = yield from chat.post(chat_thread.make("slack", "T1/C1"), markdown="Hello")
        return posted.id
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

import pyfect as fx
from pyfect._core import Effect
from pyfect.chat.chat_adapter import (
    ChatAdapter,
    Descriptor,
    Direction,
    File,
    Posted,
    Registry,
    RegistryService,
    RetriesDisabled,
    ThreadInfo,
    User,
)
from pyfect.chat.chat_error import ChatError, NoAdapter
from pyfect.chat.chat_message import Attachment, ChatMessage, ReplyTo
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.chat_ui import Action
from pyfect.context import Context, Tag
from pyfect.layer import Layer
from pyfect.layer import effect_context as _layer_effect_context
from pyfect.stream import Stream
from pyfect.stream import _constructors as _stream
from pyfect.tracer._spans import annotate_current_span

if TYPE_CHECKING:
    from pyfect.chat.chat_interaction import Defer


def _attributes(platform: str, op: str) -> dict[str, object]:
    return {"chat.platform": platform, "chat.op": op}


def _annotate_failure(error: ChatError) -> Effect[None]:
    return annotate_current_span(
        {"chat.error.reason": error.reason._tag, "chat.error.retry": error.retry}  # pyright: ignore[reportPrivateUsage]
    )


class Service:
    """Routes each op to the adapter registered for the address's platform,
    failing ``NoAdapter`` when there is none.

    - ``get_user`` takes the platform first: a bare user id names none.
    - ``follow_up`` is routed by the deferred command's thread. One call per
      deferral is the portable contract.
    - ``descriptor`` returns a platform's capabilities and limits.
    - Each call runs in a ``Chat.{op}`` span whose attributes are the
      platform, the op and, on failure, the error's reason and retry value.
    """

    __slots__ = ("_adapters",)

    def __init__(self, adapters: dict[str, ChatAdapter]) -> None:
        self._adapters = adapters

    def _lookup(self, platform: str, op: str) -> Effect[ChatAdapter, ChatError]:
        def find() -> Effect[ChatAdapter, ChatError]:
            adapter = self._adapters.get(platform)
            if adapter is None:
                return fx.fail(ChatError(platform=platform, op=op, reason=NoAdapter()))
            return fx.succeed(adapter)

        return fx.suspend(find)

    def _route[A](
        self, platform: str, op: str, f: Callable[[ChatAdapter], Effect[A, ChatError]]
    ) -> Effect[A, ChatError]:
        return (
            self._lookup(platform, op)
            .flat_map(f)
            .tap_error(_annotate_failure)
            .with_span(f"Chat.{op}", attributes=_attributes(platform, op))
        )

    def _route_stream[A](
        self, platform: str, op: str, f: Callable[[ChatAdapter], Stream[A, ChatError]]
    ) -> Stream[A, ChatError]:
        return (
            _stream.unwrap(self._lookup(platform, op).map(f))
            .tap_error(_annotate_failure)
            .with_span(f"Chat.{op}", attributes=_attributes(platform, op))
        )

    def post(
        self,
        thread: ChatThread,
        *,
        markdown: str,
        reply_to: ReplyTo | None = None,
        files: Sequence[File] = (),
        actions: Sequence[Action] = (),
    ) -> Effect[Posted, ChatError]:
        return self._route(
            thread.platform,
            "post",
            lambda a: a.post(
                thread, markdown=markdown, reply_to=reply_to, files=files, actions=actions
            ),
        )

    def edit(
        self, thread: ChatThread, message_id: str, *, markdown: str, actions: Sequence[Action] = ()
    ) -> Effect[None, ChatError]:
        return self._route(
            thread.platform,
            "edit",
            lambda a: a.edit(thread, message_id, markdown=markdown, actions=actions),
        )

    def delete(self, thread: ChatThread, message_id: str) -> Effect[None, ChatError]:
        return self._route(thread.platform, "delete", lambda a: a.delete(thread, message_id))

    def fetch_message(self, thread: ChatThread, message_id: str) -> Effect[ChatMessage, ChatError]:
        return self._route(
            thread.platform, "fetchMessage", lambda a: a.fetch_message(thread, message_id)
        )

    def history(
        self, thread: ChatThread, *, direction: Direction, from_: str | None = None
    ) -> Stream[ChatMessage, ChatError]:
        return self._route_stream(
            thread.platform,
            "history",
            lambda a: a.history(thread, direction=direction, from_=from_),
        )

    def download(
        self, thread: ChatThread, attachment: Attachment, *, max_bytes: int
    ) -> Stream[bytes, ChatError]:
        return self._route_stream(
            thread.platform,
            "download",
            lambda a: a.download(thread, attachment, max_bytes=max_bytes),
        )

    def start_thread(
        self, thread: ChatThread, message_id: str, *, name: str | None = None
    ) -> Effect[ChatThread, ChatError]:
        return self._route(
            thread.platform, "startThread", lambda a: a.start_thread(thread, message_id, name=name)
        )

    def get_thread(self, thread: ChatThread) -> Effect[ThreadInfo, ChatError]:
        return self._route(thread.platform, "getThread", lambda a: a.get_thread(thread))

    def opener(self, thread: ChatThread) -> Effect[ChatMessage | None, ChatError]:
        return self._route(thread.platform, "opener", lambda a: a.opener(thread))

    def get_user(
        self, platform: str, id: str, *, in_: ChatThread | None = None
    ) -> Effect[User, ChatError]:
        return self._route(platform, "getUser", lambda a: a.get_user(id, in_=in_))

    def follow_up(
        self, deferred: Defer, *, markdown: str, actions: Sequence[Action] = ()
    ) -> Effect[None, ChatError]:
        return self._route(
            deferred.command.thread.platform,
            "followUp",
            lambda a: a.follow_up(deferred, markdown=markdown, actions=actions),
        )

    def descriptor(self, platform: str) -> Effect[Descriptor, ChatError]:
        return self._route(platform, "descriptor", lambda a: fx.succeed(a.descriptor))


class _Registry(RegistryService):
    __slots__ = ("_adapters", "_chat")

    def __init__(self, adapters: dict[str, ChatAdapter], chat: Service) -> None:
        self._adapters = adapters
        self._chat = chat

    def register(self, adapter: ChatAdapter) -> Effect[None]:
        return fx.sync(lambda: self._adapters.__setitem__(adapter.descriptor.platform, adapter))

    def get(self, platform: str) -> Effect[ChatAdapter, ChatError]:
        return self._chat._lookup(platform, "get")  # pyright: ignore[reportPrivateUsage]

    @property
    def descriptors(self) -> Effect[tuple[Descriptor, ...]]:
        return fx.sync(lambda: tuple(a.descriptor for a in self._adapters.values()))


class Chat(Tag[Service], key="effect/chat/Chat"):
    """Routes chat operations to the adapter registered for each address's
    platform."""


def _make() -> Context[Chat | Registry]:
    adapters: dict[str, ChatAdapter] = {}
    chat = Service(adapters)
    return Context.make(Registry, _Registry(adapters, chat)).add(Chat, chat)


layer: Layer[Chat | Registry] = _layer_effect_context(fx.sync(_make))
"""The ``Chat`` router and an empty ``Registry``; adapter layers go on top
with ``layer.provide_merge``."""


def without_retries[A, E, R](effect: Effect[A, E, R]) -> Effect[A, E, R]:
    """``effect`` with adapter retries turned off, so every adapter call in
    it makes one attempt. Use with ``.pipe``."""
    return effect.pipe(fx.provide_service(RetriesDisabled, True))


__all__ = ["Chat", "ChatError", "Service", "layer", "without_retries"]
