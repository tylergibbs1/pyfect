"""Effect's ``test/cli/Errors.test.ts``."""

from __future__ import annotations

from typing import Any

import pytest

from pyfect import testing
from pyfect.cli import Argument, Config, Flag, command
from pyfect.cli import cli_error as CliError
from pyfect.cli._lexer import lex
from pyfect.cli._parser import parse_args
from pyfect.cli.cli_output import default_formatter
from pyfect.testing import Services

from ._cli_env import base_layer

env = testing.layer_fixture(base_layer, scope="module")


def test_uses_the_unknown_subcommand_class_name_as_its_runtime_tag():
    """uses the UnknownSubcommand class name as its runtime tag"""
    error = CliError.UnknownSubcommand("deplyo", ("deploy",))
    assert error.tag == "UnknownSubcommand"


# --- parse ---------------------------------------------------------------------------


@testing.effect
def test_fails_with_missing_option_when_a_required_flag_is_absent(env: Services[Any]):
    """fails with MissingOption when a required flag is absent"""

    class NeedsValue(Config):
        value = Flag.string("value")

    app = command.make("needs-value", NeedsValue)
    parsed = parse_args(lex([]), app)
    error = yield from app.state.parse(app, parsed).flip()
    assert isinstance(error, CliError.MissingOption)
    assert error.option == "value"


def test_throws_duplicate_option_when_shared_parent_and_child_flags_reuse_a_name():
    """throws DuplicateOption when shared parent and child flags reuse a name"""

    class Shared(Config):
        shared = Flag.string("shared")

    parent = command.make("parent").with_shared_flags(Shared)
    child = command.make("child", Shared)
    with pytest.raises(CliError.DuplicateOption) as raised:
        parent.with_subcommands(child)
    assert raised.value.option == "shared"
    assert raised.value.parent_command == "parent"
    assert raised.value.child_command == "child"


def test_allows_parent_local_flags_to_reuse_child_flag_names():
    """allows parent local flags to reuse child flag names"""

    class Shared(Config):
        shared = Flag.string("shared")

    parent = command.make("parent", Shared)
    child = command.make("child", Shared)
    parent.with_subcommands(child)


def test_accumulates_multiple_unrecognized_option_errors():
    """accumulates multiple UnrecognizedOption errors"""

    class Test(Config):
        verbose = Flag.boolean("verbose")

    parsed = parse_args(lex(["--unknown1", "--unknown2"]), command.make("test", Test))
    assert len(parsed.errors) == 2
    assert all(isinstance(error, CliError.UnrecognizedOption) for error in parsed.errors)


def test_accumulates_unknown_subcommand_error_with_suggestions():
    """accumulates UnknownSubcommand error with suggestions"""
    app = command.make("app").with_subcommands(command.make("deploy"))
    parsed = parse_args(lex(["deplyo"]), app)
    [error] = parsed.errors
    assert isinstance(error, CliError.UnknownSubcommand)
    assert error.subcommand == "deplyo"
    assert "deploy" in error.suggestions


@testing.effect
def test_fails_with_unexpected_argument_when_a_bounded_variadic_leaves_operands(
    env: Services[Any],
):
    """fails with UnexpectedArgument when a bounded variadic leaves operands"""

    class Test(Config):
        values = Argument.string("value").variadic(max=2)

    app = command.make("test", Test)
    error = yield from app.state.parse(app, parse_args(lex(["one", "two", "three"]), app)).flip()
    assert isinstance(error, CliError.UnexpectedArgument)
    assert error.arguments == ("three",)


@testing.effect
def test_allows_a_bounded_variadic_to_leave_an_operand_for_a_following_argument(
    env: Services[Any],
):
    """allows a bounded variadic to leave an operand for a following argument"""

    class Test(Config):
        values = Argument.string("value").variadic(max=2)
        destination = Argument.string("destination")

    app = command.make("test", Test)
    result = yield from app.state.parse(app, parse_args(lex(["one", "two", "destination"]), app))
    assert isinstance(result, Test)
    assert result.values == ("one", "two")
    assert result.destination == "destination"


