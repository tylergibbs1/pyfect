"""The plain elements of buttons, selects and modals (Effect's
``effect/chat/ChatUi``).

These are what goes on the wire, into ``ChatTest`` and into storage: every
element is a schema class and every value in one is already a string.
``chat_interaction`` holds the typed definitions that build them and
receive their clicks; a consumer that routes clicks itself builds them
directly.

- ``post`` and ``edit`` take a flat list of ``Action`` beside the Markdown,
  and the adapter lays out the rows.
- Text in a modal is plain, not Markdown: a Slack modal cannot hold a
  ``markdown`` block.
"""

from __future__ import annotations

from typing import Literal, cast

from pyfect import schema as S

type ButtonStyle = Literal["default", "primary", "danger"]

BUTTON_STYLE = S.Literals("default", "primary", "danger")


class Button(S.TaggedClass, tag="Button"):
    """A button on a message. ``value`` is the encoded value, ``None`` when
    the definition has no value schema."""

    id: str
    label: str
    style: ButtonStyle | None = S.field(S.NullOr(BUTTON_STYLE), default=None)
    value: str | None = None


class LinkButton(S.TaggedClass, tag="LinkButton"):
    """A button that opens a URL. It produces no click, so it has no id."""

    label: str
    url: str


class SelectOption(S.Class):
    """One option of a select; ``value`` is the encoded value."""

    label: str
    value: str


class Select(S.TaggedClass, tag="Select"):
    """A single-choice select on a message. ``selected`` is the ``value`` of
    the option shown as chosen."""

    id: str
    placeholder: str | None = None
    options: tuple[SelectOption, ...]
    selected: str | None = None


type Action = Button | LinkButton | Select
"""What ``post`` and ``edit`` take in ``actions``."""

ACTION: S.Bottom[Action] = cast("S.Bottom[Action]", S.Union(Button, LinkButton, Select))


class TextInput(S.TaggedClass, tag="TextInput"):
    """A text input in a modal, one line or several."""

    id: str
    label: str
    multiline: bool = False
    placeholder: str | None = None
    initial: str | None = None
    optional: bool = False
    min_length: int | None = S.field(S.NullOr(S.Int), default=None, key="minLength")
    max_length: int | None = S.field(S.NullOr(S.Int), default=None, key="maxLength")


class SelectInput(S.TaggedClass, tag="SelectInput"):
    """A single-choice select in a modal. ``initial`` is the ``value`` of
    the option chosen when the modal opens."""

    id: str
    label: str
    placeholder: str | None = None
    options: tuple[SelectOption, ...]
    initial: str | None = None
    optional: bool = False


class Text(S.TaggedClass, tag="Text"):
    """Plain text in a modal (not Markdown)."""

    text: str


type ModalElement = TextInput | SelectInput | Text
"""One element of a modal."""

MODAL_ELEMENT: S.Bottom[ModalElement] = cast(
    "S.Bottom[ModalElement]", S.Union(TextInput, SelectInput, Text)
)


class Modal(S.TaggedClass, tag="Modal"):
    """A modal. ``metadata`` is the consumer's encoded metadata; the adapter
    adds the thread and message of the click that opened it beside it. The
    elements are shown in order."""

    id: str
    title: str
    submit_label: str | None = S.field(S.NullOr(S.String), default=None, key="submitLabel")
    metadata: str | None = None
    elements: tuple[ModalElement, ...] = S.field(S.Array(MODAL_ELEMENT))


def link_button(*, label: str, url: str) -> LinkButton:
    """A button that opens ``url``, to put a link beside a message's
    buttons. It is the one element with no definition in
    ``chat_interaction``, since it produces no click."""
    return LinkButton(label=label, url=url)


__all__ = [
    "ACTION",
    "BUTTON_STYLE",
    "MODAL_ELEMENT",
    "Action",
    "Button",
    "ButtonStyle",
    "LinkButton",
    "Modal",
    "ModalElement",
    "Select",
    "SelectInput",
    "SelectOption",
    "Text",
    "TextInput",
    "link_button",
]
