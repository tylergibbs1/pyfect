"""``select``: one of a list of choices."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pyfect.cli import _ansi as ansi
from pyfect.cli.prompt._choices import (
    Choice,
    initial_index,
    paging,
    render_header,
    render_row,
    render_submitted,
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
    custom,
    entries_to_display,
    erase_text,
    get_theme,
    reset_current_line,
    submitted_symbols,
    terminal_columns,
)
from pyfect.effect import Effect, gen, succeed
from pyfect.terminal import UserInput


@dataclass(frozen=True, slots=True)
class _Select[A]:
    choices: tuple[Choice[A], ...]
    message: str | None
    max_per_page: int
    theme: ThemeOptions | None

    def _rows(self, state: int, figures: Theme, plain: bool) -> str:
        total = len(self.choices)
        window = entries_to_display(state, total, self.max_per_page)
        return "\n".join(
            render_row(
                figures,
                self.choices[index],
                state == index,
                paging(figures, window, index, total),
                plain,
            )
            for index in range(window.start, window.end)
        )

    def render(self, state: int, action: Action[int, A]) -> Effect[str]:
        def body():
            figures = yield from get_theme(self.theme)
            match action:
                case Beep():
                    return ansi.beep
                case NextFrame():
                    header = render_header(*active_symbols(figures), self.message, figures)
                    rows = self._rows(action.state, figures, False)
                    return ansi.cursor_hide + with_header(header, rows)
                case Submit():
                    header = render_header(*submitted_symbols(figures), self.message, figures)
                    return render_submitted(figures, header, self.choices[state].title)

        return gen(body)

    def process(self, input: UserInput, state: int) -> Effect[Action[int, A]]:
        last = len(self.choices) - 1
        match input.key.name:
            case "k" | "up":
                return succeed(NextFrame(last if state == 0 else state - 1))
            case "j" | "down":
                return succeed(NextFrame(0 if state == last else state + 1))
            case "tab":
                return succeed(NextFrame((state + 1) % len(self.choices)))
            case "enter" | "return":
                chosen = self.choices[state]
                return succeed(Beep() if chosen.disabled else Submit(chosen.value))
            case _:
                return succeed(Beep())

    def clear(self, state: int, action: Action[int, A]):
        def body():
            columns = yield from terminal_columns()
            figures = yield from get_theme(self.theme)
            header = render_header(
                figures.prefix, figures.pointer_small, self.message, figures, plain=True
            )
            text = with_header(header, self._rows(state, figures, True))
            return erase_text(text, columns) + reset_current_line()

        return gen(body)


def select[A](
    choices: Sequence[Choice[A]],
    *,
    message: str | None = None,
    max_per_page: int = 10,
    theme: ThemeOptions | None = None,
) -> Prompt[A]:
    """One of ``choices``: arrows or ``j`` / ``k`` move, Tab cycles, Enter
    takes the highlighted one unless it is disabled. Without ``message``
    only the list shows."""
    handlers = _Select(tuple(choices), message, max_per_page, theme)
    initial = initial_index(handlers.choices)
    return custom(initial, Handlers(handlers.render, handlers.process, handlers.clear))
