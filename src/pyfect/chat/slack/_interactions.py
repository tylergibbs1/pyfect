"""Slack's side of buttons, selects, modals and slash commands: the checks on
a message's elements, the view a modal opens as, and the interactivity
payloads and command forms."""

from __future__ import annotations

import math
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Never, cast

import pyfect as fx
from pyfect._core import Effect
from pyfect._json_value import JsonValue
from pyfect.chat import chat_interaction
from pyfect.chat.chat_error import (
    INTERACTION_EXPIRED,
    AnyReason,
    ChatError,
    InvalidRequest,
    NotFound,
    TooLarge,
)
from pyfect.chat.chat_interaction import (
    Ack,
    ButtonClicked,
    Close,
    CommandInvoked,
    Defer,
    Errors,
    Handler,
    Interaction,
    Late,
    ModalSubmitted,
    OpenModal,
    Respond,
    SelectChanged,
    Visibility,
)
from pyfect.chat.chat_ui import (
    Action,
    Button,
    LinkButton,
    Modal,
    Select,
    SelectInput,
    Text,
    TextInput,
)
from pyfect.chat.slack import _actions, _address, _errors, _json
from pyfect.chat.slack._json import JsonObject
from pyfect.duration import Duration, millis
from pyfect.result import Err

ACTIONS_PER_MESSAGE = 25
ACTION_DATA_LENGTH = 2_000
MODAL_METADATA_LENGTH = 2_800
MODAL_FIELDS = 100

_ID_LENGTH = 255
"""Slack's limit on an ``action_id`` and a ``callback_id``, in code points."""
_TITLE_LENGTH = 24
_LABEL_LENGTH = 2_000
_DEFAULT_SUBMIT_LABEL = "Submit"
"""The submit label when the modal has none: Slack needs one on a view with
inputs."""

DEFAULT_DEADLINE = millis(2_500)
"""The handler's share of Slack's 3 seconds."""


def check_actions(actions: Sequence[Action]) -> AnyReason | None:
    """Why a message's elements can't go, if they can't: more than 25, an id
    holding the join or longer than 255, or an id plus a value longer than
    2,000. All count code points."""
    if len(actions) > ACTIONS_PER_MESSAGE:
        return TooLarge(detail="too_many_actions")
    for action in actions:
        if isinstance(action, LinkButton):
            continue
        if _actions.JOIN in action.id:
            return InvalidRequest(detail="invalid_action_id")
        id = len(action.id)
        if id > _ID_LENGTH:
            return TooLarge(detail="action_id_too_long")
        values = (
            [action.value or ""]
            if isinstance(action, Button)
            else [option.value for option in action.options]
        )
        if any(id + len(value) > ACTION_DATA_LENGTH for value in values):
            return TooLarge(detail="action_data_too_long")
    return None


# Modals

_METADATA_TAG = "chat1"
"""Marks a ``private_metadata`` the adapter packed."""


@dataclass(frozen=True)
class _Origin:
    """Where a click or a command happened, which a submit gives back. A
    command has no message."""

    channel: str
    thread_ts: str | None = None
    message_id: str | None = None


def _pack_metadata(origin: _Origin, metadata: str | None) -> str:
    """Consumer metadata is last so it may contain the join delimiter."""
    parts = [_METADATA_TAG, origin.channel, origin.thread_ts or "", origin.message_id or ""]
    if metadata is not None:
        parts.append(metadata)
    return _actions.JOIN.join(parts)


def _unpack_metadata(packed: str) -> tuple[_Origin, str | None] | None:
    parts = packed.split(_actions.JOIN)
    if len(parts) < 4 or parts[0] != _METADATA_TAG or parts[1] == "":
        return None
    origin = _Origin(parts[1], parts[2] or None, parts[3] or None)
    return origin, None if len(parts) == 4 else _actions.JOIN.join(parts[4:])


