"""What a completion script describes (Effect's ``Completions`` descriptor
types and internal ``completions/descriptor``): each command's visible
flags, arguments and subcommands, read off a ``Command``."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from pyfect.cli._command import Command
from pyfect.cli.param import ARGUMENT, FLAG, Param, Single
from pyfect.cli.primitive import PathType


@dataclass(frozen=True, slots=True)
class Choice:
    values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PathKind:
    path_type: PathType


type ScalarTag = Literal["Boolean", "String", "Int", "Finite", "Date"]
type FlagType = ScalarTag | Choice | PathKind
type ArgumentType = Literal["String", "Int", "Finite", "Date"] | Choice | PathKind


@dataclass(frozen=True, slots=True)
class FlagDescriptor:
    name: str
    aliases: tuple[str, ...]
    description: str | None
    type: FlagType
    optional_value: bool = False
    negation: str | Literal[False] | None = None


@dataclass(frozen=True, slots=True)
class ArgumentDescriptor:
    name: str
    description: str | None
    required: bool
    variadic: bool
    type: ArgumentType


@dataclass(frozen=True, slots=True)
class CommandDescriptor:
    name: str
    description: str | None
    flags: tuple[FlagDescriptor, ...] = ()
    arguments: tuple[ArgumentDescriptor, ...] = ()
    subcommands: tuple[CommandDescriptor, ...] = field(default=())


_FILE_TAGS = ("FileText", "FileParse", "FileSchema")


def _value_type(single: Single[Any]) -> Choice | PathKind | ScalarTag:  # noqa: PLR0911 - one return per tag
    primitive = single.primitive
    match primitive.tag:
        case "Boolean":
            return "Boolean"
        case "Int":
            return "Int"
        case "Finite":
            return "Finite"
        case "Date":
            return "Date"
        case "Choice":
            return Choice(primitive.choice_keys or ())
        case "Path":
            return PathKind(primitive.path_type or "either")
        case tag if tag in _FILE_TAGS:
            return PathKind("file")
        case _:
            return "String"


def _argument_type(single: Single[Any]) -> ArgumentType:
    kind = _value_type(single)
    return "String" if kind == "Boolean" else kind


def from_command(
    command: Command[Any, Any, Any, Any], inherited: Sequence[Param[Any]] = ()
) -> CommandDescriptor:
    """The descriptor of ``command`` and its listed subcommands; local
    flags come first, then the shared flags of its ancestors."""
    state = command.state
    own = state.config.flags
    flags: list[FlagDescriptor] = []
    seen: set[str] = set()
    for index, flag in enumerate((*own, *inherited)):
        for single in flag.singles():
            if single.kind != FLAG or single.hidden:
                continue
            if index >= len(own) and single.name in seen:
                continue
            seen.add(single.name)
            flags.append(
                FlagDescriptor(
                    name=single.name,
                    aliases=single.aliases,
                    description=single.description,
                    type=_value_type(single),
                    optional_value=single.optional_value is not None,
                    negation=single.negation,
                )
            )
    arguments: list[ArgumentDescriptor] = []
    for arg in state.config.arguments:
        metadata = arg.metadata()
        for single in arg.singles():
            if single.kind != ARGUMENT:
                continue
            arguments.append(
                ArgumentDescriptor(
                    name=single.name,
                    description=single.description,
                    required=not metadata.is_optional,
                    variadic=metadata.is_variadic,
                    type=_argument_type(single),
                )
            )
    shared = (*inherited, *state.context_config.flags)
    subcommands: list[CommandDescriptor] = []
    for group in command.subcommands:
        for sub in group.commands:
            if sub.unlisted:
                continue
            descriptor = from_command(sub, shared)
            subcommands.append(descriptor)
            if sub.alias and sub.alias != sub.name:
                subcommands.append(replace(descriptor, name=sub.alias))
    return CommandDescriptor(
        name=command.name,
        description=(
            command.description if command.short_description is None else command.short_description
        ),
        flags=tuple(flags),
        arguments=tuple(arguments),
        subcommands=tuple(subcommands),
    )


def takes_separate_value(flag: FlagDescriptor) -> bool:
    return flag.type != "Boolean" and not flag.optional_value


def negated_name(flag: FlagDescriptor) -> str | None:
    if flag.type != "Boolean" or flag.negation is False:
        return None
    return flag.negation if flag.negation is not None else f"no-{flag.name}"


def long_forms(flag: FlagDescriptor) -> list[str]:
    """``--name``, each alias with its dashes, and the negation."""
    forms = [f"--{flag.name}"]
    forms += [f"-{alias}" if len(alias) == 1 else f"--{alias}" for alias in flag.aliases]
    negation = negated_name(flag)
    if negation is not None:
        forms.append(f"--{negation}")
    return forms


__all__ = [
    "ArgumentDescriptor",
    "ArgumentType",
    "Choice",
    "CommandDescriptor",
    "FlagDescriptor",
    "FlagType",
    "PathKind",
    "from_command",
    "long_forms",
    "negated_name",
    "takes_separate_value",
]
