"""Effect's ``test/cli/Help.test.ts``."""

from __future__ import annotations

import textwrap
from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.cli import Argument, Config, Flag, cli_output, command, group
from pyfect.cli._help import build_help_doc
from pyfect.cli.cli_error import ShowHelp
from pyfect.cli.help_doc import ExampleDoc
from pyfect.testing import Services

from . import _comprehensive_cli as cli
from ._cli_env import test_layer

env = testing.layer_fixture(test_layer, scope="function")


def snapshot(text: str) -> str:
    return textwrap.dedent(text).strip("\n")


GLOBAL_FLAGS = snapshot(
    """
    GLOBAL FLAGS
      --help, -h                                                          Show help information
      --version, -v                                                       Show version information
      --wizard                                                            Start wizard mode for a command
      --completions <bash|zsh|fish|powershell|sh|pwsh>                    Print shell completion script (choices: bash, zsh, fish, powershell, sh, pwsh)
      --log-level <all|trace|debug|info|warn|warning|error|fatal|none>    Sets the minimum log level (choices: all, trace, debug, info, warn, warning, error, fatal, none)
    """  # noqa: E501
)


def log_text():
    return "\n".join(map(str, (yield from testing.log_lines)))


def run_cli(*args: str):
    yield from cli.run(args)
    return (yield from log_text())


def runner(app: command.Command[Any, Any, Any, Any]):
    return command.run_with(app, version="1.0.0")


def ignore_help[A, E, R](eff: fx.Effect[A, E, R]) -> fx.Effect[A | None, E, R]:
    return eff.catch_if(lambda e: isinstance(e, ShowHelp), lambda _: fx.succeed(None))


def test_measures_terminal_cells():
    """measures terminal cells"""
    assert cli_output.display_width("") == 0
    assert cli_output.display_width("file") == 4
    assert cli_output.display_width("ファイル") == 8
    assert cli_output.display_width("é") == 1
    assert cli_output.display_width("1️⃣") == 2
    assert cli_output.display_width("\x1b[31mファイル\x1b[0m") == 8


def test_marks_omittable_flags_as_not_required_in_structured_help():
    """marks omittable flags as not required in structured help"""

    class App(Config):
        required = Flag.string("required")
        optional = Flag.string("optional").optional()
        defaulted = Flag.string("defaulted").with_default("output.txt")

    help = build_help_doc(command.make("app", App), ["app"])
    assert [flag.required for flag in help.flags] == [True, False, False]


def test_renders_the_type_of_a_flag_with_an_optional_value_as_optional():
    """renders the type of a flag with an optional value as optional"""

    class App(Config):
        watch = Flag.literals("watch", ["first-failure", "until-done"]).with_optional_value(
            "first-failure"
        )

    help = build_help_doc(command.make("app", App), ["app"])
    assert [flag.type for flag in help.flags] == ["[=choice]"]


def test_marks_omittable_arguments_as_not_required_in_structured_help():
    """marks omittable arguments as not required in structured help"""

    class RequiredVariadic(Config):
        files = Argument.string("files").variadic(min=1)

    class OptionalVariadic(Config):
        files = Argument.string("files").variadic()

    class Defaulted(Config):
        output = Argument.string("output").with_default("output.txt")

    required = [
        build_help_doc(command.make("app", config), ["app"]).args[0].required
        for config in (RequiredVariadic, OptionalVariadic, Defaulted)
    ]
    assert required == [True, False, False]


@testing.effect
def test_renders_root_command_help(env: Services[Any]):
    """renders root command help"""
    help_text = yield from run_cli("--help")
    assert help_text == snapshot(
        """
        DESCRIPTION
          A comprehensive CLI tool demonstrating all features

        USAGE
          mycli <subcommand> [flags]

        FLAGS
          --debug, -d          Enable debug logging
          --config, -c file    Path to configuration file
          --quiet, -q          Suppress non-error output

        """
    ) + "\n\n" + GLOBAL_FLAGS + "\n\n" + snapshot(
        """
        SUBCOMMANDS
          admin            Administrative commands
          copy             Copy files or directories
          move             Move or rename files
          remove           Remove files or directories
          build            Build the project
          git              Git version control
          test-required    Test command with required option
          test-failing     Test command that always fails
          app              Application management
          app-nested       Application with nested services
        """
    )


