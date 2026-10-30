"""Bash completion scripts (Effect's internal ``completions/bash``). The
script runs on Bash 3.2 and works without the bash-completion package."""

from __future__ import annotations

import re

from pyfect.cli.completions._descriptor import (
    ArgumentType,
    Choice,
    CommandDescriptor,
    FlagDescriptor,
    FlagType,
    PathKind,
    long_forms,
    takes_separate_value,
)

# The static parts, as Effect writes them.
INIT_COMPLETION_FALLBACK = (
    "if ! type _init_completion &>/dev/null; then\n"
    "  _init_completion()\n"
    "  {\n"
    "    COMPREPLY=()\n"
    '    local _i _j=0 _piece _line="$COMP_LINE"\n'
    '    words=("${COMP_WORDS[0]}")\n'
    "    cword=0\n"
    '    _line="${_line#*"${COMP_WORDS[0]}"}"\n'
    "    for ((_i = 1; _i < ${#COMP_WORDS[@]}; _i++)); do\n"
    '      _piece="${COMP_WORDS[_i]}"\n'
    '      if [[ "$_line" == [[:blank:]]* ]]; then\n'
    "        ((_j++))\n"
    '        words[_j]="$_piece"\n'
    "      else\n"
    '        words[_j]="${words[_j]}$_piece"\n'
    "      fi\n"
    "      ((_i == COMP_CWORD)) && cword=$_j\n"
    '      _line="${_line#*"$_piece"}"\n'
    "    done\n"
    '    cur="${words[cword]}"\n'
    '    prev=""\n'
    '    ((cword > 0)) && prev="${words[cword-1]}"\n'
    "    return 0\n"
    "  }\n"
    "fi\n"
    "\n"
)

CHOICES_HELPER_NAME = "_x--choices"
CHOICES_HELPER = (
    "_x--choices()\n"
    "{\n"
    '  local _cur="$1" _word="$2"; shift 2\n'
    "\n"
    '  local _head="${_cur%"$_word"}"\n'
    '  local _open=""\n'
    '  case "$_head" in\n'
    "    *\\') _open=\"'\" ;;\n"
    "    *\\\") _open='\"' ;;\n"
    "  esac\n"
    "\n"
    '  local _prefix="$_cur" _committed="$_head"\n'
    "  _prefix=${_prefix//\\\\/}; _prefix=${_prefix//\\\"/}; _prefix=${_prefix//\\'/}\n"
    '  _committed=${_committed//\\\\/}; _committed=${_committed//\\"/};'
    " _committed=${_committed//\\'/}\n"
    "\n"
    "  COMPREPLY=()\n"
    "  local _choice _rest _match\n"
    '  for _choice in "$@"; do\n'
    '    [[ "$_choice" == "$_prefix"* ]] || continue\n'
    '    _rest="${_choice#"$_committed"}"\n'
    '    case "$_open" in\n'
    '      "\'")\n'
    '        if [[ "$_head" == "\'" ]]; then\n'
    "          _match=${_rest//\\'/\\'\\\\\\'\\'}\n"
    "        else\n"
    '          [[ "$_rest" == *\\\'* ]] && continue\n'
    '          _match="$_rest"\n'
    "        fi\n"
    "        ;;\n"
    "      '\"')\n"
    '        _match="${_rest//\\\\/\\\\\\\\}"\n'
    '        _match="${_match//\\$/\\\\$}"\n'
    '        _match="${_match//\\`/\\\\\\`}"\n'
    '        _match="${_match//\\"/\\\\\\"}"\n'
    "        ;;\n"
    "      *)\n"
    "        printf -v _match '%q' \"$_rest\"\n"
    '        [[ -z "$_head" && "$_match" == \'~\'* ]] && _match="\\\\$_match"\n'
    "        ;;\n"
    "    esac\n"
    '    [[ -n "$_open" && "$_match" == *"$_open" ]] && _match+="$_open"\n'
    '    COMPREPLY+=("$_match")\n'
    "  done\n"
    "}\n"
)


