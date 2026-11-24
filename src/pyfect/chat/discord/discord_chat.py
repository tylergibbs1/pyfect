"""The Discord adapter for ``pyfect.chat`` (Effect's ``@effect/chat-discord/DiscordChat``):
the ``Registry`` layer, the gateway dispatch and interaction entries, the HTTP
interactions endpoint, the pure normalisers, address helpers and the scoped
post options.

- Gateway intents: ``GUILDS``, ``GUILD_MESSAGES``, ``GUILD_MESSAGE_REACTIONS``,
  ``DIRECT_MESSAGES``, ``DIRECT_MESSAGE_REACTIONS`` and ``MESSAGE_CONTENT``
  (``discord_gateway.DEFAULT_INTENTS``).
- ``MESSAGE_CONTENT`` is a privileged intent: switch it on for the
  application in Discord's developer portal. Without it, ``text`` is empty on
  every message that doesn't mention the bot, and attachments are missing.
- Bot permissions: View Channel, Send Messages, Send Messages in Threads,
  Create Public Threads, Read Message History and Attach Files.
- Slash commands need the ``applications.commands`` scope, and are
  registered by the consumer with the payloads ``command_requests`` gives.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, Never

import pyfect as fx
import pyfect.schema as S
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.byte_size import ByteSize
from pyfect.cause import Cause
from pyfect.chat.chat_adapter import Registry
from pyfect.chat.chat_error import ChatError
from pyfect.chat.chat_event import ChatEvent, MessageCreated, ReactionAdded
from pyfect.chat.chat_handler import ChatHandler, NotAccepted
from pyfect.chat.chat_interaction import Group, Handler, Interaction
from pyfect.chat.chat_test import MentionToken
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.discord import _adapter, _errors, _interactions, _mentions, _normalize, _webhook
from pyfect.chat.discord._adapter import DiscordAdapter
from pyfect.chat.discord._normalize import Member
from pyfect.chat.discord._options import CurrentPostOptions, DiscordPostOptions
from pyfect.chat.discord.discord_gateway import (
    DiscordGateway,
    DispatchHook,
    GatewayDispatch,
    Hook,
)
from pyfect.chat.discord.discord_rest import DEFAULT_BASE_URL, DiscordRest
from pyfect.chat.discord.discord_rest import layer as _rest_layer
from pyfect.context import Tag
from pyfect.crypto.signature import Signature
from pyfect.duration import Input as DurationInput
from pyfect.duration import from_input_unsafe, seconds
from pyfect.http.client import HttpClient
from pyfect.http.router import HttpRouter
from pyfect.http.router import use as _router_use
from pyfect.http.router._router import HttpRouterService
from pyfect.layer import Layer
from pyfect.layer import effect as _layer_effect
from pyfect.layer import effect_discard as _layer_effect_discard
from pyfect.layer import provide_merge as _provide_merge
from pyfect.redacted import Redacted
from pyfect.result import Err, Ok

DEFAULT_DEADLINE = seconds(2)
"""The handler's share of Discord's 3 seconds."""

_LOOKUP_TIMEOUT = seconds(5)


class DiscordChatService:
    """The Discord side of the adapter, for what the core has no op for.

    - ``bot_user_id`` comes from ``GET /users/@me``, read once. A failed read
      is tried again next time.
    - ``dispatch`` takes one gateway dispatch, ``t`` and ``d``, and hands its
      events to the ``ChatHandler`` one at a time. When a ``MESSAGE_CREATE``
      carries no ``channel_type``, it looks the channel up, cached and with a
      five second timeout. A failed lookup is logged and fails with
      ``NotAccepted``; one that would fail the same way again, such as a
      deleted channel, is logged and the event dropped.
    - ``interaction`` takes one ``INTERACTION_CREATE`` payload from the
      gateway and answers through the interaction callback endpoint, which
      has to land inside Discord's 3 seconds: ``deadline`` is the handler's
      share, 2 seconds by default. It ignores an interaction it can't
      express: a message or user command, an autocomplete request, a slash
      command with anything but at most one string option.
    - A click is answered with callback type 6, or type 9 for ``OpenModal``.
      A submit's ``close`` is type 6. An ``errors`` reply is type 4 with the
      ephemeral flag, listing each message as plain text, and the modal
      closes: Discord can't show an error inside a modal.
    - A slash command goes to ``Handler.command``. ``respond`` is callback
      type 4, ``defer`` type 5 and ``OpenModal`` type 9, each with the
      ephemeral flag when private. An ``Ack`` sends nothing, so a command
      another library owns is left to it. ``with_post_options`` does not reach
      a command's answer.
    - A modal that can't be built, a reply to a command that fails the checks
      of a ``post``, or a callback that fails, goes to ``Handler.refused``. A
      callback that comes back 404 ``Unknown interaction`` was late:
      ``NotFound`` with detail ``interaction_expired``.
    - ``guild`` reads the channel, cached; ``None`` for a direct.
    """

    def __init__(
        self,
        *,
        bot_user_id: Effect[str, ChatError],
        adapter: DiscordAdapter,
    ) -> None:
        self._bot_user_id = bot_user_id
        self._adapter = adapter

    @property
    def bot_user_id(self) -> Effect[str, ChatError]:
        """The bot's user id, from ``GET /users/@me``."""
        return self._bot_user_id

    @property
    def adapter(self) -> DiscordAdapter:
        """The registered adapter."""
        return self._adapter

    def dispatch(self, payload: GatewayDispatch) -> Effect[None, NotAccepted, ChatHandler]:
        """Hands one gateway dispatch's events to the ``ChatHandler``; see the class."""
        t, d = payload.t, payload.d
        if t not in _normalize.HANDLED:
            return fx.void
        adapter = self._adapter

        def refuse(message: str, error: ChatError) -> Effect[Never, NotAccepted]:
            return fx.log_warning(message, error).and_then(fx.fail(NotAccepted()))

        @fx.gen
        def run() -> Generator[Effect[Any, NotAccepted, Any], Any]:
            handler = yield from ChatHandler()
            bot_user_id = yield from self._bot_user_id.catch_all(
                lambda error: refuse("discord dispatch: bot user lookup failed", error)
            )
            result = _normalize.normalize(t, d, bot_user_id=bot_user_id)
            if isinstance(result, _normalize.MissingChannelType):

                def failed(error: ChatError) -> Effect[float | None, NotAccepted]:
                    if error.retry == "denied":
                        return fx.log_warning(
                            "discord dispatch: channel lookup denied, event dropped", error
                        ).as_(None)
                    return refuse("discord dispatch: channel lookup failed", error)

                found = (
                    yield from adapter.channel_type(result.channel_id)
                    .timeout_or_else(
                        _LOOKUP_TIMEOUT,
                        lambda: fx.fail(
                            _errors.chat_error(
                                "dispatch", _errors.transport(False, "lookup_timeout")
                            )
                        ),
                    )
                    .catch_all(failed)
                )
                if found is None:
                    return
                result = _normalize.normalize(t, d, bot_user_id=bot_user_id, channel_type=found)
                if isinstance(result, _normalize.MissingChannelType):
                    return
            for event in result.events:
                yield from handler.handle(event)

        return run

    def interaction(
        self, payload: object, *, deadline: DurationInput = DEFAULT_DEADLINE
    ) -> Effect[None, Never, Handler]:
        """Handles one ``INTERACTION_CREATE`` payload from the gateway; see the class."""
        return self._adapter.interaction(
            payload, from_input_unsafe(deadline), self._adapter.send_callback
        )

    def guild(self, thread: ChatThread) -> Effect[str | None, ChatError]:
        """The guild a channel or thread is in; ``None`` for a direct."""
        return self._adapter.guild(thread)


