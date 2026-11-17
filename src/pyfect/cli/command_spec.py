"""A command path as data, for documentation tools (Effect's ``CommandSpec``).

``resolve(app, ["app", "db", "push"])`` gives the ``Spec`` of ``push``: its
description, examples, the flags it accepts (local, inherited and global, in
the order help lists them, hidden ones included), its arguments and its
subcommands (unlisted ones included). It reads the tree only: no handler,
prompt, ``Config`` or effectful default runs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from pyfect.cli import global_flag as global_flag_
from pyfect.cli import param as p
from pyfect.cli import primitive as primitive_
from pyfect.cli._command import Command
from pyfect.cli._settings import Action, GlobalFlag
from pyfect.cli.help_doc import ExampleDoc
from pyfect.cli.param import Fallback
from pyfect.cli.primitive import PathType
from pyfect.context import Context

type PlainTypeTag = Literal[
    "Boolean",
    "String",
    "Int",
    "Finite",
    "Date",
    "Redacted",
    "FileText",
    "FileParse",
    "FileSchema",
    "KeyValuePair",
    "Never",
]


@dataclass(frozen=True, slots=True)
class PlainType:
    tag: PlainTypeTag


@dataclass(frozen=True, slots=True)
class ChoiceType:
    values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PathValueType:
    path_type: PathType


type Type = PlainType | ChoiceType | PathValueType
"""What a flag or argument takes, without collapsing kinds as help's type name does."""


@dataclass(frozen=True, slots=True)
class Local:
    """Declared on the command itself."""


@dataclass(frozen=True, slots=True)
class Inherited:
    """Shared by an ancestor through ``with_shared_flags``."""

    declared_by: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Global:
    """A global flag: a built-in (``declared_by`` ``None``) or one declared on the path."""

    declared_by: tuple[str, ...] | None
    kind: Literal["Action", "Setting"]


type Scope = Local | Inherited | Global


@dataclass(frozen=True, slots=True)
class VariadicBounds:
    min: int | None
    max: int | None


@dataclass(frozen=True, slots=True)
class Argument:
    name: str
    description: str | None
    type: Type
    type_name: str
    """The generic type name (``"integer"``), as help shows it without a metavar."""
    metavar: str | None
    required: bool
    """Parsing fails when this entry is absent and no fallback on its own path supplies
    a value. A ``Config`` or prompt fallback does not clear it; a sibling alternative of
    ``or_else`` is not taken into account."""
    fallbacks: tuple[Fallback, ...]
    """The fallbacks on this entry's own path, in the order the parser tries them."""
    variadic: VariadicBounds | None
    annotations: Context[Any]


@dataclass(frozen=True, slots=True)
class Flag(Argument):
    aliases: tuple[str, ...]
    """Alias names without dashes."""
    hidden: bool
    optional_value: str | None
    negation: str | None
    """The long name that sets a boolean flag to false."""
    scope: Scope


@dataclass(frozen=True, slots=True)
class Subcommand:
    name: str
    alias: str | None
    group: str | None
    unlisted: bool
    short_description: str | None
    description: str | None


@dataclass(frozen=True, slots=True)
class Spec:
    path: tuple[str, ...]
    name: str
    alias: str | None
    description: str | None
    short_description: str | None
    unlisted: bool
    examples: tuple[ExampleDoc, ...]
    """The examples for ``path``, not for the bare command name."""
    annotations: Context[Any]
    flags: tuple[Flag, ...]
    """Local flags, then those shared by ancestors from the root down, then global
    flags with the built-ins first."""
    arguments: tuple[Argument, ...]
    subcommands: tuple[Subcommand, ...]


def resolve(
    command: Command[Any, Any, Any, Any],
    path: Sequence[str],
    *,
    built_ins: Sequence[GlobalFlag] | None = None,
) -> Spec | None:
    """The ``Spec`` of the command at ``path`` (canonical names, the root's first), or
    ``None`` when no command is there. ``built_ins`` are the built-in global flags to
    report (``global_flag.built_ins`` by default; pass ``CliConfig``'s when it differs)."""
    path = tuple(path)
    lineage = _lineage(command, path)
    if lineage is None:
        return None
    current = lineage[-1]
    state = current.state
    flags: list[Flag] = []
    seen: set[str] = set()

    def add_flags(params: Sequence[p.Param[Any]], scope: Scope) -> None:
        for param in params:
            for entry in _entries(param):
                if entry.single.kind != p.FLAG:
                    continue
                # As in help, a nearer scope's name wins over an inherited one; globals
                # are deduplicated by identity only, since their aliases still route.
                if isinstance(scope, Inherited) and entry.single.name in seen:
                    continue
                seen.add(entry.single.name)
                flags.append(_flag(entry, scope))

    add_flags(state.config.flags, Local())
    for index, ancestor in enumerate(lineage[:-1]):
        add_flags(ancestor.state.context_config.flags, Inherited(path[: index + 1]))
    seen_globals: list[GlobalFlag] = []

    def add_globals(globals_: Sequence[GlobalFlag], declared_by: tuple[str, ...] | None) -> None:
        for global_flag in globals_:
            if any(global_flag is known for known in seen_globals):
                continue
            seen_globals.append(global_flag)
            kind: Literal["Action", "Setting"] = (
                "Action" if isinstance(global_flag, Action) else "Setting"
            )
            add_flags([global_flag.flag.param], Global(declared_by, kind))

    add_globals(global_flag_.built_ins if built_ins is None else built_ins, None)
    for index, ancestor in enumerate(lineage):
        add_globals(ancestor.state.global_flags, path[: index + 1])
    arguments = [
        _argument(entry)
        for param in state.config.arguments
        for entry in _entries(param)
        if entry.single.kind == p.ARGUMENT
    ]
    subcommands = [
        Subcommand(
            sub.name, sub.alias, group.group, sub.unlisted, sub.short_description, sub.description
        )
        for group in state.subcommands
        for sub in group.commands
    ]
    return Spec(
        path=path,
        name=state.name,
        alias=state.alias,
        description=state.description,
        short_description=state.short_description,
        unlisted=state.unlisted,
        examples=state.resolve_examples(path),
        annotations=state.annotations,
        flags=tuple(flags),
        arguments=tuple(arguments),
        subcommands=tuple(subcommands),
    )


