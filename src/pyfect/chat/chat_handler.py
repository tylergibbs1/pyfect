"""The service a consumer provides to receive chat events (Effect's
``effect/chat/ChatHandler``).

Adapters take ``ChatHandler`` from context and call ``handle`` for every
inbound event. The contract is "accept, fast": success means the event is
the consumer's. The platform can still deliver it again, so drop repeats
with ``chat_event.dedupe_key``. Forking the work and returning loses events
on a crash: how durable an accepted event is belongs to the consumer.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Never, overload

import pyfect as fx
from pyfect import schema as S
from pyfect._core import Effect, _call_user
from pyfect.chat.chat_event import ChatEvent, MessageCreated
from pyfect.context import Context, Tag
from pyfect.layer import Layer
from pyfect.layer import effect as _layer_effect
from pyfect.scope import Scope


class NotAccepted(
    S.TaggedError, tag="NotAccepted", identifier="effect/chat/ChatHandler/NotAccepted"
):
    """An event that was not accepted. A handler fails with it to refuse an
    event, and an adapter's entry point when it could not finish normalising
    one: Slack answers 503 so the event is redelivered. It has no fields, so
    whoever raises it logs the reason first."""


class Service:
    """Receives inbound events: success hands the event to the consumer,
    ``NotAccepted`` refuses it."""

    __slots__ = ("_handle",)

    def __init__(self, handle: Callable[[ChatEvent], Effect[None, NotAccepted]]) -> None:
        self._handle = handle

    def handle(self, event: ChatEvent) -> Effect[None, NotAccepted]:
        return self._handle(event)


class ChatHandler(Tag[Service], key="effect/chat/ChatHandler"):
    """The consumer's handler of inbound chat events; ``chat_handler.layer``
    is its only constructor."""


@overload
def layer(
    handle: Callable[[ChatEvent], Effect[None, NotAccepted, Scope]],
    *,
    deliver_self: bool = False,
) -> Layer[ChatHandler]: ...
@overload
def layer[R](
    handle: Callable[[ChatEvent], Effect[None, NotAccepted, R | Scope]],
    *,
    deliver_self: bool = False,
) -> Layer[ChatHandler, Never, R]: ...
def layer[R](
    handle: Callable[[ChatEvent], Effect[None, NotAccepted, R | Scope]],
    *,
    deliver_self: bool = False,
) -> Layer[ChatHandler, Never, R]:
    """The ``ChatHandler`` layer from a function that handles one event.

    - The bot's own messages are dropped before ``handle`` runs, unless
      ``deliver_self``. Other bots' messages are delivered, flagged with
      ``author.is_bot``.
    - Every event runs in a ``ChatHandler.handle`` span and its own
      ``Scope``.
    """

    def make(context: Context[R]) -> Service:
        def run(event: ChatEvent) -> Effect[None, NotAccepted]:
            if (
                not deliver_self
                and isinstance(event, MessageCreated)
                and event.message.author.is_self
            ):
                return fx.void
            return (
                fx.scoped(_call_user(handle, event))
                .pipe(fx.provide_context(context))
                .with_span(
                    "ChatHandler.handle",
                    attributes={"chat.platform": event.thread.platform, "chat.op": "handle"},
                )
            )

        return Service(run)

    return _layer_effect(ChatHandler, fx.context().map(make))  # pyright: ignore[reportArgumentType]


__all__ = ["ChatHandler", "NotAccepted", "Service", "layer"]
