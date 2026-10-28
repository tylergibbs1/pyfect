"""Flags every command accepts (Effect's ``GlobalFlag``).

An ``Action`` does something instead of running the command (``--help``,
``--version``, ``--wizard``, ``--completions``); a ``Setting`` is a value
the runner provides to the handler as a service (``--log-level``, or your
own: subclass ``Setting``). ``built_ins`` are the defaults, which
``cli_config.layer(built_ins=...)`` replaces.
"""

from __future__ import annotations

from pyfect import console
from pyfect.cli import completions
from pyfect.cli._help import help_for_path
from pyfect.cli._settings import Action, GlobalFlag, HandlerContext, LogLevel, Setting
from pyfect.cli.cli_output import CurrentPresenter
from pyfect.cli.cli_output import Help as HelpEvent
from pyfect.cli.cli_output import Version as VersionEvent
from pyfect.cli.flag import Flag
from pyfect.effect import Effect, gen, succeed


def _show_help(_: bool, context: HandlerContext) -> Effect[None]:
    def body():
        presenter = yield from CurrentPresenter()
        doc = help_for_path(context.command, context.command_path, context.built_ins)
        yield from presenter.present(HelpEvent("Requested", context.command_path, doc))

    return gen(body)


def _show_version(_: bool, context: HandlerContext) -> Effect[None]:
    def body():
        presenter = yield from CurrentPresenter()
        yield from presenter.present(VersionEvent(context.command.name, context.version))

    return gen(body)


def _print_completions(shell: completions.Shell | None, context: HandlerContext) -> Effect[None]:
    if shell is None:
        return succeed(None)
    descriptor = completions.from_command(context.command)
    return console.log(completions.generate(context.command.name, shell, descriptor))


Help: Action[bool] = Action(
    Flag.boolean("help")
    .with_alias("h")
    .with_description("Show help information")
    .with_default(False),
    _show_help,
)

Version: Action[bool] = Action(
    Flag.boolean("version")
    .with_alias("v")
    .with_description("Show version information")
    .with_default(False),
    _show_version,
)

Wizard: Action[bool] = Action(
    Flag.boolean("wizard").with_description("Start wizard mode for a command").with_default(False),
    lambda _value, _context: succeed(None),
)
"""``--wizard``: the runner asks for the command's arguments interactively."""

_SHELLS: list[tuple[str, completions.Shell]] = [
    ("bash", "bash"),
    ("zsh", "zsh"),
    ("fish", "fish"),
    ("powershell", "powershell"),
    ("sh", "bash"),
    ("pwsh", "powershell"),
]

Completions: Action[completions.Shell | None] = Action(
    Flag.choice_with_value("completions", _SHELLS)
    .optional()
    .with_metavar("<bash|zsh|fish|powershell|sh|pwsh>")
    .with_description("Print shell completion script"),
    _print_completions,
)

built_ins: tuple[GlobalFlag, ...] = (Help, Version, Wizard, Completions, LogLevel)

__all__ = [
    "Action",
    "Completions",
    "GlobalFlag",
    "HandlerContext",
    "Help",
    "LogLevel",
    "Setting",
    "Version",
    "Wizard",
    "built_ins",
]
