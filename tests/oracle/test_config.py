"""Ports of Effect's ``effect/test/Config.test.ts``.

Each test's docstring is the Effect test title. Effect's ``Config.Array`` and
``Config.Record`` are ``config.list_of`` and ``config.dict_of``; a
``Schema.String.check(filter)`` is ``config.string(name).map_effect(check)``.

"recognizes SourceError defects from a reloaded module copy" checks a
provider dying with a ``SourceError`` (Python has no second copy of a module
to load). The titles that are mostly about ``Config.schema`` (the schema
container titles, "materialization", "fromEnv provider" and "fromUnknown
provider") are in ``test_config_schema.py``.
"""

import math
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Never, TypedDict, cast

import pyfect as fx
from pyfect import config, testing
from pyfect import config_provider as cp
from pyfect import schema as S
from pyfect.byte_size import ByteSize
from pyfect.config import Config, ConfigError, Forbidden, InvalidValue, Pointer, SchemaError
from pyfect.config_provider import Array, Record, SourceError, Value
from pyfect.duration import infinity, millis, negative_infinity, seconds
from pyfect.redacted import Redacted


def _parse[A](cfg: Config[A], provider: cp.ConfigProvider) -> fx.Ok[A] | fx.Err[str]:
    return fx.run_blocking(cfg.parse(provider).map_error(lambda e: e.cause.message).result())


def assert_success[A](cfg: Config[A], provider: cp.ConfigProvider, expected: object) -> None:
    assert _parse(cfg, provider) == fx.Ok(expected)


def assert_failure(cfg: Config[object], provider: cp.ConfigProvider, message: str) -> None:
    assert _parse(cfg, provider) == fx.Err(message)


def unknown(value: object, *, preserve_empty_strings: bool = False) -> cp.ConfigProvider:
    return cp.from_unknown(value, preserve_empty_strings=preserve_empty_strings)


def env(values: dict[str, str], *, preserve_empty_strings: bool = False) -> cp.ConfigProvider:
    return cp.from_env(env=values, preserve_empty_strings=preserve_empty_strings)


def schema_error(path: cp.Path, issue: config.Issue) -> ConfigError:
    return ConfigError(SchemaError(Pointer(path, issue) if path else issue))


def checked(name: str, ok: Callable[[str], bool], message: str) -> Config[str]:
    """``Config.schema(Schema.String.check(filter), name)``."""

    def check(value: str) -> fx.Effect[str, ConfigError]:
        return (
            fx.succeed(value)
            if ok(value)
            else fx.fail(schema_error((name,), InvalidValue({"message": message})))
        )

    return config.string(name).map_effect(check)


@testing.effect
def test_recognizes_source_error_defects_from_a_reloaded_module_copy():
    """recognizes SourceError defects from a reloaded module copy"""
    source_error = SourceError("source unavailable")
    provider = cp.make(lambda _: fx.die(source_error))

    error = yield from config.string("value").parse(provider).flip()

    assert error.cause is source_error


@testing.effect
def test_uses_the_current_config_provider_when_yielded_as_an_effect():
    """uses the current ConfigProvider when yielded as an Effect"""
    provider = env({"STRING": "value"})
    result = yield from config.all_dict({"STRING": config.string("STRING")}).pipe(
        fx.provide(cp.layer(provider))
    )

    assert result == {"STRING": "value"}


@testing.effect
def test_preserves_provider_defects_at_the_root_and_in_nested_fields():
    """preserves provider defects at the root and in nested fields"""
    defect = RuntimeError("provider defect")
    for failed_path in ["settings", "settings.value"]:

        def lookup(path: cp.Path, failed: str = failed_path) -> fx.Effect[cp.Node | None]:
            if ".".join(map(str, path)) == failed:
                return fx.die(defect)
            return fx.succeed(Record(frozenset({"value"})))

        recovered: list[bool] = []

        def fallback(_: ConfigError, recovered: list[bool] = recovered) -> Config[dict[str, str]]:
            recovered.append(True)
            return config.succeed({"value": "fallback"})

        cfg = config.option(config.dict_of(config.string(), "settings").or_else(fallback))
        result = yield from cfg.parse(
            cp.make(lambda p: fx.suspend(lambda: lookup(p)))
        ).catch_defect(fx.succeed)

        assert result is defect
        assert recovered == []


@testing.effect
def test_does_not_recover_source_errors_with_finalizer_defects():
    """does not recover source errors with finalizer defects"""
    source_error = SourceError("read failed")
    cleanup = RuntimeError("cleanup failed")
    provider = cp.make(lambda _: fx.fail(source_error).ensuring(fx.die(cleanup)))

    exit = yield from (
        config.string("value").or_else(lambda _: config.succeed("fallback")).parse(provider).exit()
    )

    expected = fx.cause.fail(ConfigError(source_error)) + fx.cause.die(cleanup)
    assert exit == fx.Failure(expected)


def test_preserves_provider_defects_and_interruption_reasons():
    """preserves provider defects and interruption reasons"""
    cause = fx.cause.die(RuntimeError("provider defect")) + fx.cause.interrupt(123)
    provider = cp.make(lambda _: fx.fail_cause(cause))

    exit = fx.run_blocking_exit(config.string("value").parse(provider))

    assert exit == fx.Failure(cause)


# --- constructors ----------------------------------------------------------------


def test_fail_creates_an_always_failing_config():
    """fail creates an always-failing config"""
    assert_failure(
        config.fail(SchemaError(Forbidden({"message": "failure message"}))),
        unknown({}),
        "failure message",
    )


def test_succeed_creates_a_provider_independent_value():
    """succeed creates a provider-independent value"""
    assert_success(config.succeed(1), unknown({}), 1)


def test_string_decodes_present_input_and_reports_absence():
    """string decodes present input and reports absence"""
    provider = unknown({"a": "value"})
    assert_success(config.string("a"), provider, "value")
    assert_failure(config.string("b"), provider, 'Expected string\n  at ["b"]')


def test_non_empty_string_rejects_preserved_empty_input():
    """nonEmptyString rejects preserved empty input"""
    provider = unknown({"a": "value", "b": ""}, preserve_empty_strings=True)
    assert_success(config.non_empty_string("a"), provider, "value")
    assert_failure(
        config.non_empty_string("b"),
        provider,
        'Expected a value with a length of at least 1\n  at ["b"]',
    )


