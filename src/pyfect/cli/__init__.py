"""Command-line apps (Effect's ``effect/cli``).

Declare a command's params as a ``Config`` class of ``Flag`` and
``Argument`` attributes, build commands with ``command.make``, and run the
tree with ``command.run``; help, errors, ``--version``, ``--completions``
and ``--wizard`` come built in::

    from pyfect import console
    from pyfect.cli import Argument, Config, Flag, command

    class Greet(Config):
        name = Argument.string("name")
        loud = Flag.boolean("loud").with_alias("l").with_default(False)

    def greet(config: Greet):
        text = f"Hello, {config.name}"
        return console.log(text.upper() if config.loud else text)

    app = command.make("greet", Greet, greet)
    program = command.run(app, version="1.0.0")

Modules: ``command``, ``flag``, ``argument``, ``param``, ``primitive``,
``cli_error``, ``cli_output``, ``help_doc``, ``global_flag``,
``cli_config``, ``completions``, ``prompt``, ``terminal_capabilities``.
"""

from pyfect.cli import (
    cli_config,
    cli_error,
    cli_output,
    command,
    completions,
    global_flag,
    help_doc,
    param,
    primitive,
    prompt,
    terminal_capabilities,
)
from pyfect.cli._command import Command, CommandContext, SubcommandGroup, group
from pyfect.cli._config import Config, Nested, nested
from pyfect.cli._settings import Action, HandlerContext, Setting
from pyfect.cli.argument import Argument
from pyfect.cli.cli_error import CliError, ShowHelp, UserError, ValidationError
from pyfect.cli.flag import Flag
from pyfect.cli.prompt import Prompt
from pyfect.cli.terminal_capabilities import TerminalCapabilities

__all__ = [
    "Action",
    "Argument",
    "CliError",
    "Command",
    "CommandContext",
    "Config",
    "Flag",
    "HandlerContext",
    "Nested",
    "Prompt",
    "Setting",
    "ShowHelp",
    "SubcommandGroup",
    "TerminalCapabilities",
    "UserError",
    "ValidationError",
    "cli_config",
    "cli_error",
    "cli_output",
    "command",
    "completions",
    "global_flag",
    "group",
    "help_doc",
    "nested",
    "param",
    "primitive",
    "prompt",
    "terminal_capabilities",
]
