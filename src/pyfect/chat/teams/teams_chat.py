"""The Microsoft Teams adapter for ``pyfect.chat`` (Effect's
``@effect/chat-teams/TeamsChat``): the ``Registry`` layer, the Bot Framework
messaging endpoint, the pure normaliser and address helpers.

- Register a bot in Azure Bot Service with the Microsoft Teams channel, and
  point its messaging endpoint at ``layer_webhook``'s path.
- The layer works in one tenant: ``tenant_id`` is the tenant the bot's app
  registration lives in, and activities from any other tenant are refused.
- Buttons, modals, commands, ``start_thread`` and downloads are off until
  each is turned on in ``Unverified``: their live checks against Teams have
  not passed yet.
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Mapping, Sequence
from typing import Any, Literal, Never, cast

import pyfect as fx
from pyfect._context_effects import service_option
from pyfect._core import Effect, _call_user
from pyfect._json_value import JsonValue
from pyfect.byte_size import ByteSize
from pyfect.chat.chat_adapter import Registry
from pyfect.chat.chat_error import ChatError
from pyfect.chat.chat_event import ChatEvent
from pyfect.chat.chat_handler import ChatHandler
from pyfect.chat.chat_interaction import Handler
from pyfect.chat.chat_interaction import Registry as InteractionRegistry
from pyfect.chat.chat_test import MentionToken
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.teams import _address, _auth, _connector, _envelope, _interactions, _webhook
from pyfect.chat.teams._adapter import TeamsAdapter
from pyfect.chat.teams._address import Parts
from pyfect.chat.teams._cloud import PUBLIC_CLOUD, Cloud, Credentials, TokenGrant, Unverified
from pyfect.chat.teams._json import JsonObject
from pyfect.chat.teams._normalize import Context
from pyfect.chat.teams._normalize import normalize as _normalize
from pyfect.context import Tag
from pyfect.crypto.digest import Digest
from pyfect.crypto.mac import Mac
from pyfect.crypto.signature import Signature
from pyfect.duration import Input as DurationInput
from pyfect.duration import from_input_unsafe
from pyfect.http.client import HttpClient
from pyfect.http.router import HttpRouter
from pyfect.http.router import use as _router_use
from pyfect.http.router._router import HttpRouterService
from pyfect.jose.jwk import SecretJwk
from pyfect.layer import Layer
from pyfect.layer import effect as _layer_effect
from pyfect.redacted import Redacted

__all__ = [
    "PUBLIC_CLOUD",
    "ChatError",
    "Cloud",
    "Credentials",
    "Parts",
    "TeamsChat",
    "TeamsChatService",
    "TokenGrant",
    "Unverified",
    "layer",
    "layer_webhook",
    "normalize",
    "parse_mention",
    "parts",
    "thread",
]

type Method = Literal["GET", "POST", "PUT", "DELETE"]


class TeamsChatService:
    """The Teams side of the adapter.

    ``call`` sends one Connector request, with the bot's token, for what the
    adapter has no op for. ``path`` starts with ``/v3/`` and has its
    segments encoded. A ``service_url`` routes it to an inbound activity's
    Connector, after the allowlist check. A write is never retried once
    sent, and a failure that may have landed is ``uncertain``.
    """

    def __init__(
        self,
        *,
        app_id: str,
        tenant_id: str,
        cloud: Cloud,
        connector: _connector.Connector,
        interactions: _interactions.Options,
    ) -> None:
        self._app_id = app_id
        self._tenant_id = tenant_id
        self._cloud = cloud
        self._connector = connector
        # What ``layer_webhook`` needs from the layer that registered the adapter.
        self._interactions = interactions

    @property
    def app_id(self) -> str:
        return self._app_id

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    @property
    def cloud(self) -> Cloud:
        return self._cloud

    def call(
        self,
        method: Method,
        path: str,
        body: object = None,
        *,
        write: bool = False,
        service_url: str | None = None,
        query: Mapping[str, str] | None = None,
    ) -> Effect[JsonValue | None, ChatError]:
        """One Connector request; see the class."""
        return self._connector.call(
            method, path, body, write=write, service_url=service_url, query=query
        )


class TeamsChat(Tag[TeamsChatService], key="@effect/chat-teams/TeamsChat"):
    """The Teams side of the adapter; ``teams_chat.layer`` provides it."""


def layer(
    *,
    app_id: str,
    tenant_id: str,
    credentials: Credentials,
    cloud: Cloud = PUBLIC_CLOUD,
    interaction_keys: Sequence[Redacted[SecretJwk]] = (),
    modal_buttons: Sequence[str] = (),
    unverified: Unverified = Unverified(),  # noqa: B008
) -> Layer[TeamsChat, Never, HttpClient | Registry | Mac | Digest]:
    """Registers the Teams adapter in the ``Registry``, for one tenant, and
    provides ``TeamsChat``.

    - ``post`` and ``edit`` without elements send the Markdown as ``text``
      with ``textFormat: "extendedmarkdown"``, with every ``<`` and ``&`` as
      an entity, so no HTML and no ``<at>`` mention forms, and every ``$``
      outside code as ``\\$``, so Teams reads no math. Mentions notify
      nobody.
    - With elements, the message is one Adaptive Card and no ``text``:
      ``TextBlock``, ``CodeBlock`` and ``Table`` elements from the Markdown,
      then ``ActionSet`` rows. An ``edit`` may switch between the two forms.
    - ``limits.message_length`` is a budget, not Microsoft's number: 50,000
      UTF-16 units of activity JSON (half the 100 KB Microsoft documents)
      less a fixed reservation for the card's structure, the other members
      and 4,000 units of mention entities. 44,288 today.
    - A button carries a signed token (an HS256 JWT) under the card data key
      ``effect``, bound to the app, the tenant and the conversation. It is
      signed, not encrypted: anyone who sees the card can read the id and
      value, and a click can be sent again while the conversation exists.
      A dialog token also binds the user and expires after an hour.
    - The adapter's own caps: 6 elements per message, 10 fields per modal,
      1,000 units of button token (about 500 ASCII characters of id plus
      value) and 4,000 units of dialog token for the whole modal.
    - The ``HttpClient`` must add no credentials of its own. The adapter
      decides per request which host gets the bot's token, turns redirects
      off and fails a response from any other URL than the one it sent to.
    - ``get_user`` needs ``in_``, the thread whose roster to read; without it
      it fails ``InvalidRequest`` with ``thread_required``. A user's id is
      the Entra object id when Teams sends one, and the Connector id
      (``29:…``, ``28:…``) otherwise; ``raw`` keeps the Connector record.
    - ``interaction_keys`` sign button and dialog tokens. The first signs and
      any verifies by its ``kid``, so a rotation adds a key in front and
      drops the old one later. Each needs a distinct ``kid`` of 1 to 16
      characters from ``[A-Za-z0-9_-]`` and at least 32 bytes. Without keys
      there are no buttons or modals.
    - ``modal_buttons`` are the ids of the buttons that open a dialog. Only
      these may answer ``OpenModal``.

    Interaction tokens use ``Mac`` and ``Digest``
    (``pyfect.crypto.native.layer_mac`` and ``layer_digest``).
    """

    @fx.gen
    def build() -> Generator[Effect[Any, Never, Any], Any, TeamsChatService]:
        http = yield from HttpClient()
        registry = yield from Registry()
        tokens = _connector.make_tokens(
            http=http, cloud=cloud, app_id=app_id, tenant_id=tenant_id, credentials=credentials
        )
        connector = _connector.Connector(http=http, cloud=cloud, token=tokens)
        envelope = (
            None
            if not interaction_keys
            else (
                yield from _envelope.make(app_id=app_id, tenant_id=tenant_id, keys=interaction_keys)
            )
        )
        adapter = TeamsAdapter(
            connector=connector,
            http=http,
            cloud=cloud,
            app_id=app_id,
            envelope=envelope,
            unverified=unverified,
            token=tokens(cloud.connector_scope),
            modal_buttons=frozenset(modal_buttons),
        )
        yield from registry.register(adapter)
        return TeamsChatService(
            app_id=app_id,
            tenant_id=tenant_id,
            cloud=cloud,
            connector=connector,
            interactions=_interactions.Options(
                capabilities=adapter.capabilities,
                envelope=envelope,
                modal_buttons=adapter.modal_buttons,
                answer=adapter.answer,
                deadline=_interactions.DEFAULT_DEADLINE,
            ),
        )

    return _layer_effect(TeamsChat, build)


def _max_body_size(max_body_bytes: int) -> ByteSize:
    if isinstance(max_body_bytes, bool) or not 0 <= max_body_bytes <= 2**53 - 1:
        raise ValueError(
            f"max_body_bytes must be a non-negative safe integer, got {max_body_bytes!r}"
        )
    return ByteSize(max_body_bytes)


def _ignore(_activity: JsonValue) -> Effect[None]:
    return fx.void


def layer_webhook(
    *,
    path: str,
    deadline: DurationInput = "10 seconds",
    interaction_deadline: DurationInput = _interactions.DEFAULT_DEADLINE,
    max_body_bytes: int = _webhook.DEFAULT_MAX_BODY_BYTES,
    on_unhandled: Callable[[JsonValue], Effect[None]] = _ignore,
) -> Layer[Never, Never, HttpRouter | TeamsChat | ChatHandler | HttpClient | Signature]:
    """``POST {path}``: the bot's messaging endpoint.

    - Checks the bearer token: RS256 with a key from Bot Framework's key set
      that is endorsed for ``msteams``, the cloud's issuer, the app id as
      audience, five minutes of skew and an ``exp``. Then the token's
      ``serviceurl`` must equal the activity's ``serviceUrl``, ``channelId``
      must be ``msteams`` and the tenant the layer's. Any failure is 403. A
      key set that can't be read is 503.
    - A targeted activity, one only the bot can see, is classified before
      anything else. A targeted message takes the command path: its first
      word names the command and the rest is its ``text``. One that names no
      registered command is acked and nothing is sent. A targeted invoke
      goes to the interaction handler. Any other is answered 200 and
      dropped. None reaches the ``ChatHandler``, ``on_unhandled``, or
      anything public.
    - Invokes go to ``chat_interaction.Handler`` within
      ``interaction_deadline`` (4 seconds by default). Without a ``Handler``
      in context, every invoke and every targeted message gets an empty 200.
    - Other activities go through ``normalize`` to the ``ChatHandler``: 200
      when it succeeds, 503 when it fails ``NotAccepted`` or a message can't
      be normalised. An activity with no event goes to ``on_unhandled`` and
      is answered 200. Past ``deadline`` (10 seconds by default) the handler
      is interrupted and the answer is 503. Each 503 is logged with its
      reason.
    - Answers 413 past ``max_body_bytes`` (1 MiB by default), and 400 for a
      body that can't be read or is not a JSON object, both before the token
      is checked.

    The metadata and the key set are fetched with redirects off, and the
    metadata is read up to 64 KiB. Token checks use ``Signature``
    (``pyfect.crypto.native.layer_signature``).
    """
    max_body_size = _max_body_size(max_body_bytes)
    limit = from_input_unsafe(deadline)
    interaction_limit = from_input_unsafe(interaction_deadline)

    def register(router: HttpRouterService) -> Effect[None, Never, Any]:
        @fx.gen
        def body() -> Generator[Effect[Any, Never, Any], Any]:
            teams = yield from TeamsChat()
            internals = teams._interactions  # pyright: ignore[reportPrivateUsage]
            handler = yield from ChatHandler()
            interaction_handler = yield from service_option(Handler)
            interaction_registry = yield from service_option(InteractionRegistry)
            verify = yield from _auth.make_verifier(
                cloud=teams.cloud, app_id=teams.app_id, tenant_id=teams.tenant_id
            )
            options = _interactions.Options(
                capabilities=internals.capabilities,
                envelope=internals.envelope,
                modal_buttons=internals.modal_buttons,
                answer=internals.answer,
                deadline=interaction_limit,
            )

            def invoke(activity: JsonObject) -> Effect[_interactions.InvokeResponse]:
                if interaction_handler is None:
                    return fx.succeed(_interactions.InvokeResponse(200))
                return _interactions.invoke(activity, options).pipe(
                    fx.provide_service(Handler, interaction_handler.value)
                )

            def command(activity: JsonObject) -> Effect[None]:
                if interaction_handler is None or interaction_registry is None:
                    return fx.void
                registry = interaction_registry.value

                def is_registered(id: str) -> Effect[bool]:
                    return registry.get(id).map(
                        lambda entry: entry is not None and entry.definition.kind == "command"
                    )

                return _interactions.command(activity, options, is_registered).pipe(
                    fx.provide_service(Handler, interaction_handler.value)
                )

            webhook = _webhook.Options(
                verify=verify,
                context=Context(
                    app_id=teams.app_id,
                    connector_hosts=frozenset(teams.cloud.connector_hosts),
                    file_host_suffixes=teams.cloud.file_host_suffixes,
                ),
                handle=handler.handle,
                on_unhandled=lambda activity: _call_user(on_unhandled, cast("JsonValue", activity)),
                invoke=invoke,
                command=command,
                deadline=limit,
                max_body_size=max_body_size,
            )
            yield from router.add(
                "POST", path, lambda request: _webhook.handle_request(request, webhook)
            )

        return body

    return _router_use(register)


def thread(conversation_id: str) -> ChatThread:
    """The address of a Teams conversation: the Bot Framework conversation id
    as it is. A channel thread is the channel's id followed by
    ``;messageid={root}``."""
    return _address.thread(conversation_id)


def parts(address: ChatThread) -> Parts | None:
    """The parts of a Teams address, or ``None`` for another platform's or a
    malformed one."""
    return _address.parts(address)


def normalize(activity: object, *, app_id: str, cloud: Cloud = PUBLIC_CLOUD) -> list[ChatEvent]:
    """The normaliser, for a consumer's own transport. It checks no token:
    that is the transport's job.

    - Pure: takes an activity, gives zero or more events.
    - A ``message`` gives a ``MessageCreated``. Its ``text`` is Teams' text
      as delivered, with ``<at>…</at>`` for each mention, where ``mentions``
      point. A channel post is addressed to the channel, a reply to the
      post's thread.
    - ``messageReaction`` gives a ``ReactionAdded`` or ``ReactionRemoved``
      per reaction. The six types Teams documents are Unicode emoji; any
      other is ``custom:{type}``.
    - A targeted activity, a card submit and anything else give none.
    - ``raw`` is the activity.
    """
    return _normalize(
        activity,
        Context(
            app_id=app_id,
            connector_hosts=frozenset(cloud.connector_hosts),
            file_host_suffixes=cloud.file_host_suffixes,
        ),
    )


def parse_mention(text: str) -> MentionToken | None:
    """Reads one Teams mention, ``<at>…</at>``, for ``chat_test``. The tag
    holds a display name and no id, so this is always ``None``; a message's
    ``mentions`` come from its entities."""
    return None