@testing.effect
def test_fails_with_unexpected_argument_when_a_fixed_argument_leaves_operands(
    env: Services[Any],
):
    """fails with UnexpectedArgument when a fixed argument leaves operands"""

    class Test(Config):
        value = Argument.string("value")

    app = command.make("test", Test)
    error = yield from app.state.parse(app, parse_args(lex(["one", "two"]), app)).flip()
    assert isinstance(error, CliError.UnexpectedArgument)
    assert error.arguments == ("two",)


# --- error formatting ----------------------------------------------------------------


def test_escapes_control_characters_in_an_unrecognized_flag():
    """escapes control characters in an unrecognized flag"""
    formatter = default_formatter(colors=False)
    error = CliError.UnrecognizedOption("--foo\x1b]52;c;bWFsaWNpb3Vz\x07")
    assert (
        formatter.format_cli_error(error) == "Unrecognized flag: --foo\\x1b]52;c;bWFsaWNpb3Vz\\x07"
    )


def test_escapes_control_characters_in_an_unknown_subcommand_with_colors_enabled():
    """escapes control characters in an unknown subcommand with colors enabled"""
    formatter = default_formatter(colors=True)
    error = CliError.UnknownSubcommand("deplyo\x1b]8;;https://example.com\x07")
    assert formatter.format_error(error) == (
        "\n\x1b[1m\x1b[31mERROR\x1b[0m\n"
        '  Unknown subcommand "deplyo\\x1b]8;;https://example.com\\x07"\x1b[0m'
    )


def test_escapes_control_characters_in_an_invalid_argument_value_without_colors():
    """escapes control characters in an invalid argument value without colors"""
    formatter = default_formatter(colors=False)
    error = CliError.InvalidValue(
        "count", "12\x1b]52;c;bWFsaWNpb3Vz\x07\x7f", "an integer", "argument"
    )
    assert formatter.format_errors([error]) == (
        "\nERROR\n"
        '  Invalid value for argument <count>: "12\\x1b]52;c;bWFsaWNpb3Vz\\x07\\x7f". '
        "Expected: an integer"
    )


def test_preserves_multi_line_suggestion_blocks():
    """preserves multi-line suggestion blocks"""
    formatter = default_formatter(colors=False)
    errors = [
        CliError.UnrecognizedOption("--deplyo", ("--deploy",)),
        CliError.UnknownSubcommand("usrs", ("users",), ("app",)),
    ]
    assert formatter.format_errors(errors) == "\n".join(
        [
            "",
            "ERRORS",
            "  Unrecognized flag: --deplyo",
            "",
            "  Did you mean this?",
            "    --deploy",
            '  Unknown subcommand "usrs" for "app"',
            "",
            "  Did you mean this?",
            "    users",
        ]
    )


def test_preserves_line_feeds_and_tabs_in_error_messages():
    """preserves line feeds and tabs in error messages"""
    formatter = default_formatter(colors=False)
    error = CliError.InvalidValue("count", "twelve", "one line\n\tcontinuation", "argument")
    assert formatter.format_cli_error(error) == (
        'Invalid value for argument <count>: "twelve". Expected: one line\n\tcontinuation'
    )


def test_formats_single_error_with_error_header():
    """formats single error with ERROR header"""
    output = default_formatter(colors=False).format_errors([CliError.MissingOption("value")])
    assert "ERROR" in output
    assert "Missing required flag" in output


def test_formats_multiple_errors_with_errors_header():
    """formats multiple errors with ERRORS header"""
    output = default_formatter(colors=False).format_errors(
        [CliError.UnrecognizedOption("--foo"), CliError.UnrecognizedOption("--bar")]
    )
    assert "ERRORS" in output
    assert "--foo" in output
    assert "--bar" in output


def test_returns_empty_string_for_empty_array():
    """returns empty string for empty array"""
    assert default_formatter(colors=False).format_errors([]) == ""


# --- UserError -----------------------------------------------------------------------


def test_prefers_the_user_facing_message_over_the_cause():
    """prefers the user-facing message over the cause"""
    error = CliError.UserError(
        Exception("internal details"), user_message="Could not deploy the application"
    )
    assert error.message == "Could not deploy the application"


def test_uses_an_error_cause_message_as_the_fallback():
    """uses an Error cause message as the fallback"""
    assert CliError.UserError(Exception("Connection refused")).message == "Connection refused"


