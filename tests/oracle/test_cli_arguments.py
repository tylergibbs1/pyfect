"""Effect's ``test/cli/Arguments.test.ts``."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pyfect as fx
from pyfect import layer, platform_error, testing
from pyfect.cli import Argument, Config, Flag, command
from pyfect.cli.cli_error import ShowHelp
from pyfect.cli.param import ParsedArgs
from pyfect.file_system import FileSystem, NoopFileSystem
from pyfect.option import Some
from pyfect.result import Err, Ok
from pyfect.testing import Services

from ._cli_env import file_info, test_layer


class _Files(NoopFileSystem):
    def exists(self, path: str):
        return fx.succeed("/non/existent/file.txt" not in path)

    def stat(self, path: str):
        if "/non/existent/file.txt" in path:
            return fx.fail(platform_error.bad_argument(module="", method=""))
        return fx.succeed(file_info("Directory" if path.endswith("workspace") else "File"))

    def access(self, path: str, *, readable: bool = False, writable: bool = False):
        if "/non/existent/file.txt" in path:
            return fx.fail(platform_error.bad_argument(module="", method=""))
        return fx.void


env = testing.layer_fixture(
    layer.merge(test_layer, layer.succeed(FileSystem, _Files())), scope="function"
)


def run(app: command.Command[Any, Any, Any, Any], *args: str):
    return command.run_with(app, version="1.0.0")(args)


def ignore_help[A, E, R](eff: fx.Effect[A, E, R]) -> fx.Effect[A | None, E, R]:
    return eff.catch_if(lambda e: isinstance(e, ShowHelp), lambda _: fx.succeed(None))


def capture[C](seen: list[C]) -> Callable[[C], fx.Effect[None]]:
    return lambda config: fx.sync(lambda: seen.append(config))


@testing.effect
def test_should_parse_all_argument_types_correctly(env: Services[Any]):
    """should parse all argument types correctly"""

    class Test(Config):
        name = Argument.string("name")
        count = Argument.integer("count")
        ratio = Argument.finite("ratio")
        env = Argument.literals("env", ["dev", "prod"])
        config = Argument.file("config", must_exist=False)
        workspace = Argument.directory("workspace", must_exist=False)
        start_date = Argument.date("start-date")
        verbose = Flag.boolean("verbose")

    seen: list[Test] = []
    app = command.make("test", Test, capture(seen))
    yield from run(
        app,
        "myapp",
        "42",
        "3.14",
        "dev",
        "./config.json",
        "./workspace",
        "2024-01-01",
        "--verbose",
    )
    [result] = seen
    assert result.name == "myapp"
    assert result.count == 42
    assert result.ratio == 3.14
    assert result.env == "dev"
    assert "config.json" in result.config
    assert result.start_date == datetime(2024, 1, 1, tzinfo=UTC)
    assert result.verbose is True


@testing.effect
def test_should_handle_file_must_exist_validation(env: Services[Any]):
    """should handle file mustExist validation"""

    class Existing(Config):
        file = Argument.file("file", must_exist=True)

    seen: list[Existing] = []
    existing = command.make("test", Existing, capture(seen))
    yield from run(existing, "/file.txt")
    assert seen[0].file == "/file.txt"

    yield from ignore_help(run(existing, "/non/existent/file.txt"))
    stdout = yield from testing.log_lines
    assert any("USAGE" in str(line) for line in stdout)
    stderr = yield from testing.error_lines
    assert any("ERROR" in str(line) for line in stderr)
    assert any("does not exist" in str(line) for line in stderr)

    class Optional(Config):
        file = Argument.file("file", must_exist=False)

    seen_optional: list[Optional] = []
    optional = command.make("test", Optional, capture(seen_optional))
    yield from run(optional, "/non/existent/file.txt")
    assert "/non/existent/file.txt" in seen_optional[0].file


@testing.effect
def test_should_fail_with_invalid_arguments(env: Services[Any]):
    """should fail with invalid arguments"""

    class Test(Config):
        count = Argument.integer("count")
        env = Argument.literals("env", ["dev", "prod"])

    app = command.make("test", Test, fx.succeed)
    yield from ignore_help(run(app, "not-a-number", "dev"))
    help_text = "\n".join(map(str, (yield from testing.log_lines)))
    assert "USAGE" in help_text
    assert "test [flags] <count> <env>" in help_text
    assert "count integer" in help_text
    assert "env choice" in help_text
    error_text = "\n".join(map(str, (yield from testing.error_lines)))
    assert error_text == (
        "\nERROR\n"
        '  Invalid value for argument <count>: "not-a-number". '
        "Expected a string representing a finite number"
    )


@testing.effect
def test_should_handle_variadic_arguments(env: Services[Any]):
    """should handle variadic arguments"""

    class Test(Config):
        files = Argument.string("files").variadic()

    seen: list[Test] = []
    yield from run(command.make("test", Test, capture(seen)), "file1.txt", "file2.txt", "file3.txt")
    assert seen[0].files == ("file1.txt", "file2.txt", "file3.txt")


@testing.effect
def test_should_handle_choice_with_value(env: Services[Any]):
    """should handle choiceWithValue"""

    class Test(Config):
        level = Argument.choice_with_value("level", [("debug", 0), ("info", 1), ("error", 2)])

    seen: list[Test] = []
    yield from run(command.make("test", Test, capture(seen)), "info")
    assert seen[0].level == 1


class _Port(Config):
    port = Argument.integer("port").filter(
        lambda n: 1 <= n <= 65535, lambda n: f"Port {n} out of range (1-65535)"
    )


@testing.effect
def test_should_handle_filter_combinator_valid(env: Services[Any]):
    """should handle filter combinator - valid"""
    seen: list[_Port] = []
    yield from run(command.make("test", _Port, capture(seen)), "8080")
    assert seen[0].port == 8080


@testing.effect
def test_should_handle_filter_combinator_invalid(env: Services[Any]):
    """should handle filter combinator - invalid"""
    yield from ignore_help(run(command.make("test", _Port, lambda _: fx.void), "99999"))
    stderr = yield from testing.error_lines
    assert any("out of range" in str(line) for line in stderr)


class _Positive(Config):
    positive_int = Argument.integer("num").filter_map(
        lambda n: Some(n) if n > 0 else None, lambda n: f"Expected positive integer, got {n}"
    )


@testing.effect
def test_should_handle_filter_map_combinator_valid(env: Services[Any]):
    """should handle filterMap combinator - valid"""
    seen: list[_Positive] = []
    yield from run(command.make("test", _Positive, capture(seen)), "42")
    assert seen[0].positive_int == 42


@testing.effect
def test_should_handle_filter_map_combinator_invalid(env: Services[Any]):
    """should handle filterMap combinator - invalid"""
    yield from ignore_help(run(command.make("test", _Positive, lambda _: fx.void), "0"))
    stderr = yield from testing.error_lines
    assert any("Expected positive integer" in str(line) for line in stderr)


@testing.effect
def test_should_handle_or_else_combinator(env: Services[Any]):
    """should handle orElse combinator"""

    class Test(Config):
        value = Argument.integer("value").or_else(
            lambda: Argument.string("value").map(lambda _: -1)
        )

    seen: list[Test] = []
    app = command.make("test", Test, capture(seen))
    yield from run(app, "42")
    yield from run(app, "abc")
    assert [config.value for config in seen] == [42, -1]


@testing.effect
def test_should_handle_or_else_result_combinator(env: Services[Any]):
    """should handle orElseResult combinator"""

    class Test(Config):
        value = Argument.integer("value").or_else_result(lambda: Argument.string("value"))

    seen: list[Test] = []
    app = command.make("test", Test, capture(seen))
    yield from run(app, "42")
    yield from run(app, "abc")
    assert seen[0].value == Ok(42)
    assert seen[1].value == Err("abc")


@testing.effect
def test_should_handle_with_metavar_combinator(env: Services[Any]):
    """should handle withMetavar combinator"""

    class Test(Config):
        file = Argument.string("file").with_metavar("FILE_PATH")

    yield from run(command.make("test", Test, lambda _: fx.void), "--help")
    help_text = "\n".join(map(str, (yield from testing.log_lines)))
    assert "FILE_PATH" in help_text


@testing.effect
def test_should_handle_optional_arguments_when_provided(env: Services[Any]):
    """should handle optional arguments - when provided"""

    class Test(Config):
        label = Argument.string("label").with_description("Optional label name").optional()

    seen: list[Test] = []
    yield from run(command.make("test", Test, capture(seen)), "my-label")
    assert seen[0].label == "my-label"


@testing.effect
def test_returns_none_for_omitted_optional_positional_arguments(env: Services[Any]):
    """returns none for omitted optional positional arguments"""
    optional_arg = Argument.string("label").optional()
    _leftover, value = yield from optional_arg.parse(ParsedArgs({}, ()))
    assert value is None


@testing.effect
def test_uses_argument_wording_for_positional_invalid_value_errors(env: Services[Any]):
    """uses argument wording for positional InvalidValue errors"""
    error = yield from Argument.integer("count").parse(ParsedArgs({}, ("not-a-number",))).flip()
    message = error.message
    assert "flag --" not in message
    assert "argument" in message
