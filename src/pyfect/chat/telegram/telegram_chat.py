"""The Telegram adapter for ``pyfect.chat`` (Effect's
``@effect/chat-telegram/TelegramChat``), over the Bot API: the ``Registry``
layer, the webhook and polling transports, the pure normaliser and the
address helpers.

- Raw REST over ``HttpClient``, through ``TelegramBotApi``, which keeps the
  bot token out of spans and errors.
- Posts and edits are rich messages (``sendRichMessage``, ``editMessageText``
  with ``rich_message``), in Markdown escaped so that consumer text reaches
  no raw HTML, image, math, spoiler or non-web link.
- Files, buttons and commands need further live checks, so they are behind
  the ``unverified_*`` options, off by default.
- There is no ``ephemeral``: a private answer to a command is refused through
  ``Handler.refused``, never posted. ``fetch_message``, ``history``,
  ``opener``, ``start_thread``, selects, modals, native streams and reaction
  events are not in this version.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Any, Never

import pyfect as fx
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._js import text_encode
from pyfect.byte_size import ByteSize
from pyfect.chat.chat_adapter import Registry
from pyfect.chat.chat_error import ChatError
from pyfect.chat.chat_event import ChatEvent
from pyfect.chat.chat_handler import ChatHandler
from pyfect.chat.chat_interaction import ButtonClicked, CommandInvoked, Group
from pyfect.chat.chat_test import MentionToken
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.telegram import (
    _address,
    _commands,
    _errors,
    _normalize,
    _polling,
    _receive,
    _webhook,
)
from pyfect.chat.telegram._adapter import TelegramAdapter, capabilities_of
from pyfect.chat.telegram._address import Parts
from pyfect.chat.telegram._json import as_object, string
from pyfect.chat.telegram._normalize import Context as NormalizeContext
from pyfect.chat.telegram._options import CurrentPostOptions, TelegramPostOptions
from pyfect.chat.telegram._receive import Outcome
from pyfect.chat.telegram.telegram_bot_api import (
    DEFAULT_API_URL,
    Environment,
    TelegramBotApi,
    TelegramBotApiService,
)
from pyfect.chat.telegram.telegram_bot_api import layer as _bot_api_layer
from pyfect.context import Tag
from pyfect.duration import Duration, from_input_unsafe, zero
from pyfect.duration import Input as DurationInput
from pyfect.http.client import HttpClient
from pyfect.http.router import HttpRouter
from pyfect.http.router import use as _router_use
from pyfect.http.router._router import HttpRouterService
from pyfect.layer import Layer
from pyfect.layer import effect as _layer_effect
from pyfect.layer import effect_discard as _layer_effect_discard
from pyfect.layer import provide_merge as _provide_merge
from pyfect.redacted import Redacted

SECRET_HEADER: str = _webhook.SECRET_HEADER
"""The header Telegram sends the webhook secret in. An app that records
server request headers must add it to its redacted header names."""

type OnUnhandled = Callable[[object], Effect[None]]


@dataclass(frozen=True, kw_only=True)
class ReceiveOptions:
    """How updates run.

    - ``on_unhandled``: updates that give no event, the excluded contexts
      among them.
    - ``deadline``: how long ``ChatHandler.handle`` has before the update is
      ``notAccepted``. Default 10 seconds.
    - ``click_deadline``: how long a click handler has before the click is
      answered. Default 2.5 seconds. The handler then keeps running,
      detached, and the update is ``accepted``.
    - ``command_deadline``: how long a command handler has. Default 10
      seconds. The handler is then interrupted, and the update is
      ``accepted``.
    """

    on_unhandled: OnUnhandled | None = None
    deadline: DurationInput = "10 seconds"
    click_deadline: DurationInput = "2500 millis"
    command_deadline: DurationInput = "10 seconds"

    def parsed(self) -> _receive.Options:
        """The options with their durations parsed."""
        return _receive.Options(
            on_unhandled=self.on_unhandled,
            deadline=from_input_unsafe(self.deadline),
            click_deadline=from_input_unsafe(self.click_deadline),
            command_deadline=from_input_unsafe(self.command_deadline),
        )


class TelegramChatService:
    """The Telegram adapter's own service.

    - ``bot_id`` is the numeric id in front of the token's colon.
    - ``receive`` runs one update, already authenticated and parsed, as both
      transports do, for a consumer's own transport. It needs a
      ``ChatHandler``. Clicks and commands go to
      ``chat_interaction.Handler`` when there is one in context: without it
      a click is answered and dropped, and a command is an ordinary message.
    """

    def __init__(self, *, api: TelegramBotApiService, env: _receive.Environment) -> None:
        self._api = api
        self._env = env

    @property
    def bot_id(self) -> str:
        """The numeric id in front of the token's colon."""
        return self._api.bot_id

    @property
    def environment(self) -> Environment:
        """``"production"``, or ``"test"`` for Telegram's test environment."""
        return self._api.environment

    def receive(
        self, update: object, options: ReceiveOptions | None = None
    ) -> Effect[Outcome, Never, ChatHandler]:
        """Runs one update; see the class."""
        parsed = (options or ReceiveOptions()).parsed()
        return ChatHandler().flat_map(
            lambda handler: _receive.receive(update, self._env, parsed, handler.handle)
        )