@testing.effect
def test_aligns_flag_descriptions_when_flag_names_are_long(env: Services[Any]):
    """aligns flag descriptions when flag names are long"""

    class Tool(Config):
        short = Flag.string("short").with_description("Short flag description")
        very_long = Flag.string("this-is-a-very-very-long-flag-name").with_description(
            "Long flag description"
        )

    yield from runner(command.make("tool", Tool))(["--help"])
    lines = (yield from log_text()).split("\n")
    short_line = next(line for line in lines if "--short" in line)
    long_line = next(line for line in lines if "--this-is-a-very-very-long-flag-name" in line)
    assert short_line.index("Short flag description") == long_line.index("Long flag description")


@testing.effect
def test_aligns_flag_descriptions_when_flag_names_contain_wide_graphemes(env: Services[Any]):
    """aligns flag descriptions when flag names contain wide graphemes"""

    class Tool(Config):
        file = Flag.boolean("ファイル").with_description("Wide flag description")
        emoji = Flag.boolean("\U0001f469‍\U0001f4bb").with_description("Emoji flag description")
        verbose = Flag.boolean("verbose").with_description("ASCII flag description")

    yield from runner(command.make("tool", Tool))(["--help"])
    lines = (yield from log_text()).split("\n")
    assert "  --ファイル    Wide flag description" in lines
    assert "  --\U0001f469‍\U0001f4bb          Emoji flag description" in lines
    assert "  --verbose     ASCII flag description" in lines


@testing.effect
def test_aligns_flag_descriptions_when_flag_names_contain_zero_width_code_points(
    env: Services[Any],
):
    """aligns flag descriptions when flag names contain zero-width code points"""

    class Tool(Config):
        combining = Flag.boolean("é").with_description("Combining flag description")
        zero_width = Flag.boolean("a\u200bb").with_description("Zero-width flag description")
        ascii = Flag.boolean("abcd").with_description("ASCII flag description")

    yield from runner(command.make("tool", Tool))(["--help"])
    lines = (yield from log_text()).split("\n")
    assert "  --é       Combining flag description" in lines
    assert "  --a\u200bb      Zero-width flag description" in lines
    assert "  --abcd    ASCII flag description" in lines


@testing.effect
def test_separates_long_subcommand_and_argument_names_from_their_descriptions(
    env: Services[Any],
):
    """separates long subcommand and argument names from their descriptions"""

    class SetPassword(Config):
        account = Argument.string("existing-account-identifier").with_description(
            "Account to update"
        )

    child = command.make("account:set-password", SetPassword).with_description(
        "Rewrite the credential hash"
    )
    run = runner(command.make("demo").with_subcommands(child))
    yield from run(["--help"])
    root_help = yield from testing.log_lines
    yield from run(["account:set-password", "--help"])
    child_help = (yield from testing.log_lines)[len(root_help) :]
    assert any(
        "account:set-password Rewrite the credential hash" in str(line) for line in root_help
    )
    assert any(
        "existing-account-identifier string Account to update" in str(line) for line in child_help
    )


@testing.effect
def test_hides_flags_marked_with_with_hidden_from_help_output(env: Services[Any]):
    """hides flags marked with withHidden from help output"""

    class Tool(Config):
        visible = Flag.string("visible").with_description("Visible flag")
        secret = Flag.string("experimental-foo").with_description("Should not appear").with_hidden()

    yield from runner(command.make("tool", Tool))(["--help"])
    help_text = yield from log_text()
    assert "--visible" in help_text
    assert "--experimental-foo" not in help_text
    assert "Should not appear" not in help_text


class _Hidden(Config):
    secret = Flag.string("experimental-foo").with_hidden()


@testing.effect
def test_hidden_flag_still_parses_on_the_command_line(env: Services[Any]):
    """hidden flag still parses on the command line"""
    captured: list[str] = []
    app = command.make("tool", _Hidden, lambda c: fx.sync(lambda: captured.append(c.secret)))
    yield from runner(app)(["--experimental-foo", "value"])
    assert captured == ["value"]