def test_uses_a_string_cause_as_the_fallback():
    """uses a string cause as the fallback"""
    assert CliError.UserError("Connection refused").message == "Connection refused"


def test_uses_a_generic_fallback_for_causes_without_a_message():
    """uses a generic fallback for causes without a message"""
    assert CliError.UserError({"status": 503}).message == "An error occurred"


def test_falls_back_past_empty_user_facing_and_cause_messages():
    """falls back past empty user-facing and cause messages"""
    empty_user_message = CliError.UserError(Exception("Connection refused"), user_message="")
    assert empty_user_message.message == "Connection refused"
    assert CliError.UserError("").message == "An error occurred"


def test_allows_runtime_reporting_before_the_cli_runner_renders_it():
    """allows runtime reporting before the CLI runner renders it"""
    assert CliError.UserError("failed").error_reported is True


def test_escapes_control_characters_in_the_user_facing_message():
    """escapes control characters in the user-facing message"""
    error = CliError.UserError(
        "internal details", user_message="Deployment failed\x1b]52;c;bWFsaWNpb3Vz\x07"
    )
    assert default_formatter(colors=False).format_error(error) == (
        "\nERROR\n  Deployment failed\\x1b]52;c;bWFsaWNpb3Vz\\x07"
    )


def test_formats_the_resolved_fallback_message_with_other_cli_errors():
    """formats the resolved fallback message with other CLI errors"""
    error = CliError.UserError(Exception("Connection refused"))
    assert default_formatter(colors=False).format_errors([error]) == "\nERROR\n  Connection refused"


# --- ValidationError -----------------------------------------------------------------


def test_renders_its_message_like_other_parse_errors_and_can_be_carried_by_show_help():
    """renders its message like other parse errors and can be carried by ShowHelp"""
    error = CliError.ValidationError("--use-api and --use-docker are mutually exclusive")
    help = CliError.ShowHelp(("download",), (error,))
    assert error.message == "--use-api and --use-docker are mutually exclusive"
    assert default_formatter(colors=False).format_errors(help.errors) == (
        "\nERROR\n  --use-api and --use-docker are mutually exclusive"
    )


# --- InvalidValue --------------------------------------------------------------------


def test_labels_a_bare_expected_description():
    """labels a bare expected description"""
    error = CliError.InvalidValue("size", "bogus", '"small" | "medium" | "large"', "flag")
    assert error.message == (
        'Invalid value for flag --size: "bogus". Expected: "small" | "medium" | "large"'
    )


def test_does_not_double_the_prefix_for_an_expected_sentence():
    """does not double the prefix for an Expected sentence"""
    error = CliError.InvalidValue("count", "3.14", "Expected an integer, got 3.14", "argument")
    assert error.message == (
        'Invalid value for argument <count>: "3.14". Expected an integer, got 3.14'
    )
    labeled = CliError.InvalidValue("count", "x", "Expected: an integer", "flag")
    assert labeled.message == 'Invalid value for flag --count: "x". Expected: an integer'


def test_does_not_double_the_prefix_for_a_missing_flag_value():
    """does not double the prefix for a missing flag value"""
    error = CliError.InvalidValue(
        "count", "", 'Expected a string representing a finite number, got ""', "flag"
    )
    assert error.message == (
        'Missing value for flag --count. Expected a string representing a finite number, got ""'
    )


# --- UnexpectedArgument --------------------------------------------------------------


def test_formats_one_or_more_unexpected_positional_arguments():
    """formats one or more unexpected positional arguments"""
    single = CliError.UnexpectedArgument(("extra",))
    multiple = CliError.UnexpectedArgument(("first", "second"))
    assert single.message == 'Unexpected positional argument: "extra"'
    assert multiple.message == 'Unexpected positional arguments: "first", "second"'


# --- userMessage ---------------------------------------------------------------------


def test_get_user_message_reads_user_error_messages_and_ignores_values_without_the_annotation():
    """getUserMessage reads UserError messages and ignores values without the annotation"""
    assert CliError.get_user_message(CliError.UserError("failed")) == "failed"
    assert CliError.get_user_message({"user_message": "nope"}) is None
    assert CliError.get_user_message(Exception("nope")) is None
