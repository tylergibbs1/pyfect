"""``setMyCommands`` for a group's command definitions."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pyfect.chat.chat_interaction import Command, Group

_NAME = re.compile(r"[a-z0-9_]{1,32}")
_DESCRIPTION_LENGTH = 256


@dataclass(frozen=True)
class Invalid:
    """The command ids Telegram can't take."""

    ids: tuple[str, ...]


def bot_commands(group: Group[str]) -> list[dict[str, str]] | Invalid:
    """The ``commands`` of ``setMyCommands`` for a group's commands, or the
    ids Telegram can't take: its names are
    ``[a-z0-9_]{1,32}``. A command's ``argument`` has no Telegram
    counterpart and is appended to its description, cut to 256 characters.
    """
    commands: list[dict[str, str]] = []
    invalid: list[str] = []
    for definition in group.definitions:
        if not isinstance(definition, Command):
            continue
        if _NAME.fullmatch(definition.id) is None:
            invalid.append(definition.id)
            continue
        argument = definition.argument
        suffix = (
            ""
            if argument is None
            else f" <{argument.name}{'' if argument.required else '?'}>: {argument.description}"
        )
        description = (definition.description + suffix)[:_DESCRIPTION_LENGTH]
        commands.append({"command": definition.id, "description": description})
    return Invalid(tuple(invalid)) if invalid else commands
