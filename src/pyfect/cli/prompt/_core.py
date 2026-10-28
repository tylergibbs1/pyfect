"""The prompt type, its run loop and the theme (Effect's ``Prompt``
internals shared by every prompt)."""

from __future__ import annotations

import math
import re
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    Never,
    TypedDict,
    TypeVar,
    Unpack,
    cast,
    overload,
    override,
)

from pyfect.cli import _ansi as ansi
from pyfect.context import Reference
from pyfect.effect import Effect, gen, succeed
from pyfect.errors import Done
from pyfect.file_system import FileSystem
from pyfect.path import Path
from pyfect.queue import Dequeue
from pyfect.scope import Scope, scoped
from pyfect.terminal import QuitError, Terminal, TerminalService, UserInput

if TYPE_CHECKING:
    from pyfect._fiber import Fiber

type PromptEnvironment = FileSystem | Path | Terminal
"""The services a prompt runs with (Effect's ``Prompt.Environment``)."""

A_co = TypeVar("A_co", covariant=True)
S_co = TypeVar("S_co", covariant=True)
O_co = TypeVar("O_co", covariant=True)

# --- theme ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class Theme:
    """The symbols and colors prompts render with."""

    prefix: str = "?"
    pointer: str = "\u276f"
    pointer_small: str = "\u203a"
    ellipsis: str = "…"
    tick: str = "✔"
    arrow_up: str = "↑"
    arrow_down: str = "↓"
    checkbox_on: str = "☒"
    checkbox_off: str = "☐"
    description_separator: str = "- "
    password_mask: str = "*"
    toggle_separator: str = "/"
    primary_color: str = ansi.cyan_bright
    muted_color: str = ansi.black_bright
    success_color: str = ansi.green
    error_color: str = ansi.red
    submitted_color: str = ansi.white
    colors: bool = False


class ThemeOptions(TypedDict, total=False):
    """Per-prompt (or ``make_theme``) overrides of ``Theme`` fields."""

    prefix: str
    pointer: str
    pointer_small: str
    ellipsis: str
    tick: str
    arrow_up: str
    arrow_down: str
    checkbox_on: str
    checkbox_off: str
    description_separator: str
    password_mask: str
    toggle_separator: str
    primary_color: str
    muted_color: str
    success_color: str
    error_color: str
    submitted_color: str
    colors: bool


_WINDOWS = ThemeOptions(
    checkbox_on="[*]", checkbox_off="[ ]", tick="√", ellipsis="...", pointer_small="»", pointer=">"
)


def make_theme(**options: Unpack[ThemeOptions]) -> Theme:
    """The default theme (Windows symbols on Windows) with ``options``;
    ``colors`` defaults to whether stdout is a terminal and ``NO_COLOR`` is
    unset."""
    base = Theme(**_WINDOWS) if sys.platform == "win32" else Theme()
    theme = replace(base, **options)
    return theme if "colors" in options else replace(theme, colors=ansi.detect_colors())


class PromptTheme(Reference[Theme]):
    """The theme in use (Effect's ``Prompt.Theme``); defaults to
    ``make_theme()``."""

    @classmethod
    def default(cls) -> Theme:
        return make_theme()


def get_theme(overrides: ThemeOptions | None) -> Effect[Theme]:
    theme = PromptTheme()
    if not overrides:
        return theme
    return theme.map(lambda t: replace(t, **overrides))


# --- actions -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Beep:
    """Reject the input: ring the bell and keep the state."""


@dataclass(frozen=True, slots=True)
class NextFrame(Generic[S_co]):
    """Redraw with ``state``."""

    state: S_co


@dataclass(frozen=True, slots=True)
class Submit(Generic[O_co]):
    """Finish with ``value``."""

    value: O_co


type Action[S, O] = Beep | NextFrame[S] | Submit[O]


@dataclass(frozen=True, slots=True)
class Input:
    """A key press, for a custom prompt that also takes events."""

    input: UserInput