class TelegramChat(Tag[TelegramChatService], key="@effect/chat-telegram/TelegramChat"):
    """The Telegram side of the adapter; ``telegram_chat.layer`` provides it."""


def _username(api: TelegramBotApiService) -> Effect[str, ChatError]:
    """The bot's username from ``getMe``, read on first use and kept."""
    known: list[str] = []

    def read(me: object) -> Effect[str, ChatError]:
        name = string(me, "username")
        if name is None:
            return fx.fail(
                _errors.chat_error("getMe", _errors.invalid_response(False, "missing_username"))
            )
        known.append(name)
        return fx.succeed(name)

    return fx.suspend(lambda: fx.succeed(known[0]) if known else api.call("getMe").flat_map(read))


def layer(
    *,
    token: Redacted[str],
    environment: Environment = "production",
    api_url: str = DEFAULT_API_URL,
    unverified_files: bool = False,
    unverified_buttons: bool = False,
    unverified_commands: bool = False,
) -> Layer[TelegramChat | TelegramBotApi, ChatError, HttpClient | Registry]:
    """Registers the Telegram adapter in the ``Registry`` and provides
    ``TelegramChat`` and ``TelegramBotApi``.

    - The descriptor has ``edit``, ``delete``, ``replyTo``, ``download``,
      ``getThread`` and ``getUser``, beside ``post``, and whatever the
      ``unverified_*`` options turn on: ``files`` (up to 10 per post, 50 MB
      each), ``buttons`` (inline keyboards; a click is dispatched only when
      its data matches a button in Telegram's copy of the message) and
      ``commands``.
    - ``environment="test"`` uses Telegram's test environment. ``api_url``
      is for a local Bot API server and is privileged configuration.
    - Fails ``Unauthenticated`` when the token has no bot id. The token is
      not checked against Telegram here; the first call does that.
    - The bot's username, which commands and ``@`` mentions need, is read
      with ``getMe`` on the first message and kept. While it can't be read, a
      message update is ``invalid``, and Telegram sends it again.
    """
    capabilities = capabilities_of(
        files=unverified_files, buttons=unverified_buttons, commands=unverified_commands
    )

    @fx.gen
    def build() -> Generator[Effect[Any, Never, Any], Any, TelegramChatService]:
        api = yield from TelegramBotApi()
        registry = yield from Registry()
        adapter = TelegramAdapter(api=api, capabilities=capabilities)
        yield from registry.register(adapter)
        env = _receive.Environment(
            api=api, capabilities=capabilities, answer=adapter.answer, username=_username(api)
        )
        return TelegramChatService(api=api, env=env)

    return _layer_effect(TelegramChat, build).pipe(
        _provide_merge(_bot_api_layer(token=token, environment=environment, api_url=api_url))
    )


def _transport_receive(
    options: ReceiveOptions,
) -> Effect[Callable[[object], Effect[Outcome]], Never, TelegramChat | ChatHandler]:
    """``TelegramChatService.receive`` with the layer's ``ChatHandler``, as a
    transport runs it."""

    @fx.gen
    def build() -> Generator[Effect[Any, Never, Any], Any, Callable[[object], Effect[Outcome]]]:
        telegram = yield from TelegramChat()
        handler = yield from ChatHandler()
        return lambda update: telegram.receive(update, options).pipe(
            fx.provide_service(ChatHandler, handler)
        )

    return build


def _max_body_size(max_body_bytes: int) -> ByteSize:
    if isinstance(max_body_bytes, bool) or not 0 <= max_body_bytes <= 2**53 - 1:
        raise ValueError(
            f"max_body_bytes must be a non-negative safe integer, got {max_body_bytes!r}"
        )
    return ByteSize(max_body_bytes)


