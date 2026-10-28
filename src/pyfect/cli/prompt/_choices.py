"""What ``select``, ``auto_complete`` and ``multi_select`` share: the
``Choice`` type and how a row of the list is drawn."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pyfect.cli import _ansi as ansi
from pyfect.cli.prompt._core import (
    Theme,
    Window,
    annotate_symbol,
    render_paging_prefix,
    render_prompt,
    submitted_symbols,
)


@dataclass(frozen=True, slots=True)
class Choice[A]:
    """One option: its ``title``, the ``value`` it gives, an optional
    ``description`` shown while it is highlighted, whether it is
    ``disabled``, and whether it starts ``selected``."""

    title: str
    value: A
    description: str | None = None
    disabled: bool = False
    selected: bool = False


def initial_index(choices: Sequence[Choice[Any]]) -> int:
    """The choice marked ``selected`` (the first without one); at most one
    may be marked."""
    selected = [i for i, choice in enumerate(choices) if choice.selected]
    if len(selected) > 1:
        raise ValueError(
            "InvalidArgumentException: only a single choice can be selected by default "
            "for Prompt.Select"
        )
    return selected[0] if selected else 0


def render_header(
    leading: str, trailing: str, message: str | None, theme: Theme, *, plain: bool = False
) -> str | None:
    if message is None:
        return None
    return render_prompt("", message, leading, trailing, theme, plain=plain)


def with_header(header: str | None, body: str) -> str:
    return body if header is None else header + "\n" + body


def render_description(choice: Choice[Any], active: bool, theme: Theme, plain: bool) -> str:
    if not choice.disabled and choice.description and active:
        text = theme.description_separator + choice.description
        return text if plain else ansi.annotate(theme.colors, text, theme.muted_color)
    return ""


def render_title(choice: Choice[Any], active: bool, theme: Theme, plain: bool) -> str:
    if plain:
        return choice.title
    if active:
        color = theme.muted_color if choice.disabled else theme.primary_color
        return ansi.annotate(theme.colors, choice.title, ansi.underlined, color)
    if choice.disabled:
        return ansi.annotate(theme.colors, choice.title, ansi.strikethrough, theme.muted_color)
    return choice.title


def render_pointer(theme: Theme, active: bool, disabled: bool, prefix: str, plain: bool) -> str:
    if not active:
        return prefix + " " * len(theme.pointer)
    if plain:
        return theme.pointer + prefix
    if disabled:
        return annotate_symbol(theme, theme.pointer, ansi.bold, theme.muted_color) + prefix
    return annotate_symbol(theme, theme.pointer, theme.primary_color) + prefix


def paging(theme: Theme, window: Window, index: int, total: int) -> str:
    return render_paging_prefix(
        theme,
        index == window.start and window.start > 0,
        index == window.end - 1 and window.end < total,
    )


def render_row(theme: Theme, choice: Choice[Any], active: bool, prefix: str, plain: bool) -> str:
    pointer = render_pointer(theme, active, choice.disabled, prefix, plain)
    title = render_title(choice, active, theme, plain)
    return pointer + title + " " + render_description(choice, active, theme, plain)


def render_submitted(theme: Theme, header: str | None, text: str) -> str:
    """The answered prompt: the header (or the tick alone) and ``text``."""
    leading, _ = submitted_symbols(theme)
    shown = ansi.annotate(theme.colors, text, theme.submitted_color)
    return (leading if header is None else header) + " " + shown + "\n"
