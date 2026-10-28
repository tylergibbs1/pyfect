"""``file``: pick a file or directory by browsing from a starting
directory."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal, Never

from pyfect._concurrency import for_each
from pyfect.cli import _ansi as ansi
from pyfect.cli.prompt._core import (
    Action,
    Beep,
    Handlers,
    NextFrame,
    Prompt,
    PromptEnvironment,
    Submit,
    Theme,
    ThemeOptions,
    active_symbols,
    annotate_symbol,
    custom,
    entries_to_display,
    erase_text,
    get_theme,
    render_paging_prefix,
    render_prompt,
    reset_current_line,
    separate_symbol,
    submitted_symbols,
    terminal_columns,
)
from pyfect.effect import Effect, die, gen, succeed
from pyfect.file_system import FileSystem
from pyfect.path import Path
from pyfect.terminal import UserInput

type FileType = Literal["file", "directory", "either"]

CONFIRM_MESSAGE = (
    "The selected directory contains files. Would you like to traverse the selected directory?"
)
_FILTER_LABEL = "filter"
_FILTER_PLACEHOLDER = "type to filter"
_EMPTY_MESSAGE = "No matches"


@dataclass(frozen=True, slots=True)
class _State:
    cursor: int
    files: tuple[str, ...]
    all_files: tuple[str, ...]
    query: str
    path: str | None
    confirm: bool


@dataclass(frozen=True, slots=True)
class _Options:
    type: FileType
    message: str
    starting_path: str | None
    default: str | None
    max_per_page: int
    filter: Callable[[str], bool | Effect[bool, Never, PromptEnvironment]]
    theme: ThemeOptions | None


def _current_path(path: str | None, opts: _Options) -> Effect[str, Never, FileSystem]:
    if path is not None:
        return succeed(path)
    starting = opts.starting_path
    if starting is not None:

        def check(exists: bool) -> Effect[str]:
            return (
                succeed(starting)
                if exists
                else die(RuntimeError(f"The provided starting path '{starting}' does not exist"))
            )

        return FileSystem().flat_map(lambda fs: fs.exists(starting).or_die().flat_map(check))
    return succeed(os.getcwd())


def _file_list(directory: str, opts: _Options) -> Effect[tuple[str, ...], Never, PromptEnvironment]:
    def body():
        fs = yield from FileSystem()
        path = yield from Path()
        names = yield from fs.read_directory(directory).or_die()
        files = ["..", *names]

        def keep(file: str) -> Effect[bool, Never, PromptEnvironment]:
            def check():
                result = opts.filter(file)
                user = (yield from result) if isinstance(result, Effect) else result
                if opts.type != "directory":
                    return user
                info = yield from fs.stat(path.join(directory, file)).or_die()
                return user and info.type == "Directory"

            return gen(check)

        kept = yield from for_each(files, keep, concurrency="unbounded")
        return tuple(file for file, ok in zip(files, kept, strict=True) if ok)

    return gen(body)


def _filter_files(files: tuple[str, ...], query: str) -> tuple[str, ...]:
    if not query:
        return files
    needle = query.lower()
    return tuple(file for file in files if needle in file.lower())


def _update(state: _State, query: str) -> _State:
    files = _filter_files(state.all_files, query)
    if not files:
        return replace(state, query=query, files=files, cursor=0)
    selected = state.files[state.cursor] if state.cursor < len(state.files) else None
    cursor = files.index(selected) if selected in files else 0
    return replace(state, query=query, files=files, cursor=cursor)


def _render_filter(state: _State, theme: Theme, plain: bool) -> str:
    if not state.query:
        value = (
            _FILTER_PLACEHOLDER
            if plain
            else ansi.annotate(theme.colors, _FILTER_PLACEHOLDER, theme.muted_color)
        )
    else:
        value = (
            state.query
            if plain
            else ansi.annotate(theme.colors, state.query, ansi.underlined, theme.primary_color)
        )
    return f"[{_FILTER_LABEL}: {value}]"


def _render_files(state: _State, theme: Theme, opts: _Options, plain: bool) -> str:
    files = state.files
    if not files:
        return (
            _EMPTY_MESSAGE
            if plain
            else ansi.annotate(theme.colors, _EMPTY_MESSAGE, theme.muted_color)
        )
    window = entries_to_display(state.cursor, len(files), opts.max_per_page)
    lines: list[str] = []
    for index in range(window.start, window.end):
        selected = state.cursor == index
        paging = render_paging_prefix(
            theme,
            index == window.start and window.start > 0,
            index == window.end - 1 and window.end < len(files),
        )
        if selected:
            pointer = (
                theme.pointer
                if plain
                else annotate_symbol(theme, theme.pointer, theme.primary_color)
            )
            prefix = pointer + paging
        else:
            prefix = paging + " " * len(theme.pointer)
        name = files[index]
        if not plain and selected:
            name = ansi.annotate(theme.colors, name, ansi.underlined, theme.primary_color)
        lines.append(prefix + name)
    return "\n".join(lines)


class _FilePrompt:
    def __init__(self, opts: _Options) -> None:
        self.opts = opts

    def initial(self) -> Effect[_State, Never, PromptEnvironment]:
        opts = self.opts

        def body():
            current = yield from _current_path(None, opts)
            path = yield from Path()
            default = None if opts.default is None else path.resolve(current, opts.default)
            directory = current if default is None else path.dirname(default)
            files = yield from _file_list(directory, opts)
            cursor = 0
            if default is not None:
                name = path.basename(default)
                cursor = files.index(name) if name in files else 0
            start = None if default is None else path.dirname(default)
            return _State(cursor, files, files, "", start, False)

        return gen(body)

    def _resolved(self, state: _State) -> Effect[str, Never, PromptEnvironment]:
        def body():
            path = yield from Path()
            current = yield from _current_path(state.path, self.opts)
            if state.cursor >= len(state.files):
                return current
            return path.resolve(current, state.files[state.cursor])

        return gen(body)

    def _filter_prompt(self, state: _State, leading: str, trailing: str, figures: Theme) -> str:
        text = _render_filter(state, figures, False)
        return render_prompt(text, self.opts.message, leading, trailing, figures)

    def _frame(self, state: _State, figures: Theme) -> Effect[str, Never, PromptEnvironment]:
        def body():
            target = yield from self._resolved(state)
            line = separate_symbol(figures.pointer_small, target)
            target_line = ansi.annotate(figures.colors, line, figures.muted_color)
            if state.confirm:
                leading, trailing = active_symbols(figures)
                confirm = ansi.annotate(figures.colors, "(Y/n)", figures.muted_color)
                output = render_prompt(confirm, CONFIRM_MESSAGE, leading, trailing, figures)
                return ansi.cursor_hide + output + "\n" + target_line
            output = self._filter_prompt(state, *submitted_symbols(figures), figures)
            files = _render_files(state, figures, self.opts, False)
            return ansi.cursor_hide + output + "\n" + target_line + "\n" + files

        return gen(body)

    def render(
        self, state: _State, action: Action[_State, str]
    ) -> Effect[str, Never, PromptEnvironment]:
        def body():
            figures = yield from get_theme(self.opts.theme)
            match action:
                case Beep():
                    return ansi.beep
                case NextFrame():
                    return (yield from self._frame(action.state, figures))
                case Submit():
                    output = self._filter_prompt(state, *submitted_symbols(figures), figures)
                    value = ansi.annotate(figures.colors, action.value, figures.submitted_color)
                    return output + " " + value + "\n"

        return gen(body)

    def _move(self, state: _State, step: int) -> Effect[Action[_State, str]]:
        if not state.files:
            return succeed(Beep())
        cursor = (state.cursor + step) % len(state.files)
        return succeed(NextFrame(replace(state, cursor=cursor)))

    def _typed(self, text: str, state: _State) -> Effect[Action[_State, str]]:
        if state.confirm or not text:
            return succeed(Beep())
        return succeed(NextFrame(_update(state, state.query + text)))

    def _open(self, state: _State) -> Effect[Action[_State, str], Never, PromptEnvironment]:
        def body():
            target = yield from self._resolved(state)
            files = yield from _file_list(target, self.opts)
            return NextFrame(_State(0, files, files, "", target, False))

        return gen(body)

    def _select(self, state: _State) -> Effect[Action[_State, str], Never, PromptEnvironment]:
        opts = self.opts

        def body():
            if not state.files:
                return Beep()
            fs = yield from FileSystem()
            target = yield from self._resolved(state)
            info = yield from fs.stat(target).or_die()
            if info.type != "Directory":
                return Submit(target)
            files = yield from _file_list(target, opts)
            if opts.type in ("directory", "either"):
                if all(f == ".." for f in files):
                    return Submit(target)
                return NextFrame(replace(state, confirm=True))
            return NextFrame(_State(0, files, files, "", target, False))

        return gen(body)

    def _ctrl(self, input: UserInput, state: _State) -> Effect[Action[_State, str]]:
        match input.key.name:
            case "u":
                return succeed(Beep() if state.confirm else NextFrame(_update(state, "")))
            case "p" | "k":
                return self._move(state, -1)
            case "n":
                return self._move(state, 1)
            case _:
                return succeed(Beep())

    def process(  # noqa: PLR0911 - one return per key
        self, input: UserInput, state: _State
    ) -> Effect[Action[_State, str], Never, PromptEnvironment]:
        if input.key.ctrl:
            return self._ctrl(input, state)
        match input.key.name:
            case "up":
                return self._move(state, -1)
            case "down" | "tab":
                return self._move(state, 1)
            case "backspace":
                if state.confirm or not state.query:
                    return succeed(Beep())
                return succeed(NextFrame(_update(state, state.query[:-1])))
            case "enter" | "return":
                return self._select(state)
            case "y" | "t" if state.confirm:
                return self._open(state)
            case "n" | "f" if state.confirm:
                return self._resolved(state).map(Submit)
            case _:
                return self._typed(input.input or "", state)

    def clear(
        self, state: _State, action: Action[_State, str]
    ) -> Effect[str, Never, PromptEnvironment]:
        def body():
            columns = yield from terminal_columns()
            figures = yield from get_theme(self.opts.theme)
            target = yield from self._resolved(state)
            target_line = separate_symbol(figures.pointer_small, target)
            if state.confirm:
                output = render_prompt(
                    "(Y/n)",
                    CONFIRM_MESSAGE,
                    figures.prefix,
                    figures.pointer_small,
                    figures,
                    plain=True,
                )
                text = f"{output}\n{target_line}"
            else:
                filter_text = _render_filter(state, figures, True)
                output = render_prompt(
                    filter_text,
                    self.opts.message,
                    figures.tick,
                    figures.ellipsis,
                    figures,
                    plain=True,
                )
                files = _render_files(state, figures, self.opts, True)
                text = f"{output}\n{target_line}\n{files}"
            return erase_text(text, columns) + reset_current_line()

        return gen(body)


def file(
    *,
    type: FileType = "file",
    message: str = "Choose a file",
    starting_path: str | None = None,
    default: str | None = None,
    max_per_page: int = 10,
    filter: Callable[[str], bool | Effect[bool, Never, PromptEnvironment]] = lambda _: True,
    theme: ThemeOptions | None = None,
) -> Prompt[str]:
    """A path chosen by browsing: typing filters the listing, Enter opens a
    directory or takes a file. With ``type="directory"`` or ``"either"`` a
    directory with contents asks whether to open it (``y``) or take it
    (``n``)."""
    handlers = _FilePrompt(
        _Options(type, message, starting_path, default, max_per_page, filter, theme)
    )
    return custom(handlers.initial(), Handlers(handlers.render, handlers.process, handlers.clear))
