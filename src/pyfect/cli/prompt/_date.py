"""``date``: a date and time edited field by field through a mask such
as ``"YYYY-MM-DD HH:mm:ss"``."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

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
from pyfect.cli.prompt._date_parts import (
    Locales,
    Part,
    WallClock,
    first_part,
    make_parts,
    next_part,
    previous_part,
)
from pyfect.effect import Effect, gen, succeed, sync
from pyfect.terminal import UserInput

type Validate = Callable[[datetime], Effect[datetime, str]]


@dataclass(frozen=True, slots=True)
class _State:
    parts: tuple[Part, ...]
    clock: WallClock
    typed: str
    cursor: int
    error: str | None = None


@dataclass(frozen=True, slots=True)
class _DatePrompt:
    message: str
    start: datetime
    mask: str
    validate: Validate
    locales: Locales
    theme: ThemeOptions | None

    def initial(self) -> _State:
        clock = WallClock(self.start)
        parts = tuple(make_parts(self.mask, clock, self.locales))
        return _State(parts, clock, "", first_part(parts))

    def _parts(self, state: _State, figures: Theme, submitted: bool) -> str:
        output = ""
        for index, part in enumerate(state.parts):
            text = part.render()
            if index == state.cursor and not submitted:
                text = ansi.annotate(figures.colors, text, ansi.underlined, figures.primary_color)
            output += text
        return output

    def render(self, state: _State, action: Action[_State, datetime]) -> Effect[str]:
        def body():
            figures = yield from get_theme(self.theme)
            match action:
                case Beep():
                    return ansi.beep
                case NextFrame():
                    shown = action.state
                    parts = self._parts(shown, figures, False)
                    output = render_prompt(parts, self.message, *active_symbols(figures), figures)
                    error = render_error(shown.error, figures.pointer_small, figures)
                    return ansi.cursor_hide + output + error
                case Submit():
                    parts = self._parts(state, figures, True)
                    output = render_prompt(
                        parts, self.message, *submitted_symbols(figures), figures
                    )
                    return output + "\n"

        return gen(body)

    def _move(self, state: _State, index: int | None) -> Effect[Action[_State, datetime]]:
        if index is None:
            return succeed(Beep())
        return succeed(NextFrame(replace(state, typed="", cursor=index)))

    def _step(self, state: _State, step: Callable[[], None]) -> Effect[Action[_State, datetime]]:
        step()
        return succeed(NextFrame(replace(state, typed="")))

    def _type(self, text: str, state: _State) -> Effect[Action[_State, datetime]]:
        if not re.search(r"[0-9]", text):
            return succeed(Beep())
        typed = state.typed + text
        state.parts[state.cursor].set_value(typed)
        return succeed(NextFrame(replace(state, typed=typed)))

    def process(  # noqa: PLR0911 - one return per key
        self, input: UserInput, state: _State
    ) -> Effect[Action[_State, datetime]]:
        part = state.parts[state.cursor]
        match input.key.name:
            case "left":
                return self._move(state, previous_part(state.parts, state.cursor))
            case "right":
                return self._move(state, next_part(state.parts, state.cursor))
            case "k" | "up":
                return self._step(state, part.increment)
            case "j" | "down":
                return self._step(state, part.decrement)
            case "tab":
                following = next_part(state.parts, state.cursor)
                return self._move(
                    state, first_part(state.parts) if following is None else following
                )
            case "enter" | "return":
                return self.validate(state.clock.value.astimezone()).match(
                    on_failure=lambda error: NextFrame(replace(state, error=error)),
                    on_success=Submit,
                )
            case _:
                return self._type(input.input or "", state)

    def clear(self, state: _State, action: Action[_State, datetime]):
        def body():
            columns = yield from terminal_columns()
            figures = yield from get_theme(self.theme)
            parts = "".join(part.render() for part in state.parts)
            text = render_prompt(
                parts, self.message, figures.prefix, figures.pointer_small, figures, plain=True
            )
            error = render_error(state.error, figures.pointer_small, figures, plain=True)
            return clear_output_with_error(text, columns, error) + reset_current_line()

        return gen(body)


def date(
    message: str,
    *,
    initial: datetime | None = None,
    date_mask: str = "YYYY-MM-DD HH:mm:ss",
    validate: Validate = succeed,
    locales: Locales | None = None,
    theme: ThemeOptions | None = None,
) -> Prompt[datetime]:
    """A date and time, shown through ``date_mask``. Left / Right and Tab
    move between fields, the arrows or ``j`` / ``k`` step the field, digits
    type into it; Enter submits once ``validate`` accepts the value. Gives
    an aware datetime in the local time zone (naive ``initial`` values are
    read as local time)."""
    start = (initial or datetime.now()).astimezone().replace(tzinfo=None)
    handlers = _DatePrompt(message, start, date_mask, validate, locales or Locales(), theme)
    return custom(
        sync(handlers.initial), Handlers(handlers.render, handlers.process, handlers.clear)
    )