class DiscordChat(Tag[DiscordChatService], key="@effect/chat-discord/DiscordChat"):
    """The Discord side of the adapter; ``discord_chat.layer`` provides it."""


class MissingChannelType(
    S.TaggedError,
    tag="MissingChannelType",
    identifier="@effect/chat-discord/DiscordChat/MissingChannelType",
):
    """A message whose channel type is in neither the payload nor the
    context, from ``normalize``."""

    channel_id: str = S.field(S.String, key="channelId")


def layer(
    *, bot_token: Redacted[str], base_url: str = DEFAULT_BASE_URL
) -> Layer[DiscordChat | DiscordRest, Never, HttpClient | Registry]:
    """Registers the Discord adapter in the ``Registry`` and provides
    ``DiscordChat`` and ``DiscordRest``.

    - Every REST call but ``follow_up`` goes through ``DiscordRest``, and
      what is safe to send again (a read, a 429) is retried as
      ``chat_adapter.retry_safe`` retries.
    - ``HttpClient`` downloads attachments from Discord's CDN, with no token,
      and sends ``follow_up``'s edit, which needs no bot token either, once.
    - Content goes out as written: Discord reads Markdown itself. Every write
      sends ``allowed_mentions: {parse: []}`` and the ``SUPPRESS_EMBEDS``
      flag, unless ``with_post_options`` says otherwise. A reply does not
      ping its author.
    - ``post`` and ``edit`` fail ``TooLarge`` before calling Discord past
      2,000 code points.
    - A refused file fails ``denied`` with detail ``file_refused`` and leaves
      nothing posted: more than 10 files or 10 MiB, by the adapter's own
      check, or any ``denied`` answer to a post with files.
    - A message's elements go out as action rows beside ``content``: five
      buttons to a row and a select alone in its row, up to five rows. An
      ``edit`` without ``actions`` removes the ones there were.
    - A button's id and value share one ``custom_id``, joined by U+241F,
      which an id may not hold; so do a modal's id and metadata. Each has 99
      code points.
    - A modal's inputs are Label components; inputs and texts together are 5
      at most, and a title or label 45 characters. Discord has no submit
      label.
    - ``reply_to`` sends a message reference.
    - Only ``DEFAULT``, ``REPLY``, ``CHAT_INPUT_COMMAND`` and
      ``CONTEXT_MENU_COMMAND`` messages are messages.
    - A webhook message has the webhook id as its author id and ``is_bot``.
    - A mention is reported when its token is in ``content`` outside code and
      Discord says it resolved. A reply that pings its author is not a
      mention.
    - The address of a thread is its channel id. ``start_thread`` names the
      thread after the message's text, cut to 100 characters, and gives the
      existing thread when the message already has one.
    - ``history`` of a thread started from a message puts the opener, from
      the parent channel, in place of Discord's placeholder.
    - There is no native streaming: streamed replies post, then edit, at
      least 1.5 seconds apart.
    """

    @fx.gen
    def build() -> Generator[Effect[Any, Never, Any], Any, DiscordChatService]:
        rest = yield from DiscordRest()
        http = yield from HttpClient()
        registry = yield from Registry()
        cached: list[str] = []

        def read_bot_user_id() -> Effect[str, ChatError]:
            if cached:
                return fx.succeed(cached[0])

            def found(answer: object) -> Effect[str, ChatError]:
                id = _normalize.decode_option(lambda obj: obj.get("id"), answer)
                if not isinstance(id, str) or not id:
                    return fx.fail(
                        _errors.chat_error(
                            "botUserId", _errors.invalid_response(False, "missing_user_id")
                        )
                    )
                cached.append(id)
                return fx.succeed(id)

            return (
                rest.get_my_user()
                .map_error(lambda error: _errors.with_op("botUserId", error))
                .flat_map(found)
            )

        bot_user_id = fx.suspend(read_bot_user_id)
        adapter = yield from _adapter.make(rest=rest, http=http, bot_user_id=bot_user_id)
        yield from registry.register(adapter)
        return DiscordChatService(bot_user_id=bot_user_id, adapter=adapter)

    return _layer_effect(DiscordChat, build).pipe(
        _provide_merge(_rest_layer(bot_token=bot_token, base_url=base_url))
    )


