"""``integer`` and ``number``: numeric prompts, reading the typed text as
JavaScript's ``parseInt`` / ``parseFloat`` read it."""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, replace

from pyfect._js import js_number
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
    clear_output_with_error,
    custom,
    get_theme,
    render_error,
    render_prompt,
    reset_current_line,
    submitted_symbols,
    terminal_columns,
)
from pyfect.effect import Effect, fail, gen, succeed
from pyfect.terminal import UserInput

_INT_PREFIX = re.compile(r"\s*([+-]?\d+)")
_FLOAT_PREFIX = re.compile(r"\s*([+-]?(?:Infinity|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?))")


def parse_int(text: str) -> int | None:
    """JavaScript's ``parseInt(text)``: the leading integer, or ``None``
    for ``NaN``."""
    match = _INT_PREFIX.match(text)
    return int(match.group(1)) if match else None


def parse_float(text: str) -> float | None:
    """JavaScript's ``parseFloat(text)``: the leading number, or ``None``
    for ``NaN``."""
    match = _FLOAT_PREFIX.match(text)
    if not match:
        return None
    return float(match.group(1).replace("Infinity", "inf"))


def _js_round(value: float, precision: int) -> float:
    factor = 10.0**precision
    return math.floor(value * factor + 0.5) / factor


def _bounds[N: (int, float)](minimum: float, maximum: float) -> Callable[[N], Effect[N, str]]:
    def validate(n: N) -> Effect[N, str]:
        if n < minimum:
            return fail(f"{js_number(n)} must be greater than or equal to {js_number(minimum)}")
        if n > maximum:
            return fail(f"{js_number(n)} must be less than or equal to {js_number(maximum)}")
        return succeed(n)

    return validate


@dataclass(frozen=True, slots=True)
class _State:
    cursor: int
    value: str
    error: str | None = None


def _frame[N](state: _State, value: str) -> Effect[Action[_State, N]]:
    return succeed(NextFrame(replace(state, value=value, error=None)))


@dataclass(frozen=True, slots=True)
class _NumberPrompt[N: (int, float)]:
    message: str
    increment_by: N
    decrement_by: N
    validate: Callable[[N], Effect[N, str]]
    parse: Callable[[str], N | None]
    typed: Callable[[str, _State], Effect[Action[_State, N]]]
    round: Callable[[N], N]
    not_a_number: str
    theme: ThemeOptions | None

    def _output(
        self,
        state: _State,
        symbols: tuple[str, str],
        theme: Theme,
        *,
        plain: bool = False,
        submitted: bool = False,
    ) -> str:
        value = state.value
        if not (submitted or plain):
            styles = (
                (theme.error_color,)
                if state.error is not None
                else (ansi.underlined, theme.primary_color)
            )
            value = ansi.annotate(theme.colors, value, *styles)
        return render_prompt(value, self.message, *symbols, theme, plain=plain)

    def render(self, state: _State, action: Action[_State, N]) -> Effect[str]:
        def body():
            figures = yield from get_theme(self.theme)
            match action:
                case Beep():
                    return ansi.beep
                case NextFrame():
                    shown = action.state
                    error = render_error(shown.error, figures.pointer_small, figures)
                    return self._output(shown, active_symbols(figures), figures) + error
                case Submit():
                    symbols = submitted_symbols(figures)
                    return self._output(state, symbols, figures, submitted=True) + "\n"

        return gen(body)

    def _step(self, state: _State, delta: N) -> Effect[Action[_State, N]]:
        current = self.parse(state.value)
        if state.value in ("", "-") or current is None:
            return _frame(state, js_number(delta))
        return _frame(state, js_number(current + delta))

    def _submit(self, state: _State) -> Effect[Action[_State, N]]:
        parsed = self.parse(state.value)
        if parsed is None:
            return succeed(NextFrame(replace(state, error=self.not_a_number)))
        return self.validate(self.round(parsed)).match(
            on_failure=lambda error: NextFrame(replace(state, error=error)),
            on_success=Submit,
        )

    def process(self, input: UserInput, state: _State) -> Effect[Action[_State, N]]:
        key = input.key
        if key.ctrl and key.name == "u":
            return succeed(NextFrame(_State(0, "")))
        match key.name:
            case "backspace":
                return _frame(state, state.value[:-1]) if state.value else succeed(Beep())
            case "k" | "up":
                return self._step(state, self.increment_by)
            case "j" | "down":
                return self._step(state, -self.decrement_by)
            case "enter" | "return":
                return self._submit(state)
            case _:
                return self.typed(input.input or "", state)

    def clear(self, state: _State, action: Action[_State, N]):
        def body():
            columns = yield from terminal_columns()
            figures = yield from get_theme(self.theme)
            error = render_error(state.error, figures.pointer_small, figures, plain=True)
            symbols = (figures.prefix, figures.pointer_small)
            output = self._output(state, symbols, figures, plain=True)
            return clear_output_with_error(output, columns, error) + reset_current_line()

        return gen(body)

    def prompt(self, initial: str) -> Prompt[N]:
        return custom(
            _State(len(initial), initial), Handlers(self.render, self.process, self.clear)
        )


def _typed_int(text: str, state: _State) -> Effect[Action[_State, int]]:
    if not state.value and text == "-":
        return _frame(state, "-")
    parsed = parse_int(state.value + text)
    return succeed(Beep()) if parsed is None else _frame(state, str(parsed))


def _typed_float(text: str, state: _State) -> Effect[Action[_State, float]]:
    if text == "." and "." in state.value:
        return succeed(Beep())
    if not state.value and text == "-":
        return _frame(state, "-")
    parsed = parse_float(state.value + text)
    if parsed is None:
        return succeed(Beep())
    if text == ".":
        return _frame(state, f"{js_number(parsed)}.")
    if "." in state.value and re.fullmatch(r"\d", text):
        return _frame(state, state.value + text)
    return _frame(state, js_number(parsed))


def integer(
    message: str,
    *,
    default: int | None = None,
    min: float = -math.inf,
    max: float = math.inf,
    increment_by: int = 1,
    decrement_by: int = 1,
    validate: Callable[[int], Effect[int, str]] | None = None,
    theme: ThemeOptions | None = None,
) -> Prompt[int]:
    """An integer, typed or stepped with the arrows (``j`` / ``k``),
    starting from ``default``; Enter submits once it is within
    ``min`` / ``max`` (or ``validate`` accepts it)."""
    handlers = _NumberPrompt(
        message,
        increment_by,
        decrement_by,
        validate or _bounds(min, max),
        parse_int,
        _typed_int,
        lambda n: n,
        "Must provide an integer value",
        theme,
    )
    return handlers.prompt("" if default is None else str(default))


def number(
    message: str,
    *,
    default: float | None = None,
    min: float = -math.inf,
    max: float = math.inf,
    increment_by: float = 1,
    decrement_by: float = 1,
    precision: int = 2,
    validate: Callable[[float], Effect[float, str]] | None = None,
    theme: ThemeOptions | None = None,
) -> Prompt[float]:
    """``integer`` for any number, rounded to ``precision`` decimals when
    submitted."""
    handlers = _NumberPrompt(
        message,
        float(increment_by),
        float(decrement_by),
        validate or _bounds(min, max),
        parse_float,
        _typed_float,
        lambda n: _js_round(n, precision),
        "Must provide a floating point value",
        theme,
    )
    return handlers.prompt("" if default is None else js_number(default))