@testing.effect
def test_hidden_flag_name_does_not_leak_through_unrecognized_flag_suggestions(
    env: Services[Any],
):
    """hidden flag name does not leak through unrecognized-flag suggestions"""
    app = command.make("tool", _Hidden, lambda _: fx.void)
    yield from ignore_help(runner(app)(["--experimental-fo", "value"]))
    error_text = "\n".join(map(str, (yield from testing.error_lines)))
    assert "experimental-foo" not in error_text + (yield from log_text())


@testing.effect
def test_hides_unlisted_subcommands_from_help_output(env: Services[Any]):
    """hides unlisted subcommands from help output"""
    visible = command.make("visible").with_description("A visible subcommand")
    secret = command.make("experimental-foo").with_description("Should not appear").with_unlisted()
    yield from runner(command.make("tool").with_subcommands(visible, secret))(["--help"])
    help_text = yield from log_text()
    assert "visible" in help_text
    assert "experimental-foo" not in help_text
    assert "Should not appear" not in help_text


@testing.effect
def test_unlisted_subcommand_still_parses_on_the_command_line(env: Services[Any]):
    """unlisted subcommand still parses on the command line"""
    invoked: list[bool] = []
    secret = (
        command.make("experimental-foo")
        .with_unlisted()
        .with_handler(lambda _: fx.sync(lambda: invoked.append(True)))
    )
    yield from runner(command.make("tool").with_subcommands(secret))(["experimental-foo"])
    assert invoked == [True]


@testing.effect
def test_unlisted_subcommand_name_does_not_leak_through_unknown_subcommand_suggestions(
    env: Services[Any],
):
    """unlisted subcommand name does not leak through unknown-subcommand suggestions"""
    secret = command.make("experimental-foo").with_unlisted()
    yield from ignore_help(
        runner(command.make("tool").with_subcommands(secret))(["experimental-fo"])
    )
    error_text = "\n".join(map(str, (yield from testing.error_lines)))
    assert "experimental-foo" not in error_text + (yield from log_text())


@testing.effect
def test_subcommand_group_with_only_unlisted_commands_disappears_entirely(env: Services[Any]):
    """subcommand group with only unlisted commands disappears entirely"""
    secret = command.make("experimental-foo").with_unlisted()
    yield from runner(command.make("tool").with_subcommands(secret))(["--help"])
    help_text = yield from log_text()
    assert "SUBCOMMANDS" not in help_text
    assert "<subcommand>" not in help_text


@testing.effect
def test_renders_command_examples(env: Services[Any]):
    """renders command examples"""
    login = (
        command.make("login")
        .with_description("Authenticate with Supabase")
        .with_examples(
            [
                ExampleDoc("myapp login", "Log in with browser OAuth"),
                ExampleDoc("myapp login --token sbp_abc123", "Log in with a token"),
                ExampleDoc("myapp login --logout"),
                ExampleDoc("myapp login --logout"),
                ExampleDoc("myapp login", "Log in with browser OAuth"),
            ]
        )
    )
    yield from runner(login)(["--help"])
    assert (yield from log_text()) == snapshot(
        """
        DESCRIPTION
          Authenticate with Supabase

        USAGE
          login [flags]

        """
    ) + "\n\n" + GLOBAL_FLAGS + "\n\n" + snapshot(
        """
        EXAMPLES
          # Log in with browser OAuth
          myapp login

          # Log in with a token
          myapp login --token sbp_abc123

          myapp login --logout
          myapp login --logout

          # Log in with browser OAuth
          myapp login
        """
    )


@testing.effect
def test_renders_file_command_positional_arguments(env: Services[Any]):
    """renders file command positional arguments"""
    assert (yield from run_cli("copy", "--help")) == snapshot(
        """
        DESCRIPTION
          Copy files or directories

        USAGE
          mycli copy [flags] <source> <destination>

        ARGUMENTS
          source file         Source file or directory
          destination file    Destination path

        FLAGS
          --debug, -d              Enable debug logging
          --config, -c file        Path to configuration file
          --quiet, -q              Suppress non-error output
          --recursive, -r          Copy directories recursively
          --force, -f              Overwrite existing files
          --buffer-size integer    Buffer size in KB

        """
    ) + "\n\n" + GLOBAL_FLAGS