def layer_webhook(
    *,
    path: str,
    secret_token: Redacted[str],
    max_body_bytes: int = _webhook.DEFAULT_MAX_BODY_BYTES,
    options: ReceiveOptions | None = None,
) -> Layer[Never, ChatError, HttpRouter | TelegramChat | ChatHandler]:
    """``POST {path}``: the bot's webhook.

    - The ``X-Telegram-Bot-Api-Secret-Token`` header must equal
      ``secret_token``, compared in constant time. Otherwise the answer is
      401 and the body is not read. The layer fails unless ``secret_token``
      is 32 to 256 characters of ``A-Za-z0-9_-``.
    - 413 past ``max_body_bytes`` (1 MiB by default), 400 for a body that
      can't be read, nests past 64 levels or is not an update.
      ``max_body_bytes`` must be a non-negative safe integer; another value
      raises when the layer is built.
    - The update goes through ``receive``: 200 for ``accepted`` and
      ``unhandled``, 503 for ``notAccepted`` and ``invalid``, which Telegram
      sends again. A click or command is answered 200 after its reply
      attempt.
    """
    max_body_size = _max_body_size(max_body_bytes)
    receive_options = options or ReceiveOptions()

    def register(router: HttpRouterService) -> Effect[None, ChatError, Any]:
        @fx.gen
        def body() -> Generator[Effect[Any, ChatError, Any], Any]:
            secret: str = yield from _webhook.secret_token("layerWebhook", secret_token)
            receive = yield from _transport_receive(receive_options)
            settings = _webhook.Options(
                secret=text_encode(secret), max_body_size=max_body_size, receive=receive
            )
            yield from router.add(
                "POST", path, lambda request: _webhook.handle_request(request, settings)
            )

        return body

    return _router_use(register)


def layer_polling(
    *,
    timeout: DurationInput = "30 seconds",
    max_attempts: int = 3,
    options: ReceiveOptions | None = None,
) -> Layer[Never, ChatError, TelegramChat | TelegramBotApi | ChatHandler]:
    """Long polling with ``getUpdates``, for a long-running process.

    - Updates run one at a time, in order, through ``receive``. An update is
      confirmed only after it ran, so a process that dies part way sees it
      again.
    - ``notAccepted`` and ``invalid`` are retried up to ``max_attempts``
      times (3 by default) with a backoff, then logged as an error and
      skipped: ``getUpdates`` is one queue, and retrying forever would stall
      the bot.
    - The layer fails ``InvalidRequest`` with detail ``conflict`` when
      Telegram answers 409 at start: a webhook is set, or another process
      polls. It never deletes a webhook itself. A later 409 stops polling
      with an error log.
    """
    poll_timeout: Duration = from_input_unsafe(timeout)
    attempts = max(1, max_attempts)
    receive_options = options or ReceiveOptions()

    @fx.gen
    def start() -> Generator[Effect[Any, ChatError, Any], Any]:
        api = yield from TelegramBotApi()
        settings = _polling.Options(
            api=api,
            timeout=poll_timeout,
            max_attempts=attempts,
            receive=(yield from _transport_receive(receive_options)),
        )
        first: list[object] = yield from _polling.get_updates(api, None, zero).map_error(
            _polling.conflict
        )
        yield from _polling.loop(first, settings).fork_scoped()

    return _layer_effect_discard(start)


def set_webhook(
    *,
    url: str,
    secret_token: Redacted[str],
    max_connections: int | None = None,
    drop_pending_updates: bool | None = None,
) -> Effect[None, ChatError, TelegramBotApi]:
    """Registers the webhook with exactly the ``allowed_updates`` the adapter
    reads. The adapter never calls it itself."""

    @fx.gen
    def run() -> Generator[Effect[Any, ChatError, Any], Any]:
        secret: str = yield from _webhook.secret_token("setWebhook", secret_token)
        api = yield from TelegramBotApi()
        yield from api.call(
            "setWebhook",
            {
                "url": url,
                "secret_token": secret,
                "allowed_updates": list(_receive.ALLOWED_UPDATES),
                "max_connections": max_connections,
                "drop_pending_updates": drop_pending_updates,
            },
            write=True,
        )

    return run


def command_requests(group: Group[str]) -> Effect[dict[str, list[dict[str, str]]], ChatError]:
    """The ``commands`` of ``setMyCommands`` for a group's commands.

    - Fails ``InvalidRequest`` with detail ``invalid_command_names`` when a
      command id is not ``[a-z0-9_]{1,32}``. The portable rule allows ``-``;
      Telegram does not.
    - An ``argument`` has no Telegram counterpart and is appended to the
      description.
    - Commands are registered as ordinary, not ephemeral: this version has
      no ``ephemeral``.
    """
    result = _commands.bot_commands(group)
    if isinstance(result, _commands.Invalid):
        return fx.fail(
            _errors.chat_error("commandRequests", _errors.invalid_request("invalid_command_names"))
        )
    return fx.succeed({"commands": result})


