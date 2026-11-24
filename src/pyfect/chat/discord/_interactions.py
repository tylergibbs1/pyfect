"""Discord's side of buttons, selects, modals and slash commands: a message's
elements as action rows, the modal a reply opens, the interaction callbacks,
and the ``INTERACTION_CREATE`` payloads read back."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from pyfect._json_value import JsonValue
from pyfect.chat import chat_interaction as ci
from pyfect.chat.chat_error import AnyReason, InvalidRequest, TooLarge
from pyfect.chat.chat_interaction import Visibility
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.chat_ui import Action, Button, ButtonStyle, LinkButton, Modal, Text, TextInput
from pyfect.chat.discord import _json, _normalize
from pyfect.chat.discord._json import JsonObject
from pyfect.chat.discord._length import MESSAGE_LENGTH, code_points, cut

JOIN = "␟"
"""The one character between an id and its value in a ``custom_id``, for a
button and for a modal's metadata. An id may not hold it, so the first one in
a ``custom_id`` is the join."""

ACTIONS_PER_MESSAGE = 25
ACTION_DATA_LENGTH = 99
MODAL_METADATA_LENGTH = 99
MODAL_FIELDS = 5

_ROWS_PER_MESSAGE = 5
_BUTTONS_PER_ROW = 5
_TITLE_LENGTH = 45
_LABEL_LENGTH = 45

# Discord's interaction callback types and the ephemeral flag.
_CHANNEL_MESSAGE_WITH_SOURCE = 4
_DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE = 5
_DEFERRED_UPDATE_MESSAGE = 6
_MODAL = 9
EPHEMERAL = 1 << 6

# Discord's interaction types, its command type for a slash command, and its
# option type for a string.
_PING = 1
_APPLICATION_COMMAND = 2
_MESSAGE_COMPONENT = 3
_MODAL_SUBMIT = 5
_CHAT_INPUT = 1
_STRING = 3

_TOKEN = re.compile(r"[A-Za-z0-9_.\-]{1,1000}")
"""An interaction token as Discord issues it; anything else is not sent on."""

type Payload = dict[str, object]


def _visibility_flags(visibility: Visibility) -> int:
    return EPHEMERAL if visibility == "ephemeral" else 0


def _custom_id(id: str, value: str | None) -> str:
    return id if value is None else id + JOIN + value


def _split_custom_id(custom_id: str) -> tuple[str, str | None]:
    """An id and its value from a ``custom_id``, split at the first join."""
    id, join, value = custom_id.partition(JOIN)
    return (id, value) if join else (id, None)


def _button_style(style: ButtonStyle | None) -> int:
    return 1 if style == "primary" else 4 if style == "danger" else 2


def rows(actions: Sequence[Action]) -> list[Payload] | AnyReason:
    """A message's elements as action rows, or why they can't go: five
    buttons to a row and a select alone in its row, in the order given, up to
    five rows."""
    if len(actions) > ACTIONS_PER_MESSAGE:
        return TooLarge(detail="too_many_actions")
    out: list[Payload] = []
    open_row: list[Payload] | None = None
    for action in actions:
        if not isinstance(action, (Button, LinkButton)):
            id_length = code_points(action.id)
            if any(
                id_length + code_points(option.value) > ACTION_DATA_LENGTH
                for option in action.options
            ):
                return TooLarge(detail="action_data_too_long")
            open_row = None
            select: Payload = {"type": 3, "custom_id": action.id}
            if action.placeholder is not None:
                select["placeholder"] = action.placeholder
            select["options"] = [
                {"label": option.label, "value": option.value}
                | ({"default": True} if option.value == action.selected else {})
                for option in action.options
            ]
            select["min_values"] = 1
            select["max_values"] = 1
            out.append({"type": 1, "components": [select]})
            continue
        if isinstance(action, LinkButton):
            button: Payload = {"type": 2, "style": 5, "label": action.label, "url": action.url}
        else:
            if JOIN in action.id:
                return InvalidRequest(detail="invalid_action_id")
            if code_points(action.id) + code_points(action.value or "") > ACTION_DATA_LENGTH:
                return TooLarge(detail="action_data_too_long")
            button = {
                "type": 2,
                "style": _button_style(action.style),
                "label": action.label,
                "custom_id": _custom_id(action.id, action.value),
            }
        if open_row is None or len(open_row) == _BUTTONS_PER_ROW:
            open_row = [button]
            out.append({"type": 1, "components": open_row})
        else:
            open_row.append(button)
    if len(out) > _ROWS_PER_MESSAGE:
        return TooLarge(detail="too_many_actions")
    return out


_PUNCTUATION = re.compile(r"[!-/:-@\[-`{-~]")


def plain(text: str) -> str:
    """Discord's Markdown escape for any ASCII punctuation, so text shows as written."""
    return _PUNCTUATION.sub(lambda match: "\\" + match.group(0), text)