@testing.effect
def test_renders_variadic_arguments(env: Services[Any]):
    """renders variadic arguments"""
    assert (yield from run_cli("remove", "--help")) == snapshot(
        """
        DESCRIPTION
          Remove files or directories

        USAGE
          mycli remove [flags] <files...>

        ARGUMENTS
          files... string    Files to remove

        FLAGS
          --debug, -d          Enable debug logging
          --config, -c file    Path to configuration file
          --quiet, -q          Suppress non-error output
          --recursive, -r      Remove directories and contents
          --force, -f          Force removal without prompts
          --verbose, -v        Explain what is being done

        """
    ) + "\n\n" + GLOBAL_FLAGS


@testing.effect
def test_renders_deeply_nested_subcommand_help(env: Services[Any]):
    """renders deeply nested subcommand help"""
    assert (yield from run_cli("admin", "users", "list", "--help")) == snapshot(
        """
        DESCRIPTION
          List all users in the system

        USAGE
          mycli admin users list [flags]

        FLAGS
          --debug, -d          Enable debug logging
          --config, -c file    Path to configuration file
          --quiet, -q          Suppress non-error output
          --sudo               Run with elevated privileges
          --format string      Output format (json, table, csv)
          --active             Show only active users
          --verbose, -v        Show detailed information

        """
    ) + "\n\n" + GLOBAL_FLAGS


@testing.effect
def test_renders_mixed_required_and_optional_positional_arguments(env: Services[Any]):
    """renders mixed required and optional positional arguments"""
    assert (yield from run_cli("admin", "users", "create", "--help")) == snapshot(
        """
        DESCRIPTION
          Create a new user account

        USAGE
          mycli admin users create [flags] <username> [<email>]

        ARGUMENTS
          username string    Username for the new user
          email string       Email address (optional) (optional)

        FLAGS
          --debug, -d          Enable debug logging
          --config, -c file    Path to configuration file
          --quiet, -q          Suppress non-error output
          --sudo               Run with elevated privileges
          --role string        User role (admin, user, guest)
          --notify, -n         Send notification email

        """
    ) + "\n\n" + GLOBAL_FLAGS


@testing.effect
def test_renders_intermediate_subcommand_shared_flags_and_children(env: Services[Any]):
    """renders intermediate subcommand shared flags and children"""
    assert (yield from run_cli("admin", "config", "--help")) == snapshot(
        """
        DESCRIPTION
          Manage application configuration

        USAGE
          mycli admin config <subcommand> [flags]

        FLAGS
          --debug, -d             Enable debug logging
          --config, -c file       Path to configuration file
          --quiet, -q             Suppress non-error output
          --sudo                  Run with elevated privileges
          --profile, -p string    Configuration profile to use

        """
    ) + "\n\n" + GLOBAL_FLAGS + "\n\n" + snapshot(
        """
        SUBCOMMANDS
          set    Set configuration values
          get    Get configuration value
        """
    )


@testing.effect
def test_renders_variadic_arguments_with_a_minimum_count(env: Services[Any]):
    """renders variadic arguments with a minimum count"""
    assert (yield from run_cli("admin", "config", "set", "--help")) == snapshot(
        """
        DESCRIPTION
          Set configuration values

        USAGE
          mycli admin config set [flags] <key=value...>

        ARGUMENTS
          key=value... string    Configuration key-value pairs

        FLAGS
          --debug, -d               Enable debug logging
          --config, -c file         Path to configuration file
          --quiet, -q               Suppress non-error output
          --sudo                    Run with elevated privileges
          --profile, -p string      Configuration profile to use
          --config-file, -f file    Write to specific config file

        """
    ) + "\n\n" + GLOBAL_FLAGS