def thread(channel_id: str) -> ChatThread:
    """The address of a Discord channel, thread or direct: its channel id."""
    return _normalize.thread(channel_id)


def normalize(
    dispatch: GatewayDispatch, *, bot_user_id: str, channel_type: int | None = None
) -> Ok[tuple[ChatEvent, ...]] | Err[MissingChannelType]:
    """The normaliser behind ``dispatch``, without delivering.

    - Pure: it never looks a channel up. It reads the channel type from the
      payload's ``channel_type``, then from ``channel_type``, Discord's
      numeric type, and fails with ``MissingChannelType`` when neither has
      one.
    - Types 10, 11 and 12 are a ``thread``, 1 and 3 a ``direct``, and every
      other type a ``channel``.
    - ``MESSAGE_CREATE``, ``MESSAGE_REACTION_ADD`` and
      ``MESSAGE_REACTION_REMOVE`` give an event. Every other dispatch, and a
      message type that is not a message, gives none.
    - A custom emoji is ``custom:{name}``, its id left on ``raw``.
    - ``raw`` is the dispatch's ``d``, undecoded.
    """
    result = _normalize.normalize(
        dispatch.t, dispatch.d, bot_user_id=bot_user_id, channel_type=channel_type
    )
    if isinstance(result, _normalize.MissingChannelType):
        return Err(MissingChannelType(channel_id=result.channel_id))
    return Ok(result.events)


def member(event: MessageCreated | ReactionAdded) -> Member | None:
    """The member on a message's or added reaction's ``raw``: the guild, the
    roles and the nick. Pure; ``None`` for a direct, a webhook message, or a
    payload with no member. Discord sends no member on a removed reaction."""
    return _normalize.member_of(event.raw)


