"""The Slack adapter for ``pyfect.chat`` (Effect's ``@effect/chat-slack/SlackChat``):
the ``Registry`` layer, the Events API webhook, the Interactivity route for
buttons, modals and slash commands, the pure normalisers, address helpers and
the scoped post options.

- Bot token scopes: ``chat:write``, ``channels:history``, ``groups:history``,
  ``im:history``, ``mpim:history``, ``channels:read``, ``groups:read``,
  ``im:read``, ``mpim:read``, ``users:read``, ``reactions:read``,
  ``files:read`` and ``files:write`` (and ``commands`` for slash commands).
- Event subscriptions, sent to ``layer_webhook``'s path: ``message.channels``,
  ``message.groups``, ``message.im``, ``message.mpim``, ``app_mention``,
  ``reaction_added``, ``reaction_removed`` and ``agent_session_stopped``.
- Buttons, selects, modals and slash commands need Interactivity, with its
  Request URL at ``layer_interactivity``'s path. With Socket Mode, pass each
  payload to ``SlackChatService.interaction`` and send its result as the
  envelope ack's ``payload``.
- Slack's stop button needs the app declared as an agent
  (``features.agent_view``). Without it the session status calls answer
  ``not_authorized``; the adapter then stops making them.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, Never

import pyfect as fx
import pyfect.schema as S
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.byte_size import ByteSize
from pyfect.chat.chat_adapter import Registry
from pyfect.chat.chat_error import CHAT_ERROR_REASON, AnyReason, ChatError
from pyfect.chat.chat_event import ChatEvent
from pyfect.chat.chat_handler import ChatHandler
from pyfect.chat.chat_interaction import Handler, Interaction
from pyfect.chat.chat_test import MentionToken
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.slack import (
    _address,
    _emoji,
    _errors,
    _interactions,
    _json,
    _mentions,
    _normalize,
    _rich_text,
    _webhook,
)
from pyfect.chat.slack._adapter import SlackAdapter, SlackUser
from pyfect.chat.slack._address import Parts
from pyfect.chat.slack._interactions import Body
from pyfect.chat.slack._options import CurrentPostOptions, SessionStatus, SlackPostOptions
from pyfect.chat.slack.slack_web_api import DEFAULT_BASE_URL, SlackWebApi
from pyfect.chat.slack.slack_web_api import layer as _web_api_layer
from pyfect.context import Tag
from pyfect.crypto.mac import Mac
from pyfect.duration import Duration, from_input_unsafe
from pyfect.duration import Input as DurationInput
from pyfect.http.client import HttpClient
from pyfect.http.router import HttpRouter
from pyfect.http.router import use as _router_use
from pyfect.http.router._router import HttpRouterService
from pyfect.layer import Layer
from pyfect.layer import effect as _layer_effect
from pyfect.layer import provide_merge as _provide_merge
from pyfect.redacted import Redacted


class SlackChatService:
    """The Slack side of the adapter, for what the core has no op for.

    - ``bot_user_id`` comes from ``auth.test``, read once. A failed read is
      tried again next time.
    - ``user`` calls ``users.info`` each time.
    - ``interaction`` is the entry for a decoded Interactivity payload
      (``block_actions`` or ``view_submission``) and for a slash command's
      fields. It normalises with ``normalize_interaction``, calls the
      handler through ``chat_interaction.handle`` inside ``deadline`` (2.5
      seconds by default, the handler's share of Slack's 3), opens a modal
      with ``views.open`` and calls ``Handler.refused`` when it can't. It
      succeeds with the body to answer Slack with; ``None`` is an empty
      answer, and ``Late`` (a submit or command past the deadline) is no
      answer at all: ``layer_interactivity`` answers 503 for it. It checks
      no signature and no app id: that is the transport's job.
    """

    def __init__(
        self,
        *,
        team_id: str,
        bot_user_id: Effect[str, ChatError],
        adapter: SlackAdapter,
        interaction: Callable[[object, Duration], Effect[Body, Never, Handler]],
    ) -> None:
        self._team_id = team_id
        self._bot_user_id = bot_user_id
        self._adapter = adapter
        self._interaction = interaction

    @property
    def team_id(self) -> str:
        """The workspace."""
        return self._team_id

    @property
    def bot_user_id(self) -> Effect[str, ChatError]:
        """The bot's user id, from ``auth.test``."""
        return self._bot_user_id

    def user(self, id: str) -> Effect[SlackUser, ChatError]:
        """A user from ``users.info``, with team, guest and Slack Connect status."""
        return self._adapter.user(id)

    def interaction(
        self, payload: object, *, deadline: DurationInput = _interactions.DEFAULT_DEADLINE
    ) -> Effect[Body, Never, Handler]:
        """Handles one interactivity payload or slash command; see the class."""
        return self._interaction(payload, from_input_unsafe(deadline))


