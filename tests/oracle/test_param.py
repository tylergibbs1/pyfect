"""Effect's ``test/cli/Param.test.ts``.

Omitted: "preserves __proto__ as an own makeSingle option" (JavaScript
prototype pollution; Python objects have no ``__proto__``)."""

from __future__ import annotations

from typing import Any

import pyfect as fx
from pyfect import config as config_
from pyfect import config_provider, layer, testing
from pyfect.cli import Argument, Config, Flag, command, prompt
from pyfect.cli import cli_error as CliError
from pyfect.cli import param as Param
from pyfect.cli._lexer import lex
from pyfect.cli._parser import parse_args
from pyfect.cli.param import ParsedArgs
from pyfect.cli.terminal_capabilities import Capabilities, TerminalCapabilities
from pyfect.config_provider import CurrentConfigProvider
from pyfect.result import Err
from pyfect.testing import Services

from ._cli_env import base_layer, capabilities_layer
from ._mock_terminal import display_lines, input_key, input_text

env = testing.layer_fixture(layer.merge(base_layer, capabilities_layer()), scope="function")

EMPTY = ParsedArgs({}, ())


def flags(**values: list[str]) -> ParsedArgs:
    return ParsedArgs({name.replace("_", "-"): tuple(v) for name, v in values.items()}, ())


@testing.effect
def test_never_remains_an_always_failing_flag_sentinel(env: Services[Any]):
    """Never remains an always-failing flag sentinel"""
    for sentinel in [Flag.never().param, Param.never(Param.FLAG)]:
        missing = yield from sentinel.parse(EMPTY).flip()
        assert isinstance(missing, CliError.MissingOption)
        supplied = yield from sentinel.parse(ParsedArgs({"__never__": ("value",)}, ())).flip()
        assert isinstance(supplied, CliError.InvalidValue)


@testing.effect
def test_never_remains_an_always_failing_argument_sentinel(env: Services[Any]):
    """Never remains an always-failing argument sentinel"""
    for sentinel in [Argument.never().param, Param.never(Param.ARGUMENT)]:
        missing = yield from sentinel.parse(EMPTY).flip()
        assert isinstance(missing, CliError.MissingArgument)
        supplied = yield from sentinel.parse(ParsedArgs({}, ("value",))).flip()
        assert isinstance(supplied, CliError.InvalidValue)


# --- boolean -------------------------------------------------------------------------


@testing.effect
def test_returns_missing_option_when_a_boolean_flag_is_omitted(env: Services[Any]):
    """returns MissingOption when a boolean flag is omitted"""
    error = yield from Flag.boolean("verbose").parse(EMPTY).flip()
    assert isinstance(error, CliError.MissingOption)


@testing.effect
def test_uses_the_requested_default_when_a_boolean_flag_is_omitted(env: Services[Any]):
    """uses the requested default when a boolean flag is omitted"""
    _, value = yield from Flag.boolean("verbose").with_default(True).parse(EMPTY)
    assert value is True


@testing.effect
def test_restores_switch_behavior_with_a_false_default(env: Services[Any]):
    """restores switch behavior with a false default"""
    _, value = yield from Flag.boolean("verbose").with_default(False).parse(EMPTY)
    assert value is False


def test_recognizes_the_alternate_flag_declared_by_or_else():
    """recognizes the alternate flag declared by orElse"""

    class App(Config):
        config = Flag.string("config").or_else(lambda: Flag.string("config-url"))

    parsed = parse_args(lex(["--config-url", "https://example.com"]), command.make("app", App))
    assert parsed.errors == ()
    assert tuple(parsed.flags["config-url"]) == ("https://example.com",)


@testing.effect
def test_registers_and_parses_the_alternate_flag_declared_by_or_else_result(env: Services[Any]):
    """registers and parses the alternate flag declared by orElseResult"""
    flag = Flag.string("config").or_else_result(lambda: Flag.string("config-url"))
    assert [single.name for single in flag.param.singles()] == ["config", "config-url"]
    _, result = yield from flag.parse(flags(config_url=["https://example.com"]))
    assert result == Err("https://example.com")