def guild_id(event: ChatEvent) -> str | None:
    """The guild on an event's ``raw``. Pure; ``None`` for a direct."""
    return _normalize.guild_id_of(event.raw)


def layer_gateway() -> Layer[Never, Never, DiscordGateway | DiscordChat | ChatHandler]:
    """For a long-running process: subscribes to the gateway and feeds every
    dispatch to ``DiscordChatService.dispatch``, one at a time. An event that
    fails with ``NotAccepted`` is logged and dropped, and so is one the
    process stops in the middle of: Discord does not send it again. For a
    host that is stopped and started again, use ``layer_dispatch_hook``."""

    @fx.gen
    def build() -> Generator[Effect[Any, Never, Any], Any]:
        gateway = yield from DiscordGateway()
        discord = yield from DiscordChat()
        handler = yield from ChatHandler()

        def deliver(found: GatewayDispatch) -> Effect[None]:
            return (
                discord.dispatch(found)
                .pipe(fx.provide_service(ChatHandler, handler))
                .catch_cause(lambda cause: fx.log_warning("discord gateway: event dropped", cause))
            )

        yield from gateway.dispatch.run_for_each(deliver).fork_scoped(start_immediately=True)

    return _layer_effect_discard(build)


def layer_dispatch_hook() -> Layer[DispatchHook, Never, DiscordChat | ChatHandler]:
    """For a host that is stopped and started again: feeds every dispatch to
    ``DiscordChatService.dispatch`` from the gateway's ``DispatchHook``,
    before the shard stores the dispatch's sequence. Provide it to
    ``discord_gateway.layer``, beside a ``ShardStateStore`` over storage that
    outlives the host, in place of ``layer_gateway``: never both, or every
    event is delivered twice.

    - An event that fails with ``NotAccepted`` fails the hook: the shard
      drops the connection, resumes from the last stored sequence and gets
      the event again, after 1 second, doubling with every failure in a row
      up to 2 minutes. An event refused every time holds back every event
      after it.
    - A defect in the handler is logged and the event dropped, as a replay
      would only fail the same way.
    - Delivery is at least once: a handler that can't take an event twice
      remembers the ids it took.
    - Discord replays only while it keeps the session.
    """

    @fx.gen
    def build() -> Generator[Effect[Any, Never, Any], Any, Hook | None]:
        discord = yield from DiscordChat()
        handler = yield from ChatHandler()

        def defect(cause: Cause[NotAccepted]) -> Effect[None]:
            return fx.log_error("discord gateway: handler defect, event dropped", cause)

        def hook(found: GatewayDispatch) -> Effect[None, NotAccepted]:
            if found.t not in _normalize.HANDLED:
                return fx.void
            # Refused or interrupted: the sequence stays unstored and a RESUME replays the event.
            return (
                discord.dispatch(found)
                .pipe(fx.provide_service(ChatHandler, handler))
                .catch_cause_if(lambda cause: not (cause.has_fails or cause.has_interrupts), defect)
            )

        return hook

    return _layer_effect(DispatchHook, build)


def layer_gateway_interactions() -> Layer[Never, Never, DiscordGateway | DiscordChat | Handler]:
    """For a long-running process: subscribes to the gateway and feeds every
    ``INTERACTION_CREATE`` to ``DiscordChatService.interaction``, all at once,
    since each has its own 3 seconds."""

    @fx.gen
    def build() -> Generator[Effect[Any, Never, Any], Any]:
        gateway = yield from DiscordGateway()
        discord = yield from DiscordChat()
        handler = yield from Handler()

        def deliver(found: GatewayDispatch) -> Effect[None]:
            return (
                discord.interaction(found.d)
                .pipe(fx.provide_service(Handler, handler))
                .catch_cause(
                    lambda cause: fx.log_warning("discord gateway: interaction dropped", cause)
                )
            )

        yield from (
            gateway.from_dispatch("INTERACTION_CREATE")
            .map_effect(deliver, concurrency="unbounded")
            .run_drain()
            .fork_scoped(start_immediately=True)
        )

    return _layer_effect_discard(build)


def _max_body_size(max_body_bytes: int) -> ByteSize:
    if isinstance(max_body_bytes, bool) or not 0 <= max_body_bytes <= 2**53 - 1:
        raise ValueError(
            f"max_body_bytes must be a non-negative safe integer, got {max_body_bytes!r}"
        )
    return ByteSize(max_body_bytes)


