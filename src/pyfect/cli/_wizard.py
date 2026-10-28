"""``--wizard``: builds a command line by asking for each flag, argument
and subcommand (Effect's internal ``cli/internal/wizard``)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Never

from pyfect import console, redacted
from pyfect._js import js_number
from pyfect.cli import _ansi as ansi
from pyfect.cli import prompt
from pyfect.cli._command import Command
from pyfect.cli._environment import Environment
from pyfect.cli.cli_error import CliError
from pyfect.cli.param import (
    ARGUMENT,
    FLAG,
    Param,
    ParsedArgs,
    Single,
    get_underlying_single_or_throw,
)
from pyfect.effect import Effect, gen
from pyfect.terminal import QuitError

type AnyCommand = Command[Any, Any, Any, Any]


@dataclass(frozen=True, slots=True)
class Arg:
    value: str
    display: str


@dataclass(frozen=True, slots=True)
class WizardResult:
    args: tuple[str, ...]
    display_args: tuple[str, ...]


def _arg(value: str, display: str | None = None) -> Arg:
    return Arg(value, value if display is None else display)


def run(
    command: AnyCommand,
    *,
    command_path: tuple[str, ...] | None = None,
    prefix: tuple[str, ...] | None = None,
) -> Effect[WizardResult, CliError | QuitError, Environment]:
    path = command_path or (command.name,)

    def body():
        selected = _command_at(command, path)
        line = [_arg(value) for value in (prefix or path)]
        theme = yield from prompt.PromptTheme()
        yield from _log_current(line, theme.colors)
        section = "ROOT" if selected is command else selected.name
        yield from _prompt_command(selected, line, section, theme.colors)
        return WizardResult(tuple(arg.value for arg in line), tuple(arg.display for arg in line))

    return gen(body)


def _command_at(command: AnyCommand, path: tuple[str, ...]) -> AnyCommand:
    current = command
    for name in path[1:]:
        child = next(
            (
                sub
                for group in current.subcommands
                for sub in group.commands
                if name in (sub.name, sub.alias)
            ),
            None,
        )
        if child is None:
            break
        current = child
    return current


def _visible(command: AnyCommand) -> list[AnyCommand]:
    return [sub for group in command.subcommands for sub in group.commands if not sub.unlisted]


def _prompt_command(
    command: AnyCommand, line: list[Arg], section: str, colors: bool
) -> Effect[None, CliError | QuitError, Environment]:
    def body():
        visible = _visible(command)
        state = command.state
        config = state.context_config if visible else state.config
        if config.flags:
            yield from console.log(_section(section, "FLAGS", colors))
            for param in config.flags:
                line.extend((yield from _prompt_param(param)))
            if config.arguments or visible:
                yield from _log_current(line, colors)
        if config.arguments:
            yield from console.log(_section(section, "ARGUMENTS", colors))
            for param in config.arguments:
                line.extend((yield from _prompt_param(param)))
            if visible:
                yield from _log_current(line, colors)
        if not visible:
            return
        choices = [
            prompt.Choice(
                sub.name,
                sub,
                sub.short_description if sub.short_description is not None else sub.description,
            )
            for sub in visible
        ]
        child = yield from prompt.run(prompt.select(choices, message="Command"))
        yield from console.log()
        line.append(_arg(child.name))
        if _has_steps(child):
            yield from _log_current(line, colors)
        yield from _prompt_command(child, line, child.name, colors)

    return gen(body)


def _has_steps(command: AnyCommand) -> bool:
    return bool(_visible(command)) or bool(command.state.config.ordered_params)


def _prompt_param(param: Param[Any]) -> Effect[list[Arg], CliError | QuitError, Environment]:
    def body():
        single = get_underlying_single_or_throw(param)
        metadata = param.metadata()
        if metadata.is_optional:
            include = yield from prompt.run(prompt.confirm(f"Set {_label(single)}?"))
            if not include:
                yield from console.log()
                return list[Arg]()
        minimum = metadata.variadic_min or 0
        count = (
            (
                yield from prompt.run(
                    prompt.integer(
                        f"{_label(single)} count",
                        default=minimum,
                        min=minimum,
                        max=math.inf if metadata.variadic_max is None else metadata.variadic_max,
                    )
                )
            )
            if metadata.is_variadic
            else 1
        )
        values: list[Arg] = []
        while len(values) < count:
            values.append((yield from _prompt_single(single)))
        raw = tuple(value.value for value in values)
        parsed = ParsedArgs({single.name: raw}, ()) if single.kind == FLAG else ParsedArgs({}, raw)
        yield from param.parse(parsed)
        yield from console.log()
        if single.kind == ARGUMENT:
            return values
        result: list[Arg] = []
        for value in values:
            if single.optional_value is not None or (
                value.value.startswith("-") and len(value.value) > 1
            ):
                result.append(
                    _arg(f"--{single.name}={value.value}", f"--{single.name}={value.display}")
                )
            else:
                result += [_arg(f"--{single.name}"), value]
        return result

    return gen(body)


def _iso(value: datetime) -> str:
    utc = value.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def _js_bool(value: bool) -> str:
    return "true" if value else "false"


def _prompt_single(single: Single[Any]) -> Effect[Arg, QuitError, Environment]:  # noqa: PLR0911 - one return per type
    message = _label(single)
    match single.primitive.tag:
        case "Boolean":
            return prompt.run(
                prompt.confirm(
                    message,
                    confirm_label="true",
                    deny_label="false",
                    default_confirm="(T/f)",
                    default_deny="(t/F)",
                )
            ).map(lambda value: _arg(_js_bool(value)))
        case "Choice":
            keys = single.primitive.choice_keys or ()
            choices = [prompt.Choice(key, key) for key in keys]
            return prompt.run(prompt.select(choices, message=message)).map(_arg)
        case "Date":
            return prompt.run(prompt.date(message)).map(lambda value: _arg(_iso(value)))
        case "Finite":
            return prompt.run(prompt.number(message)).map(lambda value: _arg(js_number(value)))
        case "Int":
            return prompt.run(prompt.integer(message)).map(lambda value: _arg(str(value)))
        case "Redacted":
            return prompt.run(prompt.password(message)).map(
                lambda value: _arg(redacted.value(value), "<redacted>")
            )
        case _:
            return prompt.run(prompt.string(message)).map(_arg)


def _name(single: Single[Any]) -> str:
    return f"--{single.name}" if single.kind == FLAG else single.name


def _label(single: Single[Any]) -> str:
    description = single.description.strip() if single.description is not None else None
    label = (
        description
        if single.kind == FLAG and description is not None and len(description) <= 32
        else _humanize(single.name)
    )
    return f"{label} ({_name(single)})" if single.kind == FLAG else label


def _humanize(name: str) -> str:
    words = [word for word in re.split(r"[-_]+", name) if word]
    if not words:
        return name
    return " ".join([words[0][0].upper() + words[0][1:], *words[1:]])


def _log_current(line: list[Arg], colors: bool) -> Effect[None, Never]:
    block = _command_block("Current command", [arg.display for arg in line], colors, ansi.magenta)
    return console.log(block)


def _section(command: str, section: str, colors: bool) -> str:
    return (
        f"{ansi.annotate(colors, command.upper(), ansi.bold, ansi.cyan_bright)} "
        f"{ansi.annotate(colors, '·', ansi.black_bright)} "
        f"{ansi.annotate(colors, section, ansi.bold, ansi.white)}"
    )


def render_introduction(name: str, version: str, summary: str | None, colors: bool) -> str:
    title = (
        f"{ansi.annotate(colors, name, ansi.bold, ansi.cyan_bright)} "
        f"{ansi.annotate(colors, f'v{version}', ansi.white)} "
        f"{ansi.annotate(colors, '· Command wizard', ansi.bold, ansi.white)}"
    )
    hint = ansi.annotate(
        colors, "Build a command interactively. Press Ctrl+C to cancel.", ansi.black_bright
    )
    return "\n".join([title, *([summary] if summary else []), hint, ""])


def render_completion(line: list[str] | tuple[str, ...], colors: bool) -> str:
    return _command_block("Command ready", line, colors, ansi.cyan_bright, ansi.green)


def render_quit(colors: bool) -> str:
    return f"\n{ansi.annotate(colors, 'Wizard cancelled.', ansi.red)}"


def _command_block(
    label: str,
    line: list[str] | tuple[str, ...],
    colors: bool,
    command_color: str,
    label_color: str = ansi.white,
) -> str:
    lines = [ansi.annotate(colors, label, ansi.bold, label_color)]
    lines += [ansi.annotate(colors, wrapped, command_color) for wrapped in _wrap(line)]
    return "\n".join([*lines, ""])


_WIDTH = 88
_FIRST = "  $ "
_CONTINUATION = "    "


def _wrap(line: list[str] | tuple[str, ...]) -> list[str]:
    lines: list[str] = []
    current = _FIRST
    for arg in map(_shell_arg, line):
        separator = "" if current in (_FIRST, _CONTINUATION) else " "
        if len(current) + len(separator) + len(arg) > _WIDTH and current != _FIRST:
            lines.append(f"{current} \\")
            current = f"{_CONTINUATION}{arg}"
        else:
            current += f"{separator}{arg}"
    if current != _FIRST:
        lines.append(current)
    return lines


_SAFE_SHELL = re.compile(r"[A-Za-z0-9_./:@%+=,-]+")


def _shell_arg(arg: str) -> str:
    if _SAFE_SHELL.fullmatch(arg):
        return arg
    return "'" + arg.replace("'", "'\"'\"'") + "'"


__all__ = ["WizardResult", "render_completion", "render_introduction", "render_quit", "run"]