# --- optional ------------------------------------------------------------------------


@testing.effect
def test_returns_none_when_an_optional_boolean_flag_is_omitted(env: Services[Any]):
    """returns none when an optional boolean flag is omitted"""
    _, value = yield from Flag.boolean("verbose").optional().parse(EMPTY)
    assert value is None


@testing.effect
def test_returns_some_false_when_an_optional_boolean_flag_is_explicitly_disabled(
    env: Services[Any],
):
    """returns some false when an optional boolean flag is explicitly disabled"""
    _, value = yield from Flag.boolean("verbose").optional().parse(flags(verbose=["false"]))
    assert value is False


@testing.effect
def test_supports_alternative_flags(env: Services[Any]):
    """supports alternative flags"""
    flag = Flag.string("config").or_else(lambda: Flag.string("config-url")).optional()
    _, value = yield from flag.parse(flags(config=["config.json"]))
    assert value == "config.json"


@testing.effect
def test_uses_the_default_when_a_required_variadic_argument_is_omitted(env: Services[Any]):
    """uses the default when a required variadic argument is omitted"""
    argument = Argument.string("files").at_least(1).with_default(("README.md",))
    result = yield from argument.parse(EMPTY)
    assert result == ((), ("README.md",))


@testing.effect
def test_rejects_repeated_occurrences_of_a_single_valued_flag(env: Services[Any]):
    """rejects repeated occurrences of a single-valued flag"""
    flag = Flag.integer("window-minutes")
    for values in [["2", "3"], ["2", "not-an-integer"]]:
        error = yield from flag.parse(flags(window_minutes=values)).flip()
        assert isinstance(error, CliError.InvalidValue)
        assert error.option == "window-minutes"
        assert error.value == "2 occurrences"


# --- withFallbackPrompt --------------------------------------------------------------


@testing.effect
def test_prompts_for_missing_flag_values_and_preserves_remaining_args(env: Services[Any]):
    """prompts for missing flag values and preserves remaining args"""
    flag = Flag.string("name").with_fallback_prompt(prompt.string("Name"))
    yield from input_text("Chandra")
    yield from input_key("enter")
    remaining, value = yield from flag.parse(ParsedArgs({}, ("tail",)))
    assert value == "Chandra"
    assert remaining == ("tail",)


@testing.effect
def test_does_not_prompt_when_flag_value_is_provided(env: Services[Any]):
    """does not prompt when flag value is provided"""
    flag = Flag.string("name").with_fallback_prompt(prompt.string("Name"))
    _, value = yield from flag.parse(flags(name=["Ava"]))
    assert value == "Ava"


@testing.effect
def test_prompts_for_missing_arguments(env: Services[Any]):
    """prompts for missing arguments"""
    argument = Argument.string("file").with_fallback_prompt(prompt.string("File"))
    yield from input_text("notes.txt")
    yield from input_key("enter")
    remaining, value = yield from argument.parse(EMPTY)
    assert value == "notes.txt"
    assert remaining == ()


def _counting_prompt(calls: list[int], message: str) -> fx.Effect[prompt.Prompt[str]]:
    def build() -> prompt.Prompt[str]:
        calls.append(1)
        return prompt.string(message)

    return fx.sync(build)


@testing.effect
def test_builds_flag_fallback_prompts_from_effects_lazily(env: Services[Any]):
    """builds flag fallback prompts from effects lazily"""
    calls: list[int] = []
    flag = Flag.string("name").with_fallback_prompt(_counting_prompt(calls, "Name from effect"))
    _, provided = yield from flag.parse(flags(name=["Ava"]))
    assert provided == "Ava"
    assert len(calls) == 0
    yield from input_text("Mia")
    yield from input_key("enter")
    remaining, prompted = yield from flag.parse(ParsedArgs({}, ("tail",)))
    assert prompted == "Mia"
    assert remaining == ("tail",)
    assert len(calls) == 1


