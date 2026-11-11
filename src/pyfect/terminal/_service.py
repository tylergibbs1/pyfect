"""The ``Terminal`` service and its input events."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Never, Self

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._service_copy import replaced
from pyfect.context import Tag
from pyfect.errors import Done, TaggedError
from pyfect.platform_error import PlatformError
from pyfect.queue import Dequeue
from pyfect.scope import Scope


@dataclass(frozen=True, slots=True)
class Key:
    """A key pressed: its name (``"a"``, ``"return"``, ``"up"``, ``""``
    for punctuation) and the modifiers held."""

    name: str
    ctrl: bool = False
    meta: bool = False
    shift: bool = False


@dataclass(frozen=True, slots=True)
class Size:
    """Terminal dimensions in character cells."""

    columns: int
    rows: int


@dataclass(frozen=True, slots=True)
class UserInput:
    """One key press: the character it typed (``None`` for an escape
    sequence such as an arrow key) and the key."""

    input: str | None
    key: Key


@dataclass(eq=False)
class QuitError(TaggedError):
    """The user quit a prompt (usually with Ctrl+C), or input ended."""

    @property
    def message(self) -> str:
        return "QuitError"


class TerminalService:
    """Effect's ``Terminal``; the constructor is ``Terminal.make``."""

    __slots__ = ("_columns", "_display", "_read_input", "_read_line", "_rows", "_size")

    def __replace__(self, **changes: Any) -> Self:
        """A copy with ``changes`` to the constructor's arguments (``copy.replace``)."""
        return replaced(self, changes)

    def __init__(
        self,
        *,
        columns: Effect[int],
        rows: Effect[int],
        size: Effect[Dequeue[Size, Done], Never, Scope],
        read_input: Effect[Dequeue[UserInput, Done], Never, Scope],
        read_line: Effect[str, QuitError],
        display: Callable[[str], Effect[None, PlatformError]],
    ) -> None:
        for name, value in (
            ("columns", columns),
            ("rows", rows),
            ("size", size),
            ("read_input", read_input),
            ("read_line", read_line),
        ):
            require_effect(value, name)
        self._columns = columns
        self._rows = rows
        self._size = size
        self._read_input = read_input
        self._read_line = read_line
        self._display = display

    @property
    def columns(self) -> Effect[int]:
        """The terminal's width in character cells. Never fails."""
        return self._columns

    @property
    def rows(self) -> Effect[int]:
        """The terminal's height in character cells. Never fails."""
        return self._rows

    @property
    def size(self) -> Effect[Dequeue[Size, Done], Never, Scope]:
        """A queue holding the current ``Size``, then each resize until the
        scope closes, keeping only the latest. Never fails."""
        return self._size

    @property
    def read_input(self) -> Effect[Dequeue[UserInput, Done], Never, Scope]:
        """A queue of key presses from standard input for as long as the
        scope is open; it ends when input ends or the user quits. Never
        fails."""
        return self._read_input

    @property
    def read_line(self) -> Effect[str, QuitError]:
        """Reads one line from standard input, without its line break.
        Fails with ``QuitError`` when input ends first."""
        return self._read_line

    def display(self, text: str) -> Effect[None, PlatformError]:
        """Writes ``text`` to standard output. Fails with a
        ``PlatformError`` when the write does."""
        return self._display(text)


class Terminal(Tag[TerminalService]):
    """The terminal a program talks to."""


def default_should_quit(event: UserInput) -> bool:
    """Escape, Ctrl+C and Ctrl+D quit, as in Effect's Node terminal."""
    key = event.key
    return key.name == "escape" or (key.ctrl and key.name in ("c", "d"))