def test_number_accepts_finite_and_non_finite_numbers():
    """number accepts finite and non-finite numbers"""
    provider = unknown({"a": "1", "c": "c", "d": "Infinity"})
    assert_success(config.number("a"), provider, 1)
    assert_success(config.number("d"), provider, math.inf)
    assert_failure(
        config.number("b"),
        provider,
        'Expected string | "Infinity" | "-Infinity" | "NaN"\n  at ["b"]',
    )


def test_finite_rejects_invalid_and_non_finite_numbers():
    """finite rejects invalid and non-finite numbers"""
    provider = unknown({"a": "1", "b": "a", "c": "Infinity"})
    assert_success(config.finite("a"), provider, 1)
    for name in ["b", "c"]:
        assert_failure(
            config.finite(name),
            provider,
            f'Expected a string representing a finite number\n  at ["{name}"]',
        )


def test_int_rejects_non_integer_numbers():
    """int rejects non-integer numbers"""
    provider = unknown({"a": "1", "b": "1.2"})
    assert_success(config.integer("a"), provider, 1)
    assert_failure(config.integer("b"), provider, 'Expected an integer\n  at ["b"]')


def test_literal_accepts_only_the_configured_value():
    """literal accepts only the configured value"""
    provider = unknown({"a": "L"})
    assert_success(config.literal("L", name="a"), provider, "L")
    assert_failure(config.literal("-", name="a"), provider, 'Expected "-"\n  at ["a"]')


def test_literals_accepts_configured_string_alternatives():
    """literals accepts configured string alternatives"""
    provider = unknown({"a": "production", "b": "staging"})
    assert_success(config.literal("development", "production", name="a"), provider, "production")
    assert_failure(
        config.literal("development", "production", name="b"),
        provider,
        'Expected "development" | "production"\n  at ["b"]',
    )


def test_literals_accepts_configured_number_alternatives():
    """literals accepts configured number alternatives"""
    provider = unknown({"a": "1", "b": "3"})
    assert_success(config.literal(1, 2, name="a"), provider, 1)
    assert_failure(config.literal(1, 2, name="b"), provider, 'Expected "1" | "2"\n  at ["b"]')


def test_date_rejects_invalid_dates():
    """date rejects invalid dates"""
    provider = unknown({"a": "2021-01-01", "b": "invalid"})
    assert_success(config.date_time("a"), provider, datetime(2021, 1, 1, tzinfo=UTC))
    assert_failure(config.date_time("b"), provider, 'Expected a valid Date\n  at ["b"]')


def test_redacted_creates_redacted_values_and_reports_missing_input():
    """redacted creates redacted values and reports missing input"""
    provider = unknown({"a": "value"})
    assert_success(config.redacted("a"), provider, Redacted("value"))
    assert_failure(config.redacted("failure"), provider, 'Expected string\n  at ["failure"]')


def test_url_decodes_valid_urls_and_reports_absence():
    """url decodes valid URLs and reports absence"""
    provider = unknown({"a": "https://example.com"})
    assert_success(config.url("a"), provider, fx.Url("https://example.com"))
    assert_failure(config.url("failure"), provider, 'Expected string\n  at ["failure"]')


# --- combinators -------------------------------------------------------------------


def test_map_transforms_successful_values_in_data_first_and_data_last_form():
    """map transforms successful values in data-first and data-last form"""
    assert_success(config.string().map(str.upper), unknown("value"), "VALUE")


def test_map_or_fail_supports_effectful_validation():
    """mapOrFail supports effectful validation"""

    def f(s: str) -> fx.Effect[str, ConfigError]:
        if s == "":
            return fx.fail(ConfigError(SchemaError(InvalidValue({"message": "empty"}))))
        return fx.succeed(s.upper())

    assert_success(config.string().map_effect(f), unknown("value"), "VALUE")
    assert_failure(config.string().map_effect(f), unknown("", preserve_empty_strings=True), "empty")


def test_or_else_evaluates_the_fallback_after_absence():
    """orElse evaluates the fallback after absence"""
    cfg = config.string("a").or_else(lambda _: config.finite("b"))
    assert_success(cfg, unknown({"a": "value"}), "value")
    assert_success(cfg, unknown({"b": "1"}), 1)


# --- combinators: flatMap -------------------------------------------------------------


def _host(name: str) -> Config[str]:
    return checked(name, lambda s: s.endswith("effect.website"), 'Must end with "effect.website"')


host_config = config.integer("port").flat_map(
    lambda port: _host("prodHost" if port == 80 else "devHost")
)


def test_lets_an_inner_config_propagate_parsing_failure():
    """lets an inner config propagate parsing failure"""
    assert_failure(
        host_config,
        unknown({"port": 80, "prodHost": "example.com"}),
        'Must end with "effect.website"\n  at ["prodHost"]',
    )


def test_lets_an_inner_config_propagate_key_absence():
    """lets an inner config propagate key absence"""
    assert_failure(host_config, unknown({"port": 80}), 'Expected string\n  at ["prodHost"]')


def test_lets_recover_after_an_inner_config_propagated_parsing_failure():
    """lets recover after an inner config propagated parsing failure"""
    assert_success(
        host_config.or_else(lambda err: config.succeed(err.message)),
        unknown({"port": 80, "prodHost": "example.com"}),
        'SchemaError(Must end with "effect.website"\n  at ["prodHost"])',
    )


def test_lets_recover_after_an_inner_config_propagated_key_absence():
    """lets recover after an inner config propagated key absence"""
    assert_success(host_config.with_default("localhost"), unknown({"port": 80}), "localhost")


def test_propagates_inner_config_success():
    """propagates inner config success"""
    assert_success(
        host_config,
        unknown({"port": 3000, "devHost": "stage.effect.website"}),
        "stage.effect.website",
    )


_BOTH_HOSTS = {"prodHost": "effect.website", "devHost": "effect.website"}


def test_lets_the_base_config_propagate_parsing_failure():
    """lets the base config propagate parsing failure"""
    assert_failure(
        host_config,
        unknown({"port": "zzz", **_BOTH_HOSTS}),
        'Expected a string representing a finite number\n  at ["port"]',
    )


def test_lets_the_base_config_propagate_key_absence():
    """lets the base config propagate key absence"""
    assert_failure(host_config, unknown(_BOTH_HOSTS), 'Expected string\n  at ["port"]')


def test_lets_recover_after_the_base_config_propagated_parsing_failure():
    """lets recover after the base config propagated parsing failure"""
    assert_success(
        host_config.or_else(lambda err: config.succeed(err.message)),
        unknown({"port": "zzz", **_BOTH_HOSTS}),
        'SchemaError(Expected a string representing a finite number\n  at ["port"])',
    )


