"""``pyfect.config`` beyond the ``effect/test/Config.test.ts`` ports.

Expected values were printed by Effect's ``Config`` under Node first, except
where a test says it pins a Pythonic difference (docs/PARITY.md, section 4).
"""

import math
import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Literal

import pytest

import pyfect as fx
from pyfect import byte_size, config, redacted, testing
from pyfect import config_provider as cp
from pyfect.config import Config, ConfigError
from pyfect.config_provider import SourceError


def _parse[A](cfg: Config[A], provider: cp.ConfigProvider) -> fx.Ok[A] | fx.Err[str]:
    return fx.run_blocking(cfg.parse(provider).map_error(lambda e: e.cause.message).result())


def _at_a(value: str) -> cp.ConfigProvider:
    return cp.from_unknown({"a": value}, preserve_empty_strings=True)


_NOT_FINITE = 'Expected a string representing a finite number\n  at ["a"]'


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1e3", fx.Ok(1000)),
        ("+5", fx.Ok(5)),
        ("-0", fx.Ok(0)),
        ("1E2", fx.Ok(100)),
        ("1.0", fx.Ok(1)),
        (".5", fx.Err('Expected an integer\n  at ["a"]')),
        ("5.", fx.Err(_NOT_FINITE)),
        ("Infinity", fx.Err(_NOT_FINITE)),
        ("NaN", fx.Err(_NOT_FINITE)),
        ("1e400", fx.Err('Expected an integer\n  at ["a"]')),
        ("0x10", fx.Err(_NOT_FINITE)),
        (" 12 ", fx.Err(_NOT_FINITE)),
    ],
)
def test_integer_reads_effects_number_syntax(text: str, expected: object):
    assert _parse(config.integer("a"), _at_a(text)) == expected


def test_integer_stops_at_javascripts_safe_integers():
    """Node: ``Config.Int`` reads through a number, so past 2**53 - 1 fails."""
    for text in ("12345678901234567890", "9007199254740993"):
        assert _parse(config.integer("a"), _at_a(text)) == fx.Err('Expected an integer\n  at ["a"]')


def test_finite_and_number_edges():
    assert _parse(config.finite("a"), _at_a("1e400")) == fx.Err(
        'Expected a finite number\n  at ["a"]'
    )
    assert _parse(config.number("a"), _at_a("1e400")) == fx.Ok(math.inf)
    nan = _parse(config.number("a"), _at_a("NaN"))
    assert isinstance(nan, fx.Ok) and math.isnan(nan.value)
    assert _parse(config.number("a"), _at_a("5.")) == fx.Err(
        f'{_NOT_FINITE}\nExpected "Infinity" | "-Infinity" | "NaN"\n  at ["a"]'
    )


def test_port_edges():
    assert _parse(config.port("a"), _at_a("-0")) == fx.Err(
        'Expected a value between 1 and 65535\n  at ["a"]'
    )
    assert _parse(config.port("a"), _at_a("80.5")) == fx.Err('Expected an integer\n  at ["a"]')
    assert _parse(config.port("a"), _at_a("+5")) == fx.Ok(5)


def test_boolean_is_case_sensitive():
    for text in ["TRUE", "True", " true"]:
        assert isinstance(_parse(config.boolean("a"), _at_a(text)), fx.Err)


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("1.5 seconds", 1.5),
        ("-1 millis", -0.001),
        ("1  seconds", 1.0),
        ("2 weeks", 1_209_600.0),
        ("1 nano", 1e-9),
        ("3 minutes", 180.0),
    ],
)
def test_duration_reads_effects_syntax_as_seconds(text: str, seconds: float):
    assert _parse(config.duration("a"), _at_a(text)) == fx.Ok(seconds)


@pytest.mark.parametrize("text", ["1seconds", "1 Second", " 1 second", "1 second ", "1e3 millis"])
def test_duration_rejects_other_spellings(text: str):
    assert _parse(config.duration("a"), _at_a(text)) == fx.Err(
        'Expected a valid Duration string\n  at ["a"]'
    )


