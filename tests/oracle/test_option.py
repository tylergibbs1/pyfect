"""Ports of Effect's ``Option.test.ts``, for pyfect's ``Some[A] | None``.

The functions are data-first (``option.map(o, f)``): ``None`` has no methods,
and pyright infers a data-first call fully. Omitted: ``makeReducer`` /
``makeReducerFailFast``, ``makeOrder``, ``makeEquivalence`` (``key=``
functions and ``==``, docs/PARITY.md section 4); ``gen`` and the Do notation
titles (``Do``, ``bindTo``, ``bind``, ``let``: generator locals, section 4);
``toString`` / ``toJSON`` / ``inspect`` (the dataclass ``repr``); ``isOption``
(any value may be absence); ``unit`` is ``void``; ``getOrUndefined``,
``fromUndefinedOr`` and ``fromNullOr`` (Python has one ``None``; section 4);
``.pipe()`` (``None`` has no methods).
"""

import json
from collections.abc import Iterator

import pytest

from pyfect import NoSuchElementException, option
from pyfect.option import Option, Some
from pyfect.result import Err, Ok, Result


def absent() -> Option[int]:
    return None


def gt2(n: int) -> bool:
    return n > 2


def test_verify_structural_equality() -> None:
    """verify structural equality"""
    assert Some(1) == Some(1)
    assert Some(1) != Some(2)
    assert absent() == absent()


def test_verify_hash_equality() -> None:
    """verify hash equality"""
    assert hash(Some(1)) == hash(Some(1))
    assert hash(Some(1)) != hash(Some(2))
    assert hash(absent()) == hash(absent())


def test_get_success() -> None:
    """getSuccess"""
    assert option.get_success(Ok(1)) == Some(1)
    assert option.get_success(Err("a")) is None


def test_get_failure() -> None:
    """getFailure"""
    assert option.get_failure(Ok(1)) is None
    assert option.get_failure(Err("a")) == Some("a")


def test_to_refinement() -> None:
    """toRefinement"""

    def f(s: str | int) -> Option[str]:
        return Some(s) if isinstance(s, str) else None

    is_string = option.to_refinement(f)
    assert is_string("s")
    assert not is_string(1)


def test_first_some_of() -> None:
    """firstSomeOf"""
    assert option.first_some_of([]) is None
    assert option.first_some_of([Some(1)]) == Some(1)
    assert option.first_some_of([absent()]) is None
    assert option.first_some_of([absent(), absent(), absent(), absent(), Some(1)]) == Some(1)
    assert option.first_some_of([absent(), absent(), absent(), absent()]) is None
    # Effect returns at the first Some, reading no further.
    seen: list[int] = []

    def options() -> Iterator[Option[int]]:
        for n in range(5):
            seen.append(n)
            yield Some(n) if n == 1 else None

    assert option.first_some_of(options()) == Some(1)
    assert seen == [0, 1]


def test_or_else_result() -> None:
    """orElseResult"""
    assert option.or_else_result(Some(1), lambda: Some(2)) == Some(Err(1))
    assert option.or_else_result(Some(1), lambda: None) == Some(Err(1))
    assert option.or_else_result(absent(), lambda: Some(2)) == Some(Ok(2))
    assert option.or_else_result(absent(), lambda: None) is None


def test_or_else_some() -> None:
    """orElseSome"""
    assert option.or_else_some(Some(1), lambda: 2) == Some(1)
    assert option.or_else_some(absent(), lambda: 2) == Some(2)


def test_get_or_throw() -> None:
    """getOrThrow"""
    assert option.get_or_raise(Some(1)) == 1
    with pytest.raises(NoSuchElementException, match="get_or_raise called on None"):
        option.get_or_raise(None)


def test_get_or_throw_with() -> None:
    """getOrThrowWith"""
    assert option.get_or_raise_with(Some(1), lambda: ValueError("Unexpected None")) == 1
    with pytest.raises(ValueError, match="Unexpected None"):
        option.get_or_raise_with(absent(), lambda: ValueError("Unexpected None"))


def test_unit() -> None:
    """unit"""
    assert option.void == Some(None)


def test_product() -> None:
    """product"""
    assert option.product(absent(), absent()) is None
    assert option.product(Some(1), absent()) is None
    assert option.product(absent(), Some("a")) is None
    assert option.product(Some(1), Some("a")) == Some((1, "a"))


def test_product_many() -> None:
    """productMany"""
    assert option.product_many(absent(), []) is None
    assert option.product_many(Some(1), []) == Some((1,))
    assert option.product_many(Some(1), [absent()]) is None
    assert option.product_many(Some(1), [Some(2)]) == Some((1, 2))


