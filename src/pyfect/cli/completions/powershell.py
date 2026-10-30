"""PowerShell completion scripts (Effect's internal
``completions/powershell``): the command tree as data and one native
argument completer reading it."""

from __future__ import annotations

import re
from importlib import resources

from pyfect.cli.completions._descriptor import (
    ArgumentDescriptor,
    ArgumentType,
    Choice,
    CommandDescriptor,
    FlagDescriptor,
    FlagType,
    PathKind,
    negated_name,
)

_DATA_NAME = "$global:_x_Completions"

COMPLETER = (
    resources.files("pyfect.cli.completions")
    .joinpath("_completer.ps1")
    .read_text(encoding="utf-8")
    .rstrip("\n")
)
"""The completer's body, as Effect writes it, reading the data at ``$global:_x_Completions``."""


def _quote(text: str) -> str:
    """A single-quoted literal; characters outside printable ASCII are
    ``[char]`` UTF-16 code units, so the script stays ASCII."""
    parts: list[str] = []
    literal = ""
    units = text.encode("utf-16-le")
    for index in range(0, len(units), 2):
        code = int.from_bytes(units[index : index + 2], "little")
        if 0x20 <= code < 0x80:
            char = chr(code)
            literal += "''" if char == "'" else char
            continue
        if literal or not parts:
            parts.append(f"'{literal}'")
        literal = ""
        parts.append(f"[char]0x{code:04X}")
    if literal or not parts:
        parts.append(f"'{literal}'")
    return parts[0] if len(parts) == 1 else f"({' + '.join(parts)})"


def _array(items: list[str] | tuple[str, ...]) -> str:
    return f"@({', '.join(_quote(item) for item in items)})"


def _optional(text: str | None) -> str:
    return _quote(text) if text else "$null"


def _sanitize(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", text)


def _bool(value: bool) -> str:
    return "$true" if value else "$false"


def _value_fields(kind: FlagType | ArgumentType) -> str:
    values = kind.values if isinstance(kind, Choice) else ()
    path_type = _quote(kind.path_type) if isinstance(kind, PathKind) else "$null"
    return f"values = {_array(values)}; pathType = {path_type}"


def _flag_entry(flag: FlagDescriptor) -> str:
    forms = [f"--{flag.name}"] + [
        f"-{alias}" if len(alias) == 1 else f"--{alias}" for alias in flag.aliases
    ]
    negation = negated_name(flag)
    return (
        f"@{{ name = {_quote(flag.name)}; forms = {_array(forms)}; "
        f"takesValue = {_bool(flag.type != 'Boolean')}; "
        + ("" if negation is None else f"negation = {_quote(f'--{negation}')}; ")
        + ("optionalValue = $true; " if flag.optional_value else "")
        + f"{_value_fields(flag.type)}; "
        + f"description = {_optional(flag.description)} }}"
    )


def _argument_entry(argument: ArgumentDescriptor) -> str:
    return (
        f"@{{ name = {_quote(argument.name)}; variadic = {_bool(argument.variadic)}; "
        f"{_value_fields(argument.type)}; description = {_optional(argument.description)} }}"
    )


def _list(lines: list[str], name: str, entries: list[str]) -> None:
    if not entries:
        lines.append(f"  {name} = @()")
        return
    lines.append(f"  {name} = @(")
    lines.extend(f"    {entry}" for entry in entries)
    lines.append("  )")


def _contexts(
    data: str, descriptor: CommandDescriptor, path: list[str], lines: list[str], seen: set[str]
) -> None:
    key = " ".join(path)
    if key in seen:
        return
    seen.add(key)
    lines.append(f"{data}[{_quote(key)}] = @{{")
    _list(
        lines,
        "subcommands",
        [
            f"@{{ name = {_quote(sub.name)}; description = {_optional(sub.description)} }}"
            for sub in descriptor.subcommands
        ],
    )
    _list(lines, "flags", [_flag_entry(flag) for flag in descriptor.flags])
    _list(lines, "arguments", [_argument_entry(argument) for argument in descriptor.arguments])
    lines.append("}")
    for sub in descriptor.subcommands:
        _contexts(data, sub, [*path, sub.name], lines, seen)


def generate(executable: str, descriptor: CommandDescriptor) -> str:
    data = f"$global:_{_sanitize(executable)}_Completions"
    lines = [
        f"###-begin-{executable}-completions-###",
        "#",
        "# Static completion script for PowerShell",
        "#",
        "# Installation:",
        f"#   {executable} --completions powershell > {executable}-completion.ps1",
        "#   then add this line to your $PROFILE (use the full path to the file):",
        f"#   . <PATH>\\{executable}-completion.ps1",
        "#",
        "",
        f"{data} = [hashtable]::new([System.StringComparer]::Ordinal)",
    ]
    _contexts(data, descriptor, [], lines, set())
    lines.append("")
    lines.append(
        f"Register-ArgumentCompleter -Native -CommandName {_quote(executable)} -ScriptBlock {{"
    )
    lines.append(COMPLETER.replace(_DATA_NAME, data))
    lines.append("}")
    lines.append("")
    lines.append(f"###-end-{executable}-completions-###")
    return "\n".join(lines)


__all__ = ["COMPLETER", "generate"]
