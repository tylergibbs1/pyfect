"""The ``Terminal`` service and its input events."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Never

from pyfect._core import Effect
from pyfect._effect_args import require_effect
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


@dataclass(frozen=True, slots=True, kw_only=True)
class TerminalService:
    """Effect's ``Terminal``; the constructor is ``Terminal.make``.

    ``read_input`` gives a queue of key presses for as long as its scope is
    open; the queue ends when input ends or the user quits.
    ``read_line`` reads one line without its line break."""

    columns: Effect[int]
    rows: Effect[int]
    read_input: Effect[Dequeue[UserInput, Done], Never, Scope]
    read_line: Effect[str, QuitError]
    display: Callable[[str], Effect[None, PlatformError]]

    def __post_init__(self) -> None:
        for name in ("columns", "rows", "read_input", "read_line"):
            require_effect(getattr(self, name), name)


class Terminal(Tag[TerminalService]):
    """The terminal a program talks to."""


def default_should_quit(event: UserInput) -> bool:
    """Escape, Ctrl+C and Ctrl+D quit, as in Effect's Node terminal."""
    key = event.key
    return key.name == "escape" or (key.ctrl and key.name in ("c", "d"))