def test_from_iterable() -> None:
    """fromIterable"""
    assert option.from_iterable([]) is None
    assert option.from_iterable(["a"]) == Some("a")
    # The reason Option exists: a present None is not absence.
    assert option.from_iterable([None]) == Some(None)


def test_map() -> None:
    """map"""
    assert option.map(Some(2), lambda n: n * 2) == Some(4)
    assert option.map(absent(), lambda n: n * 2) is None


def test_flat_map() -> None:
    """flatMap"""

    def f(n: int) -> Option[int]:
        return Some(n * 2)

    def g(_: int) -> Option[int]:
        return None

    assert option.flat_map(Some(1), f) == Some(2)
    assert option.flat_map(None, f) is None
    assert option.flat_map(Some(1), g) is None
    assert option.flat_map(None, g) is None


def test_and_then() -> None:
    """andThen"""
    # pyfect's and_then takes the next Option, as Effect.and_then takes the next
    # effect; Effect's function and plain-value forms are flat_map and as_.
    assert option.and_then(Some(1), Some(2)) == Some(2)
    assert option.and_then(absent(), Some(2)) is None
    assert option.flat_map(Some(1), lambda _: Some(2)) == Some(2)
    assert option.as_(Some(1), 2) == Some(2)
    assert option.map(Some(1), lambda a: a) == Some(1)


def test_or_else() -> None:
    """orElse"""

    def check(a: Option[int], b: Option[int], expected: Option[int]) -> None:
        assert option.or_else(a, lambda: b) == expected

    check(Some(1), Some(2), Some(1))
    check(Some(1), None, Some(1))
    check(None, Some(2), Some(2))
    check(None, None, None)


def test_partition_map() -> None:
    """partitionMap"""

    def f(n: int) -> Result[int, int]:
        return Ok(n + 1) if gt2(n) else Err(n - 1)

    assert option.partition_map(absent(), f) == (None, None)
    assert option.partition_map(Some(1), f) == (None, Some(0))
    assert option.partition_map(Some(3), f) == (Some(4), None)


def test_filter_map() -> None:
    """filterMap"""

    def f(n: int) -> Result[int, None]:
        return Ok(n + 1) if gt2(n) else Err(None)

    assert option.filter_map(absent(), f) is None
    assert option.filter_map(Some(1), f) is None
    assert option.filter_map(Some(3), f) == Some(4)


def test_match() -> None:
    """match"""

    def match(o: Option[str]) -> str:
        return option.match(o, on_none=lambda: "none", on_some=lambda s: f"some{len(s)}")

    assert match(None) == "none"
    assert match(Some("abc")) == "some3"


def test_get_or_else() -> None:
    """getOrElse"""
    assert option.get_or_else(Some(1), lambda: 0) == 1
    assert option.get_or_else(None, lambda: 0) == 0


def test_get_or_null() -> None:
    """getOrNull"""
    assert option.get_or_none(None) is None
    assert option.get_or_none(Some(1)) == 1


def test_flat_map_nullish_or() -> None:
    """flatMapNullishOr"""
    x1: dict[str, dict[str, dict[str, int]]] = {}
    x2: dict[str, dict[str, dict[str, int]]] = {"b": {}}
    x3: dict[str, dict[str, dict[str, int]]] = {"b": {"c": {"d": 1}}}

    def path(x: dict[str, dict[str, dict[str, int]]]) -> Option[int]:
        b = option.flat_map_optional(Some(x), lambda a: a.get("b"))
        c = option.flat_map_optional(b, lambda b: b.get("c"))
        return option.flat_map_optional(c, lambda c: c.get("d"))

    assert path(x1) is None
    assert path(x2) is None
    assert path(x3) == Some(1)


def test_from_nullish_or() -> None:
    """fromNullishOr"""
    assert option.from_optional(2) == Some(2)
    assert option.from_optional(None) is None


def test_lift_predicate() -> None:
    """liftPredicate"""
    assert option.lift_predicate(1, gt2) is None
    assert option.lift_predicate(3, gt2) == Some(3)

    def is_direction(s: str) -> bool:
        return s in ("asc", "desc")

    assert option.lift_predicate("asc", is_direction) == Some("asc")
    assert option.lift_predicate("foo", is_direction) is None


def test_contains_with() -> None:
    """containsWith"""

    def same_parity(a: int, b: int) -> bool:
        return a % 2 == b % 2

    contains_with = option.contains_with(same_parity)
    assert contains_with(Some(2), 2)
    assert contains_with(Some(4), 4)
    assert contains_with(Some(1), 3)
    assert not contains_with(absent(), 2)
    assert not contains_with(Some(2), 1)


def test_contains() -> None:
    """contains"""
    assert not option.contains(absent(), 2)
    assert option.contains(Some(2), 2)
    assert not option.contains(Some(2), 1)