def layer_interactions(
    *,
    path: str,
    public_key: str,
    deadline: DurationInput = DEFAULT_DEADLINE,
    max_body_bytes: int = _webhook.DEFAULT_MAX_BODY_BYTES,
) -> Layer[Never, Never, HttpRouter | DiscordChat | Handler | Signature]:
    """``POST {path}``: the Interactions Endpoint URL, for an application that
    takes interactions over HTTP rather than the gateway.

    - Checks the Ed25519 signature of ``X-Signature-Timestamp`` and the body
      with the application's ``public_key`` (64 hex digits, as the developer
      portal shows it), and a timestamp within five minutes of now: 401
      otherwise.
    - Answers 413 past ``max_body_bytes`` (256 KiB by default), before the
      signature is checked, and 400 for a body that is not a JSON object.
    - Answers ``PING`` with ``PONG``.
    - Hands every other payload to the interaction entry with ``deadline``
      and answers with its callback as the response: 200 with the callback,
      or 204 when there is none, and Discord shows its own failure.

    Signature checks use ``Signature`` (``pyfect.crypto.native.layer_signature``,
    extra ``crypto``).
    """
    key = _webhook.parse_public_key(public_key)
    max_body_size = _max_body_size(max_body_bytes)
    limit = from_input_unsafe(deadline)

    def register(router: HttpRouterService) -> Effect[None, Never, Any]:
        @fx.gen
        def body() -> Generator[Effect[Any, Never, Any], Any]:
            discord = yield from DiscordChat()
            handler = yield from Handler()
            verify = yield from _webhook.make_verifier(key)
            adapter = discord.adapter
            options = _webhook.Options(
                verify=verify,
                interaction=adapter.interaction,
                deadline=limit,
                max_body_size=max_body_size,
            )
            yield from router.add(
                "POST",
                path,
                lambda request: _webhook.handle_request(request, options).pipe(
                    fx.provide_service(Handler, handler)
                ),
            )

        return body

    return _router_use(register)


def normalize_interaction(payload: object) -> Interaction | None:
    """The normaliser behind ``DiscordChatService.interaction``: pure.

    - A click on a button gives ``ButtonClicked``, with the id and value
      split from the ``custom_id``. A string select gives ``SelectChanged``,
      and a modal's submit ``ModalSubmitted``, its metadata split from the
      modal's ``custom_id``.
    - A modal a command opened has no message, so its submit has no
      ``message_id``, and its thread is the channel.
    - A submit's ``values`` hold each answered input by id; an input left
      empty is absent.
    - A slash command with no options, or one string option, gives
      ``CommandInvoked``: ``id`` is its name and ``text`` the option's value
      or the empty string.
    - Anything else is ``None``.
    - ``raw`` is the payload, undecoded. For a command it holds the token
      that answers it, so it is a credential for 15 minutes.
    """
    return _interactions.normalize(payload)


def command_requests(group: Group[Any]) -> list[dict[str, object]]:
    """The create payload of each command in ``group``, in the group's order,
    for Discord's application commands endpoint: a ``CHAT_INPUT`` command with
    the definition's name and description, and one ``STRING`` option when it
    has an ``argument``. The adapter registers nothing: Discord's bulk
    overwrite replaces the application's whole list, so the consumer sends
    these beside its other commands, in one call."""
    return _interactions.command_requests(group)


def with_post_options[A, E, R](
    options: DiscordPostOptions,
) -> Callable[[Effect[A, E, R]], Effect[A, E, R]]:
    """Scoped Discord options for every write inside an effect; use with
    ``.pipe``. Nested calls merge, the inner one winning field by field."""

    def apply(effect: Effect[A, E, R]) -> Effect[A, E, R]:
        require_effect(effect, "effect")
        return CurrentPostOptions().flat_map(
            lambda current: effect.pipe(
                fx.provide_service(CurrentPostOptions, current.merge(options))
            )
        )

    return apply


def parse_mention(text: str) -> MentionToken | None:
    """Reads one Discord mention token, ``<@id>``, ``<@!id>``, ``<@&id>``,
    ``<#id>``, ``@everyone`` or ``@here``, for ``chat_test``'s checks and
    conformance suite."""
    target = _mentions.parse_token(text)
    return None if target is None else MentionToken(target.kind, target.id)


__all__ = [
    "DEFAULT_DEADLINE",
    "DiscordChat",
    "DiscordChatService",
    "DiscordPostOptions",
    "Member",
    "MissingChannelType",
    "command_requests",
    "guild_id",
    "layer",
    "layer_dispatch_hook",
    "layer_gateway",
    "layer_gateway_interactions",
    "layer_interactions",
    "member",
    "normalize",
    "normalize_interaction",
    "parse_mention",
    "thread",
    "with_post_options",
]