@dataclass(frozen=True, slots=True)
class Event(Generic[A_co]):
    """A value from the custom prompt's event queue."""

    value: A_co


type ProcessInput[A] = Input | Event[A]


@dataclass(frozen=True, slots=True)
class Handlers[S, O, I = UserInput]:
    """A custom prompt's three steps: ``render`` the frame for an action,
    ``process`` one input into an action, ``clear`` the previous frame."""

    render: Callable[[S, Action[S, O]], Effect[str, Never, PromptEnvironment]]
    process: Callable[[I, S], Effect[Action[S, O], Never, PromptEnvironment]]
    clear: Callable[[S, Action[S, O]], Effect[str, Never, PromptEnvironment]]


# --- the prompt type -----------------------------------------------------------

type _Input = Effect[Dequeue[UserInput, Done], Never, Scope]


class Prompt(Effect[A_co, QuitError, PromptEnvironment], ABC):
    """An interactive question for the user; an effect that runs it
    (``run``). Build one with the constructors in ``pyfect.cli.prompt``
    and combine them with ``map``, ``flat_map`` and ``all``."""

    @override
    def _step(self, fiber: Fiber[Any, Any]) -> Effect[A_co, QuitError, PromptEnvironment]:
        return run(self)

    @abstractmethod
    def run_with(
        self, terminal: TerminalService, input: _Input
    ) -> Effect[A_co, Done, PromptEnvironment | Scope]:
        """Ask on ``terminal``, reading key presses from the shared
        ``input``; ``run`` provides both."""

    @override
    def map[B](self, f: Callable[[A_co], B]) -> Prompt[B]:
        return _OnSuccess(self, lambda value: _Succeed(f(value)))

    @overload
    def flat_map[B](self, f: Callable[[A_co], Prompt[B]]) -> Prompt[B]: ...
    @overload
    def flat_map[B, E2 = Never, R2 = Never](
        self, f: Callable[[A_co], Effect[B, E2, R2]]
    ) -> Effect[B, QuitError | E2, PromptEnvironment | R2]: ...
    @override
    def flat_map(self, f: Callable[[Any], Effect[Any, Any, Any]]) -> Effect[Any, Any, Any]:
        return _OnSuccess(self, f)


class _Succeed(Prompt[A_co]):
    def __init__(self, value: A_co) -> None:
        self._value = value

    def run_with(
        self, terminal: TerminalService, input: _Input
    ) -> Effect[A_co, Done, PromptEnvironment | Scope]:
        return succeed(self._value)


class _OnSuccess[X, A](Prompt[A]):
    def __init__(self, prompt: Prompt[X], f: Callable[[X], Effect[A, Any, Any]]) -> None:
        self._prompt = prompt
        self._f = f

    def run_with(
        self, terminal: TerminalService, input: _Input
    ) -> Effect[A, Done, PromptEnvironment | Scope]:
        def next_step(value: X) -> Effect[A, Done, PromptEnvironment | Scope]:
            following = self._f(value)
            if isinstance(following, Prompt):
                return following.run_with(terminal, input)
            return following

        return self._prompt.run_with(terminal, input).flat_map(next_step)


class _Loop[S, O, X](Prompt[O]):
    def __init__(
        self,
        initial: S | Effect[S, Never, PromptEnvironment],
        handlers: Handlers[S, O, Any],
        events: Dequeue[X, Any] | None,
    ) -> None:
        self._initial = initial
        self._handlers = handlers
        self._events = events

    def run_with(
        self, terminal: TerminalService, input: _Input
    ) -> Effect[O, Done, PromptEnvironment | Scope]:
        return input.flat_map(lambda queue: self._loop(terminal, queue))

    def _loop(
        self, terminal: TerminalService, queue: Dequeue[UserInput, Done]
    ) -> Effect[O, Done, PromptEnvironment]:
        handlers = self._handlers
        events = self._events

        def take() -> Effect[object, Done]:
            if events is None:
                return queue.take()
            return (
                queue.take()
                .map(Input)
                .race_first(cast("Effect[X, Never]", events.take()).map(Event))
            )

        def body():
            initial = self._initial
            state: S = cast("S", (yield from initial)) if isinstance(initial, Effect) else initial
            action: Action[S, O] = NextFrame(state)
            clear = ""
            while True:
                message = yield from handlers.render(state, action)
                yield from terminal.display(clear + message).or_die()
                clear = ""
                taken = yield from take()
                action = yield from handlers.process(taken, state)
                match action:
                    case Beep():
                        continue
                    case NextFrame():
                        clear = yield from handlers.clear(state, action)
                        state = action.state
                    case Submit():
                        clear = yield from handlers.clear(state, action)
                        message = yield from handlers.render(state, action)
                        yield from terminal.display(clear + message).or_die()
                        return action.value

        return gen(body).ensuring(terminal.display(ansi.cursor_show).or_die())


