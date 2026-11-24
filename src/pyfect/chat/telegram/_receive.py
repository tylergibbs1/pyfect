"""One update, as the webhook and polling both run it (Effect's
``internal/receive.ts``)."""

from __future__ import annotations

from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Never

import pyfect as fx
from pyfect._core import Effect, _call_user
from pyfect.chat import chat_interaction as ci
from pyfect.chat.chat_adapter import Posted
from pyfect.chat.chat_error import Capability, ChatError
from pyfect.chat.chat_event import ChatEvent
from pyfect.chat.chat_handler import NotAccepted
from pyfect.chat.chat_ui import Action
from pyfect.chat.telegram import _actions, _errors, _normalize
from pyfect.chat.telegram._json import JsonObject, as_object, integer, object_, string
from pyfect.chat.telegram._normalize import Context, raw
from pyfect.chat.telegram.telegram_bot_api import TelegramBotApiService
from pyfect.duration import Duration, millis, seconds

type Outcome = Literal["accepted", "unhandled", "notAccepted", "invalid"]
"""What became of one update.

- ``accepted``: its event was accepted, or its click or command was
  answered, refused or not.
- ``unhandled``: it gave nothing and went to ``on_unhandled``.
- ``notAccepted``: the ``ChatHandler`` failed ``NotAccepted`` or passed
  ``deadline``.
- ``invalid``: it is not an update, or it should give an event and could
  not be read.
"""

DEFAULT_DEADLINE = seconds(10)
DEFAULT_CLICK_DEADLINE = millis(2500)
DEFAULT_COMMAND_DEADLINE = seconds(10)

ALLOWED_UPDATES = ("message", "channel_post", "callback_query")
"""The update types the adapter reads, for ``allowed_updates``."""

type OnUnhandled = Callable[[object], Effect[None]]


@dataclass(frozen=True, kw_only=True)
class Options:
    """How updates run: see ``telegram_chat.ReceiveOptions``."""

    on_unhandled: OnUnhandled | None = None
    deadline: Duration = DEFAULT_DEADLINE
    click_deadline: Duration = DEFAULT_CLICK_DEADLINE
    command_deadline: Duration = DEFAULT_COMMAND_DEADLINE


@dataclass(frozen=True)
class Origin:
    """Where a command's answer goes: the chat it came from, the message to
    reply to, if any, and the command's ``date`` in seconds."""

    thread: Any
    reply_to: int | None
    date: int


type Answer = Callable[[str, Origin, str, Sequence[Action]], Effect[Posted, ChatError]]


@dataclass(frozen=True, kw_only=True)
class Environment:
    """The adapter's side of receiving. ``username`` reads the bot's username
    from ``getMe`` once and keeps it."""

    api: TelegramBotApiService
    capabilities: frozenset[Capability]
    answer: Answer
    username: Effect[str, ChatError]


def origin_of(command: ci.CommandInvoked) -> Origin | None:
    """Where a command's answers go. A reply to an ephemeral command would
    quote the private prompt, so a public answer to one is a new post."""
    message = _normalize.message_of(command.raw)
    id = integer(message, "message_id")
    date = integer(message, "date")
    if id is None or date is None:
        return None
    return Origin(command.thread, None if id == 0 else id, date)


def _refuse_modal(
    handler: ci.HandlerService, event: ci.ButtonClicked | ci.CommandInvoked
) -> Effect[None]:
    return handler.refused(event, _errors.chat_error("openModal", _errors.unsupported("modals")))


def _answer_query(api: TelegramBotApiService, id: str) -> Effect[None]:
    return (
        api.call("answerCallbackQuery", {"callback_query_id": id}, write=True, retry=False)
        .as_void()
        .catch_all(
            lambda error: fx.log_warning("telegram: answerCallbackQuery failed").annotate_logs(
                {"chat.error.reason": type(error.reason).__name__}
            )
        )
    )


def _is_foreign_callback(query: JsonObject) -> bool:
    """A callback the adapter leaves alone: inline mode, a game, or an
    excluded context."""
    message = object_(query, "message")
    return (
        message is None or not isinstance(query.get("data"), str) or _normalize.is_excluded(message)
    )


def click_event(update: JsonObject) -> ci.ButtonClicked | None:
    """The click of a ``callback_query``, only when its ``data`` is the
    ``callback_data`` of a button in Telegram's own copy of the message:
    ``data`` comes from the client and can be anything."""
    query = object_(update, "callback_query")
    message = object_(query, "message")
    data = string(query, "data")
    if query is None or message is None or data is None or _is_foreign_callback(query):
        return None
    user = integer(object_(query, "from"), "id")
    at = _normalize.thread_of(message)
    message_id = _normalize.message_id_of(message)
    if (
        integer(message, "date") == 0
        or data not in _actions.keyboard_data(message.get("reply_markup"))
        or user is None
        or at is None
        or message_id is None
    ):
        return None
    id, value = _actions.parse_data(data)
    return ci.ButtonClicked(
        id=id,
        value=value,
        thread=at.thread,
        message_id=message_id,
        user_id=str(user),
        raw=raw(update),
    )