def modal_data(modal: Modal) -> Payload | AnyReason:  # noqa: PLR0912
    """The callback data that opens ``modal``, or why it can't open. Inputs
    are Label components around a text input or a string select, and a
    ``Text`` is a text display. Discord has no submit label, so
    ``submit_label`` is not sent."""
    if JOIN in modal.id:
        return InvalidRequest(detail="invalid_modal_id")
    if code_points(modal.id) + code_points(modal.metadata or "") > MODAL_METADATA_LENGTH:
        return TooLarge(detail="modal_metadata_too_long")
    if len(modal.elements) > MODAL_FIELDS:
        return TooLarge(detail="too_many_fields")
    if code_points(modal.title) > _TITLE_LENGTH:
        return TooLarge(detail="title_too_long")
    components: list[Payload] = []
    for element in modal.elements:
        if isinstance(element, Text):
            components.append({"type": 10, "content": plain(element.text)})
            continue
        if code_points(element.label) > _LABEL_LENGTH:
            return TooLarge(detail="label_too_long")
        required = not element.optional
        if isinstance(element, TextInput):
            component: Payload = {
                "type": 4,
                "custom_id": element.id,
                "style": 2 if element.multiline else 1,
                "required": required,
            }
            if element.placeholder is not None:
                component["placeholder"] = element.placeholder
            if element.initial is not None:
                component["value"] = element.initial
            if element.min_length is not None:
                component["min_length"] = element.min_length
            if element.max_length is not None:
                component["max_length"] = element.max_length
        else:
            component = {
                "type": 3,
                "custom_id": element.id,
                "required": required,
                "min_values": 1 if required else 0,
                "max_values": 1,
            }
            if element.placeholder is not None:
                component["placeholder"] = element.placeholder
            component["options"] = [
                {"label": option.label, "value": option.value}
                | ({"default": True} if option.value == element.initial else {})
                for option in element.options
            ]
        components.append({"type": 18, "label": element.label, "component": component})
    return {
        "custom_id": _custom_id(modal.id, modal.metadata),
        "title": modal.title,
        "components": components,
    }


ACK_CALLBACK: Payload = {"type": _DEFERRED_UPDATE_MESSAGE}
PONG: Payload = {"type": 1}


def modal_callback(data: Payload) -> Payload:
    return {"type": _MODAL, "data": data}


def errors_callback(errors: Mapping[str, str]) -> Payload:
    """The answer to an ``errors`` reply: a private message listing each one,
    as plain text, cut to fit one message. The modal closes."""
    content = "\n".join("- " + plain(message) for message in errors.values())
    return {
        "type": _CHANNEL_MESSAGE_WITH_SOURCE,
        "data": {
            "content": cut(content, MESSAGE_LENGTH),
            "allowed_mentions": {"parse": []},
            "flags": EPHEMERAL,
        },
    }


def with_visibility(message: Mapping[str, object], visibility: Visibility) -> Payload:
    """A message as an interaction's answer sends it: with the ephemeral
    flag when private."""
    flags = cast("int", message["flags"])
    return {**message, "flags": flags | _visibility_flags(visibility)}


def respond_callback(message: Mapping[str, object], visibility: Visibility) -> Payload:
    """The answer to a ``respond`` reply: the message a ``post`` sends, with
    the ephemeral flag when private."""
    return {"type": _CHANNEL_MESSAGE_WITH_SOURCE, "data": with_visibility(message, visibility)}