def _input_block(element: TextInput | SelectInput) -> dict[str, object]:
    inner: object
    if isinstance(element, TextInput):
        text: dict[str, object] = {
            "type": "plain_text_input",
            "action_id": element.id,
            "multiline": element.multiline,
        }
        if element.placeholder is not None:
            text["placeholder"] = _actions.plain_text(element.placeholder)
        if element.initial is not None:
            text["initial_value"] = element.initial
        if element.min_length is not None:
            text["min_length"] = element.min_length
        if element.max_length is not None:
            text["max_length"] = element.max_length
        inner = text
    else:
        inner = _actions.elements(
            [
                Select(
                    id=element.id,
                    options=element.options,
                    placeholder=element.placeholder,
                    selected=element.initial,
                )
            ]
        )[0]
    return {
        "type": "input",
        "block_id": element.id,
        "label": _actions.plain_text(element.label),
        "optional": element.optional,
        "element": inner,
    }


type _Opener = ButtonClicked | SelectChanged | CommandInvoked


def view(modal: Modal, opener: _Opener) -> dict[str, object] | AnyReason:  # noqa: PLR0911
    """The view that opens ``modal`` from ``opener``, or why it can't open.

    - Inputs are ``input`` blocks whose ``block_id`` is the field id, and a
      ``Text`` is a ``section`` of plain text.
    - The modal's id is the ``callback_id``. ``private_metadata`` holds the
      click's channel, thread and message beside the consumer's metadata.
      For a command the message slot is empty.
    - The modal's id plus its metadata is held to 2,800 code points, the id
      to 255, the title to 24 and each label to 2,000.
    """
    id = len(modal.id)
    if id + len(modal.metadata or "") > MODAL_METADATA_LENGTH:
        return TooLarge(detail="modal_metadata_too_long")
    if id > _ID_LENGTH:
        return TooLarge(detail="modal_id_too_long")
    if len(modal.elements) > MODAL_FIELDS:
        return TooLarge(detail="too_many_fields")
    if len(modal.title) > _TITLE_LENGTH:
        return TooLarge(detail="title_too_long")
    parts = _address.parts(opener.thread)
    if parts is None:
        return InvalidRequest(detail="invalid_thread")
    blocks: list[object] = []
    for element in modal.elements:
        if isinstance(element, Text):
            blocks.append({"type": "section", "text": _actions.plain_text(element.text)})
            continue
        if len(element.label) > _LABEL_LENGTH:
            return TooLarge(detail="label_too_long")
        blocks.append(_input_block(element))
    message_id = None if isinstance(opener, CommandInvoked) else opener.message_id
    return {
        "type": "modal",
        "callback_id": modal.id,
        "title": _actions.plain_text(modal.title),
        "submit": _actions.plain_text(modal.submit_label or _DEFAULT_SUBMIT_LABEL),
        "private_metadata": _pack_metadata(
            _Origin(parts.channel, parts.thread_ts, message_id), modal.metadata
        ),
        "blocks": blocks,
    }


# Inbound


def _is_json(value: object) -> bool:
    """Whether ``value`` is JSON Effect's ``Schema.Json`` accepts: no
    infinite number, which ``1e999`` parses as."""
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, float) and not math.isfinite(item):
            return False
        if isinstance(item, dict):
            pending.extend(cast("dict[str, object]", item).values())
        elif _json.is_list(item):
            pending.extend(cast("list[object]", item))
    return True


def _raw(payload: JsonObject) -> JsonValue:
    """The payload without its verification ``token``."""
    return cast("JsonValue", {key: value for key, value in payload.items() if key != "token"})


def _thread_of(team_id: str, origin: _Origin):
    return _address.thread(
        _address.Parts(
            team_id,
            origin.channel,
            None if origin.thread_ts == origin.message_id else origin.thread_ts,
        )
    )