def test_lets_recover_after_the_base_config_propagated_key_absence():
    """lets recover after the base config propagated key absence"""
    assert_success(host_config.with_default("localhost"), unknown(_BOTH_HOSTS), "localhost")


def test_handles_chains_of_multiple_flat_maps_and_with_defaults():
    """handles chains of multiple flatMaps and withDefaults"""
    marker = object()

    def with_absence_fallback(
        fallback: Config[int],
    ) -> Callable[[Config[int]], Config[int]]:
        def apply(self: Config[int]) -> Config[int]:
            def choose(e: object) -> Config[int]:
                return fallback if e is marker else config.succeed(cast(int, e))

            return self.with_default(marker).flat_map(choose)

        return apply

    port_config = (
        config.port("BACKEND_PORT")
        .pipe(with_absence_fallback(config.port("POOORT")))
        .pipe(with_absence_fallback(config.port("PORT")))
        .with_default(3001)
    )

    assert_success(port_config, unknown({}), 3001)
    assert_success(port_config, unknown({"BACKEND_PORT": 5000, "PORT": 99999}), 5000)
    assert_success(port_config, unknown({"PORT": 5000}), 5000)
    assert_failure(
        port_config, unknown({"PORT": 99999}), 'Expected a value between 1 and 65535\n  at ["PORT"]'
    )
    assert_failure(
        port_config,
        unknown({"BACKEND_PORT": 99999, "PORT": 80}),
        'Expected a value between 1 and 65535\n  at ["BACKEND_PORT"]',
    )


def test_lifts_absence_in_nested_composition():
    """lifts absence in nested composition"""
    cfg = config.all_dict(
        {
            "flag": config.integer("port").flat_map(
                lambda _: config.option(config.string("unused"))
            ),
            "required": config.string("required"),
        }
    ).with_default({"flag": None, "required": "default"})

    assert_success(cfg, unknown({"port": "80"}), {"flag": None, "required": "default"})


@testing.effect
def test_matches_map_when_chained_with_succeed_including_grouped_defaults_and_options():
    """matches map when chained with succeed, including grouped defaults and options"""
    mapped = config.integer("port").map(lambda port: port + 1)
    chained = config.integer("port").flat_map(lambda port: config.succeed(port + 1))

    def group(port: Config[int]) -> Config[dict[str, object]]:
        return config.all_dict({"port": port, "host": config.string("host")})

    wrappers: list[Callable[[Config[int]], Config[object]]] = [
        lambda c: c,
        config.option,
        lambda c: c.with_default(3000),
        group,
        lambda c: config.option(group(c)),
        lambda c: group(c).with_default({"port": 3000, "host": "default"}),
    ]
    inputs: list[dict[str, str]] = [
        {},
        {"port": "80"},
        {"host": "localhost"},
        {"port": "80", "host": "localhost"},
        {"port": "invalid"},
        {"port": "invalid", "host": "localhost"},
    ]
    for value in inputs:
        provider = unknown(value)

        def parse(
            cfg: Config[object], provider: cp.ConfigProvider = provider
        ) -> fx.Effect[fx.Ok[object] | fx.Err[str]]:
            return cfg.parse(provider).map_error(lambda e: e.cause.message).result()

        for wrap in wrappers:
            assert (yield from parse(wrap(chained))) == (yield from parse(wrap(mapped)))


@testing.effect
def test_preserves_the_outer_prefix_and_composes_prefixes_in_the_selected_config():
    """preserves the outer prefix and composes prefixes in the selected config"""
    cfg = (
        config.integer("port")
        .flat_map(
            lambda port: config.string("prodHost" if port == 80 else "devHost").nested("hosts")
        )
        .nested("service")
    )
    root = {"port": 3000, "hosts": {"prodHost": "root-prod", "devHost": "root-dev"}}
    provider = unknown(
        {
            **root,
            "service": {
                "port": 80,
                "prodHost": "wrong-local-path",
                "hosts": {"prodHost": "service-prod", "devHost": "service-dev"},
            },
        }
    )
    assert (yield from cfg.parse(provider)) == "service-prod"

    missing = unknown({**root, "service": {"port": 80}})
    error = yield from cfg.parse(missing).flip()
    assert error.cause.message == 'Expected string\n  at ["service"]["hosts"]["prodHost"]'
    assert (yield from config.option(cfg).parse(missing)) is None


@testing.effect
def test_defers_user_callbacks_until_the_config_effect_is_executed():
    """defers user callbacks until the Config Effect is executed"""
    provider = unknown({})
    calls = {"map": 0, "map_effect": 0, "or_else": 0}

    def count[A](name: str, value: A) -> A:
        calls[name] += 1
        return value

    mapped = config.succeed(1).map(lambda v: count("map", v + 1)).parse(provider)
    mapped_effect = (
        config.succeed(1)
        .map_effect(lambda v: fx.succeed(count("map_effect", v + 1)))
        .parse(provider)
    )
    recovered = (
        config.fail(SchemaError(Forbidden({"message": "failure"})))
        .or_else(lambda _: count("or_else", config.succeed(1)))
        .parse(provider)
    )

    assert calls == {"map": 0, "map_effect": 0, "or_else": 0}
    yield from mapped
    yield from mapped_effect
    yield from recovered
    assert calls == {"map": 1, "map_effect": 1, "or_else": 1}


# --- combinators: all ------------------------------------------------------------------


@testing.effect
def test_resolves_empty_groups_without_using_a_default():
    """resolves empty groups without using a default"""
    provider = unknown({})
    assert (yield from config.all().with_default("fallback").parse(provider)) == ()
    assert (yield from config.all_dict({}).with_default("fallback").parse(provider)) == {}
    assert (yield from config.all(*iter(())).with_default("fallback").parse(provider)) == ()


@testing.effect
def test_preserves_result_values_as_configuration_data():
    """preserves Result values as configuration data"""
    value = fx.Err("data")
    cfg = config.option(
        config.all(
            config.succeed(value),
            config.succeed(value).map(lambda v: v),
            config.succeed(value).map_effect(fx.succeed),
        )
    )

    assert (yield from cfg.parse(unknown({}))) == fx.Some((value, value, value))


@testing.effect
def test_preserves_special_record_keys_without_changing_the_prototype():
    """preserves special record keys without changing the prototype"""
    result = yield from config.all_dict(
        {"__proto__": config.succeed("value"), "constructor": config.succeed(None)}
    ).parse(unknown({}))

    assert result == {"__proto__": "value", "constructor": None}
    assert type(result) is dict


