"""Buttons and selects as WhatsApp reply buttons, a link button or a list, and
the wire ids a click comes back with."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pyfect._equal import dedupe
from pyfect._json_value import JsonValue
from pyfect.chat.chat_error import AnyReason, InvalidRequest, TooLarge
from pyfect.chat.chat_ui import Action, Button, LinkButton, Select
from pyfect.chat.whatsapp._options import (
    DEFAULT_BUTTONS_SECTION,
    DEFAULT_LIST_BUTTON,
    WhatsAppPostOptions,
)
from pyfect.chat.whatsapp._text import (
    MESSAGE_LENGTH,
    SHORT_BODY_LENGTH,
    js_trim,
    utf8_bytes,
    utf16_length,
)

JOIN = "␟"
"""Between an element's id and its value in a wire id."""

ACTIONS_PER_MESSAGE = 10
ACTION_DATA_LENGTH = 198

_REPLY_ID_BYTES = 256
"""Meta counts a reply button's id in UTF-8 bytes, unlike every other limit."""
_REPLY_LABEL_LENGTH = 20
_ROW_TITLE_LENGTH = 24
_LIST_BUTTON_LENGTH = 20
_SECTION_TITLE_LENGTH = 24
_MAX_ROWS = 10

SHORT_BODY_OFFSET = MESSAGE_LENGTH - SHORT_BODY_LENGTH
"""What the measure adds for a layout whose body is held to 1,024 rather than
4,096."""

type Kind = Literal["none", "reply", "cta", "list"]


@dataclass(frozen=True)
class Shape:
    """The layout of a message's actions, which depends on the actions alone:
    its kind, and the link buttons that go as ``Label: url`` lines after the
    body."""

    kind: Kind
    appended: tuple[LinkButton, ...]


def shape(actions: Sequence[Action]) -> Shape:
    buttons = [action for action in actions if isinstance(action, Button)]
    links = tuple(action for action in actions if isinstance(action, LinkButton))
    selects = [action for action in actions if isinstance(action, Select)]
    if not buttons and not selects:
        if len(links) == 1 and utf16_length(links[0].label) <= _REPLY_LABEL_LENGTH:
            return Shape("cta", ())
        return Shape("none", links)
    reply = (
        not selects
        and len(buttons) <= 3
        and all(utf16_length(button.label) <= _REPLY_LABEL_LENGTH for button in buttons)
    )
    return Shape("reply" if reply else "list", links)


def generated_body(actions: Sequence[Action]) -> str:
    """The body of a post with actions and no Markdown: the labels joined by
    ``", "``."""
    return ", ".join(
        (
            action.placeholder
            if action.placeholder is not None
            else ", ".join(option.label for option in action.options)
        )
        if isinstance(action, Select)
        else action.label
        for action in actions
    )


def link_lines(links: Sequence[LinkButton]) -> str:
    return "\n".join(f"{link.label}: {link.url}" for link in links)


def measure(actions: Sequence[Action]) -> int:
    """What a message's actions add to the measure of its Markdown: the offset
    of a 1,024 body, the appended link lines with their separator, and the
    generated body, which is always counted."""
    if not actions:
        return 0
    found = shape(actions)
    offset = SHORT_BODY_OFFSET if found.kind in ("reply", "cta") else 0
    lines = 0 if not found.appended else 2 + utf16_length(link_lines(found.appended))
    return offset + utf16_length(generated_body(actions)) + lines


def body(rendered: str, actions: Sequence[Action]) -> str:
    """The body as sent: the rendered Markdown, or the generated body, then
    the link lines."""
    found = shape(actions)
    base = (
        rendered
        if js_trim(rendered) != ""
        else ""
        if found.kind == "none"
        else generated_body(actions)
    )
    lines = link_lines(found.appended)
    if base == "":
        return lines
    return base if lines == "" else f"{base}\n\n{lines}"


def button_wire_id(button: Button) -> str:
    return "b" + button.id + ("" if button.value is None else JOIN + button.value)


def option_wire_id(select: Select, value: str) -> str:
    return "s" + select.id + JOIN + value


@dataclass(frozen=True)
class WireId:
    """A wire id read back: a button's id and maybe its value, or a select's
    id and the chosen value."""

    kind: Literal["button", "select"]
    id: str
    value: str | None


def parse_wire_id(wire: str) -> WireId | None:
    """The tag, then the id and value split at the first U+241F."""
    tag, rest = wire[:1], wire[1:]
    at = rest.find(JOIN)
    if tag == "b":
        if at < 0:
            return WireId("button", rest, None)
        return WireId("button", rest[:at], rest[at + 1 :])
    if tag == "s" and at >= 0:
        return WireId("select", rest[:at], rest[at + 1 :])
    return None


