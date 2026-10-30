"""Zsh completion scripts (Effect's internal ``completions/zsh``), built on
``_arguments`` specs with a state machine for subcommands."""

from __future__ import annotations

import re

from pyfect.cli.completions._descriptor import (
    ArgumentDescriptor,
    ArgumentType,
    Choice,
    CommandDescriptor,
    FlagDescriptor,
    FlagType,
    PathKind,
    long_forms,
    negated_name,
)

_UNSAFE_CHOICE = re.compile(r"[^A-Za-z0-9_.,/@%+-]")


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "'\\''").replace(":", "\\:")


def _escape_explanation(text: str) -> str:
    return _escape(text).replace("]", "\\]")


def _escape_choice(text: str) -> str:
    return _UNSAFE_CHOICE.sub(lambda match: "\\" + match.group(), text).replace("'", "'\\''")


def _sanitize(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", text)


def _choices(choice: Choice) -> str:
    return "(" + " ".join(_escape_choice(value) for value in choice.values) + ")"


def _value_action(kind: FlagType) -> str:  # noqa: PLR0911 - one return per type
    match kind:
        case "Boolean":
            return ""
        case Choice():
            return f":value:{_choices(kind)}"
        case PathKind(path_type="directory"):
            return ":directory:_directories"
        case PathKind():
            return ":file:_files"
        case "Int":
            return ":integer:"
        case "Finite":
            return ":float:"
        case "Date":
            return ":date:"
        case _:
            return ":value:"


def _argument_action(kind: ArgumentType) -> str:
    match kind:
        case Choice():
            return _choices(kind)
        case PathKind(path_type="directory"):
            return "_directories"
        case PathKind():
            return "_files"
        case _:
            return ""


def _flag_specs(flag: FlagDescriptor) -> list[str]:
    desc = f"[{_escape_explanation(flag.description)}]" if flag.description else ""
    optional = flag.optional_value and flag.type != "Boolean"
    suffix = "=-" if optional else ""
    action = f":{_value_action(flag.type)}" if optional else _value_action(flag.type)
    exclusion = f"({' '.join(long_forms(flag))})"
    specs = [f"'{exclusion}--{flag.name}{suffix}{desc}{action}'"]
    for alias in flag.aliases:
        prefix = "-" if len(alias) == 1 else "--"
        specs.append(f"'{exclusion}{prefix}{alias}{suffix}{desc}{action}'")
    negation = negated_name(flag)
    if negation is not None:
        negated = f"[{_escape_explanation(f'Disable {flag.name}')}]" if flag.description else ""
        specs.append(f"'{exclusion}--{negation}{negated}'")
    return specs


def _argument_spec(argument: ArgumentDescriptor) -> str:
    desc = _escape(argument.description) if argument.description else argument.name
    prefix = "*" if argument.variadic else ""
    return f"'{prefix}:{desc}:{_argument_action(argument.type)}'"


def _function_name(path: list[str]) -> str:
    return "_" + "_".join(_sanitize(part) for part in path)


def _with_subcommands(descriptor: CommandDescriptor, path: list[str], lines: list[str]) -> None:
    lines.append("  local context state state_descr line")
    lines.append("  typeset -A opt_args")
    lines.append("")
    lines.append("  local -a commands")
    lines.append("  commands=(")
    for sub in descriptor.subcommands:
        desc = _escape(sub.description) if sub.description else ""
        lines.append(f"    '{sub.name}:{desc}'")
    lines.append("  )")
    lines.append("")
    lines.append("  local -a specs")
    lines.append("  specs=(")
    for flag in descriptor.flags:
        lines.extend(f"    {spec}" for spec in _flag_specs(flag))
    if descriptor.arguments:
        lines.append("    -")
        lines.append("    parent-arguments")
        lines.extend(f"    {_argument_spec(argument)}" for argument in descriptor.arguments)
        lines.append("    -")
        lines.append("    subcommands")
    lines.append("    '1:command:->command'")
    lines.append("    '*::arg:->args'")
    lines.append("  )")
    lines.append("")
    lines.append('  _arguments -C "${specs[@]}"')
    lines.append("")
    lines.append('  case "$state" in')
    lines.append("    command)")
    lines.append("      _describe -t commands 'commands' commands")
    lines.append("      ;;")
    lines.append("    args)")
    lines.append('      case "$words[1]" in')
    for sub in descriptor.subcommands:
        lines.append(f"        {sub.name})")
        lines.append(f"          {_function_name([*path, sub.name])}")
        lines.append("          ;;")
    lines.append("      esac")
    lines.append("      ;;")
    lines.append("  esac")


def _function(descriptor: CommandDescriptor, parent: list[str], lines: list[str]) -> None:
    path = [*parent, descriptor.name]
    lines.append(f"{_function_name(path)}() {{")
    if descriptor.subcommands:
        _with_subcommands(descriptor, path, lines)
    else:
        specs = [spec for flag in descriptor.flags for spec in _flag_specs(flag)]
        specs += [_argument_spec(argument) for argument in descriptor.arguments]
        if specs:
            lines.append("  local -a specs")
            lines.append("  specs=(")
            lines.extend(f"    {spec}" for spec in specs)
            lines.append("  )")
            lines.append('  _arguments "${specs[@]}"')
    lines.append("}")
    lines.append("")
    for sub in descriptor.subcommands:
        _function(sub, path, lines)


def generate(executable: str, descriptor: CommandDescriptor) -> str:
    safe = _sanitize(executable)
    lines = [
        f"#compdef {executable}",
        f"###-begin-{executable}-completions-###",
        "#",
        "# Static completion script for Zsh",
        "#",
        "# Installation:",
        f"#   {executable} --completions zsh > ~/.zsh/completions/_{executable}",
        "#   then add ~/.zsh/completions to your fpath",
        "#",
        "",
    ]
    _function(descriptor, [], lines)
    lines.append("# Handle both direct invocation and autoload")
    lines.append('if [[ "${zsh_eval_context[-1]}" == "loadautofunc" ]]; then')
    lines.append(f'  _{safe} "$@"')
    lines.append("else")
    lines.append(f"  compdef _{safe} {executable}")
    lines.append("fi")
    lines.append(f"###-end-{executable}-completions-###")
    return "\n".join(lines)


__all__ = ["generate"]
