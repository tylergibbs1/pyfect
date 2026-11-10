"""How a CLI shows help, errors and its version (Effect's ``CliOutput``).

A ``Formatter`` turns a ``HelpDoc`` or errors into text; a ``Presenter``
writes the runner's events (help, an invalid invocation, the version) to
the console. Both have defaults; replace them with ``layer`` and
``layer_presenter``. Without a formatter provided, the default one colors
its output when ``TerminalCapabilities`` says the terminal can.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from pyfect import console
from pyfect.cli import _ansi as ansi
from pyfect.cli._width import display_width
from pyfect.cli.cli_error import CliError, ParseError
from pyfect.cli.help_doc import FlagDoc, HelpDoc, SubcommandDoc
from pyfect.cli.terminal_capabilities import TerminalCapabilities
from pyfect.context import Reference, Tag
from pyfect.effect import Effect, gen, service_option
from pyfect.layer import Layer
from pyfect.layer import succeed as layer_succeed
from pyfect.option import Some


class Formatter(Protocol):
    def format_help_doc(self, doc: HelpDoc) -> str: ...
    def format_cli_error(self, error: CliError) -> str: ...
    def format_error(self, error: CliError) -> str: ...
    def format_version(self, name: str, version: str) -> str: ...
    def format_errors(self, errors: Sequence[CliError]) -> str: ...


@dataclass(frozen=True, slots=True)
class Help:
    reason: Literal["Requested", "Implicit"]
    command_path: tuple[str, ...]
    help_doc: HelpDoc


@dataclass(frozen=True, slots=True)
class InvalidInvocation:
    command_path: tuple[str, ...]
    help_doc: HelpDoc
    errors: tuple[ParseError, ...]


@dataclass(frozen=True, slots=True)
class Version:
    name: str
    version: str


type Event = Help | InvalidInvocation | Version


class Presenter(Protocol):
    def present(self, event: Event) -> Effect[None]: ...


class CurrentFormatter(Tag[Formatter]):
    """The formatter, when one is provided (Effect's ``CliOutput.Formatter``);
    otherwise output uses ``default_formatter``."""


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _escape(text: str) -> str:
    return _CONTROL.sub(lambda match: f"\\x{ord(match.group()):02x}", text)


@dataclass(frozen=True, slots=True)
class _Colors:
    enabled: bool

    def _wrap(self, code: str, text: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.enabled else text

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def cyan(self, text: str) -> str:
        return self._wrap("36", text)

    def green(self, text: str) -> str:
        return self._wrap("32", text)


type FlagSectionMode = Literal["full", "summary", "none"]
"""How help shows inherited or global flags: listed, as a pointer to the
help of the command that declares them, or not at all."""


@dataclass(frozen=True, slots=True)
class _HelpOptions:
    inherited_flags: FlagSectionMode
    global_flags: FlagSectionMode


@dataclass(frozen=True, slots=True)
class _DefaultFormatter:
    colors: _Colors
    help: _HelpOptions

    def _title(self, text: str) -> str:
        if not self.colors.enabled:
            return f"\n{text}"
        return f"\n{ansi.bold}{ansi.red}{text}{ansi.reset}"

    def _reset(self) -> str:
        return ansi.reset if self.colors.enabled else ""

    def format_help_doc(self, doc: HelpDoc) -> str:
        return _format_help_doc(doc, self.colors, self.help)

    def format_cli_error(self, error: CliError) -> str:
        return _escape(error.message)

    def format_error(self, error: CliError) -> str:
        return f"{self._title('ERROR')}\n  {_escape(error.message)}{self._reset()}"

    def format_errors(self, errors: Sequence[CliError]) -> str:
        if not errors:
            return ""
        if len(errors) == 1:
            return self.format_error(errors[0])
        grouped: dict[str, list[CliError]] = {}
        for error in errors:
            grouped.setdefault(error.tag_name, []).append(error)
        lines = [self._title("ERRORS")] + [
            f"  {_escape(error.message)}{self._reset()}"
            for group in grouped.values()
            for error in group
        ]
        return "\n".join(lines)

    def format_version(self, name: str, version: str) -> str:
        colors = self.colors
        return f"{colors.bold(name)} {colors.dim('v')}{colors.bold(version)}"


def default_formatter(
    *,
    colors: bool | None = None,
    inherited_flags: FlagSectionMode = "full",
    global_flags: FlagSectionMode = "full",
) -> Formatter:
    """The built-in formatter; ``colors`` defaults to whether stdout is a
    terminal and ``NO_COLOR`` is unset. ``inherited_flags`` and
    ``global_flags`` choose how a subcommand's help shows the shared flags of
    its ancestors and the global flags: listed (``"full"``), as a pointer to
    the declaring command's help (``"summary"``) or not at all (``"none"``).
    The command declaring global flags always lists them."""
    return _DefaultFormatter(
        _Colors(ansi.detect_colors() if colors is None else colors),
        _HelpOptions(inherited_flags, global_flags),
    )


def resolve_formatter() -> Effect[Formatter]:
    """The provided formatter, else the default one colored as the
    terminal's capabilities allow."""

    def body():
        provided = yield from service_option(CurrentFormatter)
        if isinstance(provided, Some):
            return provided.value
        capabilities = yield from TerminalCapabilities()
        return default_formatter(colors=capabilities.can_color)

    return gen(body)


class _DefaultPresenter:
    def present(self, event: Event) -> Effect[None]:
        def body():
            formatter = yield from resolve_formatter()
            match event:
                case Help():
                    yield from console.log(formatter.format_help_doc(event.help_doc))
                case InvalidInvocation():
                    yield from console.log(formatter.format_help_doc(event.help_doc))
                    yield from console.error(formatter.format_errors(event.errors))
                case Version():
                    yield from console.log(formatter.format_version(event.name, event.version))

        return gen(body)


default_presenter: Presenter = _DefaultPresenter()


class CurrentPresenter(Reference[Presenter]):
    """The presenter the runner uses; defaults to ``default_presenter``."""

    @classmethod
    def default(cls) -> Presenter:
        return default_presenter


def layer(formatter: Formatter) -> Layer[CurrentFormatter]:
    return layer_succeed(CurrentFormatter, formatter)


def layer_presenter(presenter: Presenter) -> Layer[CurrentPresenter]:
    return layer_succeed(CurrentPresenter, presenter)


# --- help text -------------------------------------------------------------------


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def _render_table(rows: Sequence[tuple[str, str]], width_cap: int | None = None) -> str:
    max_column = max(display_width(left) for left, _ in rows) + 4
    column = max_column if width_cap is None else min(max_column, width_cap)
    return "\n".join(
        f"  {_pad(left, max(column, display_width(left) + 1))}{right}" for left, right in rows
    )


def _subcommand_name(command: SubcommandDoc) -> str:
    return f"{command.name}, {command.alias}" if command.alias else command.name


def _flag_rows(flags: Sequence[FlagDoc], colors: _Colors) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for flag in flags:
        names = ", ".join(colors.green(name) for name in (f"--{flag.name}", *flag.aliases))
        type_part = f" {colors.dim(flag.type)}" if flag.type != "boolean" else ""
        rows.append((names + type_part, flag.description or ""))
    return rows


def _subcommand_rows(commands: Sequence[SubcommandDoc], colors: _Colors) -> list[tuple[str, str]]:
    return [
        (colors.cyan(_subcommand_name(sub)), sub.short_description or sub.description)
        for sub in commands
    ]


def _section(sections: list[str], title: str, body: str, *, blank: bool = True) -> None:
    sections.append(title)
    sections.append(body)
    if blank:
        sections.append("")


def _flag_sections(
    sections: list[str], doc: HelpDoc, colors: _Colors, options: _HelpOptions
) -> None:
    def render(title: str, flags: Sequence[FlagDoc]) -> None:
        _section(sections, colors.bold(title), _render_table(_flag_rows(flags, colors)))

    summaries: list[str] = []

    def render_section(
        title: str,
        flags: Sequence[FlagDoc],
        mode: FlagSectionMode,
        summary_path: Sequence[str] | None,
    ) -> None:
        if not flags or mode == "none":
            return
        if mode == "summary" and summary_path:
            summaries.append(f"Run '{' '.join(summary_path)} --help' for {title.lower()}")
        else:
            render(title, flags)

    if doc.flags:
        render("FLAGS", doc.flags)
    path = doc.command_path
    render_section(
        "INHERITED FLAGS",
        doc.inherited_flags,
        options.inherited_flags,
        None if path is None else path[:-1],
    )
    # Keep globals discoverable on their declaring command, even in "none" mode.
    scope = (
        doc.global_flags_scope
        if doc.global_flags_scope is not None
        else (None if path is None else path[:1])
    )
    declares = path is None or (scope is not None and len(scope) == len(path))
    render_section(
        "GLOBAL FLAGS", doc.global_flags, "full" if declares else options.global_flags, scope
    )
    if summaries:
        sections.extend([*summaries, ""])


def _format_help_doc(doc: HelpDoc, colors: _Colors, options: _HelpOptions) -> str:  # noqa: PLR0912 - one branch per section
    sections: list[str] = []
    if doc.description:
        sections += [colors.bold("DESCRIPTION"), f"  {doc.description}", ""]
    sections += [colors.bold("USAGE"), f"  {colors.cyan(doc.usage)}", ""]
    if doc.args:
        rows: list[tuple[str, str]] = []
        for arg in doc.args:
            name = arg.name + ("..." if arg.variadic else "")
            optional = "" if arg.required else colors.dim(" (optional)")
            rows.append(
                (f"{colors.green(name)} {colors.dim(arg.type)}", (arg.description or "") + optional)
            )
        _section(sections, colors.bold("ARGUMENTS"), _render_table(rows, 25))
    _flag_sections(sections, doc, colors, options)
    if doc.subcommands:
        ungrouped = next((g for g in doc.subcommands if g.group is None), None)
        if ungrouped is not None:
            sub_rows = _subcommand_rows(ungrouped.commands, colors)
            _section(
                sections,
                colors.bold("SUBCOMMANDS"),
                _render_table(sub_rows, 20),
                blank=len(doc.subcommands) > 1,
            )
        for group in doc.subcommands:
            if group.group is None:
                continue
            group_rows = _subcommand_rows(group.commands, colors)
            _section(sections, colors.bold(f"{group.group}:"), _render_table(group_rows, 20))
    if doc.examples:
        sections.append(colors.bold("EXAMPLES"))
        first = True
        previous_had_description = False
        for example in doc.examples:
            if example.description:
                if not first:
                    sections.append("")
                sections.append(f"  {colors.dim(f'# {example.description}')}")
            elif previous_had_description:
                sections.append("")
            sections.append(f"  {colors.cyan(example.command)}")
            first = False
            previous_had_description = bool(example.description)
        sections.append("")
    if sections and sections[-1] == "":
        sections.pop()
    return "\n".join(sections)


__all__ = [
    "CurrentFormatter",
    "CurrentPresenter",
    "Event",
    "FlagSectionMode",
    "Formatter",
    "Help",
    "InvalidInvocation",
    "Presenter",
    "Version",
    "default_formatter",
    "default_presenter",
    "display_width",
    "layer",
    "layer_presenter",
    "resolve_formatter",
]
