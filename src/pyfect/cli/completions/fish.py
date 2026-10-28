"""Fish completion scripts (Effect's internal ``completions/fish``): one
``complete`` line per subcommand, flag and typed argument, scoped by the
subcommand path."""

from __future__ import annotations

import re

from pyfect.cli.completions._descriptor import (
    ArgumentType,
    Choice,
    CommandDescriptor,
    FlagDescriptor,
    FlagType,
    PathKind,
    negated_name,
    takes_separate_value,
)

_UNSAFE_CHOICE = re.compile(r"[^A-Za-z0-9_.,/@%+-]")


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'")


def _escape_choice(text: str) -> str:
    return _escape(_UNSAFE_CHOICE.sub(lambda match: "\\" + match.group(), text))


def _subcommand_condition(parent: list[str], children: list[str]) -> str:
    if not parent:
        return "__fish_use_subcommand" if children else ""
    condition = "; and ".join(f"__fish_seen_subcommand_from {name}" for name in parent)
    if children:
        return f"{condition}; and not __fish_seen_subcommand_from {' '.join(children)}"
    return condition


def _contains_opt(flag: FlagDescriptor) -> str:
    args = [f"-s {alias}" for alias in flag.aliases if len(alias) == 1]
    args.append(flag.name)
    args += [alias for alias in flag.aliases if len(alias) > 1]
    negation = negated_name(flag)
    if negation is not None:
        args.append(negation)
    return f"not __fish_contains_opt {' '.join(args)}"


def _value_flag_dedup(flag: FlagDescriptor) -> str:
    forms = [f"--{flag.name}"]
    forms += [f"-{alias}" if len(alias) == 1 else f"--{alias}" for alias in flag.aliases]
    return (
        f"begin; {_contains_opt(flag)}; or contains -- (commandline -poc)[-1] "
        f"{' '.join(forms)}; end"
    )


def _choice_args(choice: Choice) -> str:
    return f"-r -f -a '{' '.join(_escape_choice(value) for value in choice.values)}'"


def _flag_value_args(kind: FlagType) -> str | None:
    match kind:
        case "Boolean":
            return None
        case Choice():
            return _choice_args(kind)
        case PathKind():
            return "-r -F"
        case _:
            return "-r -f"


def _argument_value_args(kind: ArgumentType) -> str | None:
    match kind:
        case Choice():
            return _choice_args(kind)
        case PathKind():
            return "-r -F"
        case _:
            return None


def _flag_args(flag: FlagDescriptor) -> list[str]:
    args = [f"-l {flag.name}"]
    args += [f"-s {alias}" if len(alias) == 1 else f"-l {alias}" for alias in flag.aliases]
    if flag.description:
        args.append(f"-d '{_escape(flag.description)}'")
    value = _flag_value_args(flag.type) if takes_separate_value(flag) else None
    if value:
        args.append(value)
    return args


def _line(executable: str, *parts: str) -> str:
    return " ".join([f"complete -c {executable}", *(part for part in parts if part)])


def _disable(flag: FlagDescriptor) -> str:
    return f"-d '{_escape(f'Disable {flag.name}')}'" if flag.description else ""


def _bare_flags(
    executable: str, descriptor: CommandDescriptor, condition: str, lines: list[str]
) -> None:
    not_dash = 'not string match -q -- "-*" (commandline -ct)'
    base = f"{condition}; and {not_dash}" if condition else not_dash
    for flag in descriptor.flags:
        bare = f"-n '{base}; and {_contains_opt(flag)}'"
        description = f"-d '{_escape(flag.description)}'" if flag.description else ""
        lines.append(_line(executable, bare, f"-f -a '--{flag.name}'", description))
        negation = negated_name(flag)
        if negation is not None:
            lines.append(_line(executable, bare, f"-f -a '--{negation}'", _disable(flag)))


def _completions(
    executable: str, descriptor: CommandDescriptor, parent: list[str], lines: list[str]
) -> None:
    condition = _subcommand_condition(parent, [sub.name for sub in descriptor.subcommands])
    condition_arg = f"-n '{condition}'" if condition else ""
    if not any(isinstance(argument.type, PathKind) for argument in descriptor.arguments):
        lines.append(_line(executable, condition_arg, "-f"))
    for sub in descriptor.subcommands:
        description = f"-d '{_escape(sub.description)}'" if sub.description else ""
        lines.append(_line(executable, condition_arg, f"-f -a '{_escape(sub.name)}'", description))
    for flag in descriptor.flags:
        dedup = _value_flag_dedup(flag) if takes_separate_value(flag) else _contains_opt(flag)
        flag_condition = f"{condition}; and {dedup}" if condition else dedup
        flag_condition_arg = f"-n '{flag_condition}'"
        lines.append(_line(executable, flag_condition_arg, *_flag_args(flag)))
        negation = negated_name(flag)
        if negation is not None:
            lines.append(_line(executable, flag_condition_arg, f"-l {negation}", _disable(flag)))
    if descriptor.flags:
        _bare_flags(executable, descriptor, condition, lines)
    for argument in descriptor.arguments:
        value = _argument_value_args(argument.type)
        if value:
            description = f"-d '{_escape(argument.description)}'" if argument.description else ""
            lines.append(_line(executable, condition_arg, value, description))
    for sub in descriptor.subcommands:
        _completions(executable, sub, [*parent, sub.name], lines)


def generate(executable: str, descriptor: CommandDescriptor) -> str:
    lines = [
        f"###-begin-{executable}-completions-###",
        "#",
        "# Static completion script for Fish",
        "#",
        "# Installation:",
        f"#   {executable} --completions fish > ~/.config/fish/completions/{executable}.fish",
        "#",
        "",
    ]
    _completions(executable, descriptor, [], lines)
    lines.append("")
    lines.append(f"###-end-{executable}-completions-###")
    return "\n".join(lines)