def _click(
    update: JsonObject,
    id: str,
    env: Environment,
    options: Options,
    handler: ci.HandlerService | None,
) -> Effect[None]:
    """A click. Every click is answered, since the client shows a progress
    bar until it is."""
    answer = _answer_query(env.api, id)
    if handler is None or "buttons" not in env.capabilities:
        return answer
    event = click_event(update)
    if event is None:
        return (
            fx.log_warning(
                "telegram: a click matched no button on its message, answered and dropped"
            )
            .annotate_logs({"chat.interaction.reason": "InvalidValue"})
            .and_then(answer)
        )

    def replied(reply: object) -> Effect[None]:
        if isinstance(reply, ci.OpenModal):
            return answer.and_then(_refuse_modal(handler, event))
        return answer

    return (
        ci.handle(event, options.click_deadline)
        .pipe(fx.provide_service(ci.Handler, handler))
        .flat_map(replied)
    )


def command_event(update: JsonObject, context: Context) -> ci.CommandInvoked | None:
    """The command of a message update, for this bot."""
    message = _normalize.message_of(update)
    if message is None or _normalize.is_excluded(message):
        return None
    found = _normalize.command_of(message, context)
    at = _normalize.thread_of(message)
    # An anonymous admin's ``from`` is Telegram's shared stand-in: the chat is the sender.
    sender_chat = integer(object_(message, "sender_chat"), "id")
    user = sender_chat if sender_chat is not None else integer(object_(message, "from"), "id")
    if found is None or at is None or user is None:
        return None
    return ci.CommandInvoked(
        id=found.id, text=found.text, thread=at.thread, user_id=str(user), raw=raw(update)
    )


def _command(
    event: ci.CommandInvoked,
    env: Environment,
    options: Options,
    handler: ci.HandlerService | None,
) -> Effect[bool]:
    """A command. ``False`` when it was not handled: no handler, no
    ``commands``, or an ``Ack``, which means no definition matched."""
    if handler is None or "commands" not in env.capabilities:
        return fx.succeed(False)

    def replied(reply: object) -> Effect[bool]:
        if isinstance(reply, ci.Ack):
            return fx.succeed(False)
        if isinstance(reply, ci.OpenModal):
            return _refuse_modal(handler, event).as_(True)
        if isinstance(reply, ci.Respond):
            # No ``ephemeral`` in this version: a private answer is refused, never posted.
            if reply.visibility == "ephemeral":
                return handler.refused(
                    event, _errors.chat_error("respond", _errors.PRIVATE_ANSWER)
                ).as_(True)
            origin = origin_of(event)
            if origin is None:
                return fx.succeed(True)
            return (
                env.answer("respond", origin, reply.markdown, reply.actions or ())
                .as_void()
                .catch_all(lambda error: handler.refused(event, error))
                .as_(True)
            )
        return fx.succeed(True)

    return (
        ci.handle(event, options.command_deadline)
        .pipe(fx.provide_service(ci.Handler, handler))
        .flat_map(replied)
    )


def _accepted(done: object) -> Outcome:
    return "notAccepted" if done is None else "accepted"


def _not_accepted(_: NotAccepted) -> Effect[Outcome]:
    return fx.succeed("notAccepted")


def receive(
    update: object,
    env: Environment,
    options: Options,
    handle: Callable[[ChatEvent], Effect[None, NotAccepted]],
    handler: ci.HandlerService | None,
) -> Effect[Outcome]:
    """One update. ``handle`` is the ``ChatHandler``'s and ``handler`` the
    ``chat_interaction.Handler``, if any: both are passed in, never looked
    up here, so every caller decides where they come from.

    - A click goes to ``chat_interaction.Handler`` and is answered.
    - An ephemeral message only ever takes the command path, and never
      reaches the ``ChatHandler`` or ``on_unhandled``.
    - A command goes to ``chat_interaction.Handler``; one answered ``Ack``
      continues as an ordinary message.
    - A message with content becomes ``MessageCreated`` for the
      ``ChatHandler``, within ``deadline``.
    - Anything else, the excluded contexts included, goes to
      ``on_unhandled``.
    """

    @fx.gen
    def body() -> Generator[Effect[Any, Never, Any], Any, Outcome]:  # noqa: PLR0912, PLR0911
        obj = as_object(update)
        if obj is None or integer(obj, "update_id") is None:
            return "invalid"
        on_unhandled = options.on_unhandled
        unhandled: Effect[Outcome] = (
            fx.succeed("unhandled")
            if on_unhandled is None
            else _call_user(on_unhandled, obj).as_("unhandled")
        )
        query = object_(obj, "callback_query")
        if query is not None:
            id = string(query, "id")
            if _is_foreign_callback(query):
                # A business chat's button is answered, so its client stops waiting,
                # but never dispatched.
                message = object_(query, "message")
                if id is not None and message is not None and _normalize.is_excluded(message):
                    yield from _answer_query(env.api, id)
                return (yield from unhandled)
            if id is None:
                return "invalid"
            yield from _click(obj, id, env, options, handler)
            return "accepted"
        message = _normalize.message_of(obj)
        if message is None or _normalize.is_excluded(message):
            return (yield from unhandled)
        username = yield from env.username.option()
        if username is None:
            return "invalid"
        context = Context(
            bot_id=env.api.bot_id, bot_username=username.value, environment=env.api.environment
        )
        found = command_event(obj, context)
        if _normalize.is_ephemeral(message):
            if found is not None:
                yield from _command(found, env, options, handler)
            return "accepted"
        if integer(message, "message_id") == 0:
            return (yield from unhandled)
        if found is not None and (yield from _command(found, env, options, handler)):
            return "accepted"
        event = _normalize.message_created(obj, context)
        if event == "none":
            return (yield from unhandled)
        if event == "invalid":
            return "invalid"
        outcome: Outcome = yield from (
            handle(event).timeout_option(options.deadline).map(_accepted).catch_all(_not_accepted)
        )
        return outcome

    return body