@pytest.mark.parametrize(
    ("text", "size"),
    [
        ("1.5kB", 1500),
        ("1.5 KiB", 1536),
        ("1 kilobytes", 1000),
        (" 1 MB ", 1_000_000),
        ("0 B", 0),
        ("2 GiB", 2 * 1024**3),
        ("1 QB", 1000**10),
        ("10 MBi", None),
        ("1.0001 kB", None),
        ("10", None),
        ("10 b", None),
        ("-1 B", None),
    ],
)
def test_byte_size_from_string(text: str, size: int | None):
    assert byte_size.from_string(text) == size
    expected = (
        fx.Ok(size) if size is not None else fx.Err('Expected a valid ByteSize string\n  at ["a"]')
    )
    assert _parse(config.byte_size("a"), _at_a(text)) == expected


def test_date_time_reads_iso_8601_and_reads_a_naive_time_as_utc():
    """Pythonic: Effect uses JavaScript's ``Date`` parser, which reads a date
    alone as UTC but a date-time without an offset as local time; pyfect
    reads ISO 8601 and treats every missing offset as UTC."""
    cases = {
        "2021-01-01": datetime(2021, 1, 1, tzinfo=UTC),
        "2021-01-01T10:00:00": datetime(2021, 1, 1, 10, tzinfo=UTC),
        "2021-01-01T10:00:00+02:00": datetime(2021, 1, 1, 10, tzinfo=timezone(timedelta(hours=2))),
    }
    for text, expected in cases.items():
        assert _parse(config.date_time("a"), _at_a(text)) == fx.Ok(expected)
    for text in ["2021-13-01", "", "Jan 1 2021"]:
        assert _parse(config.date_time("a"), _at_a(text)) == fx.Err(
            'Expected a valid Date\n  at ["a"]'
        )


@pytest.mark.parametrize(
    ("text", "valid"),
    [
        ("https://example.com/a?b=1", True),
        ("mailto:x@y.z", True),
        ("http://a b", False),
        ("foo", False),
        ("http://", False),
        ("http://host:99999", False),
        ("1http://host", False),
    ],
)
def test_url_validation(text: str, valid: bool):
    result = _parse(config.url("a"), _at_a(text))
    if valid:
        assert isinstance(result, fx.Ok) and result.value.geturl() == text
    else:
        assert result == fx.Err('Expected a valid URL string\n  at ["a"]')


def test_literals_are_written_as_effect_writes_them():
    assert _parse(config.literal(1, name="a"), _at_a("1")) == fx.Ok(1)
    assert _parse(config.literal(1, name="a"), _at_a("1.0")) == fx.Err('Expected "1"\n  at ["a"]')
    assert _parse(config.literal(True, name="a"), _at_a("true")) == fx.Ok(True)
    assert _parse(config.literal(None, name="a"), _at_a("null")) == fx.Ok(None)
    assert _parse(config.literal(1.5, name="a"), _at_a("1.5")) == fx.Ok(1.5)
    assert _parse(config.literal("a", 1, True, name="a"), _at_a("x")) == fx.Err(
        'Expected "a" | "1" | "true"\n  at ["a"]'
    )


def test_missing_values_say_what_was_expected():
    empty = cp.from_unknown({})
    cases: list[tuple[Config[object], str]] = [
        (config.literal(1, name="a"), 'Expected "1"'),
        (config.literal(1, 2, name="a"), 'Expected "1" | "2"'),
        (
            config.boolean("a"),
            'Expected "true" | "yes" | "on" | "1" | "y" | "false" | "no" | "off" | "0" | "n"',
        ),
        (config.number("a"), 'Expected string | "Infinity" | "-Infinity" | "NaN"'),
        (config.duration("a"), "Expected string"),
        (config.non_empty_string("a"), "Expected string"),
        (config.port("a"), "Expected string"),
        (config.date_time("a"), "Expected string"),
    ]
    for cfg, message in cases:
        assert _parse(cfg, empty) == fx.Err(f'{message}\n  at ["a"]')


