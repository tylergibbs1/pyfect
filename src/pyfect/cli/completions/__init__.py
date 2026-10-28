"""Shell completion scripts for a command tree (Effect's ``Completions``):
``generate(name, shell, descriptor)`` with ``from_command(command)`` gives
the script ``--completions <shell>`` prints."""

from __future__ import annotations

from typing import Literal

from pyfect.cli.completions import bash, fish, powershell, zsh
from pyfect.cli.completions._descriptor import (
    ArgumentDescriptor,
    ArgumentType,
    Choice,
    CommandDescriptor,
    FlagDescriptor,
    FlagType,
    PathKind,
    from_command,
)

type Shell = Literal["bash", "zsh", "fish", "powershell"]

_GENERATORS = {
    "bash": bash.generate,
    "zsh": zsh.generate,
    "fish": fish.generate,
    "powershell": powershell.generate,
}


def generate(executable: str, shell: Shell, descriptor: CommandDescriptor) -> str:
    return _GENERATORS[shell](executable, descriptor)


__all__ = [
    "ArgumentDescriptor",
    "ArgumentType",
    "Choice",
    "CommandDescriptor",
    "FlagDescriptor",
    "FlagType",
    "PathKind",
    "Shell",
    "bash",
    "fish",
    "from_command",
    "generate",
    "powershell",
    "zsh",
]