def _clicked(payload: JsonObject, team_id: str) -> Interaction | None:
    actions = _json.as_list(payload.get("actions"))
    action = _json.as_object(actions[0]) if len(actions) == 1 else None
    id = _json.string(action, "action_id")
    # Only an element in the adapter's own block, and not a link button, whose
    # click carries nothing.
    if (
        action is None
        or id is None
        or action.get("block_id") != _actions.BLOCK_ID
        or id.startswith(_actions.JOIN)
    ):
        return None
    container = _json.object_(payload, "container")
    message = _json.object_(payload, "message")
    channel = _json.string(container, "channel_id") or _json.string(
        _json.object_(payload, "channel"), "id"
    )
    message_id = _json.string(container, "message_ts") or _json.string(message, "ts")
    user_id = _json.string(_json.object_(payload, "user"), "id")
    if channel is None or message_id is None or user_id is None:
        return None
    thread_ts = _json.string(message, "thread_ts") or _json.string(container, "thread_ts")
    thread = _thread_of(team_id, _Origin(channel, thread_ts, message_id))
    raw = _raw(payload)
    if action.get("type") == "button":
        return ButtonClicked(
            id=id,
            value=_json.any_string(action, "value"),
            thread=thread,
            message_id=message_id,
            user_id=user_id,
            raw=raw,
        )
    value = _json.any_string(_json.object_(action, "selected_option"), "value")
    if action.get("type") == "static_select" and value is not None:
        return SelectChanged(
            id=id, value=value, thread=thread, message_id=message_id, user_id=user_id, raw=raw
        )
    return None


def _input_value(input: object) -> str | None:
    """The value of one input in ``view.state.values``, or ``None`` for an
    empty one."""
    obj = _json.as_object(input)
    if obj is None:
        return None
    if obj.get("type") == "static_select":
        value = _json.any_string(_json.object_(obj, "selected_option"), "value")
    else:
        value = _json.any_string(obj, "value")
    return value or None


def _submitted(payload: JsonObject, team_id: str) -> Interaction | None:
    view = _json.object_(payload, "view")
    id = _json.string(view, "callback_id")
    packed = _json.string(view, "private_metadata")
    unpacked = None if packed is None else _unpack_metadata(packed)
    user_id = _json.string(_json.object_(payload, "user"), "id")
    if id is None or unpacked is None or user_id is None:
        return None
    values: dict[str, str] = {}
    state = _json.object_(_json.object_(view, "state"), "values") or {}
    for block_id in state:
        inputs = _json.object_(state, block_id)
        if inputs is None:
            continue
        for input in inputs.values():
            value = _input_value(input)
            if value is not None:
                values[block_id] = value
    origin, metadata = unpacked
    return ModalSubmitted(
        id=id,
        metadata=metadata,
        values=values,
        thread=_thread_of(team_id, origin),
        message_id=origin.message_id,
        user_id=user_id,
        raw=_raw(payload),
    )


def is_command(payload: object) -> bool:
    """Whether ``payload`` is a slash command's fields: a ``command`` and no
    ``type``."""
    obj = _json.as_object(payload)
    return obj is not None and "type" not in obj and isinstance(obj.get("command"), str)


def _invoked(payload: JsonObject, team_id: str) -> Interaction | None:
    command = _json.string(payload, "command")
    channel = _json.string(payload, "channel_id")
    user_id = _json.string(payload, "user_id")
    id = command[1:] if command is not None and command.startswith("/") else command
    if not id or channel is None or user_id is None:
        return None
    return CommandInvoked(
        id=id,
        text=_json.any_string(payload, "text") or "",
        # A command can't be typed in a thread, so its address is the channel's.
        thread=_address.thread(_address.Parts(team_id, channel)),
        user_id=user_id,
        raw=_raw(payload),
    )