def _escape(text: str) -> str:
    return text.replace("'", "'\\''")


def _sanitize(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", text)


def _flag_group_declarations(flags: tuple[FlagDescriptor, ...], lines: list[str]) -> None:
    if not flags:
        return
    groups = [long_forms(flag) for flag in flags]
    lines.append("  local " + " ".join(f'_used_{index}=""' for index in range(len(groups))))
    lines.append("  for ((i = 1; i < cword; i++)); do")
    lines.append('    case "${words[i]%%=*}" in')
    for index, forms in enumerate(groups):
        lines.append(f"      {'|'.join(forms)}) _used_{index}=1 ;;")
    lines.append("    esac")
    lines.append("  done")
    lines.append('  local _filtered_flags=""')
    for index, forms in enumerate(groups):
        lines.append(f'  [[ -n "$_used_{index}" ]] || _filtered_flags+=" {" ".join(forms)}"')
    lines.append("")


def _choice_completion(helper: str, values: tuple[str, ...]) -> str:
    quoted = " ".join(f"'{_escape(value)}'" for value in values)
    return f'{helper} "$cur" "$_comp_word" {quoted}'


def _path_completion(kind: PathKind) -> str:
    if kind.path_type == "directory":
        return 'COMPREPLY=( $(compgen -d -- "$cur") )'
    return 'COMPREPLY=( $(compgen -f -- "$cur") )'


def _value_completion(kind: FlagType | ArgumentType, helper: str) -> str | None:
    if isinstance(kind, Choice):
        return _choice_completion(helper, kind.values)
    if isinstance(kind, PathKind):
        return _path_completion(kind)
    return None


def _function_name(path: list[str]) -> str:
    return "_" + "_".join(_sanitize(part) for part in path)


def _skip_cases(flag: FlagDescriptor, lines: list[str]) -> None:
    forms = long_forms(flag)
    lines.append(f"      {'|'.join(forms)}) _skip_next=1 ;;")
    lines.append(f"      {'|'.join(f'{form}=*' for form in forms)}) ;;")


def _skip_loop_head(lines: list[str]) -> None:
    lines.append("  for ((i = _command_index + 1; i < cword; i++)); do")
    lines.append("    if (( _skip_next )); then")
    lines.append("      _skip_next=0")
    lines.append("      continue")
    lines.append("    fi")


def _flag_values(descriptor: CommandDescriptor, helper: str, lines: list[str]) -> None:
    with_values = [flag for flag in descriptor.flags if takes_separate_value(flag)]
    if not with_values:
        return
    lines.append("  # Flag value completions")
    lines.append('  case "$prev" in')
    for flag in with_values:
        names = [f"--{flag.name}"] + [
            f"-{alias}" if len(alias) == 1 else f"--{alias}" for alias in flag.aliases
        ]
        completion = _value_completion(flag.type, helper)
        if completion:
            lines.append(f"    {'|'.join(names)})")
            lines.append(f"      {completion}")
            lines.append("      return")
            lines.append("      ;;")
    lines.append("  esac")
    lines.append("")


def _subcommand_dispatch(descriptor: CommandDescriptor, path: list[str], lines: list[str]) -> None:
    if not descriptor.subcommands:
        return
    lines.append("  # Subcommand dispatch")
    lines.append("  local cmd _skip_next=0")
    _skip_loop_head(lines)
    lines.append('    case "${words[i]}" in')
    for flag in descriptor.flags:
        if takes_separate_value(flag):
            _skip_cases(flag, lines)
    for sub in descriptor.subcommands:
        lines.append(f"      {sub.name})")
        lines.append(f'        {_function_name([*path, sub.name])} "$i"')
        lines.append("        return")
        lines.append("        ;;")
    lines.append("    esac")
    lines.append("  done")
    lines.append("")


def _positionals(descriptor: CommandDescriptor, helper: str, lines: list[str]) -> None:
    completions = [
        (index, argument, completion)
        for index, argument in enumerate(descriptor.arguments)
        if (completion := _value_completion(argument.type, helper)) is not None
    ]
    if not completions:
        if descriptor.subcommands:
            names = " ".join(sub.name for sub in descriptor.subcommands)
            lines.append(f"  COMPREPLY=( $(compgen -W '{names}' -- \"$cur\") )")
        return
    lines.append("  # Positional argument completions")
    lines.append("  local _position=0 _skip_next=0 _end_of_options=0")
    _skip_loop_head(lines)
    lines.append("    if (( _end_of_options )); then")
    lines.append("      ((_position += 1))")
    lines.append("      continue")
    lines.append("    fi")
    lines.append('    case "${words[i]}" in')
    lines.append("      --) _end_of_options=1 ;;")
    for flag in descriptor.flags:
        if takes_separate_value(flag):
            _skip_cases(flag, lines)
        else:
            lines.append(f"      {'|'.join(long_forms(flag))}) ;;")
    lines.append("      -*) ;;")
    lines.append("      *) ((_position += 1)) ;;")
    lines.append("    esac")
    lines.append("  done")
    lines.append('  case "$_position" in')
    for index, argument, completion in completions:
        if argument.variadic:
            continue
        lines.append(f"    {index})")
        lines.append(f"      {completion}")
        lines.append("      return")
        lines.append("      ;;")
    lines.append("  esac")
    variadic = next((entry for entry in completions if entry[1].variadic), None)
    if variadic is not None:
        lines.append(f"  if (( _position >= {variadic[0]} )); then")
        lines.append(f"    {variadic[2]}")
        lines.append("    return")
        lines.append("  fi")


def _function(
    descriptor: CommandDescriptor, parent: list[str], lines: list[str], helper: str
) -> None:
    path = [*parent, descriptor.name]
    lines.append(f"{_function_name(path)}()")
    lines.append("{")
    lines.append("  local cur prev words cword i")
    lines.append("  local _command_index=0" if not parent else '  local _command_index="$1"')
    lines.append('  _init_completion -n "$COMP_WORDBREAKS" || return')
    if not parent:
        lines.append('  local _comp_word="$2"')
    lines.append("")
    _flag_values(descriptor, helper, lines)
    _subcommand_dispatch(descriptor, path, lines)
    _flag_group_declarations(descriptor.flags, lines)
    if descriptor.flags or descriptor.subcommands:
        lines.append("  # Complete flags (filtered) and subcommands")
        lines.append('  if [[ "$cur" == -* ]]; then')
        if descriptor.flags:
            lines.append('    COMPREPLY=( $(compgen -W "$_filtered_flags" -- "$cur") )')
        lines.append("    return")
        lines.append("  fi")
        lines.append("")
    _positionals(descriptor, helper, lines)
    lines.append("}")
    lines.append("")
    for sub in descriptor.subcommands:
        _function(sub, path, lines, helper)


def generate(executable: str, descriptor: CommandDescriptor) -> str:
    safe = _sanitize(executable)
    helper = f"_{safe}--choices"
    name = _escape(executable)
    lines = [
        f"###-begin-{name}-completions-###",
        "#",
        "# Static completion script for Bash",
        "#",
        "# Installation:",
        f"#   {name} --completions bash >> ~/.bashrc",
        "#",
        "",
    ]
    lines += INIT_COMPLETION_FALLBACK.split("\n")[:-1]
    lines += CHOICES_HELPER.replace(CHOICES_HELPER_NAME, helper).split("\n")[:-1]
    lines.append("")
    _function(descriptor, [], lines, helper)
    lines.append(f"complete -F _{safe} {name}")
    lines.append(f"###-end-{name}-completions-###")
    return "\n".join(lines)


__all__ = ["CHOICES_HELPER", "CHOICES_HELPER_NAME", "INIT_COMPLETION_FALLBACK", "generate"]