def _assert_group_errors(cfg: Config[object], first: str, second: str) -> None:
    assert_failure(
        cfg,
        unknown({first: "", second: "1"}, preserve_empty_strings=True),
        f'Expected a value with a length of at least 1\n  at ["{first}"]',
    )
    assert_failure(
        cfg,
        unknown({first: "a", second: "b"}),
        f'Expected a string representing a finite number\n  at ["{second}"]',
    )


def test_combines_tuple_inputs_and_preserves_positions():
    """combines tuple inputs and preserves positions"""
    cfg = config.all(config.non_empty_string("a"), config.finite("b"))
    assert_success(cfg, unknown({"a": "a", "b": "1"}), ("a", 1))
    _assert_group_errors(cfg, "a", "b")


def test_combines_generic_iterables_in_iteration_order():
    """combines generic iterables in iteration order"""
    children: list[Config[str | float]] = [config.non_empty_string("a"), config.finite("b")]
    cfg = config.all(*iter(children))
    assert_success(cfg, unknown({"a": "a", "b": "1"}), ("a", 1))
    _assert_group_errors(cfg, "a", "b")


def test_combines_named_fields_and_preserves_their_keys():
    """combines named fields and preserves their keys"""
    cfg = config.all_dict({"a": config.non_empty_string("b"), "c": config.finite("d")})
    assert_success(cfg, unknown({"b": "b", "d": "1"}), {"a": "b", "c": 1})
    _assert_group_errors(cfg, "b", "d")


# --- combinators: withDefault --------------------------------------------------------------


def test_uses_the_parsed_value_when_present_and_the_default_when_absent():
    """uses the parsed value when present and the default when absent"""
    cfg = config.finite("a").with_default(0)
    assert_success(cfg, unknown({"a": "1"}), 1)
    assert_success(cfg, unknown({}), 0)
    assert_failure(
        cfg, unknown({"a": "value"}), 'Expected a string representing a finite number\n  at ["a"]'
    )


def test_supports_redacted_default_values():
    """supports redacted default values"""
    default = Redacted("default")
    cfg = config.redacted("a").with_default(default)
    assert_success(cfg, unknown({"a": "value"}), Redacted("value"))
    assert_success(cfg, unknown({}), default)


def test_treats_ignored_empty_env_strings_as_absent():
    """treats ignored empty env strings as absent"""
    cfg = config.string("a").with_default("default")
    assert_success(cfg, env({"a": ""}), "default")
    assert_success(cfg, env({"a": ""}, preserve_empty_strings=True), "")


_NUMBER_ERROR_AT_A = (
    'Expected a string representing a finite number\n  at ["a"]\n'
    'Expected "Infinity" | "-Infinity" | "NaN"\n  at ["a"]'
)


def test_validates_empty_env_numbers_when_they_are_preserved():
    """validates empty env numbers when they are preserved"""
    cfg = config.number("a").with_default(0)
    assert_success(cfg, env({"a": ""}), 0)
    assert_failure(cfg, env({"a": ""}, preserve_empty_strings=True), _NUMBER_ERROR_AT_A)


def test_defaults_the_whole_product_when_any_required_child_is_absent():
    """defaults the whole product when any required child is absent"""
    default = {"a": "a", "c": 0}
    cfg = config.all_dict(
        {"a": config.non_empty_string("b"), "c": config.finite("d")}
    ).with_default(default)
    assert_success(cfg, unknown({"b": "b", "d": "1"}), {"a": "b", "c": 1})
    assert_success(cfg, unknown({}), default)
    assert_success(cfg, unknown({"b": "b"}), default)
    assert_success(cfg, unknown({"d": "1"}), default)
    assert_failure(
        cfg,
        unknown({"b": "", "d": "1"}, preserve_empty_strings=True),
        'Expected a value with a length of at least 1\n  at ["b"]',
    )


def test_does_not_recover_from_invalid_union_input():
    """does not recover from invalid union input"""
    cfg = config.log_level("LOG_LEVEL").with_default(fx.LogLevel.INFO)
    assert_success(cfg, unknown({}), fx.LogLevel.INFO)
    assert_failure(
        cfg,
        unknown({"LOG_LEVEL": "debug"}),
        'Expected "All" | "Fatal" | "Error" | "Warn" | "Info" | "Debug" | "Trace" | "None"\n'
        '  at ["LOG_LEVEL"]',
    )


def test_does_not_recover_from_schema_refinement_failures():
    """does not recover from schema refinement failures"""
    cfg = checked("a", lambda s: s == "a", 'must be "a"').with_default("fallback")
    assert_success(cfg, unknown({}), "fallback")
    assert_success(cfg, unknown({"a": "a"}), "a")
    assert_failure(cfg, unknown({"a": "b"}), 'must be "a"\n  at ["a"]')


# --- combinators: option ------------------------------------------------------------------


def test_wraps_present_values_and_maps_absence_to_none():
    """wraps present values and maps absence to None"""
    cfg = config.option(config.finite("a"))
    string_cfg = config.option(config.string("a"))
    assert_success(cfg, unknown({"a": "1"}), fx.Some(1))
    assert_success(cfg, unknown({}), None)
    assert_success(cfg, env({"a": ""}), None)
    assert_success(string_cfg, env({"a": ""}, preserve_empty_strings=True), fx.Some(""))
    assert_failure(
        cfg, unknown({"a": "value"}), 'Expected a string representing a finite number\n  at ["a"]'
    )


def test_returns_none_when_any_required_child_is_absent():
    """returns None when any required child is absent"""
    cfg = config.option(
        config.all_dict({"a": config.non_empty_string("b"), "c": config.finite("d")})
    )
    assert_success(cfg, unknown({"b": "b", "d": "1"}), fx.Some({"a": "b", "c": 1}))
    assert_success(cfg, unknown({}), None)
    assert_success(cfg, unknown({"b": "b"}), None)
    assert_success(cfg, unknown({"d": "1"}), None)
    assert_success(cfg, unknown({"b": "", "d": "1"}), None)
    assert_failure(
        cfg,
        unknown({"b": "", "d": "1"}, preserve_empty_strings=True),
        'Expected a value with a length of at least 1\n  at ["b"]',
    )


# --- absence semantics ----------------------------------------------------------------------

_FALLBACK = {"host": "fallback", "port": 0}
_ALL_DATABASE = config.all_dict(
    {"host": config.string("host"), "port": config.finite("port")}
).nested("database")


class _Database(TypedDict):
    host: str
    port: float


_SCHEMA_DATABASE = config.schema(S.Struct(_Database, port=S.Finite)).nested("database")


