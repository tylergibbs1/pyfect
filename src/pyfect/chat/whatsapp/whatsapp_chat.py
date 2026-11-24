"""The WhatsApp Cloud API adapter for ``pyfect.chat`` (Effect's
``@effect/chat-whatsapp/WhatsAppChat``): the ``Registry`` layer for one
business phone number, the webhook, the pure normaliser, delivery keys,
templates, read receipts and the scoped post options.

- Cloud API only. One adapter is one business phone number, and a
  ``Registry`` holds one adapter per platform.
- An address is ``{phoneNumberId}/u/{user}``, where ``user`` is a phone
  number in digits or a business-scoped user id (BSUID), such as
  ``US.13491208655302741918``. ``{phoneNumberId}/g/{groupId}`` is reserved
  for groups, which are not supported yet: every op on it fails
  ``InvalidRequest`` with detail ``group_unsupported``, and group webhooks
  are logged and dropped.
- Inbound messages carry the BSUID form when the webhook has a BSUID, and
  the phone number only when it has none. The adapter never rewrites an
  address: a reply goes where the thread says. ``whatsapp_update.Alias``
  reports a phone number and a BSUID that name one user.
- A business may only write freely within 24 hours of the user's last
  message. Outside it, a ``post`` fails ``Forbidden`` with detail
  ``OUTSIDE_WINDOW``, and ``send_template`` is the way to write.
- The access token needs ``whatsapp_business_messaging``. Subscribe the app
  to the WhatsApp Business Account's ``messages`` field.
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Sequence
from typing import Any, Never

import pyfect as fx
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.byte_size import ByteSize
from pyfect.chat.chat_adapter import Posted, Registry
from pyfect.chat.chat_error import ChatError
from pyfect.chat.chat_event import ReactionAdded
from pyfect.chat.chat_handler import ChatHandler, NotAccepted
from pyfect.chat.chat_interaction import ButtonClicked, Handler, SelectChanged
from pyfect.chat.chat_test import MentionToken
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.whatsapp import _address, _errors, _json, _normalize, _webhook
from pyfect.chat.whatsapp._adapter import Template, WhatsAppAdapter, percent_encode
from pyfect.chat.whatsapp._address import Parts
from pyfect.chat.whatsapp._normalize import Inbound
from pyfect.chat.whatsapp._options import CurrentPostOptions, WhatsAppPostOptions
from pyfect.chat.whatsapp.whatsapp_graph_api import DEFAULT_BASE_URL, WhatsAppGraphApi
from pyfect.chat.whatsapp.whatsapp_graph_api import layer as _graph_api_layer
from pyfect.chat.whatsapp.whatsapp_update import Alias, Status, UserIdChanged, WhatsAppUpdate
from pyfect.context import Tag
from pyfect.crypto.mac import Mac
from pyfect.duration import Input as DurationInput
from pyfect.duration import from_input_unsafe
from pyfect.http.client import HttpClient
from pyfect.http.router import HttpRouter
from pyfect.http.router import use as _router_use
from pyfect.http.router._router import HttpRouterService
from pyfect.layer import Layer
from pyfect.layer import effect as _layer_effect
from pyfect.layer import provide_merge as _provide_merge
from pyfect.redacted import Redacted

OUTSIDE_WINDOW: str = _errors.OUTSIDE_WINDOW
"""The detail of a ``post`` refused outside the 24 hour customer service
window, Graph error 131047. The reason is ``Forbidden``. Write with
``send_template`` instead."""

type OnUpdate = Callable[[WhatsAppUpdate], Effect[None, NotAccepted]]


class WhatsAppChatService:
    """The WhatsApp side of the adapter, for what the core has no op for.

    - ``send_template`` sends an approved template, which is how to write
      outside the 24 hour window. An authentication template with one-tap,
      zero-tap or copy-code buttons can't be sent to a BSUID: Meta refuses it
      with error 131062, which is ``InvalidRequest``. Send those to a phone
      number address.
    - ``mark_read`` marks a received message read, which shows blue ticks,
      and with ``typing`` shows the typing indicator until the next message
      or for up to 25 seconds.
    - ``receive`` runs one webhook delivery, already verified and parsed, as
      ``layer_webhook`` does, for a consumer's own transport. It needs a
      ``ChatHandler``, and a ``chat_interaction.Handler`` when there are
      clicks: without one a click is logged and dropped. ``deadline`` is a
      click handler's share, 3 seconds by default.
    """

    def __init__(self, *, phone_number_id: str, adapter: WhatsAppAdapter) -> None:
        self._phone_number_id = phone_number_id
        self._adapter = adapter

    @property
    def phone_number_id(self) -> str:
        """The business phone number this adapter writes from."""
        return self._phone_number_id

    def send_template(self, thread: ChatThread, template: Template) -> Effect[Posted, ChatError]:
        """Sends an approved template to ``thread``."""
        return self._adapter.send_template(thread, template)

    def mark_read(
        self, thread: ChatThread, message_id: str, *, typing: bool = False
    ) -> Effect[None, ChatError]:
        """Marks ``message_id`` read, with the typing indicator when ``typing``."""
        return self._adapter.mark_read(thread, message_id, typing=typing)

    def receive(
        self,
        envelope: object,
        *,
        on_update: OnUpdate | None = None,
        deadline: DurationInput = _webhook.CLICK_DEADLINE,
    ) -> Effect[None, NotAccepted, ChatHandler]:
        """Runs one parsed webhook delivery; see the class."""
        click_deadline = fx.succeed(from_input_unsafe(deadline))
        items = _normalize.normalize(envelope, phone_number_id=self._phone_number_id)
        return ChatHandler().flat_map(
            lambda handler: _webhook.receive(
                items,
                _webhook.ReceiveOptions(
                    handle=handler.handle, on_update=on_update, click_deadline=click_deadline
                ),
            )
        )


class WhatsAppChat(Tag[WhatsAppChatService], key="@effect/chat-whatsapp/WhatsAppChat"):
    """The WhatsApp side of the adapter; ``whatsapp_chat.layer`` provides it."""


def layer(
    *,
    access_token: Redacted[str],
    phone_number_id: str,
    messaging_account_id: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
) -> Layer[WhatsAppChat | WhatsAppGraphApi, Never, HttpClient | Registry]:
    """Registers the WhatsApp adapter in the ``Registry``, for one business
    phone number, and provides ``WhatsAppChat`` and ``WhatsAppGraphApi``.

    - Capabilities: ``replyTo``, ``files``, ``download``, ``getThread``,
      ``opener``, ``buttons`` and ``selects``; every other op fails
      ``Unsupported``. WhatsApp has no edit, so ``chat_markdown`` posts each
      part of a streamed reply once.
    - Every ``post`` is one send, and every check runs before any upload or
      send. ``Posted`` means Meta accepted the message, not that it was
      delivered: a later ``failed`` status goes to ``on_update``.
    - Markdown is rendered to WhatsApp's formatting (``*b*``, ``_i_``,
      ``~s~``, a link as ``label (url)``, a heading as bold), each
      replacement only when it is no longer than the Markdown it replaces, so
      the text never grows. Anything else is sent as typed.
    - ``descriptor.measure`` and the label limits count UTF-16 units.
    - Link previews are off unless ``WhatsAppPostOptions(link_preview=True)``.
    - One file per post, uploaded, then sent as one media message with the
      text as its caption, or as the header of reply buttons or a link
      button. Refused with ``TooLarge``, subject ``files`` and detail
      ``file_refused``, before anything is sent: more than one file, a MIME
      type outside Meta's table, a file past its type's size limit, audio
      with text or actions, text over 1,024 beside a file, and a file beside
      a list. ``text/markdown`` is uploaded as ``text/plain``.
    - Actions: one to three buttons with labels up to 20 go as reply
      buttons; a lone link button with a label up to 20 as a link button;
      otherwise buttons and select options become the rows of one list, at
      most ten, with labels up to 24. Other link buttons are appended to the
      text as ``Label: url`` lines.
    - ``get_thread`` is built from the address alone, as ``direct``.
      ``opener`` is always ``None``.
    - ``messaging_account_id`` is sent as ``messaging_account_id`` on every
      message, to say which Messaging account sends.
    """

    @fx.gen
    def build() -> Generator[Effect[Any, Never, Any], Any, WhatsAppChatService]:
        graph = yield from WhatsAppGraphApi()
        http = yield from HttpClient()
        registry = yield from Registry()
        adapter = WhatsAppAdapter(
            graph=graph,
            http=http,
            access_token=access_token,
            phone_number_id=phone_number_id,
            messaging_account_id=messaging_account_id,
        )
        yield from registry.register(adapter)
        return WhatsAppChatService(phone_number_id=phone_number_id, adapter=adapter)

    return _layer_effect(WhatsAppChat, build).pipe(
        _provide_merge(_graph_api_layer(access_token=access_token, base_url=base_url))
    )


def thread(*, phone_number_id: str, user: str) -> ChatThread:
    """The address of a WhatsApp user: ``{phoneNumberId}/u/{user}``, where
    ``user`` is a phone number in digits or a BSUID."""
    return _address.thread(Parts(phone_number_id, "user", user))


def parts(address: ChatThread) -> Parts | None:
    """The parts of a WhatsApp address, or ``None`` for another platform's or
    a malformed one. A group address, which is reserved, has ``kind``
    ``"group"``."""
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
    app_secret: Redacted[str],
    verify_token: Redacted[str],
    on_update: OnUpdate | None = None,
    deadline: DurationInput = _webhook.DEFAULT_DEADLINE,
    max_body_bytes: int = _webhook.DEFAULT_MAX_BODY_BYTES,
) -> Layer[Never, Never, HttpRouter | WhatsAppChat | ChatHandler | Mac]:
    """``GET {path}`` and ``POST {path}``: the webhook's subscription check
    and its deliveries.

    - ``GET`` answers Meta's check with ``hub.challenge`` when
      ``hub.verify_token`` is ``verify_token`` (compared in constant time),
      and 403 otherwise.
    - ``POST`` reads at most ``max_body_bytes`` (3 MiB by default, 413; a
      body that can't be read is 400), checks ``X-Hub-Signature-256`` with
      the app secret in constant time through ``Mac`` (401), refuses a body
      that is not a JSON object or nests past 64 levels (400), and drops a
      delivery for another object or another phone number with a 200.
    - The updates run in order. Messages and reactions go to the
      ``ChatHandler``, clicks to ``chat_interaction.handle``, and statuses
      and changed ids to ``on_update``. A removed reaction is dropped.
    - A ``NotAccepted`` stops the delivery and answers 503, as does a request
      that takes longer than ``deadline``, 10 seconds by default. Meta then
      delivers the whole batch again, for up to 7 days. At the deadline the
      work is interrupted without waiting for its finalizers.
    - A click never causes a 503. It gets what is left of the deadline, less
      a margin. ``OpenModal`` goes to ``Handler.refused`` as
      ``Unsupported("modals")``. Without a ``chat_interaction.Handler`` in
      the layer's context, a click is logged and dropped.
    - Delivery is at least once and not in order: drop repeated events with
      ``chat_event.dedupe_key``, and claim ``delivery_key`` before a click's
      side effects.

    Signature checks use ``Mac`` (``pyfect.crypto.native.layer_mac``).
    """
    max_body_size = _max_body_size(max_body_bytes)
    limit = from_input_unsafe(deadline)

    def register(router: HttpRouterService) -> Effect[None, Never, Any]:
        @fx.gen
        def body() -> Generator[Effect[Any, Never, Any], Any]:
            whatsapp = yield from WhatsAppChat()
            handler = yield from ChatHandler()
            interactions = yield from fx.service_option(Handler)
            verify = yield from _webhook.make_verifier(app_secret)
            phone_number_id = whatsapp.phone_number_id
            options = _webhook.Options(
                verify=verify,
                normalize=lambda envelope: _normalize.normalize(
                    envelope, phone_number_id=phone_number_id
                ),
                handle=handler.handle,
                on_update=on_update,
                deadline=limit,
                max_body_size=max_body_size,
            )

            def post(request: Any) -> Effect[Any, Never, Any]:
                response = _webhook.handle_request(request, options)
                if interactions is None:
                    return response
                return response.pipe(fx.provide_service(Handler, interactions.value))

            yield from router.add(
                "GET",
                path,
                lambda request: fx.succeed(_webhook.handle_verification(request, verify_token)),
            )
            yield from router.add("POST", path, post)

        return body

    return _router_use(register)


def normalize(envelope: object, *, phone_number_id: str) -> list[Inbound]:
    """The normaliser, for a consumer's own transport.

    - Pure: takes a parsed webhook body, gives what it holds, in order. A
      change for another phone number, and a group message, give nothing.
    - A message's ``thread`` is the sender's BSUID address when the webhook
      has one, and its phone number address otherwise; ``kind`` is
      ``direct``. Text is as the user typed it, a caption for media, and
      empty for a message with neither. Media are attachments, with the media
      id as their ``id``.
    - ``raw`` of an event or a click is the change's ``metadata``, the
      sender's entry of ``contacts`` and the one message. ``message.raw`` is
      the message.
    - A reaction with an emoji is ``ReactionAdded``; a removed reaction gives
      nothing.
    - A reply button or a list row the adapter built is ``ButtonClicked`` or
      ``SelectChanged``, whose ``message_id`` is the message that carried it.
      Any other interactive reply gives nothing.
    - Statuses give ``Status``, and ``Alias`` too when they carry both ids. A
      ``system`` message about a changed number or id gives ``UserIdChanged``.
    """
    return _normalize.normalize(envelope, phone_number_id=phone_number_id)


def _encode_key(parts: Sequence[str]) -> str:
    return "/".join(percent_encode(part) for part in parts)


def _phone_number_of(thread: ChatThread) -> str:
    return thread.id.split("/")[0]


def delivery_key(event: ButtonClicked | SelectChanged | ReactionAdded) -> str:
    """The key of one delivery of a click or a reaction:
    ``{phoneNumberId}/{messageId}``, the id of the webhook message that
    carried it, each part percent-encoded.

    Meta redelivers a batch that was not answered in time, so a click can run
    again, even at the same time as the first run. Claim the key atomically,
    such as with an insert that fails on a duplicate, before any side effect,
    and skip the click when the claim fails."""
    raw = _json.as_object(event.raw)
    messages = _json.as_list(None if raw is None else raw.get("messages"))
    id = _json.string(messages[0], "id") if messages else None
    return _encode_key([_phone_number_of(event.thread), id or ""])


def update_key(update: WhatsAppUpdate) -> str:
    """The key of an update, for dropping a redelivered one, its parts
    percent-encoded and joined by ``/``.

    - ``Status``: ``{phoneNumberId}/status/{messageId}/{status}``.
    - ``UserIdChanged``: ``{phoneNumberId}/user_changed/{id}``.
    - ``Alias``: ``{phoneNumberId}/alias/{messageId}/{status}/{phone}/{userId}``.
    """
    phone_number_id = _phone_number_of(update.thread)
    match update:
        case Status():
            return _encode_key([phone_number_id, "status", update.message_id, update.status])
        case UserIdChanged():
            return _encode_key([phone_number_id, "user_changed", update.id])
        case Alias():
            return _encode_key(
                [
                    phone_number_id,
                    "alias",
                    update.message_id,
                    update.status,
                    update.phone,
                    update.user_id,
                ]
            )


def with_post_options[A, E, R](
    options: WhatsAppPostOptions,
) -> Callable[[Effect[A, E, R]], Effect[A, E, R]]:
    """Scoped WhatsApp options for every write inside an effect; use with
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
    """WhatsApp has no mention tokens outside groups, so nothing is a
    mention: for ``chat_test``'s checks and conformance suite."""
    del text
    return None


__all__ = [
    "OUTSIDE_WINDOW",
    "ChatError",
    "Inbound",
    "NotAccepted",
    "OnUpdate",
    "Parts",
    "Template",
    "WhatsAppChat",
    "WhatsAppChatService",
    "WhatsAppPostOptions",
    "delivery_key",
    "layer",
    "layer_webhook",
    "normalize",
    "parse_mention",
    "parts",
    "thread",
    "update_key",
    "with_post_options",
]