@testing.effect
def test_builds_argument_fallback_prompts_from_effects_lazily(env: Services[Any]):
    """builds argument fallback prompts from effects lazily"""
    calls: list[int] = []
    argument = Argument.string("file").with_fallback_prompt(
        _counting_prompt(calls, "File from effect")
    )
    provided_remaining, provided = yield from argument.parse(ParsedArgs({}, ("notes.txt", "tail")))
    assert provided == "notes.txt"
    assert provided_remaining == ("tail",)
    assert len(calls) == 0
    yield from input_text("draft.md")
    yield from input_key("enter")
    prompted_remaining, prompted = yield from argument.parse(EMPTY)
    assert prompted == "draft.md"
    assert prompted_remaining == ()
    assert len(calls) == 1


@testing.effect
def test_propagates_errors_from_effectful_fallback_prompt_creation(env: Services[Any]):
    """propagates errors from effectful fallback prompt creation"""
    failure = CliError.UserError("failed to build prompt")
    built: fx.Effect[prompt.Prompt[str], CliError.CliError] = fx.fail(failure)
    flag: Flag[str] = Flag.string("name").with_fallback_prompt(built)
    error = yield from flag.parse(EMPTY).flip()
    assert error is failure


@testing.effect
def test_prefers_defaults_over_fallback_prompts(env: Services[Any]):
    """prefers defaults over fallback prompts"""
    flag = Flag.string("name").with_default("guest").with_fallback_prompt(prompt.string("Name"))
    _, value = yield from flag.parse(EMPTY)
    assert value == "guest"


@testing.effect
def test_does_not_prompt_for_invalid_flag_values(env: Services[Any]):
    """does not prompt for invalid flag values"""
    flag = Flag.integer("count").with_fallback_prompt(prompt.string("Count"))
    error = yield from flag.parse(flags(count=["nope"])).flip()
    assert isinstance(error, CliError.InvalidValue)


@testing.effect
def test_does_not_prompt_for_invalid_argument_values(env: Services[Any]):
    """does not prompt for invalid argument values"""
    argument = Argument.integer("count").with_fallback_prompt(prompt.string("Count"))
    error = yield from argument.parse(ParsedArgs({}, ("nope",))).flip()
    assert isinstance(error, CliError.InvalidValue)


@testing.effect
def test_prompts_for_missing_boolean_flags(env: Services[Any]):
    """prompts for missing boolean flags"""
    flag = Flag.boolean("verbose").with_fallback_prompt(prompt.confirm("Verbose"))
    yield from input_key("y")
    _, value = yield from flag.parse(EMPTY)
    assert value is True


@testing.effect
def test_uses_an_explicitly_disabled_boolean_before_prompting(env: Services[Any]):
    """uses an explicitly disabled boolean before prompting"""
    flag = Flag.boolean("verbose").with_fallback_prompt(prompt.confirm("Verbose"))
    _, value = yield from flag.parse(flags(verbose=["false"]))
    assert value is False


@testing.effect
def test_returns_missing_option_when_prompt_is_cancelled(env: Services[Any]):
    """returns MissingOption when prompt is cancelled"""
    flag = Flag.string("name").with_fallback_prompt(prompt.string("Name"))
    yield from input_key("c", ctrl=True)
    error = yield from flag.parse(EMPTY).flip()
    assert isinstance(error, CliError.MissingOption)


@testing.effect
def test_returns_missing_argument_when_argument_prompt_is_cancelled(env: Services[Any]):
    """returns MissingArgument when argument prompt is cancelled"""
    argument = Argument.string("file").with_fallback_prompt(prompt.string("File"))
    yield from input_key("c", ctrl=True)
    error = yield from argument.parse(EMPTY).flip()
    assert isinstance(error, CliError.MissingArgument)