def test_is_none() -> None:
    """isNone"""
    assert option.is_none(absent())
    assert not option.is_none(Some(1))


def test_is_some() -> None:
    """isSome"""
    assert not option.is_some(absent())
    assert option.is_some(Some(1))


def test_exists() -> None:
    """exists"""
    assert not option.exists(absent(), lambda a: a == 2)
    assert not option.exists(Some(1), lambda a: a == 2)
    assert option.exists(Some(2), lambda a: a == 2)


def test_lift_nullish_or() -> None:
    """liftNullishOr"""

    def positive(n: int) -> int | None:
        return n if n > 0 else None

    f = option.lift_optional(positive)
    assert f(1) == Some(1)
    assert f(-1) is None


def test_lift_throwable() -> None:
    """liftThrowable"""
    parse = option.lift_throwable(json.loads)
    assert parse("1") == Some(1)
    assert parse("") is None

    # Any exception is absence, as Effect's bare catch.
    def lookup(d: dict[str, int]) -> int:
        return d["missing"]

    assert option.lift_throwable(lookup)({}) is None


def test_tap() -> None:
    """tap"""
    assert option.tap(absent(), lambda _: None) is None
    assert option.tap(Some(1), lambda _: None) is None
    assert option.tap(absent(), lambda n: Some(n * 2)) is None
    assert option.tap(Some(1), lambda n: Some(n * 2)) == Some(1)


def test_filter_keeps_do_notation_records_only_when_the_predicate_passes() -> None:
    """filter keeps Do notation records only when the predicate passes"""
    # A dict stands in for the Do record.
    same = option.filter(Some({"x": "a", "y": "a"}), lambda r: r["x"] == r["y"])
    assert same == Some({"x": "a", "y": "a"})
    assert option.filter(Some({"x": "a", "y": "b"}), lambda r: r["x"] == r["y"]) is None


def test_zip_with() -> None:
    """zipWith"""
    assert option.zip_with(absent(), Some(2), lambda a, b: a + b) is None
    assert option.zip_with(Some(1), absent(), lambda a, b: a + b) is None
    assert option.zip_with(Some(1), Some(2), lambda a, b: a + b) == Some(3)


def test_reduce_compact() -> None:
    """reduceCompact"""

    def total(items: list[Option[int]]) -> int:
        return option.reduce_compact(items, 0, lambda b, a: b + a)

    assert total([]) == 0
    assert total([Some(2), Some(3)]) == 5
    assert total([Some(2), None, Some(3)]) == 5


def test_all_tuple() -> None:
    """all: tuple"""
    assert option.all() == Some(())
    assert option.all(Some(1), Some("hello")) == Some((1, "hello"))
    assert option.all(Some(1), None) is None


def test_all_iterable() -> None:
    """all: iterable"""
    assert option.all(*[absent()]) is None
    assert option.all(*[Some(1), Some(2)]) == Some((1, 2))
    assert option.all(*(o for o in (Some(1), Some(2)))) == Some((1, 2))
    assert option.all(*[Some(1), absent()]) is None


def test_all_struct() -> None:
    """all: struct"""
    assert option.all_dict({"a": Some(1), "b": Some("hello")}) == Some({"a": 1, "b": "hello"})
    assert option.all_dict({"a": Some(1), "b": None}) is None


def test_lift2() -> None:
    """lift2"""

    def add(a: int, b: int) -> int:
        return a + b

    f = option.lift2(add)
    assert f(absent(), absent()) is None
    assert f(Some(1), absent()) is None
    assert f(absent(), Some(2)) is None
    assert f(Some(1), Some(2)) == Some(3)


def test_as() -> None:
    """as"""
    assert option.as_(absent(), "a") is None
    assert option.as_(Some(1), "a") == Some("a")


def test_as_void() -> None:
    """asVoid"""
    assert option.as_void(absent()) is None
    assert option.as_void(Some(1)) == Some(None)


def test_flatten() -> None:
    """flatten"""
    assert option.flatten(Some(Some(1))) == Some(1)
    assert option.flatten(Some(absent())) is None


def test_zip_left() -> None:
    """zipLeft"""
    assert option.zip_left(Some(1), Some("a")) == Some(1)
    assert option.zip_left(Some(1), None) is None


def test_zip_right() -> None:
    """zipRight"""
    assert option.zip_right(Some(1), Some("a")) == Some("a")
    assert option.zip_right(None, Some("a")) is None


def test_compose_k() -> None:
    """composeK"""

    def half(n: int) -> Option[int]:
        return Some(n // 2) if n % 2 == 0 else None

    quarter = option.compose_k(half, half)
    assert quarter(8) == Some(2)
    assert quarter(6) is None


def test_to_array() -> None:
    """toArray"""
    assert option.to_list(Some(1)) == [1]
    assert option.to_list(absent()) == []