def test_list_of_reports_both_readings_when_neither_applies():
    provider = cp.from_unknown(
        {"arr": "1,x,3", "empty": "", "a": ["1", "x"]}, preserve_empty_strings=True
    )
    assert _parse(config.list_of(config.finite(), "arr"), provider) == fx.Err(
        'Expected a string representing a finite number\n  at ["arr"][1]\n'
        'Expected array\n  at ["arr"]'
    )
    assert _parse(config.list_of(config.string(), "empty"), provider) == fx.Ok([])
    assert _parse(config.list_of(config.string(), "nope"), provider) == fx.Err(
        'Expected string\n  at ["nope"]\nExpected array\n  at ["nope"]'
    )
    assert _parse(config.list_of(config.finite(), "a"), provider) == fx.Err(
        'Expected string\n  at ["a"]\nExpected a string representing a finite number\n  at ["a"][1]'
    )
    holes = cp.from_env(env={"a_0": "1", "a_2": "2"})
    assert _parse(config.list_of(config.finite(), "a"), holes) == fx.Err(
        'Expected string\n  at ["a"]\nExpected string\n  at ["a"][1]'
    )


def test_list_of_is_absent_without_input_and_reads_items_under_nested():
    assert _parse(
        config.option(config.list_of(config.integer(), "ports")), cp.from_unknown({})
    ) == fx.Ok(None)
    assert _parse(
        config.list_of(config.integer(), "ports").nested("server"),
        cp.from_env(env={"server_ports": "80,443"}),
    ) == fx.Ok([80, 443])


def test_dict_of_skips_incomplete_pairs_and_reports_both_readings():
    provider = cp.from_unknown(
        {"rec": "a=1,b,=2,c=", "rec2": "a=1,b=x", "e": ""}, preserve_empty_strings=True
    )
    assert _parse(config.dict_of(config.string(), "rec"), provider) == fx.Ok({"a": "1"})
    assert _parse(config.dict_of(config.finite(), "rec2"), provider) == fx.Err(
        'Expected object\n  at ["rec2"]\n'
        'Expected a string representing a finite number\n  at ["rec2"]["b"]'
    )
    assert _parse(config.dict_of(config.string(), "nope"), provider) == fx.Err(
        'Expected object\n  at ["nope"]\nExpected string\n  at ["nope"]'
    )
    assert _parse(config.dict_of(config.string(), "e"), provider) == fx.Ok(dict[str, str]())


def _lookup(nodes: dict[cp.Path, cp.Node | SourceError]) -> cp.ConfigProvider:
    def load(path: cp.Path) -> fx.Effect[cp.Node | None, SourceError]:
        node = nodes.get(path)
        return fx.fail(node) if isinstance(node, SourceError) else fx.succeed(node)

    return cp.make(load)


def test_containers_load_every_child_before_decoding_any():
    """Effect materializes all children first, so a later child's source
    error wins over an earlier child's invalid value."""
    provider = _lookup(
        {("X",): cp.Array(3), ("X", 0): cp.Value("x"), ("X", 1): SourceError("item")}
    )
    assert _parse(config.list_of(config.integer(), "X"), provider) == fx.Err("item")
    record = _lookup(
        {
            ("X",): cp.Record(frozenset({"a", "b"})),
            ("X", "a"): cp.Value("x"),
            ("X", "b"): SourceError("item"),
        }
    )
    assert _parse(config.dict_of(config.integer(), "X"), record) == fx.Err("item")


def test_dict_of_omits_keys_whose_child_is_absent():
    provider = _lookup(
        {
            ("X",): cp.Record(frozenset({"a", "b", "c"})),
            ("X", "b"): cp.Value("1"),
            ("X", "c"): cp.Record(frozenset({"d"})),
        }
    )
    assert _parse(
        config.dict_of(config.integer(), "X"),
        _lookup(
            {
                ("X",): cp.Record(frozenset({"a", "b"})),
                ("X", "b"): cp.Value("1"),
            }
        ),
    ) == fx.Ok({"b": 1})
    assert _parse(config.dict_of(config.integer(), "X"), provider) == fx.Err(
        'Expected string\n  at ["X"]["c"]\nExpected string\n  at ["X"]'
    )


