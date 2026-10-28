"""``string``, ``password``, ``hidden`` and ``list_``: typed text."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal

from pyfect import redacted as redacted_
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
    active_symbols,
    annotate_symbol,
    clear_output_with_error,
    custom,
    get_theme,
    render_error,
    render_prompt,
    reset_current_line,
    submitted_symbols,
    terminal_columns,
)
from pyfect.effect import Effect, gen, succeed
from pyfect.redacted import Redacted
from pyfect.terminal import UserInput

type TextKind = Literal["text", "password", "hidden"]
type Validate[A] = Callable[[A], Effect[A, str]]


@dataclass(frozen=True, slots=True)
class _State:
    cursor: int
    value: str
    error: str | None = None


def _plain_input(kind: TextKind, text: str, theme: Theme) -> str:
    match kind:
        case "hidden":
            return ""
        case "password":
            return theme.password_mask * len(text)
        case "text":
            return text


def _styled_input(kind: TextKind, text: str, theme: Theme, styles: tuple[str, ...]) -> str:
    match kind:
        case "hidden":
            return ""
        case "password":
            return annotate_symbol(theme, theme.password_mask * len(text), *styles)
        case "text":
            return ansi.annotate(theme.colors, text, *styles)


@dataclass(frozen=True, slots=True)
class _TextPrompt:
    message: str
    default: str
    validate: Validate[str]
    kind: TextKind
    theme: ThemeOptions | None

    def _input(self, state: _State, theme: Theme, *, submitted: bool, plain: bool) -> str:
        if plain:
            return _plain_input(self.kind, state.value, theme)
        if not state.value:
            # Styling an empty value would make render_prompt add spacing for
            # text that takes no columns.
            return ""
        if state.error is not None:
            styles: tuple[str, ...] = (theme.error_color,)
        elif submitted:
            styles = (theme.submitted_color,)
        else:
            styles = (ansi.underlined, theme.primary_color)
        return _styled_input(self.kind, state.value, theme, styles)

    def _output(
        self,
        state: _State,
        symbols: tuple[str, str],
        theme: Theme,
        *,
        plain: bool = False,
        submitted: bool = False,
    ) -> str:
        value = self._input(state, theme, submitted=submitted, plain=plain)
        return render_prompt(value, self.message, *symbols, theme, plain=plain)

    def render(self, state: _State, action: Action[_State, str]) -> Effect[str]:
        def body():
            figures = yield from get_theme(self.theme)
            match action:
                case Beep():
                    return ansi.beep
                case NextFrame():
                    shown = action.state
                    output = self._output(shown, active_symbols(figures), figures)
                    error = render_error(shown.error, figures.pointer_small, figures)
                    width = len(figures.password_mask) if self.kind == "password" else 1
                    offset = (shown.cursor - len(shown.value)) * width
                    return output + error + ansi.cursor_move(offset)
                case Submit():
                    symbols = submitted_symbols(figures)
                    return self._output(state, symbols, figures, submitted=True) + "\n"

        return gen(body)

    def _ctrl(self, input: UserInput, state: _State) -> Effect[Action[_State, str]]:
        match input.key.name:
            case "u":
                return _frame(0, "")
            case "a":
                return _frame(0, state.value)
            case "e":
                return _frame(len(state.value), state.value)
            case _:
                return succeed(Beep())

    def _submit(self, state: _State) -> Effect[Action[_State, str]]:
        return self.validate(state.value).match(
            on_failure=lambda error: NextFrame(replace(state, error=error)),
            on_success=Submit,
        )

    def _tab(self, state: _State) -> Effect[Action[_State, str]]:
        if state.value == self.default:
            return succeed(Beep())
        value = state.value or self.default
        return _frame(len(value), value)

    def process(  # noqa: PLR0911 - one return per key
        self, input: UserInput, state: _State
    ) -> Effect[Action[_State, str]]:
        if input.key.ctrl:
            return self._ctrl(input, state)
        cursor, value = state.cursor, state.value
        match input.key.name:
            case "backspace" if cursor > 0:
                return _frame(cursor - 1, value[: cursor - 1] + value[cursor:])
            case "left" if cursor > 0:
                return _frame(cursor - 1, value)
            case "right" if cursor < len(value):
                return _frame(cursor + 1, value)
            case "backspace" | "left" | "right":
                return succeed(Beep())
            case "home":
                return _frame(0, value)
            case "end":
                return _frame(len(value), value)
            case "enter" | "return":
                return self._submit(state)
            case "tab":
                return self._tab(state)
            case _:
                typed = input.input or ""
                return _frame(cursor + len(typed), value[:cursor] + typed + value[cursor:])

    def clear(self, state: _State, action: Action[_State, str]):
        def body():
            columns = yield from terminal_columns()
            figures = yield from get_theme(self.theme)
            error = render_error(state.error, figures.pointer_small, figures, plain=True)
            symbols = (figures.prefix, figures.pointer_small)
            output = self._output(state, symbols, figures, plain=True)
            return clear_output_with_error(output, columns, error) + reset_current_line()

        return gen(body)


def _frame(cursor: int, value: str) -> Effect[Action[_State, str]]:
    return succeed(NextFrame(_State(cursor, value)))


def _text_prompt(
    message: str, default: str, validate: Validate[str], kind: TextKind, theme: ThemeOptions | None
) -> Prompt[str]:
    handlers = _TextPrompt(message, default, validate, kind, theme)
    initial = _State(len(default), default)
    return custom(initial, Handlers(handlers.render, handlers.process, handlers.clear))


def string(
    message: str,
    *,
    default: str = "",
    validate: Validate[str] = succeed,
    theme: ThemeOptions | None = None,
) -> Prompt[str]:
    """A line of text, starting from ``default`` (Tab fills it in when the
    input is empty); Enter submits once ``validate`` accepts it."""
    return _text_prompt(message, default, validate, "text", theme)


def password(
    message: str,
    *,
    default: str = "",
    validate: Validate[str] = succeed,
    theme: ThemeOptions | None = None,
) -> Prompt[Redacted[str]]:
    """``string``, shown masked and given as a ``Redacted``."""
    return _text_prompt(message, default, validate, "password", theme).map(redacted_.make)


def hidden(
    message: str,
    *,
    default: str = "",
    validate: Validate[str] = succeed,
    theme: ThemeOptions | None = None,
) -> Prompt[Redacted[str]]:
    """``string``, not shown at all and given as a ``Redacted``."""
    return _text_prompt(message, default, validate, "hidden", theme).map(redacted_.make)


def list_(
    message: str,
    *,
    delimiter: str = ",",
    default: str = "",
    validate: Validate[str] = succeed,
    theme: ThemeOptions | None = None,
) -> Prompt[list[str]]:
    """``string``, split at ``delimiter``."""
    separator = delimiter or ","
    prompt = string(message, default=default, validate=validate, theme=theme)
    return prompt.map(lambda text: text.split(separator))
