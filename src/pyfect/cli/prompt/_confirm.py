"""``confirm`` and ``toggle``: yes-or-no prompts."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pyfect.cli import _ansi as ansi
from pyfect.cli.prompt._core import (
    Action,
    Beep,
    Handlers,
    NextFrame,
    Prompt,
    Submit,
    Theme,
    ThemeOptions,
    annotate_symbol,
    custom,
    erase_text,
    get_theme,
    render_prompt,
    reset_current_line,
    separate_symbol,
    terminal_columns,
)
from pyfect.effect import Effect, gen, succeed
from pyfect.terminal import UserInput

_TRUE = re.compile(r"^y|t$")
_FALSE = re.compile(r"^n|f$")


@dataclass(frozen=True, slots=True)
class _Confirm:
    message: str
    initial: bool
    confirm_label: str
    deny_label: str
    default_confirm: str
    default_deny: str
    theme: ThemeOptions | None


def confirm(
    message: str,
    *,
    initial: bool = False,
    confirm_label: str = "yes",
    deny_label: str = "no",
    default_confirm: str = "(Y/n)",
    default_deny: str = "(y/N)",
    theme: ThemeOptions | None = None,
) -> Prompt[bool]:
    """Yes or no: ``y`` / ``t`` is yes, ``n`` / ``f`` is no, Enter takes
    ``initial``. The placeholder shows the default; the labels show the
    answer."""
    opts = _Confirm(
        message, initial, confirm_label, deny_label, default_confirm, default_deny, theme
    )

    def render(state: bool, action: Action[bool, bool]) -> Effect[str]:
        def body():
            figures = yield from get_theme(opts.theme)
            match action:
                case Beep():
                    return ansi.beep
                case NextFrame():
                    leading = annotate_symbol(figures, figures.prefix, figures.primary_color)
                    trailing = annotate_symbol(figures, figures.pointer_small, figures.muted_color)
                    placeholder = opts.default_confirm if action.state else opts.default_deny
                    styled = ansi.annotate(figures.colors, placeholder, figures.muted_color)
                    return ansi.cursor_hide + render_prompt(
                        styled, opts.message, leading, trailing, figures
                    )
                case Submit():
                    leading = annotate_symbol(figures, figures.tick, figures.success_color)
                    trailing = annotate_symbol(figures, figures.ellipsis, figures.muted_color)
                    label = opts.confirm_label if action.value else opts.deny_label
                    return render_prompt(label, opts.message, leading, trailing, figures) + "\n"

        return gen(body)

    def process(input: UserInput, state: bool) -> Effect[Action[bool, bool]]:
        value = (input.input or "").lower()
        if input.key.name in ("enter", "return"):
            return succeed(Submit(opts.initial))
        if _TRUE.search(value):
            return succeed(Submit(True))
        if _FALSE.search(value):
            return succeed(Submit(False))
        return succeed(Beep())

    def clear(state: bool, action: Action[bool, bool]):
        def body():
            columns = yield from terminal_columns()
            figures = yield from get_theme(opts.theme)
            placeholder = opts.default_confirm if state else opts.default_deny
            text = render_prompt(
                placeholder,
                opts.message,
                figures.prefix,
                figures.pointer_small,
                figures,
                plain=True,
            )
            return erase_text(text, columns) + reset_current_line()

        return gen(body)

    return custom(initial, Handlers(render, process, clear))


@dataclass(frozen=True, slots=True)
class _Toggle:
    message: str
    initial: bool
    active: str
    inactive: str
    theme: ThemeOptions | None


def toggle(
    message: str,
    *,
    initial: bool = False,
    active: str = "on",
    inactive: str = "off",
    theme: ThemeOptions | None = None,
) -> Prompt[bool]:
    """A switch between ``active`` and ``inactive``: arrows, ``j`` / ``k``,
    ``0`` / ``1``, Space or Tab change it; Enter submits."""
    opts = _Toggle(message, initial, active, inactive, theme)

    def render_toggle(value: bool, figures: Theme, submitted: bool) -> str:
        separator = annotate_symbol(figures, figures.toggle_separator, figures.muted_color)
        selected = (
            ansi.underlined,
            figures.submitted_color if submitted else figures.primary_color,
        )
        inactive_text = (
            opts.inactive if value else ansi.annotate(figures.colors, opts.inactive, *selected)
        )
        active_text = (
            ansi.annotate(figures.colors, opts.active, *selected) if value else opts.active
        )
        return active_text + " " + separate_symbol(separator, inactive_text)

    def render(state: bool, action: Action[bool, bool]) -> Effect[str]:
        def body():
            figures = yield from get_theme(opts.theme)
            match action:
                case Beep():
                    return ansi.beep
                case NextFrame():
                    leading = annotate_symbol(figures, figures.prefix, figures.primary_color)
                    trailing = annotate_symbol(figures, figures.pointer_small, figures.muted_color)
                    text = render_toggle(state, figures, False)
                    return ansi.cursor_hide + render_prompt(
                        text, opts.message, leading, trailing, figures
                    )
                case Submit():
                    leading = annotate_symbol(figures, figures.tick, figures.success_color)
                    trailing = annotate_symbol(figures, figures.ellipsis, figures.muted_color)
                    text = render_toggle(state, figures, True)
                    return render_prompt(text, opts.message, leading, trailing, figures) + "\n"

        return gen(body)

    def process(input: UserInput, state: bool) -> Effect[Action[bool, bool]]:
        match input.key.name:
            case "0" | "j" | "delete" | "right" | "down":
                return succeed(NextFrame(False))
            case "1" | "k" | "left" | "up":
                return succeed(NextFrame(True))
            case " " | "tab":
                return succeed(NextFrame(not state))
            case "enter" | "return":
                return succeed(Submit(state))
            case _:
                return succeed(Beep())

    def clear(state: bool, action: Action[bool, bool]):
        def body():
            columns = yield from terminal_columns()
            figures = yield from get_theme(opts.theme)
            text = opts.active + " " + separate_symbol(figures.toggle_separator, opts.inactive)
            line = render_prompt(
                text, opts.message, figures.prefix, figures.pointer_small, figures, plain=True
            )
            return erase_text(line, columns) + reset_current_line()

        return gen(body)

    return custom(initial, Handlers(render, process, clear))