def test_an_empty_separator_splits_into_characters():
    provider = cp.from_unknown({"X": "abc", "R": "a=1,b=2"})
    assert _parse(config.list_of(config.string(), "X", separator=""), provider) == fx.Ok(
        ["a", "b", "c"]
    )
    assert _parse(config.dict_of(config.string(), "R", separator=""), provider) == fx.Ok(
        dict[str, str]()
    )


def test_a_source_error_reads_as_effect_prints_it():
    error = fx.run_blocking(
        config.string("a").parse(cp.make(lambda _: fx.fail(SourceError("boom")))).flip().or_die()
    )
    assert error.message == "SourceError: boom"
    assert str(error) == "SourceError: boom"


def test_a_schema_error_message_names_the_schema_error():
    error = fx.run_blocking(config.string("a").parse(cp.from_unknown({})).flip().or_die())
    assert error.message == 'SchemaError(Expected string\n  at ["a"])'
    assert error.cause.message == 'Expected string\n  at ["a"]'


# --- gen ---------------------------------------------------------------------------


@config.gen
def _server() -> Generator[fx.Effect[Any, ConfigError], Any, str]:
    host = yield from config.string("HOST")
    port = yield from config.port("PORT").with_default(8080)
    scheme = yield from fx.succeed("http")
    return f"{scheme}://{host}:{port}"


def test_gen_reads_each_config_in_turn():
    assert _parse(_server, cp.from_unknown({"HOST": "localhost"})) == fx.Ok("http://localhost:8080")
    assert _parse(_server, cp.from_unknown({"HOST": "h", "PORT": "1"})) == fx.Ok("http://h:1")


def test_gen_is_absent_as_soon_as_one_read_is():
    assert _parse(_server.with_default("none"), cp.from_unknown({})) == fx.Ok("none")
    assert _parse(_server.with_default("none"), cp.from_unknown({"PORT": "0"})) == fx.Ok("none")


def test_gen_fails_on_invalid_data_and_reads_under_its_nested_prefix():
    server = _server.nested("web")
    assert _parse(server, cp.from_env(env={"web_HOST": "h"})) == fx.Ok("http://h:8080")
    assert _parse(server, cp.from_env(env={"web_HOST": "h", "web_PORT": "x"})) == fx.Err(
        'Expected a string representing a finite number\n  at ["web"]["PORT"]'
    )


def test_gen_closes_the_generator_when_it_stops_early():
    closed: list[str] = []

    @config.gen
    def tracked() -> Generator[fx.Effect[Any, ConfigError], Any, int]:
        try:
            return (yield from config.integer("N"))
        finally:
            closed.append("closed")

    assert _parse(tracked.with_default(0), cp.from_unknown({})) == fx.Ok(0)
    assert isinstance(_parse(tracked, cp.from_unknown({"N": "x"})), fx.Err)
    assert _parse(tracked, cp.from_unknown({"N": "3"})) == fx.Ok(3)
    assert closed == ["closed", "closed", "closed"]


def test_gen_closes_the_generator_when_interrupted():
    closed: list[str] = []
    slow = cp.make(lambda _path: fx.sleep("1 second").as_(cp.Value("1")))

    @config.gen
    def tracked() -> Generator[fx.Effect[Any, ConfigError], Any, int]:
        try:
            return (yield from config.integer("N"))
        finally:
            closed.append("closed")

    exit = fx.run_blocking_exit(tracked.parse(slow).timeout("10 millis"))
    assert isinstance(exit, fx.Failure)
    assert closed == ["closed"]


def test_gen_runs_the_generator_afresh_each_time():
    runs: list[int] = []

    @config.gen
    def counted() -> Generator[fx.Effect[Any, ConfigError], Any, int]:
        runs.append(1)
        return (yield from config.integer("N"))

    provider = cp.from_unknown({"N": "1"})
    assert _parse(counted, provider) == _parse(counted, provider) == fx.Ok(1)
    assert len(runs) == 2


# --- as an effect ------------------------------------------------------------------


