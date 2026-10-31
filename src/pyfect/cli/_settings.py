"""Setting global flags: a flag whose value the runner provides to the
handler as a service (Effect's ``GlobalFlag.Setting``), and the built-in
``--log-level``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from pyfect.cli.flag import Flag
from pyfect.context import Tag
from pyfect.effect import Effect
from pyfect.logger import LogLevel as Level

if TYPE_CHECKING:
    from pyfect.cli._command import Command


class Setting[A](Tag[A], base=True):
    """A global flag read in handlers as a service. Subclass it with the
    flag; ``yield from Region()`` reads the value::

        class Region(Setting[str | None]):
            flag = Flag.string("region").optional()

    ``Command.pipe(with_global_flags(Region))`` makes the command (and its
    subcommands) accept ``--region`` and provides ``Region``.
    """

    flag: ClassVar[Flag[Any]]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not isinstance(cls.__dict__.get("flag"), Flag):
            raise TypeError(f"Setting {cls.__qualname__} must define a 'flag'")


class LogLevel(Setting[Level | None]):
    """``--log-level``: the minimum log level for the handler, when given."""

    flag = (
        Flag.choice_with_value(
            "log-level",
            [
                ("all", Level.ALL),
                ("trace", Level.TRACE),
                ("debug", Level.DEBUG),
                ("info", Level.INFO),
                ("warn", Level.WARN),
                ("warning", Level.WARN),
                ("error", Level.ERROR),
                ("fatal", Level.FATAL),
                ("none", Level.NONE),
            ],
        )
        .optional()
        .with_description("Sets the minimum log level")
        .with_metavar("<all|trace|debug|info|warn|warning|error|fatal|none>")
    )


@dataclass(frozen=True, slots=True)
class HandlerContext:
    """What an action global flag's ``run`` is given besides the value."""

    command: Command[Any, Any, Any, Any]
    command_path: tuple[str, ...]
    version: str
    built_ins: tuple[GlobalFlag, ...]


@dataclass(frozen=True, eq=False, slots=True)
class Action[A]:
    """A global flag that does something instead of running the command
    (``--help``, ``--version``): when given, the runner calls ``run`` with
    its value and stops."""

    flag: Flag[A]
    run: Callable[[A, HandlerContext], Effect[None]]


type GlobalFlag = Action[Any] | type[Setting[Any]]

__all__ = ["Action", "GlobalFlag", "HandlerContext", "LogLevel", "Setting"]