def defer_callback(visibility: Visibility) -> Payload:
    """The answer to a ``defer`` reply. The visibility is fixed here and
    holds for the edit that follows."""
    callback: Payload = {"type": _DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE}
    if visibility == "ephemeral":
        callback["data"] = {"flags": EPHEMERAL}
    return callback


# --- inbound -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Input:
    custom_id: str | None
    value: str | None
    values: list[str] | None


def _decode_input(obj: JsonObject) -> _Input:
    _json.req_number(obj, "type")
    return _Input(
        custom_id=_json.opt_str(obj, "custom_id"),
        value=_json.opt_str(obj, "value"),
        values=_json.opt_str_list(obj, "values"),
    )


@dataclass(frozen=True, slots=True)
class _Option:
    type: float
    name: str | None
    value: object


@dataclass(frozen=True, slots=True)
class _Fields:
    id: str
    application_id: str | None
    type: float
    token: str
    channel_id: str | None
    user_id: str | None
    message_id: str | None
    message_channel_id: str | None
    custom_id: str | None
    component_type: float | None
    values: list[str] | None
    inputs: list[list[_Input]] | None
    name: str | None
    command_type: float | None
    options: list[_Option] | None


def _user_id(obj: JsonObject) -> str | None:
    member = _json.opt_obj(obj, "member")
    member_user = None if member is None else _json.opt_obj(member, "user")
    user = _json.opt_obj(obj, "user")
    member_id = None if member_user is None else _json.req_str(member_user, "id")
    user_id = None if user is None else _json.req_str(user, "id")
    return member_id if member_id is not None else user_id


def _decode_fields(obj: JsonObject) -> _Fields:
    message = _json.opt_obj(obj, "message")
    data = _json.req_obj(obj, "data")
    components = _json.opt_list(data, "components")
    inputs: list[list[_Input]] | None = None
    if components is not None:
        inputs = []
        for component in _json.objects(components):
            _json.req_number(component, "type")
            inner = _json.opt_obj(component, "component")
            many = _json.opt_list(component, "components")
            listed = [_decode_input(item) for item in _json.objects(many)]
            inputs.append([_decode_input(inner)] if inner is not None else listed)
    options = _json.opt_list(data, "options")
    return _Fields(
        id=_json.req_str(obj, "id"),
        application_id=_json.opt_str(obj, "application_id"),
        type=_json.req_number(obj, "type"),
        token=_json.req_str(obj, "token"),
        channel_id=_json.opt_str(obj, "channel_id"),
        user_id=_user_id(obj),
        message_id=None if message is None else _json.req_str(message, "id"),
        message_channel_id=None if message is None else _json.opt_str(message, "channel_id"),
        custom_id=_json.opt_str(data, "custom_id"),
        component_type=_json.opt_number(data, "component_type"),
        values=_json.opt_str_list(data, "values"),
        inputs=inputs,
        name=_json.opt_str(data, "name"),
        command_type=_json.opt_number(data, "type"),
        options=None
        if options is None
        else [
            _Option(
                type=_json.req_number(option, "type"),
                name=_json.opt_str(option, "name"),
                value=option.get("value"),
            )
            for option in _json.objects(options)
        ],
    )


def _decode(raw: object) -> _Fields | None:
    return _normalize.decode_option(_decode_fields, raw)


def is_ping(raw: object) -> bool:
    """Whether a payload is Discord's ``PING``, sent to check an endpoint."""
    obj = _json.as_object(raw)
    return obj is not None and obj.get("type") == _PING and not isinstance(obj.get("type"), bool)


@dataclass(frozen=True, slots=True)
class AnswerTo:
    """Credentials for answering an interaction."""

    id: str
    token: str


def answer_to(raw: object) -> AnswerTo | None:
    """Credentials for answering an interaction; ``None`` for an id or token
    that could not be sent on safely."""
    fields = _decode(raw)
    if fields is None or not _sendable(fields.id, fields.token):
        return None
    return AnswerTo(fields.id, fields.token)


@dataclass(frozen=True, slots=True)
class FollowUpTo:
    """Credentials for editing a deferred command's response."""

    id: str
    application_id: str
    token: str


