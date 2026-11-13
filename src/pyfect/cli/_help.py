"""Help docs for a command path (Effect's internal ``buildHelpDoc`` and
``cli/internal/help``): usage, arguments, the command's flags, the
shared flags inherited from its ancestors, subcommands, examples and the
global flags in scope."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pyfect.cli import primitive as primitive_
from pyfect.cli._command import Command
from pyfect.cli._settings import GlobalFlag
from pyfect.cli.flag import Flag
from pyfect.cli.help_doc import ArgDoc, FlagDoc, HelpDoc, SubcommandDoc, SubcommandGroupDoc
from pyfect.cli.param import ParamMetadata, Single

type AnyCommand = Command[Any, Any, Any, Any]


def flag_of(global_flag: GlobalFlag) -> Flag[Any]:
    return global_flag.flag


def _type_name(single: Single[Any]) -> str:
    return single.type_name or primitive_.type_name(single.primitive)


def _with_choices(description: str | None, choices: tuple[str, ...] | None) -> str | None:
    if not choices:
        return description
    suffix = f"(choices: {', '.join(choices)})"
    return suffix if description is None else f"{description} {suffix}"


def to_flag_doc(single: Single[Any], metadata: ParamMetadata) -> FlagDoc:
    type_ = _type_name(single)
    return FlagDoc(
        name=single.name,
        aliases=tuple(f"-{a}" if len(a) == 1 else f"--{a}" for a in single.aliases),
        type=type_ if single.optional_value is None else f"[={type_}]",
        description=_with_choices(single.description, single.primitive.choice_keys),
        required=not primitive_.is_boolean(single.primitive) and not metadata.is_optional,
    )


def build_help_doc(command: AnyCommand, path: Sequence[str]) -> HelpDoc:
    state = command.state
    args = [
        ArgDoc(
            name=single.name,
            type=_type_name(single),
            description=single.description,
            required=not metadata.is_optional
            and (not metadata.is_variadic or (metadata.variadic_min or 0) > 0),
            variadic=metadata.is_variadic,
        )
        for arg in state.config.arguments
        for metadata in (arg.metadata(),)
        for single in arg.singles()
    ]
    usage = " ".join(path) if path else state.name
    if any(not sub.unlisted for group in state.subcommands for sub in group.commands):
        usage += " <subcommand>"
    usage += " [flags]"
    for arg_doc in args:
        name = f"<{arg_doc.name}...>" if arg_doc.variadic else f"<{arg_doc.name}>"
        usage += f" {name}" if arg_doc.required else f" [{name}]"
    flags = [
        to_flag_doc(single, flag.metadata())
        for flag in state.config.flags
        for single in flag.singles()
        if not single.hidden
    ]
    groups: list[SubcommandGroupDoc] = []
    for group in state.subcommands:
        visible = [sub for sub in group.commands if not sub.unlisted]
        if visible:
            groups.append(
                SubcommandGroupDoc(
                    group.group,
                    tuple(
                        SubcommandDoc(
                            sub.name, sub.alias, sub.short_description, sub.description or ""
                        )
                        for sub in visible
                    ),
                )
            )
    return HelpDoc(
        description=state.description or "",
        usage=usage,
        flags=tuple(flags),
        annotations=state.annotations,
        args=tuple(args),
        subcommands=tuple(groups),
        examples=state.resolve_examples(tuple(path)),
    )


def commands_for_path(command: AnyCommand, path: Sequence[str]) -> list[AnyCommand]:
    commands = [command]
    current = command
    for name in path[1:]:
        found = next(
            (sub for group in current.subcommands for sub in group.commands if sub.name == name),
            None,
        )
        if found is None:
            break
        commands.append(found)
        current = found
    return commands


def _dedupe(flags: Sequence[GlobalFlag]) -> tuple[GlobalFlag, ...]:
    return tuple(dict.fromkeys(flags))


def global_flags_for_path(
    command: AnyCommand, path: Sequence[str], built_ins: Sequence[GlobalFlag]
) -> tuple[GlobalFlag, ...]:
    declared = [flag for c in commands_for_path(command, path) for flag in c.state.global_flags]
    return _dedupe([*built_ins, *declared])


def global_flags_for_tree(
    command: AnyCommand, built_ins: Sequence[GlobalFlag]
) -> tuple[GlobalFlag, ...]:
    collected: list[GlobalFlag] = []
    _collect_global_flags(command, collected)
    return _dedupe([*built_ins, *_dedupe(collected)])


def _collect_global_flags(command: AnyCommand, collected: list[GlobalFlag]) -> None:
    collected.extend(command.state.global_flags)
    for group in command.subcommands:
        for sub in group.commands:
            _collect_global_flags(sub, collected)


def _inherited_flags(commands: Sequence[AnyCommand], current: Sequence[FlagDoc]) -> list[FlagDoc]:
    if len(commands) <= 1:
        return []
    seen = {flag.name for flag in current}
    inherited: list[FlagDoc] = []
    for ancestor in commands[:-1]:
        for flag in ancestor.state.context_config.flags:
            metadata = flag.metadata()
            for single in flag.singles():
                if single.name in seen or single.hidden:
                    continue
                seen.add(single.name)
                inherited.append(to_flag_doc(single, metadata))
    return inherited


def help_for_path(
    command: AnyCommand, path: Sequence[str], built_ins: Sequence[GlobalFlag]
) -> HelpDoc:
    commands = commands_for_path(command, path)
    base = build_help_doc(commands[-1], path)
    inherited = _inherited_flags(commands, base.flags)
    global_docs: list[FlagDoc] = []
    for global_flag in global_flags_for_path(command, path, built_ins):
        param = flag_of(global_flag).param
        metadata = param.metadata()
        for single in param.singles():
            if single.hidden:
                continue
            doc = to_flag_doc(single, metadata)
            global_docs.append(
                FlagDoc(doc.name, doc.aliases, doc.type, doc.description, required=False)
            )
    # Globals accumulate along the path, so the deepest declaring scope lists them all.
    scope_length = next(
        (i + 1 for i in range(len(commands) - 1, 0, -1) if commands[i].state.global_flags), 1
    )
    command_path = tuple(path)
    return HelpDoc(
        description=base.description,
        usage=base.usage,
        flags=base.flags,
        annotations=base.annotations,
        global_flags=tuple(global_docs),
        args=base.args,
        subcommands=base.subcommands,
        examples=base.examples,
        inherited_flags=tuple(inherited),
        global_flags_scope=command_path[:scope_length],
        command_path=command_path,
    )


__all__ = [
    "build_help_doc",
    "commands_for_path",
    "flag_of",
    "global_flags_for_path",
    "global_flags_for_tree",
    "help_for_path",
    "to_flag_doc",
]