def set_commands(
    group: Group[str], *, scope: object = None, language_code: str | None = None
) -> Effect[None, ChatError, TelegramBotApi]:
    """Sends a group's commands with ``setMyCommands``."""

    @fx.gen
    def run() -> Generator[Effect[Any, ChatError, Any], Any]:
        request: dict[str, list[dict[str, str]]] = yield from command_requests(group)
        api = yield from TelegramBotApi()
        yield from api.call(
            "setMyCommands",
            {**request, "scope": scope, "language_code": language_code},
            write=True,
        )

    return run


def thread(chat_id: str | int, message_thread_id: str | int | None = None) -> ChatThread:
    """The address of a chat, or of a forum topic in it."""
    return _address.thread(chat_id, message_thread_id)


def parts(address: ChatThread) -> Parts | None:
    """The parts of a Telegram address, or ``None`` for another platform's or
    a malformed one."""
    return _address.parts(address)


def normalize(update: object, context: NormalizeContext) -> list[ChatEvent]:
    """The normaliser, for a consumer's own transport. It checks no secret:
    that is the transport's job.

    - A ``message`` or ``channel_post`` with text, a caption, a file or rich
      content gives a ``MessageCreated``. ``text`` is verbatim, and empty for
      an inbound rich message, whose content is only in ``raw``.
    - ``text_mention`` entities are mentions by id. An ``@username`` is a
      mention only when it names the bot. Offsets are UTF-16 units, as
      Telegram's are.
    - The author is ``sender_chat`` when there is one, else ``from``.
    - A private (ephemeral) message, a service message, and anything from a
      business connection, a channel's direct messages or guest mode give
      none, as does every other update. Commands are messages here too:
      ``receive`` is what routes them.
    - ``raw`` is the update.
    """
    return _normalize.normalize(update, context)


def normalize_interaction(
    update: object, context: NormalizeContext
) -> ButtonClicked | CommandInvoked | None:
    """The click or command of an update, as ``receive`` would dispatch it.
    A click is given only when its ``data`` is the ``callback_data`` of a
    button in Telegram's own copy of the message. That proves the bot put the
    button there, not that it is still current or that this user may press
    it."""
    obj = as_object(update)
    if obj is None:
        return None
    click = _receive.click_event(obj)
    return click if click is not None else _receive.command_event(obj, context)


def delivery_key(
    raw: object, *, bot_id: str, environment: Environment = "production"
) -> str | None:
    """The delivery key of an update, or of an event or interaction's
    ``raw``: ``{botId}.{update_id}.{date}``, with ``test.`` in front in the
    test environment. Telegram sends an update again until it gets a 200,
    clicks and commands included, so a handler whose work must not be lost or
    run twice commits this key and a recoverable work item in one transaction
    before it returns."""
    return _normalize.delivery_id(raw, bot_id=bot_id, environment=environment)


def parse_mention(text: str) -> MentionToken | None:
    """A mention's text is a display name or an ``@username``, neither of
    which holds the id, so this is always ``None``: a message's ``mentions``
    come from its entities. For ``chat_test``."""
    del text
    return None


def with_post_options[A, E, R](
    options: TelegramPostOptions,
) -> Callable[[Effect[A, E, R]], Effect[A, E, R]]:
    """Scoped Telegram options for every write inside an effect; use with
    ``.pipe``. Nested calls merge, the inner one winning field by field.
    Answers to commands and follow-ups ignore them."""

    def apply(effect: Effect[A, E, R]) -> Effect[A, E, R]:
        require_effect(effect, "effect")
        return CurrentPostOptions().flat_map(
            lambda current: effect.pipe(
                fx.provide_service(CurrentPostOptions, current.merge(options))
            )
        )

    return apply


__all__ = [
    "SECRET_HEADER",
    "ChatError",
    "NormalizeContext",
    "OnUnhandled",
    "Outcome",
    "Parts",
    "ReceiveOptions",
    "TelegramChat",
    "TelegramChatService",
    "TelegramPostOptions",
    "command_requests",
    "delivery_key",
    "layer",
    "layer_polling",
    "layer_webhook",
    "normalize",
    "normalize_interaction",
    "parse_mention",
    "parts",
    "set_commands",
    "set_webhook",
    "thread",
    "with_post_options",
]