def test_default_wholly_absent_nested_configurations():
    """default wholly absent nested configurations"""
    assert_success(_SCHEMA_DATABASE.with_default(_FALLBACK), unknown({}), _FALLBACK)
    assert_success(_ALL_DATABASE.with_default(_FALLBACK), unknown({}), _FALLBACK)


def test_distinguish_an_explicit_empty_schema_container_from_an_absent_all_group():
    """distinguish an explicit empty schema container from an absent all group"""
    provider = unknown({"database": {}})
    missing_host = 'Missing key\n  at ["database"]["host"]'
    assert_failure(_SCHEMA_DATABASE.with_default(_FALLBACK), provider, missing_host)
    assert_success(_ALL_DATABASE.with_default(_FALLBACK), provider, _FALLBACK)
    assert_failure(config.option(_SCHEMA_DATABASE), provider, missing_host)
    assert_success(config.option(_ALL_DATABASE), provider, None)


def test_validates_partial_schema_objects_and_recovers_absent_all_children():
    """validates partial schema objects and recovers absent all children"""
    provider = unknown({"database": {"host": "localhost"}})
    assert_failure(
        _SCHEMA_DATABASE.with_default(_FALLBACK),
        provider,
        'Missing key\n  at ["database"]["port"]',
    )
    assert_success(_ALL_DATABASE.with_default(_FALLBACK), provider, _FALLBACK)
    assert_success(config.option(_ALL_DATABASE), provider, None)


@testing.effect
def test_recovers_an_absent_child_alongside_a_successfully_decoded_undefined():
    """recovers an absent child alongside a successfully decoded undefined"""
    cfg = config.all_dict(
        {
            "optional": config.string("optional").with_default(None),
            "required": config.string("required"),
        }
    )
    fallback = {"optional": "fallback", "required": "fallback"}
    provider = unknown({})

    assert (yield from cfg.with_default(fallback).parse(provider)) == fallback
    assert (yield from config.option(cfg).parse(provider)) is None


@testing.effect
def test_rejects_invalid_input_alongside_missing_fields_in_either_field_order():
    """rejects invalid input alongside missing fields in either field order"""
    provider = unknown({"invalid": "not-a-number"})

    class MissingFirst(TypedDict):
        missing: str
        invalid: float

    class InvalidFirst(TypedDict):
        invalid: float
        missing: str

    configs: list[Config[Mapping[str, object]]] = [
        config.schema(S.Struct(MissingFirst, invalid=S.Finite)),
        config.schema(S.Struct(InvalidFirst, invalid=S.Finite)),
        config.all_dict({"missing": config.string("missing"), "invalid": config.finite("invalid")}),
        config.all_dict({"invalid": config.finite("invalid"), "missing": config.string("missing")}),
    ]
    for cfg in configs:
        error = (
            yield from cfg.with_default({"missing": "default", "invalid": 0}).parse(provider).flip()
        )
        assert isinstance(error, ConfigError)


@testing.effect
def test_replaces_the_whole_group_when_a_required_child_remains_absent():
    """replaces the whole group when a required child remains absent"""
    fallback = {"required": "fallback", "defaulted": 0}
    cfg = config.all_dict(
        {
            "required": config.string("required"),
            "defaulted": config.integer("defaulted").with_default(1),
        }
    ).with_default(fallback)

    assert (yield from cfg.parse(unknown({}))) == fallback
    assert (yield from cfg.parse(unknown({"required": "value"}))) == {
        "required": "value",
        "defaulted": 1,
    }
    assert (yield from cfg.parse(unknown({"defaulted": "2"}))) == fallback


@testing.effect
def test_recovers_missing_tuple_and_iterable_children_without_hiding_invalid_input():
    """recovers missing tuple and iterable children without hiding invalid input"""
    orders: list[list[Config[str | int]]] = [
        [config.string("host"), config.integer("port")],
        [config.integer("port"), config.string("host")],
    ]
    for children in orders:
        for cfg in [config.all(*children), config.all(*iter(children))]:
            for value in [{}, {"port": "80"}, {"host": "localhost"}]:
                provider = unknown(value)
                assert (yield from cfg.with_default("default").parse(provider)) == "default"
                assert (yield from config.option(cfg).parse(provider)) is None

            missing = yield from cfg.parse(unknown({"port": "80"})).flip()
            assert missing.cause.message == 'Expected string\n  at ["host"]'

            invalid = unknown({"port": "invalid"})
            wrapped: list[Config[object]] = [cfg.with_default("default"), config.option(cfg)]
            for w in wrapped:
                error = yield from w.parse(invalid).flip()
                assert error.cause.message == (
                    'Expected a string representing a finite number\n  at ["port"]'
                )


@testing.effect
def test_propagates_source_failures_alongside_absence_in_every_group_shape():
    """propagates source failures alongside absence in every group shape"""
    source_error = SourceError("source unavailable")
    provider = cp.make(
        lambda path: fx.fail(source_error) if path[:1] == ("failed",) else fx.succeed(None)
    )
    missing, failed = config.string("missing"), config.string("failed")
    configs: list[Config[object]] = [
        config.all_dict({"missing": missing, "failed": failed}),
        config.all_dict({"failed": failed, "missing": missing}),
        config.all(missing, failed),
        config.all(failed, missing),
        config.all(*iter([missing, failed])),
    ]
    for cfg in configs:
        wrapped: list[Config[object]] = [cfg.with_default("default"), config.option(cfg)]
        for w in wrapped:
            error = yield from w.parse(provider).flip()
            assert error.cause is source_error


@testing.effect
def test_propagates_nested_group_absence_alongside_a_resolved_sibling():
    """propagates nested group absence alongside a resolved sibling"""
    cfg = config.all_dict(
        {
            "name": config.string("name"),
            "database": config.all_dict(
                {"host": config.string("host"), "port": config.integer("port")}
            ).nested("database"),
        }
    )
    provider = unknown({"name": "app", "database": {"host": "db.internal"}})
    fallback = {"name": "default", "database": {"host": "localhost", "port": 5432}}

    assert (yield from cfg.with_default(fallback).parse(provider)) == fallback
    assert (yield from config.option(cfg).parse(provider)) is None
    error = yield from cfg.parse(provider).flip()
    assert error.cause.message == 'Expected string\n  at ["database"]["port"]'


