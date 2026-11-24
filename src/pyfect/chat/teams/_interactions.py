"""Verified invokes, card submit fallbacks and targeted messages, as
``chat_interaction`` events, and the answers Teams takes for them."""

from __future__ import annotations

import re
from collections.abc import Callable, Generator, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Any, Never, cast

import pyfect as fx
from pyfect._core import Effect
from pyfect._js import SPACE, to_well_formed
from pyfect._json_value import JsonValue
from pyfect.chat import chat_interaction as ci
from pyfect.chat.chat_error import AnyReason, Capability, ChatError
from pyfect.chat.chat_interaction import Handler
from pyfect.chat.chat_ui import Action, Modal, SelectInput, Text, TextInput
from pyfect.chat.teams import _envelope, _errors, _json, _render
from pyfect.chat.teams._envelope import Envelope
from pyfect.chat.teams._json import JsonObject
from pyfect.chat.teams._normalize import locate, thread_of, user_id
from pyfect.duration import Duration, seconds
from pyfect.result import Err

DEFAULT_DEADLINE = seconds(4)
"""The default share of Teams' invoke timeout the handler gets."""

MODAL_METADATA_LENGTH = 4_000
"""The adapter's own cap on a modal's id plus metadata, counted as the whole
signed dialog token that carries them: the claims, the metadata and the
modal's definition (title, labels, options, texts)."""

MODAL_FIELDS = 10
"""The adapter's own cap on a modal's inputs and texts."""


@dataclass(frozen=True)
class InvokeResponse:
    """An answer to an invoke: the HTTP status and the JSON body, if any."""

    status: int
    body: JsonValue = None


_OK = InvokeResponse(200)
_FAILURE_MESSAGE = "This action could not be completed."


def _safe_failure(name: str) -> InvokeResponse:
    """What an invoke that fails a check gets. It names no reason."""
    if name == "adaptiveCard/action":
        return InvokeResponse(
            200,
            {
                "statusCode": 400,
                "type": "application/vnd.microsoft.error",
                "value": {"code": "BadRequest", "message": _FAILURE_MESSAGE},
            },
        )
    return InvokeResponse(200, {"task": {"type": "message", "value": _FAILURE_MESSAGE}})


_EXECUTE_ACK = InvokeResponse(
    200, {"statusCode": 200, "type": "application/vnd.microsoft.activity.message", "value": ""}
)

type Answer = Callable[
    [str, JsonValue, str, tuple[Action, ...], ci.Visibility], Effect[None, ChatError]
]
"""Sends a command's answer through the inbound ``serviceUrl`` in ``raw``."""


@dataclass(frozen=True, kw_only=True)
class Options:
    capabilities: AbstractSet[Capability]
    envelope: Envelope | None
    modal_buttons: AbstractSet[str]
    """The ids of the buttons that open a dialog."""
    answer: Answer
    deadline: Duration


def _refused(
    event: ci.ButtonClicked | ci.CommandInvoked, error: ChatError
) -> Effect[None, Never, Handler]:
    return Handler().flat_map(lambda handler: handler.refused(event, error))


def _own(record: Mapping[str, str], key: str) -> str | None:
    value = record.get(key)
    return value if isinstance(value, str) else None