@dataclass(frozen=True)
class Interactive:
    """The ``interactive`` object of a message, less its body and header."""

    type: Literal["button", "cta_url", "list"]
    action: JsonValue


@dataclass(frozen=True)
class Plan:
    kind: Kind
    interactive: Interactive | None = None


def _unique(values: Sequence[str]) -> bool:
    return len(dedupe(values)) == len(values)


def plan(actions: Sequence[Action], options: WhatsAppPostOptions) -> Plan | AnyReason:  # noqa: PLR0911, PLR0912
    """Checks a message's actions and builds their ``interactive`` object.
    Every refusal is found here, before any call."""
    if not actions:
        return Plan("none")
    if len(actions) > ACTIONS_PER_MESSAGE:
        return TooLarge(detail="too_many_actions")
    for action in actions:
        if isinstance(action, LinkButton):
            if utf16_length(action.label) > _ROW_TITLE_LENGTH:
                return TooLarge(detail="label_too_long")
            continue
        if JOIN in action.id:
            return InvalidRequest(detail="invalid_action_id")
        if isinstance(action, Button):
            value = "" if action.value is None else action.value
            if utf16_length(action.id) + utf16_length(value) > ACTION_DATA_LENGTH:
                return TooLarge(detail="action_data_too_long")
        else:
            if not action.options:
                return InvalidRequest(detail="empty_select")
            for option in action.options:
                if utf16_length(action.id) + utf16_length(option.value) > ACTION_DATA_LENGTH:
                    return TooLarge(detail="action_data_too_long")
    kind = shape(actions).kind
    buttons = [action for action in actions if isinstance(action, Button)]
    selects = [action for action in actions if isinstance(action, Select)]
    if kind == "none":
        return Plan(kind)
    if kind == "cta":
        link = next(action for action in actions if isinstance(action, LinkButton))
        return Plan(
            kind,
            Interactive(
                "cta_url",
                {"name": "cta_url", "parameters": {"display_text": link.label, "url": link.url}},
            ),
        )
    if kind == "reply":
        ids = [button_wire_id(button) for button in buttons]
        if not _unique([button.label for button in buttons]):
            return InvalidRequest(detail="duplicate_label")
        if not _unique(ids):
            return InvalidRequest(detail="duplicate_id")
        if any(utf8_bytes(id) > _REPLY_ID_BYTES for id in ids):
            return TooLarge(detail="action_data_too_long")
        return Plan(
            kind,
            Interactive(
                "button",
                {
                    "buttons": [
                        {"type": "reply", "reply": {"id": id, "title": button.label}}
                        for id, button in zip(ids, buttons, strict=True)
                    ]
                },
            ),
        )
    list_button = options.list_button if options.list_button is not None else DEFAULT_LIST_BUTTON
    sections: list[tuple[str, list[dict[str, JsonValue]]]] = []
    if buttons:
        title = (
            options.buttons_section
            if options.buttons_section is not None
            else DEFAULT_BUTTONS_SECTION
        )
        sections.append(
            (
                title,
                [{"id": button_wire_id(button), "title": button.label} for button in buttons],
            )
        )
    sections.extend(
        (
            select.placeholder if select.placeholder is not None else list_button,
            [
                {"id": option_wire_id(select, option.value), "title": option.label}
                for option in select.options
            ],
        )
        for select in selects
    )
    rows = [row for _, section_rows in sections for row in section_rows]
    if len(rows) > _MAX_ROWS:
        return TooLarge(detail="list_rows")
    if any(utf16_length(str(row["title"])) > _ROW_TITLE_LENGTH for row in rows):
        return TooLarge(detail="label_too_long")
    if not _unique([str(row["id"]) for row in rows]):
        return InvalidRequest(detail="duplicate_id")
    opener = next(
        (select.placeholder for select in selects if select.placeholder is not None), list_button
    )
    if utf16_length(opener) > _LIST_BUTTON_LENGTH:
        return TooLarge(detail="label_too_long")
    if len(sections) > 1 and any(
        utf16_length(title) > _SECTION_TITLE_LENGTH for title, _ in sections
    ):
        return TooLarge(detail="label_too_long")
    many = len(sections) > 1
    return Plan(
        kind,
        Interactive(
            "list",
            {
                "button": opener,
                "sections": [
                    {"title": title, "rows": list(section_rows)}
                    if many
                    else {"rows": list(section_rows)}
                    for title, section_rows in sections
                ],
            },
        ),
    )