@testing.effect
def test_treats_mapped_effectfully_mapped_and_constant_siblings_alike():
    """treats mapped, effectfully mapped, and constant siblings alike"""
    provider = unknown({"port": "80"})
    fallback = {"port": 3000, "host": "localhost"}
    ports: list[Config[int]] = [
        config.integer("port").map(lambda v: v + 1),
        config.integer("port").map_effect(lambda v: fx.succeed(v + 1)),
        config.succeed(81),
    ]
    for port in ports:
        cfg = config.all_dict({"port": port, "host": config.string("host")})
        assert (yield from cfg.with_default(fallback).parse(provider)) == fallback
        assert (yield from config.option(cfg).parse(provider)) is None


def _recovering_group() -> Config[Mapping[str, object]]:
    return config.all_dict(
        {
            "recovered": config.integer("recovered").or_else(lambda _: config.succeed(1)),
            "required": config.string("required"),
        }
    ).with_default({"recovered": 0, "required": "default"})


@testing.effect
def test_recovers_an_absent_sibling_after_or_else_handles_invalid_input():
    """recovers an absent sibling after orElse handles invalid input"""
    cfg = _recovering_group()
    assert (yield from cfg.parse(unknown({"recovered": "invalid"}))) == {
        "recovered": 0,
        "required": "default",
    }
    assert (yield from cfg.parse(unknown({"recovered": "invalid", "required": "value"}))) == {
        "recovered": 1,
        "required": "value",
    }


@testing.effect
def test_recovers_an_absent_sibling_after_or_else_handles_absence():
    """recovers an absent sibling after orElse handles absence"""
    assert (yield from _recovering_group().parse(unknown({}))) == {
        "recovered": 0,
        "required": "default",
    }


@testing.effect
def test_lets_defaults_and_option_handle_an_absent_or_else_fallback():
    """lets defaults and option handle an absent orElse fallback"""
    cfg = config.integer("primary").or_else(lambda _: config.string("fallback"))
    provider = unknown({"primary": "invalid"})

    assert (yield from cfg.with_default("default").parse(provider)) == "default"
    assert (yield from config.option(cfg).parse(provider)) is None


@testing.effect
def test_uses_the_or_else_fallback_result_within_the_nested_path():
    """uses the orElse fallback result within the nested path"""
    cfg = config.integer("primary").or_else(lambda _: config.integer("fallback")).nested("service")
    assert (
        yield from cfg.parse(unknown({"service": {"primary": "invalid", "fallback": "80"}}))
    ) == 80
    assert (
        yield from cfg.with_default(3000).parse(
            unknown({"service": {"primary": "invalid"}, "fallback": "80"})
        )
    ) == 3000

    invalid = unknown({"service": {"primary": "invalid", "fallback": "1.5"}})
    wrapped: list[Config[object]] = [cfg.with_default(3000), config.option(cfg)]
    for w in wrapped:
        error = yield from w.parse(invalid).flip()
        assert error.cause.message == 'Expected an integer\n  at ["service"]["fallback"]'


@testing.effect
def test_propagates_an_or_else_fallback_source_error_after_recovering_invalid_input():
    """propagates an orElse fallback source error after recovering invalid input"""
    source_error = SourceError("fallback unavailable")
    provider = cp.make(
        lambda path: (
            fx.succeed(Value("invalid")) if path[:1] == ("primary",) else fx.fail(source_error)
        )
    )
    cfg = config.integer("primary").or_else(lambda _: config.integer("fallback"))
    wrapped: list[Config[object]] = [cfg.with_default(3000), config.option(cfg)]
    for w in wrapped:
        error = yield from w.parse(provider).flip()
        assert error.cause is source_error


@testing.effect
def test_recovers_an_absent_sibling_after_or_else_handles_map_effect_failure():
    """recovers an absent sibling after orElse handles mapEffect failure"""
    validation_error = ConfigError(SchemaError(Forbidden({"message": "invalid value"})))
    fallback = {"recovered": "default", "required": "default"}

    def reject(_: str) -> fx.Effect[Never, ConfigError]:
        return fx.fail(validation_error)

    cfg = config.all_dict(
        {
            "recovered": config.string("recovered")
            .map_effect(reject)
            .or_else(lambda _: config.succeed("fallback")),
            "required": config.string("required"),
        }
    ).with_default(fallback)

    assert (yield from cfg.parse(unknown({"recovered": "value"}))) == fallback


def _group_with_recovered(recovered: Config[object]) -> Config[Mapping[str, object]]:
    return config.all_dict({"recovered": recovered, "required": config.string("required")})


@testing.effect
def test_recovers_an_absent_sibling_after_or_else_handles_a_descendant_source_failure():
    """recovers an absent sibling after orElse handles a descendant source failure"""
    source_error = SourceError("source unavailable")

    def lookup(path: cp.Path) -> fx.Effect[cp.Node | None, SourceError]:
        if path == ():
            return fx.succeed(Record(frozenset({"value"})))
        return fx.fail(source_error) if path == ("value",) else fx.succeed(None)

    fallback = {"recovered": {"value": "default"}, "required": "default"}
    recovered = config.dict_of(config.string()).or_else(
        lambda _: config.succeed({"value": "fallback"})
    )
    cfg = _group_with_recovered(recovered).with_default(fallback)

    assert (yield from cfg.parse(cp.make(lookup))) == fallback


@testing.effect
def test_recovers_an_absent_sibling_after_or_else_handles_a_nested_group_failure():
    """recovers an absent sibling after orElse handles a nested group failure"""
    source_error = SourceError("source unavailable")

    def lookup(path: cp.Path) -> fx.Effect[cp.Node | None, SourceError]:
        if path[:1] == ("failed",):
            return fx.fail(source_error)
        return fx.succeed(Value("value") if path[:1] == ("present",) else None)

    recovered = config.all_dict(
        {"failed": config.string("failed"), "present": config.string("present")}
    ).or_else(lambda _: config.succeed({"failed": "recovered", "present": "recovered"}))
    fallback = {"recovered": {"failed": "default", "present": "default"}, "required": "default"}
    cfg = _group_with_recovered(recovered).with_default(fallback)

    assert (yield from cfg.parse(cp.make(lookup))) == fallback


@testing.effect
def test_recovers_an_absent_sibling_after_or_else_handles_an_initial_source_failure():
    """recovers an absent sibling after orElse handles an initial source failure"""
    source_error = SourceError("source unavailable")
    provider = cp.make(lambda path: fx.fail(source_error) if path == () else fx.succeed(None))
    fallback = {"recovered": {"value": "default"}, "required": "default"}
    recovered = config.dict_of(config.string()).or_else(
        lambda _: config.succeed({"value": "fallback"})
    )
    cfg = _group_with_recovered(recovered).with_default(fallback)

    assert (yield from cfg.parse(provider)) == fallback