def normalize(payload: object, *, team_id: str) -> Interaction | None:
    """The interaction a decoded ``payload`` is: a click on a button or
    select in an ``actions`` block the adapter built, a submit of a view it
    opened, or a slash command's fields. Anything else, a link button's
    click and a value that is not JSON included, is ``None``."""
    obj = _json.as_object(payload)
    if obj is None or not _is_json(obj):
        return None
    if obj.get("type") == "block_actions":
        return _clicked(obj, team_id)
    if obj.get("type") == "view_submission":
        return _submitted(obj, team_id)
    if is_command(obj):
        return _invoked(obj, team_id)
    return None


def _expired(error: ChatError) -> ChatError:
    """A trigger past its 3 seconds is the same refusal ``handle`` gives a
    late click."""
    if error.reason.detail != "expired_trigger_id":
        return error
    return _errors.chat_error("openModal", NotFound(detail=INTERACTION_EXPIRED, cause=error.reason))


type Answer = Callable[
    [str, str, Sequence[Action], Visibility], Effect[Mapping[str, object], ChatError]
]
"""Builds the body of a ``Respond``: the op, the Markdown, the elements and
the visibility, checked as a post is."""

type Body = JsonValue | Late
"""What an interactivity request is answered with: a JSON body, ``None`` for
an empty answer, or ``Late``."""


def make(
    *,
    call_views_open: Callable[[Mapping[str, object]], Effect[object, ChatError]],
    team_id: str,
    answer: Answer,
) -> Callable[[object, Duration], Effect[Body, Never, Handler]]:
    """``SlackChat.interaction``: normalises, calls the handler through
    ``chat_interaction.handle`` and gives the body to answer with.

    - An ack, a close, a late click, a deferral and a payload that is not
      the adapter's give ``None``, an empty answer.
    - ``Errors`` gives ``response_action: "errors"``, keyed by field id.
    - A late submit or command gives ``Late``.
    - ``OpenModal`` calls ``views.open`` with the click's or command's
      ``trigger_id`` before answering. A modal that can't be built, or that
      Slack refuses, goes to ``Handler.refused``, and the click is still
      acked.
    - ``Respond`` gives the message as the body, with its
      ``response_type``. One that fails the checks of a ``post`` goes to
      ``Handler.refused`` and gives an empty answer.
    """

    def interaction(payload: object, deadline: Duration) -> Effect[Body, Never, Handler]:
        event = normalize(payload, team_id=team_id)
        if event is None:
            return fx.succeed(None)

        @fx.gen
        def body() -> Generator[Effect[Any, Never, Handler], Any, Body]:  # noqa: PLR0911
            reply = yield from chat_interaction.handle(event, deadline)
            match reply:
                case Late():
                    # A late click is acked: its handler runs on and ``handle`` refuses a
                    # modal it opens.
                    return None if isinstance(event, (ButtonClicked, SelectChanged)) else reply
                case Ack() | Close() | Defer():
                    return None
                case Errors():
                    return {"response_action": "errors", "errors": dict(reply.errors)}
                case Respond():
                    command = cast("CommandInvoked", event)
                    handler = yield from Handler()
                    answered = yield from answer(
                        "respond", reply.markdown, reply.actions or (), reply.visibility
                    ).result()
                    if isinstance(answered, Err):
                        yield from handler.refused(command, answered.error)
                        return None
                    return cast("JsonValue", answered.value)
                case OpenModal():
                    opener = cast("_Opener", event)
                    handler = yield from Handler()
                    built = view(reply.modal, opener)
                    if not isinstance(built, dict):
                        yield from handler.refused(opener, _errors.chat_error("openModal", built))
                        return None
                    trigger_id = _json.string(payload, "trigger_id")
                    if trigger_id is None:
                        yield from handler.refused(
                            opener,
                            _errors.chat_error("openModal", InvalidRequest(detail="no_trigger_id")),
                        )
                        return None
                    opened = yield from call_views_open(
                        {"trigger_id": trigger_id, "view": built}
                    ).result()
                    if isinstance(opened, Err):
                        yield from handler.refused(
                            opener, _expired(_errors.with_op("openModal", opened.error))
                        )
                    return None

        return body

    return interaction