@overload
def custom[S, O](
    initial: S | Effect[S, Never, PromptEnvironment], handlers: Handlers[S, O, UserInput], /
) -> Prompt[O]: ...
@overload
def custom[S, O, X](
    initial: S | Effect[S, Never, PromptEnvironment],
    events: Dequeue[X, Any],
    handlers: Handlers[S, O, ProcessInput[X]],
    /,
) -> Prompt[O]: ...
def custom(initial: Any, *args: Any) -> Prompt[Any]:
    """A prompt from ``handlers`` starting at ``initial`` (or the state an
    effect gives); with an ``events`` queue, ``process`` gets ``Input`` and
    ``Event`` values."""
    if len(args) == 1:
        return _Loop[Any, Any, Any](initial, args[0], None)
    return _Loop[Any, Any, Any](initial, args[1], args[0])


def prompt_succeed[A](value: A) -> Prompt[A]:
    """A prompt that asks nothing and gives ``value``."""
    return _Succeed(value)


def run[A](prompt: Prompt[A]) -> Effect[A, QuitError, PromptEnvironment]:
    """Ask: render, read key presses until the prompt submits. Fails with
    ``QuitError`` when input ends (Ctrl+C, Ctrl+D)."""

    def body():
        terminal = yield from Terminal()
        input = yield from terminal.read_input.cached()
        return (yield from prompt.run_with(terminal, input))

    return scoped(gen(body)).map_error(lambda _: QuitError())


@overload
def all[A](prompts: Mapping[str, Prompt[A]], /) -> Prompt[dict[str, A]]: ...
@overload
def all[A](prompts: Iterable[Prompt[A]], /) -> Prompt[list[A]]: ...
def all(prompts: Mapping[str, Prompt[Any]] | Iterable[Prompt[Any]], /) -> Prompt[Any]:
    """Ask each prompt in order: a mapping gives a dict by key, an iterable
    a list."""
    if isinstance(prompts, Mapping):
        entries = list(cast("Mapping[str, Prompt[Any]]", prompts).items())
        result: Prompt[dict[str, Any]] = _Succeed({})
        for key, prompt in entries:
            result = result.flat_map(_add_entry(key, prompt))
        return result
    items: Prompt[list[Any]] = _Succeed([])
    for prompt in prompts:
        items = items.flat_map(_append(prompt))
    return items


def _add_entry(key: str, prompt: Prompt[Any]) -> Callable[[dict[str, Any]], Prompt[dict[str, Any]]]:
    return lambda record: prompt.map(lambda value: {**record, key: value})


def _append(prompt: Prompt[Any]) -> Callable[[list[Any]], Prompt[list[Any]]]:
    return lambda values: prompt.map(lambda value: [*values, value])


# --- rendering helpers -----------------------------------------------------------

NEWLINE = re.compile(r"\r?\n")


def annotate_symbol(theme: Theme, symbol: str, *styles: str) -> str:
    return "" if not symbol else ansi.annotate(theme.colors, symbol, *styles)


def active_symbols(theme: Theme) -> tuple[str, str]:
    """The leading and trailing symbols of a prompt waiting for input."""
    return (
        annotate_symbol(theme, theme.prefix, theme.primary_color),
        annotate_symbol(theme, theme.pointer_small, theme.muted_color),
    )