@testing.effect
def test_normalizes_unavailable_scalar_representations_to_absence():
    """normalizes unavailable scalar representations to absence"""
    provider = cp.make(lambda path: fx.succeed(Record(frozenset()) if path == ("value",) else None))
    cfg = config.string("value")

    assert (yield from cfg.with_default("default").parse(provider)) == "default"
    assert (yield from config.option(cfg).parse(provider)) is None


@testing.effect
def test_treats_incompatible_container_representations_as_absent():
    """treats incompatible container representations as absent"""
    record = config.dict_of(config.string(), "value")
    array = config.list_of(config.string(), "value")

    assert (yield from record.with_default({"value": "default"}).parse(unknown({"value": []}))) == {
        "value": "default"
    }
    assert (yield from config.option(array).parse(unknown({"value": {}}))) is None


@testing.effect
def test_propagates_provider_failures():
    """propagates provider failures"""
    cause = SourceError("source unavailable")
    provider = cp.make(lambda _: fx.fail(cause))

    error = yield from config.string("a").with_default("fallback").parse(provider).flip()

    assert error.cause is cause


# --- nested ----------------------------------------------------------------------------


def test_prefixes_a_root_config_with_from_unknown():
    """with fromUnknown: prefixes a root config"""
    cfg = config.string().nested("a")
    assert_success(cfg, unknown({"a": "value"}), "value")
    assert_failure(cfg, unknown({}), 'Expected string\n  at ["a"]')


def test_composes_a_constructor_path_with_a_prefix_with_from_unknown():
    """with fromUnknown: composes a constructor path with a prefix"""
    cfg = config.string("a").nested("b")
    assert_success(cfg, unknown({"b": {"a": "value"}}), "value")
    assert_failure(cfg, unknown({}), 'Expected string\n  at ["b"]["a"]')


def test_composes_multiple_prefixes_from_outermost_to_innermost_with_from_unknown():
    """with fromUnknown: composes multiple prefixes from outermost to innermost"""
    cfg = config.string("a").nested("b").nested("c")
    assert_success(cfg, unknown({"c": {"b": {"a": "value"}}}), "value")
    assert_failure(cfg, unknown({"c": {"b": {}}}), 'Expected string\n  at ["c"]["b"]["a"]')


def _database() -> Config[Mapping[str, object]]:
    return config.all_dict({"host": config.string("host"), "port": config.number("port")}).nested(
        "database"
    )


def test_prefixes_every_child_of_an_all_product_with_from_unknown():
    """with fromUnknown: prefixes every child of an all product"""
    assert_success(
        _database(),
        unknown({"database": {"host": "localhost", "port": "5432"}}),
        {"host": "localhost", "port": 5432},
    )
    assert_failure(_database(), unknown({}), 'Expected string\n  at ["database"]["host"]')


def test_prefixes_a_root_config_with_from_env():
    """with fromEnv: prefixes a root config"""
    cfg = config.string().nested("a")
    assert_success(cfg, env({"a": "value"}), "value")
    assert_failure(cfg, env({}), 'Expected string\n  at ["a"]')


def test_composes_a_constructor_path_with_a_prefix_with_from_env():
    """with fromEnv: composes a constructor path with a prefix"""
    cfg = config.string("a").nested("b")
    assert_success(cfg, env({"b_a": "value"}), "value")
    assert_failure(cfg, env({}), 'Expected string\n  at ["b"]["a"]')


def test_composes_multiple_prefixes_from_outermost_to_innermost_with_from_env():
    """with fromEnv: composes multiple prefixes from outermost to innermost"""
    cfg = config.string("a").nested("b").nested("c")
    assert_success(cfg, env({"c_b_a": "value"}), "value")
    assert_failure(cfg, env({"c_b": "value"}), 'Expected string\n  at ["c"]["b"]["a"]')


def test_prefixes_every_child_of_an_all_product_with_from_env():
    """with fromEnv: prefixes every child of an all product"""
    assert_success(
        _database(),
        env({"database_host": "localhost", "database_port": "5432"}),
        {"host": "localhost", "port": 5432},
    )
    assert_failure(_database(), env({}), 'Expected string\n  at ["database"]["host"]')


def test_composes_config_and_provider_prefixes_without_leaking_provider_paths_into_errors():
    """composes Config and provider prefixes without leaking provider paths into errors"""
    cfg = config.string("host").nested("database")
    assert_success(cfg, env({"app_database_host": "localhost"}).nested("app"), "localhost")
    assert_failure(cfg, env({}).nested("app"), 'Expected string\n  at ["database"]["host"]')


def test_preserves_logical_error_paths_through_provider_fallback():
    """preserves logical error paths through provider fallback"""
    provider = env({"app_port": "abc"}).or_else(env({})).nested("app")
    assert_failure(
        config.number("port"),
        provider,
        'Expected a string representing a finite number\n  at ["port"]\n'
        'Expected "Infinity" | "-Infinity" | "NaN"\n  at ["port"]',
    )


# --- unwrap ------------------------------------------------------------------------------


def test_combines_a_plain_record_of_configs():
    """combines a plain record of configs"""
    assert_success(
        config.unwrap({"a": config.string("a2")}), unknown({"a2": "value"}), {"a": "value"}
    )


def test_recursively_combines_nested_records():
    """recursively combines nested records"""
    assert_success(
        config.unwrap({"a": {"b": config.string("b2")}}),
        unknown({"b2": "value"}),
        {"a": {"b": "value"}},
    )


# --- schema: built-in schema-backed constructors --------------------------------------------


def test_preserves_proto_record_keys():
    """preserves __proto__ record keys"""
    assert_success(
        config.dict_of(config.string(), "a"),
        unknown({"a": {"__proto__": "value"}}),
        {"__proto__": "value"},
    )


def test_decodes_supported_boolean_spellings():
    """decodes supported boolean spellings"""
    spellings = {"a": "true", "b": "false", "c": "yes", "d": "no", "e": "on", "f": "off"}
    spellings |= {"g": "1", "h": "0", "i": "y", "j": "n", "failure": "value"}
    provider = unknown(spellings)
    for name, expected in zip("abcdefghij", [True, False] * 5, strict=True):
        assert_success(config.boolean(name), provider, expected)
    assert_failure(
        config.boolean("failure"),
        provider,
        'Expected "true" | "yes" | "on" | "1" | "y" | "false" | "no" | "off" | "0" | "n"\n'
        '  at ["failure"]',
    )