@testing.effect
def test_shared_flags_are_visible_in_subcommand_help_while_local_flags_stay_local(
    env: Services[Any],
):
    """shared flags are visible in subcommand help while local flags stay local"""

    class Model(Config):
        model = Flag.string("model")

    class Tool(Model):
        workspace = Flag.string("workspace")

    class Chat(Config):
        topic = Flag.string("topic")

    root = (
        command.make("tool", Tool)
        .with_shared_flags(Model)
        .with_subcommands(command.make("chat", Chat))
    )
    run = runner(root)
    yield from run(["--help"])
    root_help = [str(line) for line in (yield from testing.log_lines)]
    assert any("--workspace" in line for line in root_help)
    assert any("--model" in line for line in root_help)
    yield from run(["chat", "--help"])
    chat_help = [str(line) for line in (yield from testing.log_lines)][len(root_help) :]
    assert not any("--workspace" in line for line in chat_help)
    assert any("--model" in line for line in chat_help)
    assert any("--topic" in line for line in chat_help)


@testing.effect
def test_includes_inherited_shared_flags_in_subcommand_completions(env: Services[Any]):
    """includes inherited shared flags in subcommand completions"""

    class Workspace(Config):
        workspace = Flag.string("workspace").with_alias("w")

    class Chat(Config):
        topic = Flag.string("topic").with_alias("t")

    root = (
        command.make("tool")
        .with_shared_flags(Workspace)
        .with_subcommands(command.make("chat", Chat))
    )
    yield from runner(root)(["--completions", "bash"])
    script = yield from log_text()
    chat_completions = script[script.index("_tool_chat()") :]
    assert '_filtered_flags+=" --topic -t"' in chat_completions
    assert '_filtered_flags+=" --workspace -w"' in chat_completions


@testing.effect
def test_renders_grouped_subcommands(env: Services[Any]):
    """renders grouped subcommands"""
    ungrouped = command.make("ungrouped").with_description("This command is not in a group")
    init = command.make("init").with_description("Create a new project")
    login = command.make("login").with_description("Authenticate with the platform")
    start = command.make("start").with_description("Start local services")
    stop = command.make("stop").with_description("Stop local services")
    db = command.make("db").with_description("Manage local database")
    projects = command.make("projects").with_description("Manage cloud projects")
    functions = command.make("functions").with_description("Manage edge functions")
    grouped = command.make("tool").with_subcommands(
        group("Quick Start", init, login),
        group("Local Development", start, stop, db),
        group("Management APIs", projects, functions),
        ungrouped,
    )
    yield from runner(grouped)(["--help"])
    assert (yield from log_text()) == snapshot(
        """
        USAGE
          tool <subcommand> [flags]

        """
    ) + "\n\n" + GLOBAL_FLAGS + "\n\n" + snapshot(
        """
        SUBCOMMANDS
          ungrouped    This command is not in a group

        Quick Start:
          init     Create a new project
          login    Authenticate with the platform

        Local Development:
          start    Start local services
          stop     Stop local services
          db       Manage local database

        Management APIs:
          projects     Manage cloud projects
          functions    Manage edge functions
        """
    )


@testing.effect
def test_renders_subcommand_aliases_in_listings(env: Services[Any]):
    """renders subcommand aliases in listings"""
    plan = command.make("plan").with_alias("p").with_description("Draft a plan in your editor")
    yield from runner(command.make("tool").with_subcommands(plan))(["--help"])
    assert (yield from log_text()) == snapshot(
        """
        USAGE
          tool <subcommand> [flags]

        """
    ) + "\n\n" + GLOBAL_FLAGS + "\n\n" + snapshot(
        """
        SUBCOMMANDS
          plan, p    Draft a plan in your editor
        """
    )


@testing.effect
def test_keeps_subcommand_flags_in_aliased_completion_contexts(env: Services[Any]):
    """keeps subcommand flags in aliased completion contexts"""

    class ListConfig(Config):
        format = Flag.literals("format", ["json", "text"])

    root = command.make("ctl").with_subcommands(command.make("list", ListConfig).with_alias("ls"))
    yield from runner(root)(["--completions", "bash"])
    completion = yield from log_text()
    parts = completion.split("_ctl_ls()")
    alias_context = parts[1].split("\n}")[0] if len(parts) > 1 else ""
    assert "--format" in alias_context
