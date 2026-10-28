"""The structured help of a command (Effect's ``HelpDoc``), which a
``Formatter`` renders as text."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pyfect.context import Context


@dataclass(frozen=True, slots=True)
class FlagDoc:
    name: str
    aliases: tuple[str, ...]
    """With their dashes: ``("-f",)``."""
    type: str
    description: str | None
    required: bool


@dataclass(frozen=True, slots=True)
class ArgDoc:
    name: str
    type: str
    description: str | None
    required: bool
    variadic: bool


@dataclass(frozen=True, slots=True)
class SubcommandDoc:
    name: str
    alias: str | None
    short_description: str | None
    description: str


@dataclass(frozen=True, slots=True)
class SubcommandGroupDoc:
    group: str | None
    commands: tuple[SubcommandDoc, ...]


@dataclass(frozen=True, slots=True)
class ExampleDoc:
    command: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class HelpDoc:
    description: str
    usage: str
    flags: tuple[FlagDoc, ...]
    annotations: Context[Any] = field(default_factory=Context[Any])
    global_flags: tuple[FlagDoc, ...] = ()
    args: tuple[ArgDoc, ...] = ()
    subcommands: tuple[SubcommandGroupDoc, ...] = ()
    examples: tuple[ExampleDoc, ...] = ()


__all__ = ["ArgDoc", "ExampleDoc", "FlagDoc", "HelpDoc", "SubcommandDoc", "SubcommandGroupDoc"]