@testing.effect
def test_a_config_reads_the_current_provider_inside_gen():
    @fx.gen
    def program() -> Generator[fx.Effect[Any, ConfigError, Any], Any, int]:
        return (yield from config.port("PORT"))

    port = yield from program.pipe(fx.provide(cp.layer(cp.from_unknown({"PORT": "9000"}))))
    assert port == 9000


def test_a_config_reads_os_environ_by_default():
    assert fx.run_blocking(config.string("PATH").or_die()) == os.environ["PATH"]


def test_flat_map_into_a_plain_effect_gives_an_effect():
    eff = config.integer("N").flat_map(lambda n: fx.succeed(n * 2))
    assert (
        fx.run_blocking(eff.pipe(fx.provide(cp.layer(cp.from_unknown({"N": "21"})))).or_die()) == 42
    )


def test_the_option_method_keeps_invalid_data_failing():
    # DOGFOOD B3: ``cfg.option()`` was the inherited ``Effect.option``, so an
    # invalid value silently became ``None``.
    invalid = cp.from_unknown({"N": "x"})
    assert _parse(config.integer("N").option(), invalid) == fx.Err(
        'Expected a string representing a finite number\n  at ["N"]'
    )
    assert _parse(config.option(config.integer("N")), invalid) == _parse(
        config.integer("N").option(), invalid
    )


def test_the_option_method_gives_none_when_absent_and_some_when_present():
    assert _parse(config.integer("N").option(), cp.from_unknown({})) == fx.Ok(None)
    assert _parse(config.integer("N").option(), cp.from_unknown({"N": "3"})) == fx.Ok(fx.Some(3))


def test_the_option_method_is_a_config():
    # It composes as a config: absence under ``nested`` and ``with_default``.
    cfg = config.integer("N").option().nested("app")
    assert isinstance(cfg, Config)
    assert _parse(cfg, cp.from_unknown({"app": {"N": "4"}})) == fx.Ok(fx.Some(4))


def test_combinators_reject_a_non_config_when_called():
    with pytest.raises(TypeError, match=r"configs\[1\] must be a Config, got int: 5"):
        config.all(config.string("a"), 5)  # pyright: ignore[reportCallIssue, reportArgumentType]
    with pytest.raises(TypeError, match=r"configs\['b'\] must be a Config"):
        config.all_dict({"b": fx.succeed(1)})  # pyright: ignore[reportArgumentType, reportCallIssue]
    with pytest.raises(TypeError, match=r"element must be a Config"):
        config.list_of(config.string)  # pyright: ignore[reportArgumentType]
    with pytest.raises(TypeError, match=r"value must be a Config"):
        config.dict_of(None)  # pyright: ignore[reportArgumentType]


def test_repr():
    assert repr(config.string("a")) == "Config()"


# --- Redacted ------------------------------------------------------------------------


def test_redacted_hides_its_value():
    secret = redacted.make("sk-123")
    labelled = redacted.make("sk-123", label="api key")
    assert str(secret) == repr(secret) == "<redacted>"
    assert str(labelled) == "<redacted:api key>"
    assert redacted.value(labelled) == "sk-123"
    assert secret == labelled and hash(secret) == hash(labelled)
    assert secret != redacted.make("other")
    assert f"{[secret]}" == "[<redacted>]"


def test_wipe_unsafe_drops_the_value():
    secret = redacted.make("sk-123", label="key")
    assert redacted.wipe_unsafe(secret)
    assert not redacted.wipe_unsafe(secret)
    with pytest.raises(ValueError, match='Unable to get redacted value with label: "key"'):
        redacted.value(secret)


def test_literal_takes_a_sequence_as_effect_does():
    # The sibling of B1: Effect v4 writes ``Config.Literals(["dev", "prod"], name)``.
    env: Config[Literal["dev", "prod"]] = config.literal(["dev", "prod"], name="ENV")
    assert _parse(env, cp.from_unknown({"ENV": "prod"})) == fx.Ok("prod")
    assert _parse(env, cp.from_unknown({"ENV": "x"})) == _parse(
        config.literal("dev", "prod", name="ENV"), cp.from_unknown({"ENV": "x"})
    )