def test_decodes_durations_including_infinities():
    """decodes durations including infinities"""
    provider = unknown(
        {"a": "1000 millis", "b": "1 second", "c": "Infinity", "d": "-Infinity", "failure": "value"}
    )
    assert_success(config.duration("a"), provider, millis(1000))
    assert_success(config.duration("b"), provider, seconds(1))
    assert_success(config.duration("c"), provider, infinity)
    assert_success(config.duration("d"), provider, negative_infinity)
    assert_failure(
        config.duration("failure"), provider, 'Expected a valid Duration string\n  at ["failure"]'
    )


def test_decodes_exact_byte_sizes_and_reports_invalid_input():
    """decodes exact byte sizes and reports invalid input"""
    provider = unknown({"huge": "9007199254740993 B", "invalid": "10 MBi"})
    assert_success(config.byte_size("huge"), provider, ByteSize(9_007_199_254_740_993))
    assert_failure(
        config.byte_size("invalid"), provider, 'Expected a valid ByteSize string\n  at ["invalid"]'
    )


def test_validates_port_ranges():
    """validates port ranges"""
    provider = unknown({"a": "8080", "failure": "-1"})
    assert_success(config.port("a"), provider, 8080)
    assert_failure(
        config.port("failure"), provider, 'Expected a value between 1 and 65535\n  at ["failure"]'
    )


def test_validates_log_level_literals():
    """validates log-level literals"""
    provider = unknown({"a": "Info", "failure_1": "info", "failure_2": "value"})
    assert_success(config.log_level("a"), provider, fx.LogLevel.INFO)
    for name in ["failure_1", "failure_2"]:
        assert_failure(
            config.log_level(name),
            provider,
            'Expected "All" | "Fatal" | "Error" | "Warn" | "Info" | "Debug" | "Trace" | "None"\n'
            f'  at ["{name}"]',
        )


# --- schema: Config.Record (dict_of) ----------------------------------------------------------

_ATTRIBUTES = {
    "service.name": "my-service",
    "service.version": "1.0.0",
    "custom.attribute": "value",
}


def test_decodes_object_input():
    """Record: decodes object input"""
    assert_success(
        config.dict_of(config.string(), "OTEL_RESOURCE_ATTRIBUTES"),
        unknown({"OTEL_RESOURCE_ATTRIBUTES": _ATTRIBUTES}),
        _ATTRIBUTES,
    )


def test_decodes_separated_string_input():
    """Record: decodes separated string input"""
    text = "service.name=my-service,service.version=1.0.0,custom.attribute=value"
    assert_success(
        config.dict_of(config.string(), "OTEL_RESOURCE_ATTRIBUTES"),
        env({"OTEL_RESOURCE_ATTRIBUTES": text}),
        _ATTRIBUTES,
    )


def test_keeps_key_value_separators_inside_values():
    """Record: keeps key-value separators inside values"""
    assert_success(
        config.dict_of(config.string(), "OTEL_EXPORTER_OTLP_HEADERS"),
        env({"OTEL_EXPORTER_OTLP_HEADERS": "authorization=Basic dXNlcjpwYXNz==,x-tenant=a=b"}),
        {"authorization": "Basic dXNlcjpwYXNz==", "x-tenant": "a=b"},
    )


def test_supports_an_empty_key_value_separator():
    """Record: supports an empty key-value separator"""
    assert_success(
        config.dict_of(config.string(), key_value_separator=""),
        unknown("ab,cd"),
        {"a": "b", "c": "d"},
    )


def test_supports_custom_separators():
    """Record: supports custom separators"""
    text = "service.name==my-service&service.version==1.0.0&custom.attribute==a==b"
    expected = {
        "service.name": "my-service",
        "service.version": "1.0.0",
        "custom.attribute": "a==b",
    }
    options: dict[str, Any] = {"separator": "&", "key_value_separator": "=="}
    assert_success(config.dict_of(config.string(), **options), unknown(text), expected)
    assert_success(
        config.dict_of(config.string(), "OTEL_RESOURCE_ATTRIBUTES", **options),
        unknown({"OTEL_RESOURCE_ATTRIBUTES": text}),
        expected,
    )


def test_trims_and_keeps_empty_values_when_requested():
    """Record: trims and keeps empty values when requested"""
    assert_success(
        config.dict_of(
            config.string(), "OTEL_RESOURCE_ATTRIBUTES", trim=True, keep_empty_values=True
        ),
        env({"OTEL_RESOURCE_ATTRIBUTES": " b = x ,empty=, =ignored"}),
        {"b": "x", "empty": ""},
    )
    assert_success(
        config.dict_of(config.string(), "OTEL_RESOURCE_ATTRIBUTES"),
        env({"OTEL_RESOURCE_ATTRIBUTES": " b = x ,empty=, =ignored"}),
        {" b ": " x ", " ": "ignored"},
    )


# --- schema: materialization (Config.Record / Config.Array) -------------------------------------


@testing.effect
def test_leaves_separated_record_parsing_to_the_explicit_config_record_constructor():
    """leaves separated record parsing to the explicit Config.Record constructor"""
    provider = env({"values": "first=1,second=2"})
    assert (yield from config.dict_of(config.finite(), "values").parse(provider)) == {
        "first": 1,
        "second": 2,
    }


@testing.effect
def test_preserves_missing_array_positions_as_undefined_values():
    """preserves missing array positions as undefined values"""

    def lookup(path: cp.Path) -> fx.Effect[cp.Node | None]:
        if path == ():
            return fx.succeed(Array(2))
        return fx.succeed(Value("value") if path == (0,) else None)

    cfg = config.list_of(config.string().with_default(None))
    assert (yield from cfg.parse(cp.make(lookup))) == ["value", None]


@testing.effect
def test_leaves_scalar_to_array_parsing_to_the_explicit_config_array_constructor():
    """leaves scalar-to-array parsing to the explicit Config.Array constructor"""
    provider = env({"values": "1,2", "values_0": "3"})
    assert (yield from config.list_of(S.Finite, "values").parse(provider)) == [1, 2]
    assert (yield from config.schema(S.Array(S.Finite), "values").parse(provider)) == (3,)


@testing.effect
def test_supports_options_with_and_without_a_path():
    """supports options with and without a path"""
    assert (yield from config.list_of(config.finite(), separator=";").parse(unknown("1;2"))) == [
        1,
        2,
    ]
    assert (
        yield from config.list_of(config.finite(), "values", separator=";").parse(
            unknown({"values": "1;2"})
        )
    ) == [1, 2]