class SlackChat(Tag[SlackChatService], key="@effect/chat-slack/SlackChat"):
    """The Slack side of the adapter; ``slack_chat.layer`` provides it."""


class SlackAttachFailed(
    S.TaggedError,
    tag="SlackAttachFailed",
    identifier="@effect/chat-slack/SlackChat/SlackAttachFailed",
):
    """The ``cause`` of a ``post`` with files that failed with detail
    ``attach_failed_message_left``: the attach failed and the message could
    not be deleted, so it may still exist, with or without its files.
    ``message_id`` is that message and ``file_ids`` its files, which are
    kept. ``reason`` is the attach's own. Its ``message`` leaves the ids
    out."""

    thread: ChatThread
    message_id: str = S.field(S.String, key="messageId")
    file_ids: tuple[str, ...] = S.field(S.Array(S.String), key="fileIds")
    reason: AnyReason = S.field(CHAT_ERROR_REASON)

    @property
    def message(self) -> str:
        return f"Slack did not attach the files and the message may be left: {self.reason.message}"

    def __str__(self) -> str:
        return self.message


def layer(
    *,
    bot_token: Redacted[str],
    team_id: str,
    base_url: str = DEFAULT_BASE_URL,
    max_retry_after: DurationInput | None = None,
) -> Layer[SlackChat | SlackWebApi, Never, HttpClient | Registry]:
    """Registers the Slack adapter in the ``Registry``, for one workspace,
    and provides ``SlackChat`` and ``SlackWebApi``.

    - Web API calls go to ``{base_url}/{method}``, as with
      ``slack_web_api.layer``: ``"https://slack-gov.com/api"`` for GovSlack.

    - ``post`` and ``edit`` send the Markdown as one ``markdown`` block, in
      which a ``<`` outside code goes as ``&lt;``, plus a ``text`` the adapter
      builds, in which every ``<``, ``>`` and ``&`` goes as an entity. Slack
      decides who a message mentions from ``text``, so no token notifies
      unless ``with_post_options`` allows it.
    - That ``text`` is cut to 16,000 code points on a post and 3,800 UTF-8
      bytes on an edit, on a grapheme cluster boundary, ending in ``…``.
    - Stream appends go as ``markdown_text``; token shapes get a zero-width
      space after their ``<``, which one cleanup edit takes out when the
      stream stops.
    - ``post``, ``edit`` and stream writes fail ``TooLarge`` before calling
      Slack past 12,000 code points as sent.
    - A post with files uploads them, posts, then attaches them, all or
      nothing; see ``SlackAttachFailed``.
    - Edits to one message are at least 3 seconds apart; after a 429 a
      reply's writes back off.
    - ``replyTo`` is not supported.
    - A call Slack answers 429 is retried after its ``Retry-After``, however
      long, unless ``max_retry_after`` is set: a longer wait then fails the
      op at once with ``RateLimited``, its ``retry_after`` the wait asked
      for.
    """
    retry_ceiling = None if max_retry_after is None else from_input_unsafe(max_retry_after)

    @fx.gen
    def build() -> Generator[Effect[Any, Never, Any], Any, SlackChatService]:
        api = yield from SlackWebApi()
        http = yield from HttpClient()
        registry = yield from Registry()
        cached: list[str] = []

        def read_bot_user_id() -> Effect[str, ChatError]:
            if cached:
                return fx.succeed(cached[0])

            def found(answer: object) -> Effect[str, ChatError]:
                id = _json.string(answer, "user_id")
                if id is None:
                    return fx.fail(
                        _errors.chat_error(
                            "botUserId", _errors.invalid_response(False, "missing_user_id")
                        )
                    )
                cached.append(id)
                return fx.succeed(id)

            return (
                api.call("auth.test", {})
                .map_error(lambda error: _errors.with_op("botUserId", error))
                .flat_map(found)
            )

        bot_user_id = fx.suspend(read_bot_user_id)
        adapter = SlackAdapter(
            api=api,
            http=http,
            bot_token=bot_token,
            team_id=team_id,
            bot_user_id=bot_user_id,
            attach_failed=lambda thread, message_id, file_ids, reason: SlackAttachFailed(
                thread=thread, message_id=message_id, file_ids=file_ids, reason=reason
            ),
            max_retry_after=retry_ceiling,
        )
        yield from registry.register(adapter)
        interaction = _interactions.make(
            call_views_open=lambda body: api.call("views.open", body, write=True, retry=False),
            team_id=team_id,
            answer=adapter.answer,
        )
        return SlackChatService(
            team_id=team_id, bot_user_id=bot_user_id, adapter=adapter, interaction=interaction
        )

    return _layer_effect(SlackChat, build).pipe(
        _provide_merge(
            _web_api_layer(bot_token=bot_token, base_url=base_url, max_retry_after=retry_ceiling)
        )
    )