def dialog_card(
    modal: Modal,
    token: str,
    values: Mapping[str, str] | None = None,
    errors: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """The adaptive card of a dialog, built only from the signed definition.
    A dialog sent again with errors keeps what the user entered, not the
    definition's ``initial``."""
    body: list[object] = []
    for element in modal.elements:
        if isinstance(element, Text):
            body.append(_render.text_block(_render.escape_text(to_well_formed(element.text))))
            continue
        value = element.initial if values is None else _own(values, element.id)
        if isinstance(element, TextInput):
            item: dict[str, object] = {
                "type": "Input.Text",
                "id": element.id,
                "label": element.label,
                "isMultiline": element.multiline,
                "isRequired": not element.optional,
                "maxLength": _envelope.DEFAULT_MAX_LENGTH
                if element.max_length is None
                else element.max_length,
            }
        else:
            select: SelectInput = element
            item = {
                "type": "Input.ChoiceSet",
                "id": select.id,
                "label": select.label,
                "style": "compact",
                "isRequired": not select.optional,
                "choices": [{"title": o.label, "value": o.value} for o in select.options],
            }
        if element.placeholder is not None:
            item["placeholder"] = element.placeholder
        if value is not None:
            item["value"] = value
        body.append(item)
        error = None if errors is None else _own(errors, element.id)
        if error is not None:
            body.append(
                {
                    **_render.text_block(_render.escape_text(to_well_formed(error))),
                    "color": "attention",
                }
            )
    content = {
        **_render.card(body),
        "actions": [
            {
                "type": "Action.Submit",
                "title": modal.submit_label or "Submit",
                "data": {_envelope.RESERVED_KEY: token},
            }
        ],
    }
    return {
        "task": {
            "type": "continue",
            "value": {
                "title": modal.title,
                "card": {"contentType": _render.CARD_CONTENT_TYPE, "content": content},
            },
        }
    }


def _modal_refusal(modal: Modal) -> AnyReason | None:
    if len(modal.elements) > MODAL_FIELDS:
        return _errors.too_large(None, "too_many_modal_fields")
    return _envelope.check_modal(modal)


def invoke(activity: JsonObject, options: Options) -> Effect[InvokeResponse, Never, Handler]:
    """One verified invoke, or a card's ``Action.Submit`` fallback, which
    comes as a ``message`` with a ``value``.

    - ``adaptiveCard/action`` and the fallback are clicks. A click can't
      open a dialog there: an ``OpenModal`` goes to ``Handler.refused`` as
      ``Unsupported``.
    - ``task/fetch`` is a click on a button named in ``modal_buttons``,
      whose ``OpenModal`` opens the dialog, signed for the clicking user.
    - ``task/submit`` is a dialog submit, checked against its signed
      definition.
    - A token that does not verify, or values that do not match the
      definition, get the safe failure and dispatch nothing.
    """
    name = "message" if activity.get("type") == "message" else _json.string(activity, "name") or ""
    failure = _safe_failure(name)
    envelope = options.envelope
    if envelope is None or "buttons" not in options.capabilities:
        return fx.succeed(failure)
    conversation_id = _json.string(_json.object_(activity, "conversation"), "id")
    user = user_id(_json.object_(activity, "from"))
    if conversation_id is None or user is None:
        return fx.succeed(failure)
    value = _json.object_(activity, "value")
    data = (
        _json.object_(_json.object_(value, "action"), "data")
        if name == "adaptiveCard/action"
        else value
        if name == "message"
        else _json.object_(value, "data")
    )
    token = None if data is None else data.get(_envelope.RESERVED_KEY)
    raw = cast("JsonValue", activity)

    @fx.gen
    def submit() -> Generator[Effect[Any, Never, Any], Any, InvokeResponse]:
        if "modals" not in options.capabilities:
            return failure
        assert envelope is not None
        dialog = yield from envelope.verify_dialog(
            token, conversation_id=conversation_id, user_id=user
        )
        if dialog is None:
            return failure
        values = _envelope.validate_submission(dialog.modal, data)
        # The thread of the click that opened it, from the signed conversation
        # id and message, never from the submit.
        origin = locate(dialog.conversation_id, dialog.message_id)
        if values is None or origin is None:
            return failure
        modal = dialog.modal
        event = ci.ModalSubmitted(
            id=modal.id,
            metadata=modal.metadata,
            values=values,
            thread=origin.thread,
            message_id=dialog.message_id,
            user_id=user,
            raw=raw,
        )
        reply = yield from ci.handle(event, options.deadline)
        if isinstance(reply, ci.Late):
            return failure
        if isinstance(reply, ci.Errors):
            card = dialog_card(modal, cast("str", token), values, reply.errors)
            return InvokeResponse(200, cast("JsonValue", card))
        return _OK

    @fx.gen
    def click() -> Generator[Effect[Any, Never, Any], Any, InvokeResponse]:  # noqa: PLR0911
        assert envelope is not None
        button = yield from envelope.verify_button(token, conversation_id=conversation_id)
        message_id = _json.string(activity, "replyToId")
        # A card posted as a channel post has the channel as its address, as normalize gives it.
        at = locate(conversation_id, message_id)
        if button is None or at is None or message_id is None:
            return failure
        opens_dialog = name == "task/fetch"
        if opens_dialog != (button.id in options.modal_buttons):
            return failure
        event = ci.ButtonClicked(
            id=button.id,
            value=button.value,
            thread=at.thread,
            message_id=message_id,
            user_id=user,
            raw=raw,
        )
        reply = yield from ci.handle(event, options.deadline)
        acked = (
            _EXECUTE_ACK if name == "adaptiveCard/action" else _OK if name == "message" else failure
        )
        if isinstance(reply, (ci.Late, ci.Ack)):
            return acked
        if not opens_dialog or "modals" not in options.capabilities:
            yield from _refused(
                event, _errors.chat_error("openModal", _errors.unsupported("modals"))
            )
            return acked
        refusal = _modal_refusal(reply.modal)
        if refusal is not None:
            yield from _refused(event, _errors.chat_error("openModal", refusal))
            return failure
        signed = yield from envelope.sign_dialog(
            _envelope.Dialog(
                conversation_id=conversation_id,
                modal=reply.modal,
                message_id=message_id,
            ),
            user_id=user,
        ).result()
        # ``MODAL_METADATA_LENGTH`` holds the whole signed token: the definition,
        # the metadata and every claim. Signing is local, so the check is exact
        # and nothing has opened yet.
        if isinstance(signed, Err) or len(signed.value) > MODAL_METADATA_LENGTH:
            reason = signed.error if isinstance(signed, Err) else None
            yield from _refused(
                event,
                _errors.chat_error(
                    "openModal", reason or _errors.too_large(None, "modal_too_large")
                ),
            )
            return failure
        return InvokeResponse(200, cast("JsonValue", dialog_card(reply.modal, signed.value)))

    if name == "task/submit":
        return submit
    if name not in ("adaptiveCard/action", "message", "task/fetch"):
        return fx.succeed(failure)
    return click


_LEADING_SPACE = re.compile(f"[{SPACE}]*")
_LEADING_MENTION = re.compile("<at>[^<]*</at>")


def _command_start(text: str) -> int:
    """Where a command's name starts: after leading ``<at>…</at>`` tokens,
    spaces and one slash."""
    at = 0
    while True:
        at = _LEADING_SPACE.match(text, at).end()  # pyright: ignore[reportOptionalMemberAccess]
        mention = _LEADING_MENTION.match(text, at)
        if mention is None:
            break
        at = mention.end()
    return at + 1 if text.startswith("/", at) else at


_COMMAND = re.compile(f"([^{SPACE}]+)[{SPACE}]*(.*)", re.DOTALL)


def command(
    activity: JsonObject,
    options: Options,
    is_registered: Callable[[str], Effect[bool]],
) -> Effect[None, Never, Handler]:
    """A verified targeted message. Its first word names the command, and
    the rest is the command's ``text``. A message whose first word names no
    registered command is acked and nothing is sent. Nothing here ever
    reaches ``ChatHandler`` or posts in public unless the handler asks."""
    if "commands" not in options.capabilities:
        return fx.void
    text = activity.get("text")
    text = text if isinstance(text, str) else ""
    rest = text[_command_start(text) :]
    match = _COMMAND.fullmatch(rest)
    user = user_id(_json.object_(activity, "from"))
    at = thread_of(activity)
    if match is None or user is None or at is None:
        return fx.void
    id, argument = match.group(1), match.group(2)
    raw = cast("JsonValue", activity)

    @fx.gen
    def run() -> Generator[Effect[Any, Never, Any], Any]:
        if not (yield from is_registered(id)):
            return
        event = ci.CommandInvoked(id=id, text=argument, thread=at.thread, user_id=user, raw=raw)
        reply = yield from ci.handle(event, options.deadline)
        if isinstance(reply, ci.OpenModal):
            yield from _refused(
                event, _errors.chat_error("openModal", _errors.unsupported("modals"))
            )
        elif isinstance(reply, ci.Respond):
            yield from options.answer(
                "respond", raw, reply.markdown, reply.actions or (), reply.visibility
            ).catch_all(lambda error: _refused(event, error))

    return run


def is_submit_fallback(activity: JsonObject) -> bool:
    """Whether a ``message`` is a card's ``Action.Submit`` fallback."""
    value = _json.as_object(activity.get("value"))
    return (
        activity.get("type") == "message" and value is not None and _envelope.RESERVED_KEY in value
    )