@testing.effect
def test_returns_the_missing_error_without_prompting_when_the_terminal_cannot_prompt(
    env: Services[Any],
):
    """returns the missing error without prompting when the terminal cannot prompt"""
    calls: list[int] = []
    flag = Flag.string("name").with_fallback_prompt(_counting_prompt(calls, "Value"))
    argument = Argument.string("file").with_fallback_prompt(_counting_prompt(calls, "Value"))

    def body():
        yield from input_key("c", ctrl=True)
        flag_error = yield from flag.parse(EMPTY).flip()
        argument_error = yield from argument.parse(EMPTY).flip()
        assert isinstance(flag_error, CliError.MissingOption)
        assert isinstance(argument_error, CliError.MissingArgument)
        assert len(calls) == 0
        assert (yield from display_lines()) == []

    yield from fx.gen(body).pipe(
        fx.provide_service(TerminalCapabilities, Capabilities(False, False, False))
    )


# --- withFallbackConfig --------------------------------------------------------------


def with_env[A, E, R](eff: fx.Effect[A, E, R], env: dict[str, str]) -> fx.Effect[A, E, R]:
    return eff.pipe(fx.provide_service(CurrentConfigProvider, config_provider.from_env(env)))


@testing.effect
def test_uses_config_provider_when_a_boolean_flag_is_missing(env: Services[Any]):
    """uses ConfigProvider when a boolean flag is missing"""
    flag = Flag.boolean("verbose").with_fallback_config(config_.boolean("VERBOSE"))
    _, value = yield from with_env(flag.parse(EMPTY), {"VERBOSE": "true"})
    assert value is True


@testing.effect
def test_uses_an_explicitly_disabled_boolean_before_reading_config_fallbacks(
    env: Services[Any],
):
    """uses an explicitly disabled boolean before reading config fallbacks"""
    flag = Flag.boolean("verbose").with_fallback_config(config_.boolean("VERBOSE"))
    _, value = yield from with_env(flag.parse(flags(verbose=["false"])), {"VERBOSE": "true"})
    assert value is False


@testing.effect
def test_uses_config_provider_when_a_flag_is_missing(env: Services[Any]):
    """uses ConfigProvider when a flag is missing"""
    flag = Flag.string("name").with_fallback_config(config_.string("NAME"))
    _, value = yield from with_env(flag.parse(EMPTY), {"NAME": "Ava"})
    assert value == "Ava"


@testing.effect
def test_uses_flag_values_before_reading_config_fallbacks(env: Services[Any]):
    """uses flag values before reading config fallbacks"""
    flag = Flag.string("name").with_fallback_config(config_.string("NAME"))
    _, value = yield from with_env(flag.parse(flags(name=["Maya"])), {"NAME": "Ava"})
    assert value == "Maya"


@testing.effect
def test_uses_config_provider_when_an_argument_is_missing(env: Services[Any]):
    """uses ConfigProvider when an argument is missing"""
    argument = Argument.string("repository").with_fallback_config(config_.string("REPOSITORY"))
    _, value = yield from with_env(argument.parse(EMPTY), {"REPOSITORY": "repo"})
    assert value == "repo"


@testing.effect
def test_returns_missing_option_when_config_is_missing(env: Services[Any]):
    """returns MissingOption when config is missing"""
    flag = Flag.string("name").with_fallback_config(config_.string("NAME"))
    error = yield from with_env(flag.parse(EMPTY).flip(), {})
    assert isinstance(error, CliError.MissingOption)


@testing.effect
def test_returns_invalid_value_when_config_fails_to_parse(env: Services[Any]):
    """returns InvalidValue when config fails to parse"""
    flag = Flag.integer("count").with_fallback_config(config_.integer("COUNT"))
    error = yield from with_env(flag.parse(EMPTY).flip(), {"COUNT": "nope"})
    assert isinstance(error, CliError.InvalidValue)