def thread(*, team: str, channel: str, thread_ts: str | None = None) -> ChatThread:
    """The address of a Slack channel, direct conversation or thread:
    ``{team}/{channel}``, or ``{team}/{channel}/{thread_ts}``."""
    return _address.thread(Parts(team, channel, thread_ts))


def parts(address: ChatThread) -> Parts | None:
    """The parts of a Slack address, or ``None`` for another platform's or a
    malformed one."""
    return _address.parts(address)


def _max_body_size(max_body_bytes: int) -> ByteSize:
    if isinstance(max_body_bytes, bool) or not 0 <= max_body_bytes <= 2**53 - 1:
        raise ValueError(
            f"max_body_bytes must be a non-negative safe integer, got {max_body_bytes!r}"
        )
    return ByteSize(max_body_bytes)


def layer_webhook(
    *,
    path: str,
    signing_secret: Redacted[str],
    app_id: str,
    deadline: DurationInput = "2500 millis",
    max_body_bytes: int = _webhook.DEFAULT_MAX_BODY_BYTES,
) -> Layer[Never, Never, HttpRouter | SlackChat | ChatHandler | Mac]:
    """``POST {path}``: the Events API webhook.

    - Checks the ``v0`` signature with the signing secret (constant time) and
      a five minute window, then answers ``url_verification``.
    - An envelope for another app, another workspace or of another type is
      answered 200 and dropped.
    - The events go through ``normalize`` to the ``ChatHandler``, one at a
      time.
    - Answers 503, so Slack retries, when the handler fails ``NotAccepted``,
      when the bot user can't be read, or when the request takes longer than
      ``deadline``; each is logged with its own message.
    - Answers 413 past ``max_body_bytes`` (1 MiB by default), before the
      signature is checked.
    - Slack redelivers on a timeout or an error; ``chat_event.dedupe_key``
      gives the two deliveries equal keys.

    Signature checks use ``Mac`` (``pyfect.crypto.native.layer_mac``).
    """
    max_body_size = _max_body_size(max_body_bytes)
    limit = from_input_unsafe(deadline)

    def register(router: HttpRouterService) -> Effect[None, Never, Any]:
        @fx.gen
        def body() -> Generator[Effect[Any, Never, Any], Any]:
            slack = yield from SlackChat()
            handler = yield from ChatHandler()
            verify = yield from _webhook.make_verifier(signing_secret)
            options = _webhook.Options(
                verify=verify,
                app_id=app_id,
                team_id=slack.team_id,
                bot_user_id=slack.bot_user_id,
                handle=handler.handle,
                deadline=limit,
                max_body_size=max_body_size,
            )
            yield from router.add(
                "POST", path, lambda request: _webhook.handle_request(request, options)
            )

        return body

    return _router_use(register)


def layer_interactivity(
    *,
    path: str,
    signing_secret: Redacted[str],
    app_id: str,
    deadline: DurationInput = _interactions.DEFAULT_DEADLINE,
    max_body_bytes: int = _webhook.DEFAULT_MAX_BODY_BYTES,
) -> Layer[Never, Never, HttpRouter | SlackChat | Handler | Mac]:
    """``POST {path}``: the Interactivity Request URL, which Slack posts
    form-encoded, and the Request URL of slash commands.

    - Checks the ``v0`` signature as ``layer_webhook`` does, decodes the
      form's ``payload`` (or takes a command's fields) and drops one for
      another app with a 200.
    - Hands the payload to ``SlackChatService.interaction`` with
      ``deadline``. Its body is the response, and ``Late`` is answered 503,
      so a modal stays open with Slack's own error.
    - Answers 413 past ``max_body_bytes``. Slack never redelivers an
      interaction.
    """
    max_body_size = _max_body_size(max_body_bytes)
    limit = from_input_unsafe(deadline)

    def register(router: HttpRouterService) -> Effect[None, Never, Any]:
        @fx.gen
        def body() -> Generator[Effect[Any, Never, Any], Any]:
            slack = yield from SlackChat()
            handler = yield from Handler()
            verify = yield from _webhook.make_verifier(signing_secret)
            options = _webhook.InteractivityOptions(
                verify=verify,
                app_id=app_id,
                interaction=lambda payload, until: slack.interaction(payload, deadline=until).pipe(
                    fx.provide_service(Handler, handler)
                ),
                deadline=limit,
                max_body_size=max_body_size,
            )
            yield from router.add(
                "POST", path, lambda request: _webhook.handle_interactivity(request, options)
            )

        return body

    return _router_use(register)


