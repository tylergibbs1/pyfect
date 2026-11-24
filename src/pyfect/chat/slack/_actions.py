"""A message's elements as Slack's ``actions`` block, and what that block
costs against the 13,200 cap."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, NotRequired, TypedDict

from pyfect.chat.chat_ui import Action, Button, LinkButton, Select
from pyfect.chat.slack import _emoji

BLOCK_ID = "chat1"
"""The ``block_id`` of the ``actions`` block the adapter builds, and so the
mark of a click on one of its own elements. Five ASCII characters, the length
of the id Slack generates, which ``cost`` charges."""

JOIN = "␟"
"""The one character the adapter reserves: a button or select id may not
hold it, a link button's ``action_id`` starts with it, and it separates the
parts of a modal's ``private_metadata``."""


class PlainText(TypedDict):
    type: Literal["plain_text"]
    text: str


class SelectOptionJson(TypedDict):
    text: PlainText
    value: str


class ButtonElement(TypedDict):
    type: Literal["button"]
    action_id: str
    text: PlainText
    value: NotRequired[str]
    url: NotRequired[str]
    style: NotRequired[Literal["primary", "danger"]]


class SelectElement(TypedDict):
    type: Literal["static_select"]
    action_id: str
    placeholder: NotRequired[PlainText]
    options: list[SelectOptionJson]
    initial_option: NotRequired[SelectOptionJson]


type Element = ButtonElement | SelectElement


class ActionsBlock(TypedDict):
    type: Literal["actions"]
    block_id: str
    elements: list[Element]


def plain_text(text: str) -> PlainText:
    return {"type": "plain_text", "text": text}


def option(label: str, value: str) -> SelectOptionJson:
    return {"text": plain_text(label), "value": value}


def _element(action: Action, index: int) -> Element:
    match action:
        case Button():
            button: ButtonElement = {
                "type": "button",
                "action_id": action.id,
                "text": plain_text(action.label),
            }
            if action.value is not None:
                button["value"] = action.value
            if action.style in ("primary", "danger"):
                button["style"] = action.style
            return button
        case LinkButton():
            return {
                "type": "button",
                "action_id": JOIN + str(index),
                "text": plain_text(action.label),
                "url": action.url,
            }
        case Select():
            select: SelectElement = {
                "type": "static_select",
                "action_id": action.id,
                "options": [option(entry.label, entry.value) for entry in action.options],
            }
            if action.placeholder is not None:
                select["placeholder"] = plain_text(action.placeholder)
            selected = next(
                (entry for entry in action.options if entry.value == action.selected), None
            )
            if selected is not None:
                select["initial_option"] = option(selected.label, selected.value)
            return select


def elements(actions: Sequence[Action]) -> list[Element]:
    """The elements for ``actions``, in order. A button's id is its
    ``action_id`` and its value its ``value``. A link button is a button with
    a ``url``, and an ``action_id`` of the join and its index, which no id
    of the consumer's can be. A select's options carry their values, and
    ``selected`` is its ``initial_option``."""
    return [_element(action, index) for index, action in enumerate(actions)]


def block(actions: Sequence[Action]) -> ActionsBlock:
    """The ``actions`` block for a message's elements."""
    return {"type": "actions", "block_id": BLOCK_ID, "elements": elements(actions)}


def labels(actions: Sequence[Action]) -> str:
    """The ``text`` of a message with elements and no Markdown, before
    escaping: the button labels and the select placeholders, joined by a
    space."""
    out: list[str] = []
    for action in actions:
        if isinstance(action, Select):
            if action.placeholder is not None:
                out.append(action.placeholder)
        else:
            out.append(action.label)
    return " ".join(out)


# The fixed costs of each part of the block.
_BLOCK = 56
_SELECT = 52
_PLACEHOLDER = 59
_OPTION = 64
_INITIAL_OPTION = 18
_BUTTON = 95
_URL = 9
_NO_VALUE = 11
_STYLE = 18
_SEPARATOR = 1


def _unit_cost(code: int) -> int:
    """One UTF-16 unit as Slack's server writes it in JSON."""
    if not 0x20 <= code <= 0x7E:
        return 6
    return 2 if code in (0x2F, 0x22, 0x5C) else 1


def _char_cost(char: str) -> int:
    code = ord(char)
    return 12 if code > 0xFFFF else _unit_cost(code)


def string_cost(text: str) -> int:
    """A string as Slack's server writes it in JSON: 6 for any UTF-16 unit
    that is not printable ASCII, 2 for ``/``, ``"`` and ``\\``, 1 otherwise.
    An id, a value, a url and an option label cost this."""
    return sum(_char_cost(char) for char in text)


def label_cost(text: str) -> int:
    """A button label or a placeholder: ``<``, ``>`` and ``&`` are stored as
    entities, and an emoji costs the greater of its ``:name:`` and its
    escaped form."""
    cost = 0
    i = 0
    while i < len(text):
        emoji = _emoji.longest_at(text, i)
        if emoji is not None:
            cost += max(len(emoji.name) + 2, 6 * emoji.utf16)
            i += emoji.length
            continue
        char = text[i]
        i += 1
        cost += 4 if char in "<>" else 5 if char == "&" else _char_cost(char)
    return cost


def _option_cost(entry: SelectOptionJson) -> int:
    return _OPTION + string_cost(entry["text"]["text"]) + string_cost(entry["value"])


def _element_cost(element: Element) -> int:
    if element["type"] == "button":
        value = element.get("value")
        cost = (
            _BUTTON
            + label_cost(element["text"]["text"])
            + string_cost(element["action_id"])
            + string_cost(value or "")
        )
        url = element.get("url")
        if url is not None:
            cost += _URL + string_cost(url) - (_NO_VALUE if value is None else 0)
        return cost if element.get("style") is None else cost + _STYLE
    cost = _SELECT + string_cost(element["action_id"])
    placeholder = element.get("placeholder")
    if placeholder is not None:
        cost += _PLACEHOLDER + label_cost(placeholder["text"])
    cost += sum(_option_cost(entry) for entry in element["options"])
    cost += max(0, len(element["options"]) - 1) * _SEPARATOR
    initial = element.get("initial_option")
    if initial is not None:
        cost += _INITIAL_OPTION + _option_cost(initial)
    return cost


def cost(elements: Sequence[Element]) -> int:
    """An upper bound on the ``actions`` block's JSON as Slack's server
    writes it, which the 13,200 cap charges. 0 for no elements."""
    if not elements:
        return 0
    return (
        _BLOCK
        + (len(elements) - 1) * _SEPARATOR
        + sum(_element_cost(element) for element in elements)
    )
