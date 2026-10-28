"""Effect's ``test/cli/LogLevel.test.ts``."""

from __future__ import annotations

from typing import Any

import pytest

import pyfect as fx
from pyfect import layer, logger, testing
from pyfect.cli import Config, Flag, cli_output, command
from pyfect.cli.cli_error import InvalidValue, ShowHelp
from pyfect.cli.global_flag import LogLevel
from pyfect.logger import Logger, Options
from pyfect.testing import Services

from ._cli_env import base_layer

logs: list[tuple[str, object]] = []


def _record(options: Options) -> None:
    message = options.message[0] if len(options.message) == 1 else options.message
    logs.append((options.log_level.name.capitalize(), message))


mock_logger = Logger.make(_record)

env = testing.layer_fixture(
    layer.merge(
        base_layer,
        cli_output.layer(cli_output.default_formatter(colors=False)),
        logger.layer([mock_logger]),
    ),
    scope="function",
)


@pytest.fixture(autouse=True)
def _clear_logs():
    logs.clear()


all_logs: list[tuple[str, object]] = [
    ("Fatal", "fatal"),
    ("Error", "error"),
    ("Warn", "warn"),
    ("Info", "info"),
    ("Debug", "debug"),
    ("Info", "trace"),
]
severity_order = ["Fatal", "Error", "Warn", "Info", "Debug", "Trace"]


def filter_logs(min_level: str) -> list[tuple[str, object]]:
    if min_level == "none":
        return []
    if min_level == "all":
        return all_logs[::-1]
    name = "Warn" if min_level == "warning" else min_level.capitalize()
    min_severity = severity_order.index(name)
    return [log for log in all_logs if severity_order.index(log[0]) <= min_severity][::-1]


def _log_everything(_: Config):
    def body():
        yield from fx.log("trace")
        yield from fx.log_debug("debug")
        yield from fx.log_info("info")
        yield from fx.log_warning("warn")
        yield from fx.log_error("error")
        yield from fx.log_fatal("fatal")

    return fx.gen(body)


def run_logging(level: str | None = None):
    app = command.make("test", Config, _log_everything)
    yield from command.run_with(app, version="1.0.0")(["--log-level", level] if level else [])
    return list(logs)


@pytest.mark.parametrize(
    "level", ["all", "trace", "debug", "info", "warn", "warning", "error", "fatal", "none"]
)
@testing.effect
def test_level_s(env: Services[Any], level: str):
    """level=%s"""
    assert (yield from run_logging(level)) == filter_logs(level)


@testing.effect
def test_uses_info_as_the_default_minimum_when_log_level_is_omitted(env: Services[Any]):
    """uses Info as the default minimum when --log-level is omitted"""
    expected = [log for log in all_logs if log[1] != "debug"][::-1]
    assert (yield from run_logging()) == expected


@testing.effect
def test_exposes_the_built_in_log_level_setting_value(env: Services[Any]):
    """exposes the built-in log-level setting value"""
    seen: list[str | None] = []

    def handler(_: Config):
        return LogLevel().map(
            lambda level: seen.append(None if level is None else level.name.lower())
        )

    run = command.run_with(command.make("test", Config, handler), version="1.0.0")
    yield from run([])
    yield from run(["--log-level", "warn"])
    assert seen == [None, "warn"]


@testing.effect
def test_applies_the_selected_log_level_to_subcommands(env: Services[Any]):
    """applies the selected log level to subcommands"""

    class Parent(Config):
        verbose = Flag.boolean("verbose")

    def child_handler(_: Config):
        def body():
            yield from fx.log_debug("debug from child")
            yield from fx.log_info("info from child")
            yield from fx.log_error("error from child")

        return fx.gen(body)

    parent = command.make("parent", Parent)
    child = command.make("child", Config, child_handler)
    combined = parent.with_subcommands(child)
    yield from command.run_with(combined, version="1.0.0")(["--log-level", "info", "child"])
    assert logs == [("Info", "info from child"), ("Error", "error from child")]


@testing.effect
def test_keeps_concurrent_command_log_levels_scoped_to_each_run(env: Services[Any]):
    """keeps concurrent command log levels scoped to each run"""
    app = command.make("test", Config, lambda _: fx.log_info("Should not see this"))
    result = yield from command.run_with(app, version="1.0.0")(["--log-level", "invalid"]).flip()
    assert isinstance(result, ShowHelp)
    [error] = result.errors
    assert isinstance(error, InvalidValue)
    assert error.option == "log-level"
    assert error.value == "invalid"
    assert logs == []
