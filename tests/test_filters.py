"""``pyfect.filters``: Effect's ``Filter`` module (Filter.ts is the spec;
Effect has no Filter.test.ts)."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import pyfect as fx
from pyfect import filters
from pyfect.option import Some
from pyfect.result import Err, Ok, Result


def even(n: int) -> Result[int, int]:
    return Ok(n) if n % 2 == 0 else Err(n)


def positive_n(n: int) -> bool:
    return n > 0


def bigger_than_two(n: int) -> bool:
    return n > 2


def halve(n: int) -> Result[int, str]:
    return Ok(n // 2) if n % 4 == 0 else Err(f"{n} is not a multiple of 4")


def test_make_and_to_result_are_the_function_itself() -> None:
    assert filters.make(even) is even
    assert filters.to_result(even) is even

    def even_effect(n: int) -> fx.Effect[Result[int, int]]:
        return fx.succeed(even(n))

    assert filters.make_effect(even_effect) is even_effect


def test_map_fail_maps_only_the_failure() -> None:
    f = filters.map_fail(even, str)
    assert f(2) == Ok(2)
    assert f(3) == Err("3")


def test_try_fails_with_the_input_when_the_function_raises() -> None:
    parse = filters.try_(json.loads)
    assert parse("1") == Ok(1)
    assert parse("") == Err("")


def test_from_predicate_and_back() -> None:
    positive = filters.from_predicate(positive_n)
    assert positive(1) == Ok(1)
    assert positive(-1) == Err(-1)
    assert filters.to_predicate(positive)(1)
    assert not filters.to_predicate(positive)(-1)


def test_from_predicate_option_and_to_option() -> None:
    def doubled(n: int) -> Some[int] | None:
        return Some(n * 2) if n > 0 else None

    f = filters.from_predicate_option(doubled)
    assert f(1) == Ok(2)
    assert f(0) == Err(0)
    assert filters.to_option(even)(2) == Some(2)
    assert filters.to_option(even)(3) is None


def test_type_filters() -> None:
    now = datetime.now(UTC)
    assert filters.string("a") == Ok("a")
    assert filters.string(1) == Err(1)
    assert filters.number(1.5) == Ok(1.5)
    assert filters.number(True) == Err(True)
    assert filters.boolean(False) == Ok(False)
    assert filters.boolean(0) == Err(0)
    assert filters.date(now) == Ok(now)
    assert filters.date("2020") == Err("2020")


def test_equals_passes_the_given_value() -> None:
    f = filters.equals((1, 2))
    assert f((1, 2)) == Ok((1, 2))
    assert f((2, 1)) == Err((2, 1))
    # An equal input passes ``value`` itself, not the input.
    one = filters.equals(1)(1.0)
    assert isinstance(one, Ok)
    assert type(one.value) is int


def test_has_and_instance_of() -> None:
    has_a = filters.has("a")
    assert has_a({"a", "b"}) == Ok({"a", "b"})
    assert has_a({"b"}) == Err({"b"})
    ints = filters.instance_of(int)
    assert ints(1) == Ok(1)
    assert ints("1") == Err("1")


@dataclass
class RateLimited:
    seconds: int


@dataclass
class QuotaExceeded:
    pass


@dataclass
class AiError(Exception):
    reason: RateLimited | QuotaExceeded


def test_reason_passes_the_matching_reason_of_the_error() -> None:
    f = filters.reason(AiError, RateLimited)
    assert f(AiError(RateLimited(3))) == Ok(RateLimited(3))
    quota = AiError(QuotaExceeded())
    assert f(quota) == Err(quota)
    assert f("other") == Err("other")


def test_or_tries_the_second_filter_on_the_same_input() -> None:
    def big(n: int) -> Result[int, str]:
        return Ok(-n) if n > 10 else Err(f"small {n}")

    f = filters.or_(even, big)
    assert f(2) == Ok(2)
    assert f(11) == Ok(-11)
    assert f(3) == Err("small 3")


def test_zip_and_and_left_right_need_both_filters_to_pass() -> None:
    big = filters.from_predicate(bigger_than_two)
    assert filters.zip(even, big)(4) == Ok((4, 4))
    assert filters.zip(even, big)(3) == Err(3)
    assert filters.zip(even, big)(2) == Err(2)
    assert filters.zip_with(even, big, lambda a, b: a + b)(4) == Ok(8)
    assert filters.and_left(even, filters.map_fail(big, str))(2) == Err("2")
    assert filters.and_right(even, halve)(8) == Ok(4)


def test_compose_runs_the_second_filter_on_what_the_first_passes() -> None:
    f = filters.compose(even, halve)
    assert f(8) == Ok(4)
    assert f(3) == Err(3)
    assert f(6) == Err("6 is not a multiple of 4")


def test_compose_passthrough_fails_with_the_original_input() -> None:
    f = filters.compose_passthrough(even, halve)
    assert f(8) == Ok(4)
    assert f(3) == Err(3)
    assert f(6) == Err(6)


def test_a_filter_built_here_works_with_catch_filter() -> None:
    eff = fx.fail(4).catch_filter(even, lambda n: fx.succeed(n * 10))
    assert fx.run_sync_exit(eff) == fx.exit.succeed(40)
