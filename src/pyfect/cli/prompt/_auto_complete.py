"""``auto_complete``: ``select`` with a filter typed above the list."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from pyfect.cli import _ansi as ansi
from pyfect.cli.prompt._choices import Choice, initial_index, paging, render_row, render_submitted
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
    custom,
    entries_to_display,
    erase_text,
    get_theme,
    render_prompt,
    reset_current_line,
    submitted_symbols,
    terminal_columns,
)
from pyfect.effect import Effect, gen, succeed
from pyfect.terminal import UserInput


@dataclass(frozen=True, slots=True)
class _State:
    query: str
    index: int
    filtered: tuple[int, ...]

    @property
    def cursor(self) -> int:
        return self.filtered.index(self.index) if self.index in self.filtered else 0


def _filter(choices: Sequence[Choice[Any]], query: str) -> tuple[int, ...]:
    needle = query.lower()
    return tuple(i for i, choice in enumerate(choices) if needle in choice.title.lower())


@dataclass(frozen=True, slots=True)
class _AutoComplete[A]:
    message: str
    choices: tuple[Choice[A], ...]
    max_per_page: int
    filter_label: str
    filter_placeholder: str
    empty_message: str
    theme: ThemeOptions | None

    def initial(self) -> _State:
        start = initial_index(self.choices)
        filtered = _filter(self.choices, "")
        index = 0 if not filtered else start if start in filtered else filtered[0]
        return _State("", index, filtered)

    def _update(self, state: _State, query: str) -> _State:
        matches = _filter(self.choices, query)
        if not matches:
            return _State(query, 0, matches)
        index = state.index if state.index in matches else matches[0]
        return _State(query, index, matches)

    def _filter_text(self, state: _State, figures: Theme, plain: bool) -> str:
        if not state.query:
            placeholder = self.filter_placeholder
            value = (
                placeholder
                if plain
                else ansi.annotate(figures.colors, placeholder, figures.muted_color)
            )
        elif plain:
            value = state.query
        else:
            value = ansi.annotate(
                figures.colors, state.query, ansi.underlined, figures.primary_color
            )
        return f"[{self.filter_label}: {value}]"

    def _output(
        self, state: _State, leading: str, trailing: str, figures: Theme, plain: bool
    ) -> str:
        text = self._filter_text(state, figures, plain)
        return render_prompt(text, self.message, leading, trailing, figures, plain=plain)

    def _rows(self, state: _State, figures: Theme, plain: bool) -> str:
        if not state.filtered:
            empty = self.empty_message
            return empty if plain else ansi.annotate(figures.colors, empty, figures.muted_color)
        total = len(state.filtered)
        window = entries_to_display(state.cursor, total, self.max_per_page)
        rows: list[str] = []
        for position in range(window.start, window.end):
            index = state.filtered[position]
            prefix = paging(figures, window, position, total)
            rows.append(
                render_row(figures, self.choices[index], state.index == index, prefix, plain)
            )
        return "\n".join(rows)

    def render(self, state: _State, action: Action[_State, A]) -> Effect[str]:
        def body():
            figures = yield from get_theme(self.theme)
            match action:
                case Beep():
                    return ansi.beep
                case NextFrame():
                    next_state = action.state
                    output = self._output(next_state, *active_symbols(figures), figures, False)
                    return ansi.cursor_hide + output + "\n" + self._rows(next_state, figures, False)
                case Submit():
                    output = self._output(state, *submitted_symbols(figures), figures, False)
                    return render_submitted(figures, output, self.choices[state.index].title)

        return gen(body)

    def _move(self, state: _State, step: int) -> Effect[Action[_State, A]]:
        if not state.filtered:
            return succeed(Beep())
        position = (state.cursor + step) % len(state.filtered)
        return succeed(NextFrame(replace(state, index=state.filtered[position])))

    def _submit(self, state: _State) -> Effect[Action[_State, A]]:
        if not state.filtered:
            return succeed(Beep())
        chosen = self.choices[state.index]
        return succeed(Beep() if chosen.disabled else Submit(chosen.value))

    def _ctrl(self, input: UserInput, state: _State) -> Effect[Action[_State, A]]:
        match input.key.name:
            case "u":
                return succeed(NextFrame(self._update(state, "")))
            case "p" | "k":
                return self._move(state, -1)
            case "n":
                return self._move(state, 1)
            case _:
                return succeed(Beep())

    def process(  # noqa: PLR0911 - one return per key
        self, input: UserInput, state: _State
    ) -> Effect[Action[_State, A]]:
        if input.key.ctrl:
            return self._ctrl(input, state)
        match input.key.name:
            case "up":
                return self._move(state, -1)
            case "down" | "tab":
                return self._move(state, 1)
            case "backspace":
                if not state.query:
                    return succeed(Beep())
                return succeed(NextFrame(self._update(state, state.query[:-1])))
            case "enter" | "return":
                return self._submit(state)
            case _:
                text = input.input or ""
                if not text:
                    return succeed(Beep())
                return succeed(NextFrame(self._update(state, state.query + text)))

    def clear(self, state: _State, action: Action[_State, A]):
        def body():
            columns = yield from terminal_columns()
            figures = yield from get_theme(self.theme)
            output = self._output(state, figures.prefix, figures.pointer_small, figures, True)
            text = f"{output}\n{self._rows(state, figures, True)}"
            return erase_text(text, columns) + reset_current_line()

        return gen(body)


def auto_complete[A](
    message: str,
    choices: Sequence[Choice[A]],
    *,
    max_per_page: int = 10,
    filter_label: str = "filter",
    filter_placeholder: str = "type to filter",
    empty_message: str = "No matches",
    theme: ThemeOptions | None = None,
) -> Prompt[A]:
    """``select`` with a filter: typing narrows the list to titles
    containing the text (case-insensitively); Ctrl+N / Ctrl+P / Ctrl+K and
    the arrows move, Ctrl+U clears the filter."""
    handlers = _AutoComplete(
        message,
        tuple(choices),
        max_per_page,
        filter_label,
        filter_placeholder,
        empty_message,
        theme,
    )
    initial = handlers.initial()
    return custom(initial, Handlers(handlers.render, handlers.process, handlers.clear))
