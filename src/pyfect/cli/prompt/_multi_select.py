"""``multi_select``: any number of a list of choices."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from pyfect.cli import _ansi as ansi
from pyfect.cli.prompt._choices import (
    Choice,
    paging,
    render_description,
    render_header,
    render_submitted,
    render_title,
    with_header,
)
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
    entries_to_display,
    get_theme,
    render_error,
    reset_current_line,
    submitted_symbols,
    terminal_columns,
)
from pyfect.effect import Effect, gen, succeed
from pyfect.terminal import UserInput

_META_OPTIONS = 2


@dataclass(frozen=True, slots=True)
class _State:
    index: int
    selected: frozenset[int]
    error: str | None = None


@dataclass(frozen=True, slots=True)
class _MultiSelect[A]:
    choices: tuple[Choice[A], ...]
    message: str | None
    max_per_page: int
    select_all: str
    select_none: str
    inverse_selection: str
    min: int | None
    max: int | None
    theme: ThemeOptions | None

    def _enabled(self, selected: frozenset[int]) -> list[int]:
        return sorted(i for i in selected if not self.choices[i].disabled)

    def _all_selected(self, selected: frozenset[int]) -> bool:
        selectable = sum(1 for choice in self.choices if not choice.disabled)
        return len(self._enabled(selected)) == selectable

    def _choice_row(self, state: _State, index: int, figures: Theme, plain: bool) -> str:
        highlighted = state.index == index + _META_OPTIONS
        choice = self.choices[index]
        checkbox = figures.checkbox_on if index in state.selected else figures.checkbox_off
        shown = (
            ansi.annotate(figures.colors, checkbox, figures.primary_color)
            if highlighted and not plain
            else checkbox
        )
        width = max(len(figures.checkbox_on), len(figures.checkbox_off))
        box = "" if width == 0 else shown + " " * (width - len(checkbox) + 1)
        title = render_title(choice, highlighted, figures, plain)
        return box + title + " " + render_description(choice, highlighted, figures, plain)

    def _rows(self, state: _State, figures: Theme, plain: bool) -> str:
        first = self.select_none if self._all_selected(state.selected) else self.select_all
        meta = (first, self.inverse_selection)
        total = len(meta) + len(self.choices)
        window = entries_to_display(state.index, total, self.max_per_page)
        rows: list[str] = []
        for index in range(window.start, window.end):
            prefix = paging(figures, window, index, total)
            gap = "" if not prefix else " "
            if index < len(meta):
                title = meta[index]
                if state.index == index and not plain:
                    title = ansi.annotate(
                        figures.colors, title, ansi.underlined, figures.primary_color
                    )
                rows.append(prefix + gap + title)
            else:
                rows.append(
                    prefix + gap + self._choice_row(state, index - len(meta), figures, plain)
                )
        return "\n".join(rows)

    def render(self, state: _State, action: Action[_State, list[A]]) -> Effect[str]:
        def body():
            figures = yield from get_theme(self.theme)
            match action:
                case Beep():
                    return ansi.beep
                case NextFrame():
                    next_state = action.state
                    header = render_header(*active_symbols(figures), self.message, figures)
                    rows = self._rows(next_state, figures, False)
                    error = render_error(next_state.error, figures.pointer, figures)
                    return ansi.cursor_hide + with_header(header, rows) + error
                case Submit():
                    header = render_header(*submitted_symbols(figures), self.message, figures)
                    titles = ", ".join(self.choices[i].title for i in sorted(state.selected))
                    return render_submitted(figures, header, titles)

        return gen(body)

    def _toggle(self, state: _State) -> Action[_State, list[A]]:
        selected = set(state.selected)
        enabled = {i for i, choice in enumerate(self.choices) if not choice.disabled}
        if state.index == 0:
            selected = set[int]() if self._all_selected(state.selected) else selected | enabled
        elif state.index == 1:
            selected = enabled - state.selected
        else:
            index = state.index - _META_OPTIONS
            if index not in enabled:
                return Beep()
            selected ^= {index}
        return NextFrame(replace(state, selected=frozenset(selected)))

    def _submit(self, state: _State) -> Action[_State, list[A]]:
        chosen = self._enabled(state.selected)
        if self.min is not None and len(chosen) < self.min:
            return NextFrame(replace(state, error=f"At least {self.min} are required"))
        if self.max is not None and len(chosen) > self.max:
            return NextFrame(replace(state, error=f"At most {self.max} choices are allowed"))
        return Submit([self.choices[i].value for i in chosen])

    def process(self, input: UserInput, state: _State) -> Effect[Action[_State, list[A]]]:
        total = len(self.choices) + _META_OPTIONS
        match input.key.name:
            case "k" | "up":
                index = total - 1 if state.index == 0 else state.index - 1
                return succeed(NextFrame(_State(index, state.selected)))
            case "j" | "down" | "tab":
                return succeed(NextFrame(_State((state.index + 1) % total, state.selected)))
            case "space":
                return succeed(self._toggle(state))
            case "enter" | "return":
                return succeed(self._submit(state))
            case _:
                return succeed(Beep())

    def clear(self, state: _State, action: Action[_State, list[A]]):
        def body():
            columns = yield from terminal_columns()
            figures = yield from get_theme(self.theme)
            header = render_header(
                figures.prefix, figures.pointer_small, self.message, figures, plain=True
            )
            text = with_header(header, self._rows(state, figures, True))
            error = render_error(state.error, figures.pointer, figures, plain=True)
            return clear_output_with_error(text, columns, error) + reset_current_line()

        return gen(body)


def multi_select[A](
    choices: Sequence[Choice[A]],
    *,
    message: str | None = None,
    max_per_page: int = 10,
    select_all: str = "Select All",
    select_none: str = "Select None",
    inverse_selection: str = "Inverse Selection",
    min: int | None = None,
    max: int | None = None,
    theme: ThemeOptions | None = None,
) -> Prompt[list[A]]:
    """Any number of ``choices``, toggled with Space; the first two rows
    select all (or none) and invert the selection. Enter submits once the
    count is within ``min`` / ``max``."""
    handlers = _MultiSelect(
        tuple(choices),
        message,
        max_per_page,
        select_all,
        select_none,
        inverse_selection,
        min,
        max,
        theme,
    )
    initial = frozenset(
        i for i, choice in enumerate(handlers.choices) if choice.selected and not choice.disabled
    )
    return custom(_State(0, initial), Handlers(handlers.render, handlers.process, handlers.clear))