def normalize_interaction(payload: object, *, team_id: str) -> Interaction | None:
    """The normaliser behind ``SlackChatService.interaction``: pure, ``None``
    for any payload that is not from an element this adapter built. Every
    command gives a ``CommandInvoked``, known or not. A submit's thread and
    message are those of the click that opened the modal. ``raw`` is the
    payload without its verification ``token``; a command's holds its
    ``response_url``, so it is a credential for 30 minutes."""
    return _interactions.normalize(payload, team_id=team_id)


def normalize(envelope: object, *, team_id: str, bot_user_id: str) -> list[ChatEvent]:
    """The normaliser, for Socket Mode or a consumer's own transport: pure,
    an ``event_callback`` envelope to zero or more events.

    - An envelope for another workspace gives none.
    - ``message`` and ``app_mention`` for one message give equal events. An
      ``app_mention`` that carries ``edited`` gives none.
    - A message subtype other than ``file_share``, ``thread_broadcast``,
      ``bot_message`` and ``me_message`` gives none.
    - Mentions come from the message's ``rich_text`` block when it has one,
      and only for elements whose token is in ``text``.
    - The bot's own messages with a ``rich_text`` block read back with
      ``text`` rendered from the blocks as Markdown.
    - ``agent_session_stopped`` gives a ``StopRequested``.
    - ``raw`` is the envelope without its verification ``token``.
    """
    return _normalize.normalize(envelope, team_id=team_id, bot_user_id=bot_user_id)


def with_post_options[A, E, R](
    options: SlackPostOptions,
) -> Callable[[Effect[A, E, R]], Effect[A, E, R]]:
    """Scoped Slack options for every write inside an effect; use with
    ``.pipe``. Nested calls merge, the inner one winning field by field."""

    def apply(effect: Effect[A, E, R]) -> Effect[A, E, R]:
        require_effect(effect, "effect")
        return CurrentPostOptions().flat_map(
            lambda current: effect.pipe(
                fx.provide_service(CurrentPostOptions, current.merge(options))
            )
        )

    return apply


_CONTROL = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;"})


def escape_markdown(text: str) -> str:
    """``text``, such as a display name, as Markdown that shows it as typed:
    no mention, link, emphasis, code or block forms from it, whatever the
    post options let notify. Escape what users write before putting it into
    a post's Markdown, within a line."""
    return _rich_text.escape_markdown(text.translate(_CONTROL))


def emoji_from_name(name: str) -> str | None:
    """A Slack emoji name, with or without colons and with at most one skin
    tone suffix (``+1::skin-tone-4``), as Unicode; ``None`` for a name the
    table doesn't know, such as a custom emoji, and for two tones."""
    return _emoji.from_name(name)


def emoji_to_name(emoji: str) -> str | None:
    """An emoji as its Slack name, without colons."""
    return _emoji.to_name(emoji)


def parse_mention(text: str) -> MentionToken | None:
    """Reads one Slack mention token, such as ``<@U123>``,
    ``<!subteam^S123|@team>``, ``<#C123|name>`` or ``<!here>``, for
    ``chat_test``'s checks and conformance suite."""
    target = _mentions.parse_token(text)
    return None if target is None else MentionToken(target.kind, target.id)


__all__ = [
    "ChatError",
    "Parts",
    "SessionStatus",
    "SlackAttachFailed",
    "SlackChat",
    "SlackChatService",
    "SlackPostOptions",
    "SlackUser",
    "emoji_from_name",
    "emoji_to_name",
    "escape_markdown",
    "layer",
    "layer_interactivity",
    "layer_webhook",
    "normalize",
    "normalize_interaction",
    "parse_mention",
    "parts",
    "thread",
    "with_post_options",
]
