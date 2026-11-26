"""What a completion script describes (Effect's ``Completions`` descriptor
types and internal ``completions/descriptor``): each command's visible
flags, arguments and subcommands, read off a ``Command``."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal, cast

from pyfect.cli._command import Command
from pyfect.cli.param import (
    ARGUMENT,
    FLAG,
    Mapped,
    Optional,
    Param,
    Single,
    Transformed,
    Variadic,
)
from pyfect.cli.primitive import PathType


@dataclass(frozen=True, slots=True)
class Choice:
    """A completion value type: one of a fixed set of strings."""

    values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PathKind:
    """A completion value type: a path to a file, a directory or either."""

    path_type: PathType


type ScalarTag = Literal["Boolean", "String", "Int", "Finite", "Date"]
type FlagType = ScalarTag | Choice | PathKind
type ArgumentType = Literal["String", "Int", "Finite", "Date"] | Choice | PathKind


@dataclass(frozen=True, slots=True)
class FlagDescriptor:
    """A flag as a completion script sees it: names, value type and whether it repeats."""

    name: str
    aliases: tuple[str, ...]
    description: str | None
    type: FlagType
    optional_value: bool = False
    negation: str | Literal[False] | None = None
    repeatable: bool = False
    """Whether the flag can be given more than once, so completion keeps offering it after
    it is used."""


@dataclass(frozen=True, slots=True)
class ArgumentDescriptor:
    """An argument as a completion script sees it: name, type and whether it repeats."""

    name: str
    description: str | None
    required: bool
    variadic: bool
    type: ArgumentType


@dataclass(frozen=True, slots=True)
class CommandDescriptor:
    """A command as a completion script sees it: its flags, arguments and subcommands."""

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


def _repeatable_singles(
    param: Param[Any], repeatable: bool | None = None
) -> list[tuple[Single[Any], bool]]:
    """Each single flag with whether it can be repeated. The outermost variadic decides, and
    each ``or_else`` alternative is resolved on its own."""
    if isinstance(param, Single):
        return [(param, repeatable is True)]
    if isinstance(param, Variadic):
        variadic = cast("Variadic[Any]", param)
        outermost = repeatable if repeatable is not None else not _at_most_once(variadic)
        return _repeatable_singles(variadic.param, outermost)
    if isinstance(param, (Mapped, Optional, Transformed)):
        inner: Param[Any] = cast(
            "Mapped[Any, Any] | Optional[Any] | Transformed[Any, Any]", param
        ).param
        alternatives = (
            cast("Transformed[Any, Any]", param).alternatives
            if isinstance(param, Transformed)
            else ()
        )
        return [
            pair
            for tree in (inner, *(alternative() for alternative in alternatives))
            for pair in _repeatable_singles(tree, repeatable)
        ]
    raise TypeError(f"completions do not know the param {type(param).__name__}")


def _at_most_once(param: Variadic[Any]) -> bool:
    return param.max is not None and param.max <= 1


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
        for single, repeatable in _repeatable_singles(flag):
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
                    repeatable=repeatable,
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
                    required=not metadata.is_optional
                    and (not metadata.is_variadic or (metadata.variadic_min or 0) > 0),
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