def _lineage(
    root: Command[Any, Any, Any, Any], path: tuple[str, ...]
) -> list[Command[Any, Any, Any, Any]] | None:
    if not path or path[0] != root.name:
        return None
    lineage = [root]
    for name in path[1:]:
        found = next(
            (
                sub
                for group in lineage[-1].subcommands
                for sub in group.commands
                if sub.name == name
            ),
            None,
        )
        if found is None:
            return None
        lineage.append(found)
    return lineage


@dataclass(frozen=True, slots=True)
class _Entry:
    single: p.Single[Any]
    required: bool
    fallbacks: tuple[Fallback, ...]
    variadic: VariadicBounds | None


@dataclass(frozen=True, slots=True)
class _PathState:
    omittable: bool = False
    fallbacks: tuple[Fallback, ...] = ()
    """Outermost first; reversed into the order they are tried."""
    variadic: VariadicBounds | None = None


def _entries(param: p.Param[Any]) -> list[_Entry]:
    """Each ``Single`` of ``param`` with the wrappers on its own path."""
    entries: list[_Entry] = []
    _visit(param, _PathState(), entries)
    return entries


def _visit(node: p.Param[Any], state: _PathState, entries: list[_Entry]) -> None:
    """Adds each ``Single`` under ``node`` to ``entries``."""
    if isinstance(node, p.Single):
        single: p.Single[Any] = node
        fallbacks = tuple(reversed(state.fallbacks))
        entries.append(_Entry(single, not state.omittable, fallbacks, state.variadic))
    elif isinstance(node, p.Mapped):
        _visit(cast("p.Mapped[Any, Any]", node).param, state, entries)
    elif isinstance(node, p.Transformed):
        transformed = cast("p.Transformed[Any, Any]", node)
        fallback = transformed.fallback
        # Per-item fallbacks inside a variadic do not satisfy its minimum.
        inner = (
            state
            if fallback is None or state.variadic is not None
            else _PathState(state.omittable, (*state.fallbacks, fallback), state.variadic)
        )
        _visit(transformed.param, inner, entries)
        for alternative in transformed.alternatives:
            _visit(alternative(), inner, entries)
    elif isinstance(node, p.Optional):
        omitted = state if state.variadic is not None else _PathState(True, state.fallbacks)
        _visit(node.param, omitted, entries)
    elif isinstance(node, p.Variadic):
        variadic = cast("p.Variadic[Any]", node)
        if state.variadic is not None:
            _visit(variadic.param, state, entries)
            return
        minimum = variadic.min
        bounds = VariadicBounds(minimum, variadic.max)
        omittable = state.omittable or minimum is None or minimum <= 0
        _visit(variadic.param, _PathState(omittable, state.fallbacks, bounds), entries)


def _type(primitive: primitive_.Primitive[Any]) -> Type:
    match primitive.tag:
        case "Choice":
            return ChoiceType(primitive.choice_keys or ())
        case "Path":
            return PathValueType(primitive.path_type or "either")
        case (
            "Boolean"
            | "Int"
            | "Finite"
            | "Date"
            | "Redacted"
            | "FileText"
            | "FileParse"
            | "FileSchema"
            | "KeyValuePair"
            | "Never"
        ) as tag:
            return PlainType(tag)
        case _:
            return PlainType("String")


def _argument(entry: _Entry) -> Argument:
    single = entry.single
    return Argument(
        name=single.name,
        description=single.description,
        type=_type(single.primitive),
        type_name=primitive_.type_name(single.primitive),
        metavar=single.type_name,
        required=entry.required,
        fallbacks=entry.fallbacks,
        variadic=entry.variadic,
        annotations=single.annotations,
    )


def _flag(entry: _Entry, scope: Scope) -> Flag:
    single = entry.single
    negation = (
        (single.negation or f"no-{single.name}")
        if primitive_.is_boolean(single.primitive) and single.negation is not False
        else None
    )
    return Flag(
        name=single.name,
        description=single.description,
        type=_type(single.primitive),
        type_name=primitive_.type_name(single.primitive),
        metavar=single.type_name,
        # The runner parses an Action only when it is on the command line.
        required=entry.required and not (isinstance(scope, Global) and scope.kind == "Action"),
        fallbacks=entry.fallbacks,
        variadic=entry.variadic,
        annotations=single.annotations,
        aliases=single.aliases,
        hidden=single.hidden,
        optional_value=single.optional_value,
        negation=negation,
        scope=scope,
    )


__all__ = [
    "Argument",
    "ChoiceType",
    "Fallback",
    "Flag",
    "Global",
    "Inherited",
    "Local",
    "PathValueType",
    "PlainType",
    "PlainTypeTag",
    "Scope",
    "Spec",
    "Subcommand",
    "Type",
    "VariadicBounds",
    "resolve",
]
