"""CLI behavior Effect's suite leaves unpinned; each expected value was
printed by Effect v4.0.6 under Node."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.cli import Config, Flag, Setting, command, primitive, prompt
from pyfect.cli.cli_error import ShowHelp
from pyfect.cli.prompt import Choice
from pyfect.exit import Failure
from pyfect.file_system import NoopFileSystem
from pyfect.testing import Services

from ._cli_env import file_info, test_layer, with_file_system
from ._mock_terminal import input_key, input_text

env = testing.layer_fixture(test_layer, scope="function")


def _run(app: command.Command[Any, Any, Any, Any], *args: str):
    return command.run_with(app, version="1")(args)


class _Shared(Config):
    verbose = Flag.boolean("verbose")


class _Tool(_Shared):
    model = Flag.string("model")


@testing.effect
def test_help_lists_a_commands_own_flags_before_its_shared_ones(env: Services[Any]):
    tool = (
        command.make("tool", _Tool).with_shared_flags(_Shared).with_subcommands(command.make("sub"))
    )
    yield from _run(tool, "--help")
    text = "\n".join(map(str, (yield from testing.log_lines)))
    assert "FLAGS\n  --model string    \n  --verbose         \n" in text


class _Count(Config):
    n = Flag.integer("n")


@testing.effect
def test_global_flag_errors_are_shown_with_the_commands_own_parse_errors(env: Services[Any]):
    error = yield from _run(command.make("simple", _Count), "--bogus", "--log-level").flip()
    assert isinstance(error, ShowHelp)
    assert [e.message for e in error.errors] == [
        "Missing value for flag --log-level. Expected: all | trace | debug | info | warn"
        " | warning | error | fatal | none",
        "Unrecognized flag: --bogus in command simple",
    ]


@testing.effect
def test_a_prompt_quit_in_a_handler_interrupts_the_run(env: Services[Any]):
    asking = command.make("quit", Config, lambda _: prompt.run(prompt.confirm("ok?")))
    yield from input_key("c", ctrl=True)
    exit = yield from _run(asking).exit()
    assert isinstance(exit, Failure)
    assert exit.cause.has_interrupts_only


class _Region(Setting[str]):
    flag = Flag.string("region").with_default("us")


class _Zone(Setting[str]):
    flag = Flag.string("zone").with_default("a")


@testing.effect
def test_with_global_flags_applied_twice_keeps_both(env: Services[Any]):
    seen: list[tuple[str, str]] = []

    def handler(_: Config):
        def body():
            region = yield from _Region()
            zone = yield from _Zone()
            seen.append((region, zone))

        return fx.gen(body)

    app = (
        command.make("d", Config, handler)
        .pipe(command.with_global_flags(_Region))
        .pipe(command.with_global_flags(_Zone))
    )
    yield from _run(app, "--region", "eu", "--zone", "b")
    assert seen == [("eu", "b")]


@testing.effect
def test_number_prompt_rounds_half_up_like_javascript(env: Services[Any]):
    yield from input_text("2.5")
    yield from input_key("enter")
    assert (yield from prompt.run(prompt.number("F", precision=0))) == 3


@testing.effect
def test_tab_fills_the_cleared_text_prompt_with_its_default(env: Services[Any]):
    yield from input_key("u", ctrl=True)
    yield from input_key("tab")
    yield from input_text("!")
    yield from input_key("enter")
    assert (yield from prompt.run(prompt.string("Name", default="bob"))) == "bob!"


@testing.effect
def test_auto_complete_keeps_the_highlighted_choice_while_it_still_matches(env: Services[Any]):
    fruits = [Choice("Apple", "apple"), Choice("Banana", "banana"), Choice("Cherry", "cherry")]
    yield from input_text("an")
    yield from input_key("backspace")
    yield from input_key("enter")
    assert (yield from prompt.run(prompt.auto_complete("Find", fruits))) == "banana"


def test_a_config_is_built_from_exactly_its_declared_params():
    assert _Tool(verbose=True, model="m") == _Tool(model="m", verbose=True)
    with pytest.raises(TypeError, match="unexpected param 'modle'"):
        _Tool(verbose=True, modle="m")
    with pytest.raises(TypeError, match="missing param 'model'"):
        _Tool(verbose=True)


_UTC_DATES = [
    ("2024-01-15", "2024-01-15T00:00:00+00:00"),
    ("2024-01", "2024-01-01T00:00:00+00:00"),
    ("2024", "2024-01-01T00:00:00+00:00"),
    ("+002024-01-15", "2024-01-15T00:00:00+00:00"),
    ("2024-01-15t10:30:00Z", "2024-01-15T10:30:00+00:00"),
    ("2024-01-15T10:30:00z", "2024-01-15T10:30:00+00:00"),
    ("2024-01-15T10:30+0200", "2024-01-15T08:30:00+00:00"),
    ("2024-01-15T23:59:59.999-23:59", "2024-01-16T23:58:59.999000+00:00"),
    ("2024-01-15T24:00Z", "2024-01-16T00:00:00+00:00"),
    ("2024-01-15T10:30:00.000000001Z", "2024-01-15T10:30:00+00:00"),
    ("2024-01-15 10:30:00+01:00", "2024-01-15T09:30:00+00:00"),
    ("2024-01-15T10:30:00-00:00", "2024-01-15T10:30:00+00:00"),
]


@pytest.mark.parametrize(("text", "expected"), _UTC_DATES)
@testing.effect
def test_date_reads_the_ecmascript_date_time_format(env: Services[Any], text: str, expected: str):
    parsed = yield from primitive.date_.parse(text)
    assert parsed.astimezone(UTC).isoformat() == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2024-01-15T10:30", datetime(2024, 1, 15, 10, 30)),
        ("2024-01-15 10:30", datetime(2024, 1, 15, 10, 30)),
        ("2024-01-15T10:30:00.5", datetime(2024, 1, 15, 10, 30, 0, 500000)),
    ],
)
@testing.effect
def test_date_reads_a_date_time_without_an_offset_as_local_time(
    env: Services[Any], text: str, expected: datetime
):
    parsed = yield from primitive.date_.parse(text)
    assert parsed == expected.astimezone()


@pytest.mark.parametrize(
    "text",
    [
        "20240115",
        "2024-W03-1",
        "2024-01-15T10Z",
        "2024-01-15T10",
        "2024-01-15T10:30:00+02",
        "2024-01-15T10:30:00,5Z",
        "2024-01-15T10:30:00 Z",
        "2024-01-15 T10:30",
        "2024-01-15T10:30:00Z ",
        "2024-01-15T10:30:00.Z",
        "2024-01-15T1:30",
        "2024-01-15T10:3",
        "2024-01-15T10:30:60Z",
        "2024-01-15T10:30:00+24:00",
        "2024-00-10",
        "2024-01-00",
        "2024-01-32",
        "2024-01-15T24:00:01Z",
        "garbage",
        "",
    ],
)
@testing.effect
def test_date_rejects_what_javascript_rejects(env: Services[Any], text: str):
    error = yield from primitive.date_.parse(text).flip()
    assert error == "Expected a valid Date"


class _YamlFile(NoopFileSystem):
    def exists(self, path: str):
        return fx.succeed(True)

    def stat(self, path: str):
        return fx.succeed(file_info("File"))

    def read_file_string(self, path: str, encoding: str = "utf-8"):
        return fx.succeed("name: effect\nports: [3000, 3001]\n")


@testing.effect
def test_file_parse_reads_yaml_by_extension_or_format(env: Services[Any]):
    def body():
        expected = {"name": "effect", "ports": [3000, 3001]}
        assert (yield from primitive.file_parse().parse("/config.yml")) == expected
        assert (yield from primitive.file_parse().parse("/config.yaml")) == expected
        assert (yield from primitive.file_parse("yaml").parse("/config.txt")) == expected

    yield from with_file_system(fx.gen(body), _YamlFile())