def submitted_symbols(theme: Theme) -> tuple[str, str]:
    """The leading and trailing symbols of an answered prompt."""
    return (
        annotate_symbol(theme, theme.tick, theme.success_color),
        annotate_symbol(theme, theme.ellipsis, theme.muted_color),
    )


def annotate_error_line(theme: Theme, line: str) -> str:
    return ansi.annotate(theme.colors, line, ansi.italicized, theme.error_color)


def separate_symbol(symbol: str, text: str) -> str:
    return text if not symbol else f"{symbol} {text}"


def render_paging_prefix(theme: Theme, show_up: bool, show_down: bool) -> str:
    width = max(len(theme.arrow_up), len(theme.arrow_down))
    if show_up:
        return theme.arrow_up.ljust(width)
    if show_down:
        return theme.arrow_down.ljust(width)
    return " " * width


def render_prompt(
    confirm: str,
    message: str,
    leading: str,
    trailing: str,
    theme: Theme,
    *,
    plain: bool = False,
) -> str:
    """The prompt line: the leading symbol, the message (bold unless
    ``plain``), the trailing symbol and ``confirm``."""
    prefix = "" if not leading else leading + " "
    lines = NEWLINE.split(message)
    if not plain:
        lines = [ansi.annotate(theme.colors, line, ansi.bold) for line in lines]
    output = prefix + "\n".join(lines)
    if trailing:
        output += " " + trailing
    if confirm:
        output += " " + confirm
    elif trailing:
        output += " "
    return output


def erase_text(text: str, columns: int) -> str:
    if columns == 0:
        return ansi.erase_line + ansi.cursor_to(0)
    rows = 0
    for line in NEWLINE.split(text):
        rows += 1 + max(len(line) - 1, 0) // columns
    return ansi.erase_lines(rows)


def line_count(text: str, columns: int) -> int:
    lines = NEWLINE.split(text)
    if columns == 0:
        return len(lines)
    return sum(math.ceil(len(line) / columns) for line in lines)


def clear_output_with_error(output: str, columns: int, error: str = "") -> str:
    if error:
        return (
            ansi.cursor_down(line_count(error, columns))
            + erase_text(f"\n{error}", columns)
            + erase_text(output, columns)
        )
    return erase_text(output, columns)


def render_error(error: str | None, pointer: str, theme: Theme, *, plain: bool = False) -> str:
    """A validation error under the prompt (``""`` without one)."""
    if error is None:
        return ""
    lines = NEWLINE.split(error)
    if plain:
        return separate_symbol(pointer, "\n".join(lines))
    prefix = annotate_symbol(theme, pointer, theme.error_color)
    styled = [annotate_error_line(theme, line) for line in lines]
    return (
        ansi.cursor_save_position
        + "\n"
        + separate_symbol(prefix, "\n".join(styled))
        + ansi.cursor_restore_position
    )


def reset_current_line() -> str:
    return ansi.erase_line + ansi.cursor_left


def terminal_columns() -> Effect[int, Never, Terminal]:
    return Terminal().flat_map(lambda terminal: terminal.columns)


@dataclass(frozen=True, slots=True)
class Window:
    start: int
    end: int


def entries_to_display(cursor: int, total: int, max_visible: int | None = None) -> Window:
    """The page of ``total`` entries to show around ``cursor``."""
    maximum = total if max_visible is None else max_visible
    start = max(min(total - maximum, cursor - maximum // 2), 0)
    return Window(start, min(start + maximum, total))


__all__ = [
    "Action",
    "Beep",
    "Event",
    "Handlers",
    "Input",
    "NextFrame",
    "ProcessInput",
    "Prompt",
    "PromptEnvironment",
    "PromptTheme",
    "Submit",
    "Theme",
    "ThemeOptions",
    "all",
    "custom",
    "entries_to_display",
    "make_theme",
    "prompt_succeed",
    "run",
]
