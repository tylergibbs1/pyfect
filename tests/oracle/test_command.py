"""Effect's ``test/cli/Command.test.ts``.

Adapted: a command's own config subclasses its shared flags' config in
pyfect (``class Tool(Shared)``), so "sees only the input that exists where
it is applied in the pipeline" checks that validators before
``with_shared_flags`` see both fields, where Effect's see only the local
ones; stacked ``with_shared_flags`` calls likewise take subclassing
configs, and the shared-negation case builds its ``Config`` with ``type``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import layer, redacted, testing
from pyfect.cli import (
    Action,
    Argument,
    Config,
    Flag,
    Setting,
    cli_config,
    cli_output,
    command,
    global_flag,
)
from pyfect.cli.cli_error import ShowHelp
from pyfect.cli.help_doc import HelpDoc
from pyfect.cli.prompt import PromptTheme, make_theme
from pyfect.context import Context, Tag
from pyfect.exit import Failure
from pyfect.path import Path
from pyfect.testing import Services

from . import _comprehensive_cli as cli
from ._cli_env import TestAction, base_layer, get_actions, test_layer
from ._mock_terminal import display_lines, input_key, input_text

env = testing.layer_fixture(test_layer, scope="function")

ESC = "\x1b"
type AnyCommand = command.Command[Any, Any, Any, Any]


def runner(app: AnyCommand):
    return command.run_with(app, version="1.0.0")


def ignore_help[A, E, R](eff: fx.Effect[A, E, R]) -> fx.Effect[A | None, E, R]:
    return eff.catch_if(lambda e: isinstance(e, ShowHelp), lambda _: fx.succeed(None))


def lines_text(lines: list[object]) -> str:
    return "\n".join(map(str, lines))


def all_output():
    """The test console's log lines and the mock terminal's frames."""
    logs = yield from testing.log_lines
    frames = yield from display_lines()
    return lines_text([*logs, *frames])


def error_text():
    return lines_text((yield from testing.error_lines))


def recorder[C](seen: list[C]) -> Callable[[C], fx.Effect[None]]:
    return lambda config: fx.sync(lambda: seen.append(config))


@testing.effect
def test_omits_styles_from_wizard_headings_and_command_blocks_when_colors_are_disabled(
    env: Services[Any],
):
    """omits styles from wizard headings and command blocks when colors are disabled"""

    class Greet(Config):
        name = Flag.string("name")

    app = command.make("greet", Greet, lambda _: fx.void)

    def body():
        fiber = yield from runner(app)(["--wizard"]).fork()
        yield from input_text("Alice")
        yield from input_key("enter")
        yield from input_key("enter")
        yield from fiber.join()

    yield from fx.gen(body).pipe(fx.provide_service(PromptTheme, make_theme(colors=False)))
    logs = lines_text((yield from testing.log_lines))
    assert "$ greet --name Alice" in logs
    assert re.search(rf"{ESC}\[[0-9;]*m", logs) is None


# --- annotations ---------------------------------------------------------------------


_UNCOLORED = cli_output.default_formatter(colors=False)


@dataclass(frozen=True, slots=True)
class _CapturingFormatter:
    docs: list[HelpDoc]
    inner: cli_output.Formatter = _UNCOLORED

    def format_help_doc(self, doc: HelpDoc) -> str:
        self.docs.append(doc)
        return ""

    def format_cli_error(self, error: Any) -> str:
        return self.inner.format_cli_error(error)

    def format_error(self, error: Any) -> str:
        return self.inner.format_error(error)

    def format_version(self, name: str, version: str) -> str:
        return self.inner.format_version(name, version)

    def format_errors(self, errors: Any) -> str:
        return self.inner.format_errors(errors)


bare_env = testing.layer_fixture(base_layer, scope="function")


class Team(Tag[str]): ...


class Priority(Tag[int]): ...


class Scope(Tag[str]): ...


@testing.effect
def test_should_expose_annotations_in_help_docs(bare_env: Services[Any]):
    """should expose annotations in help docs"""
    docs: list[HelpDoc] = []
    app = command.make("deploy").annotate(Team, "runtime").annotate_merge(Context.make(Priority, 2))
    yield from runner(app)(["--help"]).pipe(
        fx.provide_service(cli_output.CurrentFormatter, _CapturingFormatter(docs))
    )
    assert len(docs) == 1
    assert docs[0].annotations.get(Team) == "runtime"
    assert docs[0].annotations.get(Priority) == 2


@testing.effect
def test_should_keep_annotations_when_adding_subcommands(bare_env: Services[Any]):
    """should keep annotations when adding subcommands"""
    docs: list[HelpDoc] = []
    child = command.make("child").annotate(Scope, "child")
    app = command.make("root").annotate(Scope, "root").with_subcommands(child)
    run = runner(app)
    formatter = fx.provide_service(cli_output.CurrentFormatter, _CapturingFormatter(docs))
    yield from run(["--help"]).pipe(formatter)
    yield from run(["child", "--help"]).pipe(formatter)
    assert len(docs) == 2
    assert docs[0].annotations.get(Scope) == "root"
    assert docs[1].annotations.get(Scope) == "child"


# --- run -----------------------------------------------------------------------------


class _Greet(Config):
    name = Flag.string("name")
    count = Argument.integer("count")


@testing.effect
def test_should_invoke_the_wizard_programmatically_from_a_command_handler(env: Services[Any]):
    """should invoke the wizard programmatically from a command handler"""
    captured: list[tuple[str, ...]] = []
    target = command.make("greet", _Greet)
    launcher = command.make(
        "launcher",
        Config,
        lambda _: command.wizard(target).map(captured.append),
    )
    fiber = yield from runner(launcher)([]).fork()
    yield from input_text("Alice")
    yield from input_key("enter")
    yield from input_text("2")
    yield from input_key("enter")
    yield from fiber.join()
    assert captured == [("greet", "--name", "Alice", "2")]


class _Name(Config):
    name = Flag.string("name")


@testing.effect
def test_should_run_wizard_generated_arguments_with_wizard(env: Services[Any]):
    """should run wizard-generated arguments with --wizard"""
    captured: list[str] = []
    app = command.make("greet", _Name, lambda c: fx.sync(lambda: captured.append(c.name)))
    fiber = yield from runner(app)(["--wizard"]).fork()
    yield from input_text("Alice Smith")
    yield from input_key("enter")
    yield from input_key("enter")
    yield from fiber.join()
    assert captured == ["Alice Smith"]
    output = yield from all_output()
    for text in [
        "Command wizard",
        "Build a command interactively. Press Ctrl+C to cancel.",
        "Current command",
        "ROOT",
        "FLAGS",
        "Name (--name)",
        "Command ready",
        "$ greet --name 'Alice Smith'",
        "Run this command?",
    ]:
        assert text in output


@testing.effect
def test_should_parse_negative_numbers_as_flag_and_argument_values(env: Services[Any]):
    """should parse negative numbers as flag and argument values"""

    class Geo(Config):
        lat = Flag.finite("lat")
        lon = Flag.finite("lon")
        offset = Argument.integer("offset")

    captured: list[tuple[float, float, int]] = []
    app = command.make(
        "geo", Geo, lambda c: fx.sync(lambda: captured.append((c.lat, c.lon, c.offset)))
    )
    yield from runner(app)(["--lat", "-40.41", "--lon", "-3.70", "-2"])
    assert captured == [(-40.41, -3.7, -2)]


@testing.effect
def test_should_run_negative_integer_flag_values_with_wizard(env: Services[Any]):
    """should run negative integer flag values with --wizard"""

    class Demo(Config):
        offset = Flag.integer("offset")

    captured: list[int] = []
    app = command.make("demo", Demo, lambda c: fx.sync(lambda: captured.append(c.offset)))
    fiber = yield from runner(app)(["--wizard"]).fork()
    yield from input_text("-2")
    yield from input_key("enter")
    yield from input_key("enter")
    yield from fiber.join()
    assert captured == [-2]
    assert "$ demo --offset=-2" in (yield from all_output())


class _Value(Config):
    value = Flag.string("value")


@pytest.mark.parametrize(
    ("value", "expected_args"),
    [
        ("-v", ["--value=-v"]),
        ("--verbose", ["--value=--verbose"]),
        ("--", ["--value=--"]),
        ("--mode=x=y", ["--value=--mode=x=y"]),
        ("plain", ["--value", "plain"]),
        ("", ["--value", ""]),
        ("-", ["--value", "-"]),
    ],
)
@testing.effect
def test_should_round_trip_wizard_flag_value(
    env: Services[Any], value: str, expected_args: list[str]
):
    """should round trip wizard flag value ${JSON.stringify(value)}"""
    captured: list[str] = []
    app = command.make("demo", _Value, lambda c: fx.sync(lambda: captured.append(c.value)))
    fiber = yield from command.wizard(app).fork()
    yield from input_text(value)
    yield from input_key("enter")
    args = yield from fiber.join()
    assert args == ("demo", *expected_args)
    yield from runner(app)(args[1:])
    assert captured == [value]


@testing.effect
def test_should_round_trip_mixed_repeated_wizard_flag_values(env: Services[Any]):
    """should round trip mixed repeated wizard flag values"""

    class Demo(Config):
        value = Flag.string("value").at_least(1)

    values = ["-v", "plain", "--name=x", ""]
    captured: list[tuple[str, ...]] = []
    app = command.make("demo", Demo, lambda c: fx.sync(lambda: captured.append(c.value)))
    fiber = yield from command.wizard(app).fork()
    yield from input_key("backspace")
    yield from input_text("4")
    yield from input_key("enter")
    for value in values:
        yield from input_text(value)
        yield from input_key("enter")
    args = yield from fiber.join()
    assert args == (
        "demo",
        "--value=-v",
        "--value",
        "plain",
        "--value=--name=x",
        "--value",
        "",
    )
    yield from runner(app)(args[1:])
    assert captured == [tuple(values)]


@testing.effect
def test_should_redact_option_looking_values_in_wizard_command_output(env: Services[Any]):
    """should redact option-looking values in wizard command output"""

    class Login(Config):
        password = Flag.redacted("password")
        account = Argument.string("account")

    secret = "-hunter2-secret"
    captured: list[tuple[str, str]] = []
    app = command.make(
        "login",
        Login,
        lambda c: fx.sync(lambda: captured.append((redacted.value(c.password), c.account))),
    )
    fiber = yield from runner(app)(["--wizard"]).fork()
    yield from input_text(secret)
    yield from input_key("enter")
    yield from input_text("alice")
    yield from input_key("enter")
    yield from input_key("enter")
    yield from fiber.join()
    output = yield from all_output()
    current = output[output.index("Current command") : output.index("Command ready")]
    ready = output[output.index("Command ready") :]
    assert captured == [(secret, "alice")]
    assert "--password=<redacted>" in current
    assert "--password=<redacted>" in ready
    assert secret not in output


@testing.effect
def test_should_print_a_message_when_wizard_mode_is_cancelled(env: Services[Any]):
    """should print a message when wizard mode is cancelled"""
    invoked: list[bool] = []
    app = command.make("greet", _Name, lambda _: fx.sync(lambda: invoked.append(True)))
    fiber = yield from runner(app)(["--wizard"]).fork()
    yield from input_key("c", ctrl=True)
    yield from fiber.join()
    assert invoked == []
    assert "Wizard cancelled." in (yield from all_output())


@testing.effect
def test_should_render_boolean_wizard_values_consistently(env: Services[Any]):
    """should render boolean wizard values consistently"""

    class Deploy(Config):
        dry_run = Flag.boolean("dry-run")

    captured: list[bool] = []
    app = command.make("deploy", Deploy, lambda c: fx.sync(lambda: captured.append(c.dry_run)))
    fiber = yield from runner(app)(["--wizard"]).fork()
    yield from input_key("y")
    yield from input_key("enter")
    yield from fiber.join()
    output = yield from all_output()
    assert captured == [True]
    assert "Dry run (--dry-run)" in output
    assert "deploy --dry-run true" in output
    assert "on / off" not in output


@testing.effect
def test_should_start_wizard_mode_at_a_selected_subcommand(env: Services[Any]):
    """should start wizard mode at a selected subcommand"""

    class Child(Config):
        value = Argument.string("value")

    captured: list[str] = []
    child = command.make("child", Child, lambda c: fx.sync(lambda: captured.append(c.value)))
    app = command.make("root").with_subcommands(child)
    fiber = yield from runner(app)(["child", "--wizard"]).fork()
    yield from input_text("selected")
    yield from input_key("enter")
    yield from input_key("enter")
    yield from fiber.join()
    assert captured == ["selected"]


@testing.effect
def test_should_reject_completions_without_a_shell(env: Services[Any]):
    """should reject --completions without a shell"""
    invoked: list[bool] = []
    app = command.make("demo", Config, lambda _: fx.sync(lambda: invoked.append(True)))
    yield from runner(app)(["--completions"]).ignore()
    assert invoked == []
    assert (
        "Missing value for flag --completions. Expected: bash | zsh | fish | powershell | sh | pwsh"
        in (yield from error_text())
    )


@testing.effect
def test_should_print_power_shell_completions_for_completions_pwsh(env: Services[Any]):
    """should print PowerShell completions for --completions pwsh"""
    yield from runner(command.make("demo"))(["--completions", "pwsh"])
    stdout = lines_text((yield from testing.log_lines))
    assert "Register-ArgumentCompleter -Native -CommandName 'demo'" in stdout


@pytest.mark.parametrize(
    ("flag", "name", "expected"),
    [
        (Flag.string("name").optional(), "name", "string"),
        (Flag.integer("count").optional(), "count", "integer"),
        (Flag.path("config").optional(), "config", "path"),
        (Flag.key_value_pair("env").optional(), "env", "key=value"),
    ],
)
@testing.effect
def test_should_reject_flag_without_a_value(
    env: Services[Any], flag: Flag[Any], name: str, expected: str
):
    """should reject --${name} without a ${expected} value"""

    class Demo(Config):
        value = flag

    invoked: list[bool] = []
    app = command.make("demo", Demo, lambda _: fx.sync(lambda: invoked.append(True)))
    yield from runner(app)([f"--{name}"]).ignore()
    assert invoked == []
    assert f"Missing value for flag --{name}. Expected: {expected}" in (yield from error_text())


@testing.effect
def test_should_render_invalid_choice_values_without_doubling_the_expected_prefix(
    env: Services[Any],
):
    """should render invalid choice values without doubling the Expected prefix"""

    class Demo(Config):
        size = Flag.literals("size", ["small", "medium", "large"])

    invoked: list[bool] = []
    app = command.make("demo", Demo, lambda _: fx.sync(lambda: invoked.append(True)))
    yield from runner(app)(["--size", "bogus"]).ignore()
    assert invoked == []
    assert 'Invalid value for flag --size: "bogus". Expected: "small" | "medium" | "large"' in (
        yield from error_text()
    )


# --- withOptionalValue ---------------------------------------------------------------

watch_flag = (
    Flag.literals("watch", ["first-failure", "until-done"])
    .with_alias("w")
    .with_optional_value("first-failure")
)


@testing.effect
def test_uses_the_optional_value_for_a_bare_flag_without_consuming_the_next_token(
    env: Services[Any],
):
    """uses the optional value for a bare flag without consuming the next token"""

    class App(Config):
        watch = watch_flag
        files = Argument.string("file").variadic()

    captured: list[tuple[str, tuple[str, ...]]] = []
    app = command.make("app", App, lambda c: fx.sync(lambda: captured.append((c.watch, c.files))))
    run = runner(app)
    yield from run(["-w", "until-done"])
    yield from run(["--watch=until-done"])
    assert captured == [("first-failure", ("until-done",)), ("until-done", ())]


@testing.effect
def test_does_not_consume_a_boolean_literal_after_a_negated_flag(env: Services[Any]):
    """does not consume a boolean literal after a negated flag"""

    class App(Config):
        watch = Flag.boolean("watch").with_optional_value("true")
        files = Argument.string("file").variadic()

    captured: list[tuple[bool, tuple[str, ...]]] = []
    app = command.make("app", App, lambda c: fx.sync(lambda: captured.append((c.watch, c.files))))
    yield from runner(app)(["--no-watch", "false"])
    assert captured == [(False, ("false",))]


@testing.effect
def test_emits_the_wizard_value_inline(env: Services[Any]):
    """emits the wizard value inline"""

    class App(Config):
        watch = watch_flag

    captured: list[tuple[str, ...]] = []
    target = command.make("app", App)
    launcher = command.make(
        "launcher", Config, lambda _: command.wizard(target).map(captured.append)
    )
    fiber = yield from runner(launcher)([]).fork()
    yield from input_key("down")
    yield from input_key("enter")
    yield from fiber.join()
    assert captured == [("app", "--watch=until-done")]


@testing.effect
def test_should_execute_handler_with_parsed_config(env: Services[Any]):
    """should execute handler with parsed config"""
    paths = yield from Path()
    yield from cli.run(["copy", "src.txt", "dest.txt", "--recursive", "--force"])
    assert (yield from get_actions()) == [
        TestAction(
            "copy",
            {
                "source": paths.resolve("src.txt"),
                "destination": paths.resolve("dest.txt"),
                "recursive": True,
                "force": True,
                "bufferSize": 64,
            },
        )
    ]


@testing.effect
def test_should_handle_nested_config_in_handler(env: Services[Any]):
    """should handle nested config in handler"""
    yield from cli.run(
        ["admin", "users", "create", "john_doe", "john@example.com", "--role", "admin", "--notify"]
    )
    assert (yield from get_actions()) == [
        TestAction(
            "users create",
            {"username": "john_doe", "email": "john@example.com", "role": "admin", "notify": True},
        )
    ]


@testing.effect
def test_should_work_with_effectful_handlers(env: Services[Any]):
    """should work with effectful handlers"""
    files = ("file1.txt", "file2.txt", "dir/")
    yield from cli.run(["remove", *files, "--recursive", "--force", "--verbose"])
    assert (yield from get_actions()) == [
        TestAction("remove", {"files": files, "recursive": True, "force": True, "verbose": True})
    ]


@testing.effect
def test_should_work_with_option_aliases_in_handler(env: Services[Any]):
    """should work with option aliases in handler"""
    yield from cli.run(["build", "-o", "dist/", "-v", "-f", "build.json"])
    assert (yield from get_actions()) == [
        TestAction("build", {"output": "dist/", "verbose": True, "config": "build.json"})
    ]


@testing.effect
def test_should_merge_repeated_key_value_flags_into_a_single_record(env: Services[Any]):
    """should merge repeated key=value flags into a single record"""

    class Env(Config):
        env = Flag.key_value_pair("env")

    captured: list[dict[str, str]] = []
    app = command.make("env", Env, lambda c: fx.sync(lambda: captured.append(c.env)))
    yield from runner(app)(["--env", "foo=bar", "--env", "cool=dude"])
    assert captured == [{"foo": "bar", "cool": "dude"}]


@testing.effect
def test_should_merge_key_value_flags_even_when_interleaved_with_other_options(
    env: Services[Any],
):
    """should merge key=value flags even when interleaved with other options"""

    class Env(Config):
        env = Flag.key_value_pair("env")
        verbose = Flag.boolean("verbose")
        profile = Flag.string("profile")

    captured: list[Env] = []
    yield from runner(command.make("env", Env, recorder(captured)))(
        [
            "--env",
            "foo=bar",
            "--profile",
            "dev",
            "--env",
            "cool=dude",
            "--verbose",
            "--env",
            "zip=zop",
        ]
    )
    [config] = captured
    assert config.env == {"foo": "bar", "cool": "dude", "zip": "zop"}
    assert config.verbose is True
    assert config.profile == "dev"


class Region(Setting[str | None]):
    flag = Flag.string("region").optional()


@testing.effect
def test_should_expose_setting_global_flags_to_command_handlers(env: Services[Any]):
    """should expose setting global flags to command handlers"""
    captured: list[str | None] = []
    app = command.make("deploy", Config, lambda _: Region().map(captured.append)).pipe(
        command.with_global_flags(Region)
    )
    run = runner(app)
    yield from run(["--region", "us-east-1"])
    yield from run([])
    assert captured == ["us-east-1", None]


@testing.effect
def test_should_expose_setting_global_flags_with_flag_with_default(env: Services[Any]):
    """should expose setting global flags with Flag.withDefault"""

    class DefaultRegion(Setting[str]):
        flag = Flag.string("region").with_default("us-west-2")

    captured: list[str] = []
    app = command.make("deploy", Config, lambda _: DefaultRegion().map(captured.append)).pipe(
        command.with_global_flags(DefaultRegion)
    )
    run = runner(app)
    yield from run(["--region", "eu-west-1"])
    yield from run([])
    assert captured == ["eu-west-1", "us-west-2"]


@testing.effect
def test_should_configure_built_in_global_flags_per_run(env: Services[Any]):
    """should configure built-in global flags per run"""
    run = runner(command.make("app", Config, lambda _: fx.void))
    config = cli_config.make(
        built_ins=[flag for flag in global_flag.built_ins if flag is not global_flag.LogLevel]
    )
    yield from run(["--help"]).pipe(fx.provide(cli_config.layer(built_ins=config.built_ins)))
    configured_help = yield from testing.log_lines
    assert not any("--log-level" in str(line) for line in configured_help)

    yield from (
        run(["--log-level", "debug"])
        .pipe(fx.provide_service(cli_config.CliConfig, config))
        .ignore()
    )
    assert "Unrecognized flag: --log-level" in (yield from error_text())

    before = len((yield from testing.log_lines))
    yield from run(["--help"])
    default_help = (yield from testing.log_lines)[before:]
    assert any("--log-level" in str(line) for line in default_help)


@testing.effect
def test_should_support_mixed_action_and_setting_global_flags(env: Services[Any]):
    """should support mixed action and setting global flags"""
    actions: list[bool] = []
    captured: list[str] = []
    invocations: list[int] = []

    verbose_action = Action(
        Flag.boolean("verbose").with_default(False),
        lambda value, _: fx.sync(lambda: actions.append(value)),
    )

    class Format(Setting[str]):
        flag = Flag.string("format").with_default("text")

    def handler(_: Config):
        invocations.append(1)
        return Format().map(captured.append)

    app = command.make("deploy", Config, handler).pipe(
        command.with_global_flags(verbose_action, Format)
    )
    run = runner(app)
    yield from run(["--format", "json"])
    yield from run(["--verbose", "--format", "yaml"])
    assert captured == ["json"]
    assert actions == [True]
    assert invocations == [1]


@testing.effect
def test_should_reject_explicit_values_for_canonical_negated_global_flags(env: Services[Any]):
    """should reject explicit values for canonical negated global flags"""

    class Verbose(Setting[bool]):
        flag = Flag.boolean("verbose")

    invoked: list[bool] = []
    app = command.make("deploy", Config, lambda _: fx.sync(lambda: invoked.append(True))).pipe(
        command.with_global_flags(Verbose)
    )
    yield from ignore_help(runner(app)(["--no-verbose", "false"]))
    assert invoked == []
    assert "use --no-verbose by itself to set --verbose to false" in (yield from error_text())


class RegionFromProvide(Tag[str | None]): ...


@testing.effect
def test_should_expose_setting_global_flags_in_command_provide_apis(env: Services[Any]):
    """should expose setting global flags in Command.provide APIs"""
    from_provide: list[str | None] = []
    from_provide_effect: list[str | None] = []

    def region_layer(_: Config) -> layer.Layer[RegionFromProvide, Never, Region]:
        return layer.effect(RegionFromProvide, Region())

    base = command.make("deploy", Config, lambda _: RegionFromProvide().map(from_provide.append))
    provided = base.pipe(command.provide(region_layer))
    discarded = command.provide_effect_discard(
        provided, lambda _: Region().map(from_provide_effect.append)
    )
    app = discarded.pipe(command.with_global_flags(Region))
    yield from runner(app)(["--region", "eu-west-1"])
    assert from_provide == ["eu-west-1"]
    assert from_provide_effect == ["eu-west-1"]


class _DefaultRegion(Setting[str]):
    flag = Flag.string("region").with_default("us-east-1")


@testing.effect
def test_should_reject_global_flags_that_are_out_of_scope_for_selected_subcommand(
    env: Services[Any],
):
    """should reject global flags that are out of scope for selected subcommand"""
    invoked: list[str] = []
    deploy = command.make(
        "deploy", Config, lambda _: fx.sync(lambda: invoked.append("deploy"))
    ).pipe(command.with_global_flags(_DefaultRegion))
    db = command.make("db", Config, lambda _: fx.sync(lambda: invoked.append("db")))
    root = command.make("app", Config).with_subcommands(deploy, db)
    yield from runner(root)(["db", "--region", "eu-west-1"]).ignore()
    assert "--region" in (yield from error_text())
    assert invoked == []


@testing.effect
def test_should_show_only_path_active_global_flags_in_subcommand_help(env: Services[Any]):
    """should show only path-active global flags in subcommand help"""
    deploy = command.make("deploy", Config, lambda _: fx.void).pipe(
        command.with_global_flags(_DefaultRegion)
    )
    db = command.make("db", Config, lambda _: fx.void)
    run = runner(command.make("app", Config).with_subcommands(deploy, db))
    yield from run(["deploy", "--help"])
    deploy_help = yield from testing.log_lines
    assert any("--region" in str(line) for line in deploy_help)
    yield from run(["db", "--help"])
    db_section = (yield from testing.log_lines)[len(deploy_help) :]
    assert not any("--region" in str(line) for line in db_section)


@testing.effect
def test_should_fail_for_malformed_key_value_flags(env: Services[Any]):
    """should fail for malformed key=value flags"""

    class Env(Config):
        env = Flag.key_value_pair("env")

    invoked: list[bool] = []
    app = command.make("env", Env, lambda _: fx.sync(lambda: invoked.append(True)))
    yield from runner(app)(["--env", "invalid"]).ignore()
    assert "Invalid key=value format" in (yield from error_text())
    assert invoked == []


@testing.effect
def test_should_handle_parsing_errors_from_run(env: Services[Any]):
    """should handle parsing errors from run"""
    yield from runner(cli.comprehensive_cli)(["invalid-command"]).ignore()
    stdout = lines_text((yield from testing.log_lines))
    assert "DESCRIPTION" in stdout
    assert "comprehensive CLI tool" in stdout
    stderr = yield from error_text()
    assert "ERROR" in stderr
    assert "Unknown subcommand" in stderr
    assert "invalid-command" in stderr


@testing.effect
def test_should_route_built_in_output_through_the_configured_presenter(env: Services[Any]):
    """should route built-in output through the configured presenter"""
    events: list[str] = []

    class Recording:
        def present(self, event: cli_output.Event) -> fx.Effect[None]:
            name = (
                f"Help({event.reason})"
                if isinstance(event, cli_output.Help)
                else type(event).__name__
            )
            return fx.sync(lambda: events.append(name))

    run = runner(command.make("greet", _Name))
    run_empty = runner(command.make("empty"))

    def body():
        yield from run(["--help"])
        yield from run(["--version"])
        yield from run([]).flip()
        yield from run_empty([]).flip()

    yield from fx.gen(body).pipe(fx.provide(cli_output.layer_presenter(Recording())))
    assert events == ["Help(Requested)", "Version", "InvalidInvocation", "Help(Implicit)"]
    assert (yield from testing.log_lines) == []
    assert (yield from testing.error_lines) == []


@testing.effect
def test_should_show_help_for_invalid_global_flag_values(env: Services[Any]):
    """should show help for invalid global flag values"""
    from pyfect.cli.cli_error import InvalidValue

    class ChoiceRegion(Setting[str]):
        flag = Flag.literals("region", ["us", "eu"]).with_default("us")

    deploy = command.make("deploy").pipe(command.with_global_flags(ChoiceRegion))
    run = runner(command.make("app").with_subcommands(deploy))
    for flag in ["completions", "log-level", "region"]:
        error = yield from run(["deploy", f"--{flag}", "bad"]).flip()
        assert isinstance(error, ShowHelp)
        assert error.command_path == ("app", "deploy")
        assert isinstance(error.errors[0], InvalidValue)


@testing.effect
def test_should_propagate_handler_errors_from_run(env: Services[Any]):
    """should propagate handler errors from run"""
    assert (yield from cli.run(["test-failing", "--input", "test"]).flip()) == "Handler error"


@testing.effect
def test_should_render_and_rethrow_user_error_handler_failures_without_help(env: Services[Any]):
    """should render and rethrow UserError handler failures without help"""
    from pyfect.cli.cli_error import UserError

    failure = UserError(Exception("internal details"), user_message="Deployment failed")
    error = yield from runner(command.make("deploy", Config, lambda _: fx.fail(failure)))([]).flip()
    assert error is failure
    assert failure.error_reported is False
    assert [str(line) for line in (yield from testing.error_lines)] == [
        "\nERROR\n  Deployment failed"
    ]
    assert (yield from testing.log_lines) == []


@testing.effect
def test_should_render_tagged_handler_failures_with_a_user_message_and_rethrow_the_original_error(
    env: Services[Any],
):
    """should render tagged handler failures with a userMessage and rethrow the original error"""
    from pyfect.errors import TaggedError

    @dataclass(eq=False)
    class Occupied(TaggedError):
        path: str

        @property
        def __cli_user_message__(self) -> str:
            return f"{self.path} already exists. Re-run with --force to replace it."

    failure = Occupied("config.yaml")
    error = yield from runner(command.make("deploy", Config, lambda _: fx.fail(failure)))([]).flip()
    assert error is failure
    assert failure.error_reported is False
    assert [str(line) for line in (yield from testing.error_lines)] == [
        "\nERROR\n  config.yaml already exists. Re-run with --force to replace it."
    ]
    assert (yield from testing.log_lines) == []


@dataclass(frozen=True, slots=True)
class _CustomErrorFormatter(_CapturingFormatter):
    def format_help_doc(self, doc: HelpDoc) -> str:
        return self.inner.format_help_doc(doc)

    def format_error(self, error: Any) -> str:
        return f"CUSTOM ERROR: {error.message}"


@testing.effect
def test_should_render_user_error_handler_failures_with_the_installed_formatter(
    bare_env: Services[Any],
):
    """should render UserError handler failures with the installed formatter"""
    from pyfect.cli.cli_error import UserError

    failure = UserError("Deployment failed")
    yield from (
        runner(command.make("deploy", Config, lambda _: fx.fail(failure)))([])
        .flip()
        .pipe(fx.provide_service(cli_output.CurrentFormatter, _CustomErrorFormatter([])))
    )
    assert [str(line) for line in (yield from testing.error_lines)] == [
        "CUSTOM ERROR: Deployment failed"
    ]


@testing.effect
def test_should_color_built_in_output_from_terminal_capabilities(bare_env: Services[Any]):
    """should color built-in output from TerminalCapabilities"""
    from pyfect.cli.terminal_capabilities import Capabilities, TerminalCapabilities

    capabilities = Capabilities(can_color=True, can_animate=False, can_prompt=False)
    run = command.run_with(command.make("tool"), version="1.2.3")(["--version"])
    yield from run.pipe(fx.provide_service(TerminalCapabilities, capabilities))
    yield from run.pipe(fx.provide_service(TerminalCapabilities, capabilities)).pipe(
        fx.provide_service(cli_output.CurrentFormatter, cli_output.default_formatter(colors=False))
    )
    colored, custom = yield from testing.log_lines
    assert "\x1b[1mtool" in str(colored)
    assert str(custom) == "tool v1.2.3"


@testing.effect
def test_should_render_user_error_once_when_running_wizard_generated_arguments(
    env: Services[Any],
):
    """should render UserError once when running wizard-generated arguments"""
    from pyfect.cli.cli_error import UserError

    failure = UserError("Deployment failed")
    app = command.make("deploy", Config, lambda _: fx.fail(failure))
    fiber = yield from runner(app)(["--wizard"]).flip().fork()
    yield from input_key("enter")
    error = yield from fiber.join()
    assert error is failure
    assert [str(line) for line in (yield from testing.error_lines)] == [
        "\nERROR\n  Deployment failed"
    ]


@testing.effect
def test_should_render_user_error_argument_failures_with_command_help(env: Services[Any]):
    """should render UserError argument failures with command help"""
    from pyfect.cli.cli_error import UserError

    class Deploy(Config):
        target = Argument.string("target").map_effect(
            lambda _: fx.fail(UserError("Invalid deployment target"))
        )

    error = yield from runner(command.make("deploy", Deploy))(["invalid"]).flip()
    assert isinstance(error, ShowHelp)
    assert "Invalid deployment target" in (yield from error_text())
    assert "USAGE" in lines_text((yield from testing.log_lines))


@testing.effect
def test_should_suppress_automatic_error_rendering(env: Services[Any]):
    """should suppress automatic error rendering"""
    from pyfect.cli.cli_error import UserError

    user_error = UserError("Deployment failed")
    app = command.make("deploy", Config, lambda _: fx.fail(user_error))
    run = command.run_with(app, version="1.0.0", render_errors=False)
    handler_failure = yield from run([]).flip()
    parse_failure = yield from run(["--unknown"]).flip()
    assert handler_failure is user_error
    assert user_error.error_reported is True
    assert isinstance(parse_failure, ShowHelp)
    assert (yield from testing.error_lines) == []
    assert "USAGE" in lines_text((yield from testing.log_lines))


@testing.effect
def test_should_still_render_help_when_automatic_error_rendering_is_disabled(env: Services[Any]):
    """should still render help when automatic error rendering is disabled"""
    app = command.make("app").with_subcommands(command.make("child"))
    error = yield from command.run_with(app, version="1.0.0", render_errors=False)([]).flip()
    assert isinstance(error, ShowHelp)
    assert error.errors == ()
    assert "USAGE" in lines_text((yield from testing.log_lines))
    assert (yield from testing.error_lines) == []


# --- validate ------------------------------------------------------------------------


@testing.effect
def test_rejects_the_parsed_input_with_help_before_the_handler_runs(env: Services[Any]):
    """rejects the parsed input with help before the handler runs"""
    from pyfect.cli.cli_error import ValidationError

    class Download(Config):
        use_api = Flag.boolean("use-api").with_default(False)
        use_docker = Flag.boolean("use-docker").with_default(False)

    handled: list[tuple[bool, bool]] = []

    def check(c: Download) -> fx.Effect[None, ValidationError]:
        if c.use_api and c.use_docker:
            return fx.fail(ValidationError("--use-api and --use-docker are mutually exclusive"))
        return fx.void

    app = command.make(
        "download", Download, lambda c: fx.sync(lambda: handled.append((c.use_api, c.use_docker)))
    ).validate(check)
    run = runner(app)
    yield from run(["--use-api"])
    error = yield from run(["--use-api", "--use-docker"]).flip()
    assert handled == [(True, False)]
    assert isinstance(error, ShowHelp)
    assert len(error.errors) == 1
    assert isinstance(error.errors[0], ValidationError)
    assert "--use-api and --use-docker are mutually exclusive" in (yield from error_text())
    assert "USAGE" in lines_text((yield from testing.log_lines))


@testing.effect
def test_keeps_validators_through_with_handler_and_stops_at_the_first_failure(
    env: Services[Any],
):
    """keeps validators through withHandler and stops at the first failure"""
    from pyfect.cli.cli_error import ValidationError

    class Download(Config):
        use_docker = Flag.boolean("use-docker").with_default(False)

    calls: list[str] = []

    def first(c: Download) -> fx.Effect[None, ValidationError]:
        def check() -> fx.Effect[None, ValidationError]:
            calls.append("first")
            return fx.fail(ValidationError("no docker")) if c.use_docker else fx.void

        return fx.suspend(check)

    app = (
        command.make("download", Download)
        .validate(first)
        .validate(lambda _: fx.sync(lambda: calls.append("second")))
        .with_handler(lambda _: fx.sync(lambda: calls.append("handler")))
    )
    run = runner(app)
    yield from run([])
    error = yield from run(["--use-docker"]).flip()
    assert calls == ["first", "second", "handler", "first"]
    assert isinstance(error, ShowHelp)


@testing.effect
def test_sees_only_the_input_that_exists_where_it_is_applied_in_the_pipeline(
    env: Services[Any],
):
    """sees only the input that exists where it is applied in the pipeline"""
    seen: list[tuple[str, list[str]]] = []

    def record(label: str) -> Callable[[Config], fx.Effect[None]]:
        return lambda c: fx.sync(lambda: seen.append((label, sorted(type(c).__cli_fields__))))

    class Shared(Config):
        use_api = Flag.boolean("use-api").with_default(False)

    class Tool(Shared):
        dry_run = Flag.boolean("dry-run").with_default(False)

    child = command.make("deploy", Config, lambda _: fx.void)
    root = (
        command.make("tool", Tool, lambda _: fx.void)
        .validate(record("before shared flags"))
        .with_shared_flags(Shared)
        .validate(record("before subcommands"))
        .with_subcommands(child)
        .validate(record("after subcommands"))
    )
    run = runner(root)
    yield from run(["--use-api"])
    leaf = list(seen)
    seen.clear()
    yield from run(["--use-api", "deploy"])
    both = ["dry_run", "use_api"]
    assert leaf == [
        ("before shared flags", both),
        ("before subcommands", both),
        ("after subcommands", both),
    ]
    assert seen == [("after subcommands", ["use_api"])]


# --- withSubcommands -----------------------------------------------------------------


def test_preserves_unlisted_metadata_when_adding_subcommands():
    """preserves unlisted metadata when adding subcommands"""
    with_child = command.make("internal").with_unlisted().with_subcommands(command.make("child"))
    assert with_child.unlisted is True


def test_preserves_unlisted_metadata_when_adding_shared_flags():
    """preserves unlisted metadata when adding shared flags"""

    class Verbose(Config):
        verbose = Flag.boolean("verbose")

    assert command.make("internal").with_unlisted().with_shared_flags(Verbose).unlisted is True


@testing.effect
def test_should_execute_parent_handler_when_no_subcommand_provided(env: Services[Any]):
    """should execute parent handler when no subcommand provided"""
    yield from cli.run(["git", "--verbose"])
    assert (yield from get_actions()) == [TestAction("git", {"verbose": True})]


@testing.effect
def test_should_execute_subcommand_when_provided(env: Services[Any]):
    """should execute subcommand when provided"""
    yield from cli.run(["git", "clone", "myrepo", "--branch", "develop"])
    assert (yield from get_actions()) == [
        TestAction("git clone", {"repository": "myrepo", "branch": "develop"})
    ]


@testing.effect
def test_should_execute_subcommand_when_provided_by_alias(env: Services[Any]):
    """should execute subcommand when provided by alias"""
    executed: list[str] = []
    plan = command.make("plan", Config, lambda _: fx.sync(lambda: executed.append("plan")))
    root = command.make("tool").with_subcommands(plan.with_alias("p"))
    yield from runner(root)(["p"])
    assert executed == ["plan"]


@testing.effect
def test_should_accept_grouped_and_ungrouped_subcommands(env: Services[Any]):
    """should accept grouped and ungrouped subcommands"""
    from pyfect.cli import group

    executed: list[str] = []

    def leaf(name: str) -> AnyCommand:
        return command.make(name, Config, lambda _: fx.sync(lambda: executed.append(name)))

    app = command.make("tool").with_subcommands(
        group("Auth commands", leaf("login"), leaf("logout")), leaf("status")
    )
    run = runner(app)
    yield from run(["login"])
    yield from run(["status"])
    assert executed == ["login", "status"]


@testing.effect
def test_should_handle_multiple_subcommands_correctly(env: Services[Any]):
    """should handle multiple subcommands correctly"""
    yield from cli.run(["git", "clone", "repo1"])
    yield from cli.run(["git", "add", "file1", "--update"])
    yield from cli.run(["git", "status", "--short"])
    assert (yield from get_actions()) == [
        TestAction("git clone", {"repository": "repo1", "branch": "main"}),
        TestAction("git add", {"files": "file1", "update": True}),
        TestAction("git status", {"short": True}),
    ]


@testing.effect
def test_should_handle_nested_config_structures_in_subcommands(env: Services[Any]):
    """should handle nested config structures in subcommands"""
    yield from cli.run(
        [
            "app",
            "--env",
            "prod",
            "deploy",
            "api-service",
            "production",
            "--db-host",
            "localhost",
            "--db-port",
            "5432",
            "--dry-run",
        ]
    )
    assert (yield from get_actions()) == [
        TestAction(
            "deploy",
            {
                "service": "api-service",
                "environment": "production",
                "database": {"host": "localhost", "port": 5432},
                "dryRun": True,
            },
        )
    ]


@testing.effect
def test_should_execute_parent_handler_with_options_when_no_subcommand_provided(
    env: Services[Any],
):
    """should execute parent handler with options when no subcommand provided"""
    yield from cli.run(["git", "--verbose"])
    assert (yield from get_actions()) == [TestAction("git", {"verbose": True})]


@testing.effect
def test_should_propagate_subcommand_errors(env: Services[Any]):
    """should propagate subcommand errors"""
    assert (yield from cli.run(["test-failing", "--input", "test"]).flip()) == "Handler error"


@testing.effect
def test_should_provide_shared_parent_context_to_subcommands(env: Services[Any]):
    """should provide shared parent context to subcommands"""

    class Parent(Config):
        verbose = Flag.boolean("verbose")
        config = Flag.string("config")

    class Child(Config):
        action = Flag.string("action")

    messages: list[str] = []
    parent = command.make("parent").with_shared_flags(Parent)

    def child_handler(c: Child):
        def body():
            parent_config = yield from parent
            messages.append(f"child: parent.verbose={_js(parent_config.verbose)}")
            messages.append(f"child: parent.config={parent_config.config}")
            messages.append(f"child: action={c.action}")

        return fx.gen(body)

    combined = parent.with_subcommands(command.make("child", Child, child_handler))
    yield from runner(combined)(
        ["--verbose", "--config", "prod.json", "child", "--action", "deploy"]
    )
    assert messages == [
        "child: parent.verbose=true",
        "child: parent.config=prod.json",
        "child: action=deploy",
    ]


def _js(value: bool) -> str:
    return "true" if value else "false"


class _Global(Config):
    global_ = Flag.boolean("global")


class _Pkg(Config):
    pkg = Flag.string("pkg")


def _npm(messages: list[str]) -> AnyCommand:
    root = command.make("npm").with_shared_flags(_Global)

    def install(c: _Pkg):
        def body():
            parent = yield from root
            messages.append(f"install: global={_js(parent.global_)}, pkg={c.pkg}")

        return fx.gen(body)

    return root.with_subcommands(command.make("install", _Pkg, install))


@testing.effect
def test_should_accept_shared_parent_flags_before_or_after_a_subcommand_npm_style(
    env: Services[Any],
):
    """should accept shared parent flags before or after a subcommand (npm-style)"""
    messages: list[str] = []
    run = runner(_npm(messages))
    yield from run(["--global", "install", "--pkg", "cowsay"])
    yield from run(["install", "--pkg", "cowsay", "--global"])
    assert messages == ["install: global=true, pkg=cowsay"] * 2


@testing.effect
def test_should_parse_shared_flags_for_parent_handlers(env: Services[Any]):
    """should parse shared flags for parent handlers"""

    class Model(Config):
        model = Flag.string("model")

    class Tool(Model):
        workspace = Flag.string("workspace")

    messages: list[str] = []
    root = (
        command.make("tool", Tool)
        .with_shared_flags(Model)
        .with_handler(
            lambda c: fx.sync(
                lambda: messages.append(f"root: workspace={c.workspace}, model={c.model}")
            )
        )
    )
    yield from runner(root)(["--workspace", "docs", "--model", "gpt-4o"])
    assert messages == ["root: workspace=docs, model=gpt-4o"]


class _Workspace(Config):
    workspace = Flag.string("workspace")


class _ToolWithModel(_Workspace):
    model = Flag.string("model")


@testing.effect
def test_should_allow_child_flags_to_reuse_parent_local_flag_names(env: Services[Any]):
    """should allow child flags to reuse parent local flag names"""

    class Chat(Config):
        model = Flag.string("model")

    messages: list[str] = []
    root = command.make("tool", _ToolWithModel).with_shared_flags(_Workspace)

    def chat(c: Chat):
        def body():
            parent = yield from root
            messages.append(f"chat: workspace={parent.workspace}, model={c.model}")

        return fx.gen(body)

    app = root.with_subcommands(command.make("chat", Chat, chat))
    yield from runner(app)(["--workspace", "docs", "chat", "--model", "gpt-4o-mini"])
    assert messages == ["chat: workspace=docs, model=gpt-4o-mini"]


@testing.effect
def test_should_reject_parent_local_flags_on_subcommand_paths(env: Services[Any]):
    """should reject parent local flags on subcommand paths"""

    class Chat(Config):
        topic = Flag.string("topic")

    root = command.make("tool", _ToolWithModel).with_shared_flags(_Workspace)
    app = root.with_subcommands(command.make("chat", Chat))
    yield from ignore_help(
        runner(app)(["--workspace", "docs", "--model", "gpt-4o", "chat", "--topic", "bugs"])
    )
    assert "Unrecognized flag: --model in command tool chat" in (yield from error_text())


@testing.effect
def test_should_allow_direct_accessing_parent_config_in_subcommands(env: Services[Any]):
    """should allow direct accessing parent config in subcommands"""
    messages: list[str] = []
    yield from runner(_npm(messages))(["--global", "install", "--pkg", "effect"])
    assert messages == ["install: global=true, pkg=effect"]


@testing.effect
def test_should_handle_nested_subcommands_with_context_sharing(env: Services[Any]):
    """should handle nested subcommands with context sharing"""

    class Env(Config):
        env = Flag.string("env")

    class Name(Config):
        name = Flag.string("name")

    class Deploy(Config):
        target_version = Flag.string("target-version")

    messages: list[str] = []
    root = (
        command.make("app")
        .with_shared_flags(Env)
        .with_handler(lambda c: fx.sync(lambda: messages.append(f"root: env={c.env}")))
    )

    def service_handler(c: Name):
        def body():
            root_config = yield from root
            messages.append(f"service: root.env={root_config.env}")
            messages.append(f"service: name={c.name}")

        return fx.gen(body)

    service = command.make("service").with_shared_flags(Name).with_handler(service_handler)

    def deploy_handler(c: Deploy):
        def body():
            root_config = yield from root
            service_config = yield from service
            messages.append(f"deploy: root.env={root_config.env}")
            messages.append(f"deploy: service.name={service_config.name}")
            messages.append(f"deploy: target-version={c.target_version}")

        return fx.gen(body)

    deploy = command.make("deploy", Deploy, deploy_handler)
    app = root.with_subcommands(service.with_subcommands(deploy))
    yield from runner(app)(
        ["--env", "production", "service", "--name", "api", "deploy", "--target-version", "1.0.0"]
    )
    assert messages == [
        "deploy: root.env=production",
        "deploy: service.name=api",
        "deploy: target-version=1.0.0",
    ]


@testing.effect
def test_should_handle_boolean_shared_flags_before_subcommands(env: Services[Any]):
    """should handle boolean shared flags before subcommands"""

    class Parent(Config):
        verbose = Flag.boolean("verbose")
        config = Flag.string("config")

    class Deploy(Config):
        target_version = Flag.string("target-version")

    messages: list[str] = []
    parent = (
        command.make("app")
        .with_shared_flags(Parent)
        .with_handler(
            lambda c: fx.sync(
                lambda: messages.append(f"parent: verbose={_js(c.verbose)}, config={c.config}")
            )
        )
    )

    def deploy(c: Deploy):
        def body():
            parent_config = yield from parent
            messages.append(f"deploy: parent.verbose={_js(parent_config.verbose)}")
            messages.append(f"deploy: target-version={c.target_version}")

        return fx.gen(body)

    app = parent.with_subcommands(command.make("deploy", Deploy, deploy))
    yield from runner(app)(
        ["--config", "prod.json", "--verbose", "deploy", "--target-version", "1.0.0"]
    )
    assert messages == ["deploy: parent.verbose=true", "deploy: target-version=1.0.0"]


@testing.effect
def test_should_merge_stacked_with_shared_flags_calls(env: Services[Any]):
    """should merge stacked withSharedFlags calls"""

    class Verbose(Config):
        verbose = Flag.boolean("verbose")

    class Format(Verbose):
        format = Flag.string("format")

    class Tool(Format):
        dry_run = Flag.boolean("dry-run")

    messages: list[str] = []
    root = command.make("tool", Tool).with_shared_flags(Verbose).with_shared_flags(Format)

    def run_handler(_: Config):
        def body():
            parent = yield from root
            messages.append(f"verbose={_js(parent.verbose)}, format={parent.format}")

        return fx.gen(body)

    app = root.with_subcommands(command.make("run", Config, run_handler))
    yield from runner(app)(["--verbose", "--format", "json", "run"])
    assert messages == ["verbose=true, format=json"]


class DbUrl(Tag[str]): ...


class _Env(Config):
    env = Flag.string("env")


def _db_url(c: _Env) -> str:
    return f"db://{c.env}.example.com"


@testing.effect
def test_should_work_with_command_provide_when_shared_flags_are_present(env: Services[Any]):
    """should work with Command.provide when shared flags are present"""

    class App(_Env):
        dry_run = Flag.boolean("dry-run")

    messages: list[str] = []
    root = command.make("app", App).with_shared_flags(_Env)

    def deploy_handler(_: Config):
        def body():
            parent = yield from root
            db_url = yield from DbUrl()
            messages.append(f"env={parent.env}, db={db_url}")

        return fx.gen(body)

    app = root.with_subcommands(command.make("deploy", Config, deploy_handler)).pipe(
        command.provide_sync(DbUrl, _db_url)
    )
    yield from runner(app)(["--env", "production", "deploy"])
    assert messages == ["env=production, db=db://production.example.com"]


def test_should_reject_shared_child_flag_collisions_when_with_shared_flags_is_applied_after_with_subcommands():  # noqa: E501
    """should reject shared/child flag collisions when withSharedFlags is applied after withSubcommands"""  # noqa: E501
    from pyfect.cli.cli_error import DuplicateOption

    class Verbose(Config):
        verbose = Flag.boolean("verbose")

    child = command.make("run", Verbose)
    with pytest.raises(DuplicateOption):
        command.make("tool").with_subcommands(child).with_shared_flags(Verbose)


@testing.effect
def test_should_require_with_shared_flags_before_with_subcommands_for_subcommand_access(
    env: Services[Any],
):
    """should require withSharedFlags before withSubcommands for subcommand access"""

    class Verbose(Config):
        verbose = Flag.boolean("verbose")

    messages: list[str] = []
    root = command.make("tool").with_shared_flags(Verbose)

    def run_handler(_: Config):
        def body():
            parent = yield from root
            messages.append(f"verbose={_js(parent.verbose)}")

        return fx.gen(body)

    app = root.with_subcommands(command.make("run", Config, run_handler))
    yield from runner(app)(["--verbose", "run"])
    assert messages == ["verbose=true"]


@testing.effect
def test_should_treat_tokens_after_double_dash_as_operands_no_subcommand_or_flags(
    env: Services[Any],
):
    """should treat tokens after -- as operands (no subcommand or flags)"""

    class Tool(Config):
        rest = Argument.string("rest").variadic()

    class Child(Config):
        value = Flag.string("value")

    captured: list[tuple[str, ...]] = []
    invoked: list[bool] = []
    root = command.make("tool", Tool, lambda c: fx.sync(lambda: captured.append(c.rest)))
    child = command.make("child", Child, lambda _: fx.sync(lambda: invoked.append(True)))
    yield from runner(root.with_subcommands(child))(["--", "child", "--value", "x"])
    assert invoked == []
    assert captured == [("child", "--value", "x")]


@testing.effect
def test_should_pass_trailing_operands_to_the_selected_subcommand(env: Services[Any]):
    """should pass trailing operands to the selected subcommand"""

    class Child(Config):
        values = Argument.string("value").variadic()

    captured: list[tuple[str, ...]] = []
    child = command.make("child", Child, lambda c: fx.sync(lambda: captured.append(c.values)))
    app = command.make("tool").with_subcommands(child)
    yield from runner(app)(["child", "--", "value", "--literal", "-x"])
    assert captured == [("value", "--literal", "-x")]


@testing.effect
def test_should_pass_trailing_operands_through_nested_subcommands(env: Services[Any]):
    """should pass trailing operands through nested subcommands"""

    class Child(Config):
        value = Argument.string("value")

    captured: list[str] = []
    child = command.make("child", Child, lambda c: fx.sync(lambda: captured.append(c.value)))
    group_command = command.make("group").with_subcommands(child)
    app = command.make("tool").with_subcommands(group_command)
    yield from runner(app)(["group", "child", "--", "-literal"])
    assert captured == ["-literal"]


@testing.effect
def test_should_allow_no_trailing_operands_after_double_dash_for_a_subcommand(
    env: Services[Any],
):
    """should allow no trailing operands after -- for a subcommand"""
    invoked: list[bool] = []
    child = command.make("child", Config, lambda _: fx.sync(lambda: invoked.append(True)))
    yield from runner(command.make("tool").with_subcommands(child))(["child", "--"])
    assert invoked == [True]


@testing.effect
def test_should_preserve_trailing_operands_for_a_leaf_command(env: Services[Any]):
    """should preserve trailing operands for a leaf command"""

    class Tool(Config):
        values = Argument.string("value").variadic()

    captured: list[tuple[str, ...]] = []
    app = command.make("tool", Tool, lambda c: fx.sync(lambda: captured.append(c.values)))
    yield from runner(app)(["--", "--literal", "-x"])
    assert captured == [("--literal", "-x")]


@testing.effect
def test_should_preserve_inherited_flags_around_a_subcommand_with_trailing_operands(
    env: Services[Any],
):
    """should preserve inherited flags around a subcommand with trailing operands"""

    class Shared(Config):
        before = Flag.boolean("before")
        after = Flag.boolean("after")

    class Child(Config):
        value = Argument.string("value")

    captured: list[tuple[bool, bool, str]] = []
    root = command.make("tool").with_shared_flags(Shared)

    def child(c: Child):
        def body():
            parent = yield from root
            captured.append((parent.before, parent.after, c.value))

        return fx.gen(body)

    app = root.with_subcommands(command.make("child", Child, child))
    yield from runner(app)(["--before", "child", "--after", "--", "-literal"])
    assert captured == [(True, True, "-literal")]


class _Verbose(Config):
    verbose = Flag.boolean("verbose")


@testing.effect
def test_should_coerce_boolean_flags_to_false_when_given_falsey_literals(env: Services[Any]):
    """should coerce boolean flags to false when given falsey literals"""
    captured: list[bool] = []
    run = runner(
        command.make("tool", _Verbose, lambda c: fx.sync(lambda: captured.append(c.verbose)))
    )
    yield from run(["--verbose", "false"])
    yield from run(["--verbose", "0"])
    assert captured == [False, False]


@testing.effect
def test_should_parse_required_boolean_flags_when_explicitly_enabled_or_disabled(
    env: Services[Any],
):
    """should parse required boolean flags when explicitly enabled or disabled"""
    captured: list[bool] = []
    run = runner(
        command.make("tool", _Verbose, lambda c: fx.sync(lambda: captured.append(c.verbose)))
    )
    yield from run(["--verbose"])
    yield from run(["--no-verbose"])
    assert captured == [True, False]


@testing.effect
def test_should_support_optional_boolean_flags_and_no_flag_negation(env: Services[Any]):
    """should support optional boolean flags and --no-<flag> negation"""

    class Tool(Config):
        open = Flag.boolean("open").optional()

    captured: list[bool | None] = []
    run = runner(command.make("tool", Tool, lambda c: fx.sync(lambda: captured.append(c.open))))
    yield from run([])
    yield from run(["--open"])
    yield from run(["--no-open"])
    assert captured == [None, True, False]


@testing.effect
def test_should_not_accept_no_flag_for_boolean_flags_without_negation(env: Services[Any]):
    """should not accept --no-<flag> for boolean flags without negation"""

    class Tool(Config):
        unsafe = Flag.boolean("unsafe").with_default(False).without_negation()

    captured: list[bool] = []
    run = runner(command.make("tool", Tool, lambda c: fx.sync(lambda: captured.append(c.unsafe))))
    yield from run(["--unsafe"])
    yield from ignore_help(run(["--no-unsafe"]))
    assert captured == [True]
    assert "Unrecognized flag: --no-unsafe" in (yield from error_text())


@testing.effect
def test_should_negate_boolean_flags_through_a_custom_negation_name(env: Services[Any]):
    """should negate boolean flags through a custom negation name"""

    class Tool(Config):
        validate = Flag.boolean("validate").with_default(True).with_negation("skip-validate")

    captured: list[bool] = []
    run = runner(command.make("tool", Tool, lambda c: fx.sync(lambda: captured.append(c.validate))))
    yield from run([])
    yield from run(["--skip-validate"])
    yield from ignore_help(run(["--no-validate"]))
    assert captured == [True, False]
    assert "Unrecognized flag: --no-validate" in (yield from error_text())


@testing.effect
def test_should_reject_boolean_flags_that_share_a_negation_name(env: Services[Any]):
    """should reject boolean flags that share a negation name"""

    def run(flags: dict[str, Flag[bool]]):
        config = type("Flags", (Config,), dict(flags))
        return fx.suspend(lambda: runner(command.make("tool", config))([])).exit()

    shared_custom = yield from run(
        {
            "validate": Flag.boolean("validate").with_negation("skip"),
            "verify": Flag.boolean("verify").with_negation("skip"),
        }
    )
    custom_matches_default = yield from run(
        {"bar": Flag.boolean("bar"), "foo": Flag.boolean("foo").with_negation("no-bar")}
    )
    assert isinstance(shared_custom, Failure)
    assert shared_custom.cause.has_dies
    assert isinstance(custom_matches_default, Failure)
    assert custom_matches_default.cause.has_dies


@testing.effect
def test_should_resolve_a_disabled_negation_name_to_a_conflicting_alias(env: Services[Any]):
    """should resolve a disabled negation name to a conflicting alias"""

    class Tool(Config):
        prompt = Flag.boolean("prompt").with_default(True).without_negation()
        force = Flag.boolean("force").with_alias("no-prompt").with_default(False)

    captured: list[tuple[bool, bool]] = []
    app = command.make(
        "tool", Tool, lambda c: fx.sync(lambda: captured.append((c.prompt, c.force)))
    )
    yield from runner(app)(["--no-prompt"])
    assert captured == [(True, True)]


@testing.effect
def test_should_prefer_canonical_negation_over_conflicting_aliases(env: Services[Any]):
    """should prefer canonical negation over conflicting aliases"""

    class Tool(Config):
        prompt = Flag.boolean("prompt")
        force = Flag.boolean("force").with_alias("no-prompt").with_default(False)

    captured: list[tuple[bool, bool]] = []
    app = command.make(
        "tool", Tool, lambda c: fx.sync(lambda: captured.append((c.prompt, c.force)))
    )
    yield from runner(app)(["--no-prompt"])
    assert captured == [(False, False)]


class _Open(Config):
    open = Flag.boolean("open")


@testing.effect
def test_should_reject_explicit_values_for_canonical_negated_flags(env: Services[Any]):
    """should reject explicit values for canonical negated flags"""
    invoked: list[bool] = []
    run = runner(command.make("tool", _Open, lambda _: fx.sync(lambda: invoked.append(True))))
    yield from ignore_help(run(["--no-open", "false"]))
    yield from ignore_help(run(["--no-open=true"]))
    assert invoked == []
    assert "use --no-open by itself to set --open to false" in (yield from error_text())


@testing.effect
def test_should_not_leak_a_negated_flag_literal_into_subcommand_parsing(env: Services[Any]):
    """should not leak a negated flag literal into subcommand parsing"""
    invoked: list[str] = []
    child = command.make("child", Config, lambda _: fx.sync(lambda: invoked.append("child")))
    root = command.make(
        "tool", _Open, lambda _: fx.sync(lambda: invoked.append("parent"))
    ).with_subcommands(child)
    yield from ignore_help(runner(root)(["--no-open", "false", "child"]))
    assert invoked == []
    output = yield from error_text()
    assert "use --no-open by itself to set --open to false" in output
    assert 'Unknown subcommand "false"' not in output


@testing.effect
def test_should_fail_when_a_required_flag_value_is_missing(env: Services[Any]):
    """should fail when a required flag value is missing"""
    invoked: list[bool] = []
    run = runner(command.make("tool", _Pkg, lambda _: fx.sync(lambda: invoked.append(True))))
    yield from ignore_help(run(["--pkg"]))
    assert invoked == []
    stderr = yield from testing.error_lines
    assert len(stderr) > 0
    assert "--pkg" in lines_text(stderr)


@testing.effect
def test_should_parse_combined_short_flags_including_one_that_expects_a_value(
    env: Services[Any],
):
    """should parse combined short flags including one that expects a value"""

    class Tool(Config):
        all = Flag.boolean("all").with_alias("a")
        verbose = Flag.boolean("verbose").with_alias("v")
        pkg = Flag.string("pkg").with_alias("p")

    captured: list[tuple[bool, bool, str]] = []
    app = command.make(
        "tool", Tool, lambda c: fx.sync(lambda: captured.append((c.all, c.verbose, c.pkg)))
    )
    yield from runner(app)(["-avp", "cowsay"])
    assert captured == [(True, True, "cowsay")]


@testing.effect
def test_should_honor_double_dash_while_still_applying_parent_flags(env: Services[Any]):
    """should honor -- while still applying parent flags"""

    class Tool(Config):
        global_ = Flag.boolean("global")
        rest = Argument.string("rest").variadic()

    class Child(Config):
        value = Flag.string("value")

    captured: list[tuple[bool, tuple[str, ...]]] = []
    root = command.make(
        "tool", Tool, lambda c: fx.sync(lambda: captured.append((c.global_, c.rest)))
    )
    yield from runner(root.with_subcommands(command.make("child", Child)))(
        ["--global", "--", "child", "--value", "x"]
    )
    assert captured == [(True, ("child", "--value", "x"))]


@testing.effect
def test_should_report_unknown_flag_even_when_subcommand_is_unknown(env: Services[Any]):
    """should report unknown flag even when subcommand is unknown"""
    app = command.make("root", Config).with_subcommands(command.make("known", Config))
    yield from ignore_help(runner(app)(["--unknown", "bogus"]))
    assert "Unrecognized flag: --unknown" in (yield from error_text())


@testing.effect
def test_should_keep_variadic_argument_order_when_options_are_interleaved(env: Services[Any]):
    """should keep variadic argument order when options are interleaved"""

    class Copy(Config):
        verbose = Flag.boolean("verbose")
        files = Argument.string("file").variadic()

    captured: list[tuple[tuple[str, ...], bool]] = []
    app = command.make(
        "copy", Copy, lambda c: fx.sync(lambda: captured.append((c.files, c.verbose)))
    )
    yield from runner(app)(["a.txt", "b.txt", "--verbose", "c.txt"])
    assert captured == [(("a.txt", "b.txt", "c.txt"), True)]


@testing.effect
def test_should_support_options_before_after_or_between_operands_relaxed_posix_syntax_guideline_no_9(  # noqa: E501
    env: Services[Any],
):
    """should support options before, after, or between operands (relaxed POSIX Syntax Guideline No. 9)"""  # noqa: E501
    yield from cli.run(["copy", "--recursive", "--force", "src.txt", "dest.txt"])
    yield from cli.run(["copy", "src.txt", "dest.txt", "--recursive", "--force"])
    yield from cli.run(["copy", "--recursive", "src.txt", "dest.txt", "--force"])
    actions = yield from get_actions()
    assert len(actions) == 3
    for action in actions:
        assert action.command == "copy"
        assert action.details["recursive"] is True
        assert action.details["force"] is True
        assert action.details["bufferSize"] == 64
        assert "src.txt" in str(action.details["source"])
        assert "dest.txt" in str(action.details["destination"])


@testing.effect
def test_should_suggest_similar_subcommands_for_unknown_subcommands(env: Services[Any]):
    """should suggest similar subcommands for unknown subcommands"""
    yield from ignore_help(cli.run(["cpy"]))
    assert (yield from error_text()) == (
        '\nERROR\n  Unknown subcommand "cpy" for "mycli"\n\n  Did you mean this?\n    copy'
    )


@testing.effect
def test_should_suggest_similar_subcommands_for_nested_unknown_subcommands(env: Services[Any]):
    """should suggest similar subcommands for nested unknown subcommands"""
    yield from ignore_help(cli.run(["admin", "usrs", "list"]))
    assert (yield from error_text()) == (
        '\nERROR\n  Unknown subcommand "usrs" for "mycli admin"\n\n  Did you mean this?\n    users'
    )


@testing.effect
def test_should_suggest_similar_options_for_unrecognized_options(env: Services[Any]):
    """should suggest similar options for unrecognized options"""
    yield from ignore_help(cli.run(["--debugs", "copy", "src.txt", "dest.txt"]))
    assert (yield from error_text()) == (
        "\nERROR\n  Unrecognized flag: --debugs in command mycli\n\n  Did you mean this?\n"
        "    --debug"
    )


@testing.effect
def test_should_suggest_similar_short_options_for_unrecognized_short_options(
    env: Services[Any],
):
    """should suggest similar short options for unrecognized short options"""
    yield from ignore_help(cli.run(["-u", "copy", "src.txt", "dest.txt"]))
    assert (yield from error_text()) == (
        "\nERROR\n  Unrecognized flag: -u in command mycli\n\n  Did you mean this?\n"
        "    -d\n    -c\n    -q"
    )


@testing.effect
def test_should_print_version_and_exit_even_with_subcommands_global_precedence(
    env: Services[Any],
):
    """should print version and exit even with subcommands (global precedence)"""
    yield from cli.run(["--version"])
    assert "1.0.0" in lines_text((yield from testing.log_lines))


@testing.effect
def test_should_print_version_and_exit_when_version_appears_before_subcommand(
    env: Services[Any],
):
    """should print version and exit when --version appears before subcommand"""
    yield from cli.run(["--version", "copy", "src.txt", "dest.txt"])
    assert "1.0.0" in lines_text((yield from testing.log_lines))
    assert (yield from get_actions()) == []


def _has_version(lines: list[object]) -> bool:
    return any("1.0.0" in str(line) for line in lines)


@testing.effect
def test_should_let_global_flags_before_subcommands_override_non_shared_parent_locals(
    env: Services[Any],
):
    """should let global flags before subcommands override non-shared parent locals"""

    class Tool(Config):
        version = Flag.boolean("version")

    captured: list[bool] = []
    invoked: list[bool] = []
    child = command.make("child", Config, lambda _: fx.sync(lambda: invoked.append(True)))
    app = command.make(
        "tool", Tool, lambda c: fx.sync(lambda: captured.append(c.version))
    ).with_subcommands(child)
    yield from runner(app)(["--version", "child"])
    assert captured == []
    assert invoked == []
    assert _has_version((yield from testing.log_lines))


@testing.effect
def test_should_keep_shared_flags_before_subcommands_over_globals(env: Services[Any]):
    """should keep shared flags before subcommands over globals"""

    class Version(Config):
        version = Flag.boolean("version")

    captured: list[bool] = []
    root = command.make("tool", Config, lambda _: fx.void).with_shared_flags(Version)

    def child(_: Config):
        def body():
            parent = yield from root
            captured.append(parent.version)

        return fx.gen(body)

    run = runner(root.with_subcommands(command.make("child", Config, child)))
    yield from run(["--version", "child"])
    assert captured == [True]
    assert not _has_version((yield from testing.log_lines))
    yield from run(["child", "--version"])
    assert captured == [True, True]


@testing.effect
def test_should_keep_root_local_flags_over_globals_when_no_subcommand_is_selected(
    env: Services[Any],
):
    """should keep root local flags over globals when no subcommand is selected"""

    class Tool(Config):
        version = Flag.string("version")

    captured: list[str] = []
    child = command.make("child", Config, lambda _: fx.void)
    app = command.make(
        "tool", Tool, lambda c: fx.sync(lambda: captured.append(c.version))
    ).with_subcommands(child)
    yield from runner(app)(["--version", "canary"])
    assert captured == ["canary"]
    assert not _has_version((yield from testing.log_lines))


class _NameVersion(Config):
    name = Flag.string("name")
    version = Flag.boolean("version")


@testing.effect
def test_should_skip_intervening_local_flag_values_before_selecting_subcommands(
    env: Services[Any],
):
    """should skip intervening local flag values before selecting subcommands"""
    captured: list[tuple[str, bool]] = []
    invoked: list[bool] = []
    child = command.make("child", Config, lambda _: fx.sync(lambda: invoked.append(True)))
    app = command.make(
        "tool", _NameVersion, lambda c: fx.sync(lambda: captured.append((c.name, c.version)))
    ).with_subcommands(child)
    yield from runner(app)(["--version", "--name", "child"])
    assert captured == [("child", True)]
    assert invoked == []
    assert not _has_version((yield from testing.log_lines))


@testing.effect
def test_should_stop_looking_for_subcommands_after_the_first_positional_argument(
    env: Services[Any],
):
    """should stop looking for subcommands after the first positional argument"""

    class Tool(Config):
        files = Argument.string("file").variadic()
        version = Flag.boolean("version")

    captured: list[tuple[tuple[str, ...], bool]] = []
    invoked: list[bool] = []
    child = command.make("child", Config, lambda _: fx.sync(lambda: invoked.append(True)))
    app = command.make(
        "tool", Tool, lambda c: fx.sync(lambda: captured.append((c.files, c.version)))
    ).with_subcommands(child)
    yield from runner(app)(["--version", "file", "child"])
    assert captured == [(("file", "child"), True)]
    assert invoked == []
    assert not _has_version((yield from testing.log_lines))


@testing.effect
def test_should_still_select_subcommands_after_skipped_flag_values(env: Services[Any]):
    """should still select subcommands after skipped flag values"""
    captured: list[tuple[str, bool]] = []
    invoked: list[bool] = []
    child = command.make("child", Config, lambda _: fx.sync(lambda: invoked.append(True)))
    app = command.make(
        "tool", _NameVersion, lambda c: fx.sync(lambda: captured.append((c.name, c.version)))
    ).with_subcommands(child)
    yield from runner(app)(["--version", "--name", "value", "child"])
    assert captured == []
    assert invoked == []
    assert _has_version((yield from testing.log_lines))


@testing.effect
def test_should_let_local_flags_override_global_flags_on_the_selected_command(
    env: Services[Any],
):
    """should let local flags override global flags on the selected command"""

    class Release(Config):
        version = Flag.string("version")

    captured: list[str] = []
    release = command.make(
        "release", Release, lambda c: fx.sync(lambda: captured.append(c.version))
    )
    package = command.make("package").with_subcommands(release)
    app = command.make("tool").with_subcommands(package)
    yield from runner(app)(["package", "release", "--version", "canary"])
    assert captured == ["canary"]
    assert not _has_version((yield from testing.log_lines))


@testing.effect
def test_should_let_local_short_aliases_override_global_short_aliases_on_the_selected_command(
    env: Services[Any],
):
    """should let local short aliases override global short aliases on the selected command"""

    class Output(Setting[str]):
        flag = (
            Flag.literals("output", ["pretty", "json", "yaml"])
            .with_alias("o")
            .with_default("pretty")
        )

    class Report(Config):
        output = (
            Flag.literals("output", ["summary", "json", "csv"])
            .with_alias("o")
            .with_default("summary")
        )

    captured: list[str] = []
    report = command.make("report", Report, lambda c: fx.sync(lambda: captured.append(c.output)))
    app = command.make("tool").with_subcommands(report).pipe(command.with_global_flags(Output))
    yield from runner(app)(["report", "-o", "csv"])
    assert captured == ["csv"]


@testing.effect
def test_should_let_local_flags_override_scoped_global_flags_from_another_command_branch(
    env: Services[Any],
):
    """should let local flags override scoped global flags from another command branch"""

    class ChoiceRegion(Setting[str]):
        flag = Flag.literals("region", ["us", "eu"]).with_default("us")

    class Status(Config):
        region = Flag.string("region")

    captured: list[str] = []
    invoked: list[bool] = []
    deploy = command.make("deploy", Config, lambda _: fx.sync(lambda: invoked.append(True))).pipe(
        command.with_global_flags(ChoiceRegion)
    )
    status = command.make("status", Status, lambda c: fx.sync(lambda: captured.append(c.region)))
    app = command.make("app").with_subcommands(deploy, status)
    yield from runner(app)(["status", "--region", "local"])
    assert captured == ["local"]
    assert invoked == []


@testing.effect
def test_should_print_help_when_invoked_with_no_arguments(env: Services[Any]):
    """should print help when invoked with no arguments"""
    yield from ignore_help(cli.run([]))
    stdout = lines_text((yield from testing.log_lines))
    assert "DESCRIPTION" in stdout
    assert "comprehensive CLI tool" in stdout
    assert (yield from get_actions()) == []


def _build_child() -> AnyCommand:
    return (
        command.make("build")
        .with_description("Build the project and all artifacts")
        .with_short_description("Build artifacts")
    )


@testing.effect
def test_should_use_short_descriptions_in_subcommand_listings(env: Services[Any]):
    """should use short descriptions in subcommand listings"""
    fallback = command.make("test").with_description("Run the full test suite")
    yield from runner(command.make("tool").with_subcommands(_build_child(), fallback))(["--help"])
    stdout = lines_text((yield from testing.log_lines))
    assert "Build artifacts" in stdout
    assert "Build the project and all artifacts" not in stdout
    assert "Run the full test suite" in stdout


@testing.effect
def test_should_keep_full_description_on_the_command_help_page(env: Services[Any]):
    """should keep full description on the command help page"""
    yield from runner(command.make("tool").with_subcommands(_build_child()))(["build", "--help"])
    assert "Build the project and all artifacts" in lines_text((yield from testing.log_lines))


def test_should_include_short_description_metadata_in_help_doc_subcommands():
    """should include short description metadata in HelpDoc subcommands"""
    from pyfect.cli._help import build_help_doc

    root = command.make("tool").with_subcommands(_build_child().with_alias("b"))
    listed = build_help_doc(root, ["tool"]).subcommands[0].commands[0]
    assert listed.alias == "b"
    assert listed.short_description == "Build artifacts"
    assert listed.description == "Build the project and all artifacts"


# --- withExamples --------------------------------------------------------------------


def test_should_expose_examples_in_help_docs():
    """should expose examples in help docs"""
    from pyfect.cli._help import build_help_doc
    from pyfect.cli.help_doc import ExampleDoc

    examples = [
        ExampleDoc("myapp login", "Log in with browser OAuth"),
        ExampleDoc("myapp login --token sbp_abc123", "Log in with a token"),
    ]
    login = command.make("login").with_examples(examples)
    assert list(build_help_doc(login, ["login"]).examples) == examples


def test_should_preserve_examples_when_adding_subcommands():
    """should preserve examples when adding subcommands"""
    from pyfect.cli._help import build_help_doc
    from pyfect.cli.help_doc import ExampleDoc

    examples = [ExampleDoc("myapp root", "Run root command")]
    root = command.make("root").with_examples(examples).with_subcommands(command.make("child"))
    assert list(build_help_doc(root, ["root"]).examples) == examples


@testing.effect
def test_should_resolve_examples_from_the_command_path(env: Services[Any]):
    """should resolve examples from the command path"""
    from pyfect.cli.help_doc import ExampleDoc

    class Verbose(Config):
        verbose = Flag.boolean("verbose")

    deploy = (
        command.make("deploy")
        .with_examples(lambda path: [ExampleDoc(f"{' '.join(path)} --yes", "Take every default")])
        .with_subcommands(command.make("status"))
        .with_shared_flags(Verbose)
    )
    tool = command.make("tool").with_subcommands(deploy)
    yield from runner(deploy)(["--help"])
    standalone = [line.strip() for line in lines_text((yield from testing.log_lines)).split("\n")]
    assert "deploy --yes" in standalone
    assert "tool deploy --yes" not in standalone
    yield from runner(tool)(["deploy", "--help"])
    mounted = [line.strip() for line in lines_text((yield from testing.log_lines)).split("\n")]
    assert "tool deploy --yes" in mounted


# --- help docs -----------------------------------------------------------------------


def test_should_include_flag_choices_in_help_doc_descriptions():
    """should include flag choices in help doc descriptions"""
    from pyfect.cli._help import build_help_doc
    from pyfect.cli.help_doc import FlagDoc

    class Tool(Config):
        mode = Flag.literals("mode", ["dev", "prod"]).with_description("Execution mode")
        format = Flag.literals("format", ["json", "yaml"])

    assert list(build_help_doc(command.make("tool", Tool), ["tool"]).flags) == [
        FlagDoc("mode", (), "choice", "Execution mode (choices: dev, prod)", True),
        FlagDoc("format", (), "choice", "(choices: json, yaml)", True),
    ]


@testing.effect
def test_should_render_flag_choices_in_formatted_help_output(env: Services[Any]):
    """should render flag choices in formatted help output"""

    class Tool(Config):
        mode = Flag.literals("mode", ["dev", "prod"]).with_description("Execution mode")

    yield from runner(command.make("tool", Tool))(["--help"])
    assert "Execution mode (choices: dev, prod)" in lines_text((yield from testing.log_lines))