def follow_up_to(raw: object) -> FollowUpTo | None:
    fields = _decode(raw)
    if fields is None or not fields.application_id:
        return None
    if not _sendable(fields.id, fields.token) or not _normalize.SNOWFLAKE.fullmatch(
        fields.application_id
    ):
        return None
    return FollowUpTo(fields.id, fields.application_id, fields.token)


def _sendable(id: str, token: str) -> bool:
    return (
        _normalize.SNOWFLAKE.fullmatch(id) is not None
        and _TOKEN.fullmatch(token) is not None
        and token.strip(".") != ""
    )


def _command_text(options: list[_Option] | None) -> str | None:
    """The text of a slash command's options: none, or one string. ``None``
    for anything else."""
    if not options:
        return ""
    if len(options) == 1 and options[0].type == _STRING and isinstance(options[0].value, str):
        return options[0].value
    return None


def _raw(raw: object) -> JsonValue:
    return cast("JsonValue", raw)


def normalize(raw: object) -> ci.Interaction | None:  # noqa: PLR0911
    """The interaction a payload is, when it is a click on a button or string
    select, a submit of a modal, or a slash command with at most one string
    option. Anything else, a message or user command for one, is ``None``."""
    fields = _decode(raw)
    if fields is None:
        return None
    channel_id = fields.message_channel_id or fields.channel_id
    if (
        fields.user_id is None
        or channel_id is None
        or not _normalize.SNOWFLAKE.fullmatch(channel_id)
    ):
        return None
    thread = _normalize.thread(channel_id)
    if fields.type == _APPLICATION_COMMAND:
        text = _command_text(fields.options)
        # A missing command type is taken as a slash command, which is Discord's default.
        command_type = _CHAT_INPUT if fields.command_type is None else fields.command_type
        if command_type != _CHAT_INPUT or not fields.name or text is None:
            return None
        return ci.CommandInvoked(
            id=fields.name, text=text, thread=thread, user_id=fields.user_id, raw=_raw(raw)
        )
    if fields.custom_id is None:
        return None
    if fields.type == _MODAL_SUBMIT:
        return _submitted(fields, fields.custom_id, fields.user_id, thread, raw)
    if fields.message_id is None or fields.type != _MESSAGE_COMPONENT:
        return None
    if fields.component_type == 2:
        id, value = _split_custom_id(fields.custom_id)
        return ci.ButtonClicked(
            id=id,
            value=value,
            thread=thread,
            message_id=fields.message_id,
            user_id=fields.user_id,
            raw=_raw(raw),
        )
    if fields.component_type == 3 and fields.values:
        return ci.SelectChanged(
            id=fields.custom_id,
            value=fields.values[0],
            thread=thread,
            message_id=fields.message_id,
            user_id=fields.user_id,
            raw=_raw(raw),
        )
    return None


def _submitted(
    fields: _Fields, custom_id: str, user_id: str, thread: ChatThread, raw: object
) -> ci.Interaction:
    """A modal's submit. One a command opened has no ``message``, and no ``message_id``."""
    values: dict[str, str] = {}
    for inputs in fields.inputs or ():
        for found in inputs:
            value = found.value if found.value is not None else (found.values or [None])[0]
            if found.custom_id is not None and value:
                values[found.custom_id] = value
    id, metadata = _split_custom_id(custom_id)
    return ci.ModalSubmitted(
        id=id,
        metadata=metadata,
        values=values,
        thread=thread,
        message_id=fields.message_id,
        user_id=user_id,
        raw=_raw(raw),
    )


def command_requests(group: ci.Group[Any]) -> list[Payload]:
    """The create payload of each command in ``group``, in the group's order."""
    out: list[Payload] = []
    for definition in group.definitions:
        if not isinstance(definition, ci.Command):
            continue
        request: Payload = {
            "type": _CHAT_INPUT,
            "name": definition.id,
            "description": definition.description,
        }
        argument = definition.argument
        if argument is not None:
            request["options"] = [
                {
                    "type": _STRING,
                    "name": argument.name,
                    "description": argument.description,
                    "required": argument.required,
                }
            ]
        out.append(request)
    return out
