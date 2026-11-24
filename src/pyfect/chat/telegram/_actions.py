"""Inline keyboards: a message's buttons as ``reply_markup``, and the
``callback_data`` a click carries."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from pyfect._js import text_encode
from pyfect.chat.chat_error import AnyReason
from pyfect.chat.chat_message import utf16_length
from pyfect.chat.chat_ui import Action, Button, LinkButton, Select
from pyfect.chat.telegram import _errors, _json

ACTIONS_PER_MESSAGE = 100
"""The adapter's own cap, as Telegram publishes no button count."""

ACTION_DATA_LENGTH = 63
"""``callback_data`` is 1 to 64 bytes, less the separator."""

SEPARATOR = "\x1f"
"""Between a button's id and its value in ``callback_data``."""

_SHORT_LABEL = 12
"""A label short enough to share a row with two others."""
_PER_ROW = 3
_WEB = re.compile(r"https?://", re.IGNORECASE | re.ASCII)

type KeyboardButton = dict[str, str]


@dataclass(frozen=True)
class Keyboard:
    """``reply_markup``'s ``inline_keyboard``."""

    rows: tuple[tuple[KeyboardButton, ...], ...]

    def json(self) -> dict[str, object]:
        return {"inline_keyboard": [list(row) for row in self.rows]}


def callback_data(id: str, value: str | None) -> str:
    """A button's ``callback_data``: its id, and its value after the
    separator when it has one."""
    return id if value is None else id + SEPARATOR + value


def parse_data(data: str) -> tuple[str, str | None]:
    """The id and value of ``callback_data``."""
    id, separator, value = data.partition(SEPARATOR)
    return (id, value) if separator else (data, None)


def _bytes(text: str) -> int:
    return len(text_encode(text))


def keyboard(actions: Sequence[Action]) -> Keyboard | AnyReason:  # noqa: PLR0912
    """The inline keyboard of a message's actions, or the reason it can't be
    sent: a select (``Unsupported``), too many elements, data past 63
    bytes, an id holding the separator, or a link that is not http or
    https."""
    if any(isinstance(action, Select) for action in actions):
        return _errors.unsupported("selects")
    if len(actions) > ACTIONS_PER_MESSAGE:
        return _errors.too_large(None, "too_many_actions")
    buttons: list[KeyboardButton] = []
    for action in actions:
        if isinstance(action, Button):
            if SEPARATOR in action.id:
                return _errors.invalid_request("invalid_action_id")
            if _bytes(action.id) + _bytes(action.value or "") > ACTION_DATA_LENGTH:
                return _errors.too_large(None, "action_data_too_long")
            button = {"text": action.label, "callback_data": callback_data(action.id, action.value)}
            if action.style in ("primary", "danger"):
                button["style"] = action.style
            buttons.append(button)
        elif isinstance(action, LinkButton):
            if _WEB.match(action.url) is None:
                return _errors.invalid_request("untrusted_url")
            buttons.append({"text": action.label, "url": action.url})
    rows: list[tuple[KeyboardButton, ...]] = []
    row: list[KeyboardButton] = []
    row_has_long = False
    for button in buttons:
        short = utf16_length(button["text"]) <= _SHORT_LABEL
        if not short or len(row) == _PER_ROW or row_has_long:
            if row:
                rows.append(tuple(row))
            row = []
            row_has_long = False
        row.append(button)
        row_has_long = row_has_long or not short
    if row:
        rows.append(tuple(row))
    return Keyboard(tuple(rows))


def keyboard_data(reply_markup: object) -> frozenset[str]:
    """Every ``callback_data`` in a message's ``reply_markup``."""
    markup = _json.as_object(reply_markup)
    rows = _json.as_list(None if markup is None else markup.get("inline_keyboard"))
    return frozenset(
        data
        for row in rows
        for button in _json.as_list(row)
        if (data := _json.string(button, "callback_data")) is not None
    )
