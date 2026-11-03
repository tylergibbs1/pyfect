"""Ports of Effect's ``Result.test.ts``.

``Result`` combinators are methods of ``Ok`` and ``Err``; constructors and
the functions over several values are in ``pyfect.result``. Omitted:
``toString`` / ``toJSON`` / ``inspect`` (the dataclass ``repr`` is Python's
form); ``pipe composes Result operations`` (Result has methods, not
``pipe``); ``getOrUndefined`` (Python has one ``None``; docs/PARITY.md
section 4); ``makeEquivalence compares successes and failures by channel``
(``==``; section 4); the Do notation titles and ``gen`` (generator locals;
section 4).
"""

from typing import TypeIs

import pytest

from pyfect import option, result
from pyfect.option import Option, Some
from pyfect.result import Err, Ok, Result


def length(s: str) -> int:
    return len(s)


def test_succeed_creates_a_success_value() -> None:
    """succeed creates a Success value"""
    r = Ok(42)
    assert result.is_ok(r)
    assert r.value == 42


def test_fail_creates_a_failure_value() -> None:
    """fail creates a Failure value"""
    r = Err("err")
    assert result.is_err(r)
    assert r.error == "err"


def test_try() -> None:
    """try"""
    assert result.try_(lambda: 1) == Ok(1)
    boom = ValueError("b")

    def throw() -> int:
        raise boom

    assert result.try_(throw) == Err(boom)
    assert result.try_(lambda: 1, lambda e: RuntimeError(str(e))) == Ok(1)
    assert result.try_(throw, str) == Err("b")


def test_from_nullish_or() -> None:
    """fromNullishOr"""
    assert result.from_optional(None, lambda: "fallback") == Err("fallback")
    assert result.from_optional(1, lambda: "fallback") == Ok(1)


def test_equal_trait_compares_matching_tags_and_values() -> None:
    """Equal trait compares matching tags and values"""
    assert Ok(1) == Ok(1)
    assert Err("e") == Err("e")
    assert Ok(1) != Err("e")
    assert Err("e") != Ok(1)
    assert hash(Ok(1)) == hash(Ok(1))


def test_is_failure() -> None:
    """isFailure"""
    assert not result.is_err(Ok(1))
    assert result.is_err(Err(1))


def test_is_success() -> None:
    """isSuccess"""
    assert result.is_ok(Ok(1))
    assert not result.is_ok(Err(1))


def test_get_or_else() -> None:
    """getOrElse"""
    ok: Result[int, str] = Ok(1)
    err: Result[int, str] = Err("not a number")
    assert ok.get_or_else(lambda error: error + "!") == 1
    assert err.get_or_else(lambda error: error + "!") == "not a number!"


def test_get_or_throw() -> None:
    """getOrThrow"""
    assert Ok(1).get_or_raise() == 1
    error = ValueError("e")
    with pytest.raises(ValueError) as raised:
        Err(error).get_or_raise()
    assert raised.value is error


def test_map() -> None:
    """map"""
    failure: Result[str, str] = Err("s")
    assert Ok("abc").map(length) == Ok(3)
    assert failure.map(length) is failure


def test_map_both() -> None:
    """mapBoth"""

    def f(r: Result[int, str]) -> Result[bool, int]:
        return r.map_both(on_failure=length, on_success=lambda n: n > 2)

    assert f(Ok(1)) == Ok(False)
    assert f(Err("a")) == Err(1)


def test_map_error() -> None:
    """mapError"""
    success: Result[str, int] = Ok("a")
    assert success.map_error(lambda n: n * 2) is success
    assert Err(1).map_error(lambda n: n * 2) == Err(2)


def test_match_handles_failure_and_success_cases() -> None:
    """match handles failure and success cases"""

    def match(r: Result[str, str]) -> str:
        return r.match(
            on_failure=lambda s: f"failure{len(s)}", on_success=lambda s: f"success{len(s)}"
        )

    assert match(Err("abc")) == "failure3"
    assert match(Ok("abc")) == "success3"


def test_flat_map() -> None:
    """flatMap"""

    def f(s: str) -> Result[int, str]:
        return Ok(len(s))

    ok: Result[str, str] = Ok("abc")
    err: Result[str, str] = Err("maError")
    assert ok.flat_map(f) == Ok(3)
    assert err.flat_map(f) == Err("maError")


def test_all() -> None:
    """all"""
    assert result.all() == Ok(())
    assert result.all(Ok(1)) == Ok((1,))
    assert result.all(Ok(1), Ok(True)) == Ok((1, True))
    assert result.all(Ok(1), Err("e")) == Err("e")

    def iterable() -> list[Result[int, str]]:
        return [Ok(1), Ok(2), Ok(3)]

    assert result.all(*iterable()) == Ok((1, 2, 3))

    def iterable_with_failure() -> list[Result[int, str]]:
        return [Ok(1), Err("e"), Ok(3)]

    assert result.all(*iterable_with_failure()) == Err("e")
    # structs and records
    empty: dict[str, Result[int, str]] = {}
    nothing: dict[str, int] = {}
    assert result.all_dict(empty) == Ok(nothing)
    assert result.all_dict({"a": Ok(1)}) == Ok({"a": 1})
    assert result.all_dict({"a": Ok(1), "b": Ok(True)}) == Ok({"a": 1, "b": True})
    assert result.all_dict({"a": Ok(1), "b": Err("e")}) == Err("e")


def test_void() -> None:
    """void"""
    assert result.void == Ok(None)


def test_from_option() -> None:
    """fromOption"""
    none: Option[int] = None
    assert result.from_option(none, lambda: "none") == Err("none")
    assert result.from_option(Some(1), lambda: "none") == Ok(1)


def test_succeed_none() -> None:
    """succeedNone"""
    assert result.succeed_none == Ok(None)


def test_succeed_some() -> None:
    """succeedSome"""
    assert result.succeed_some(1) == Ok(Some(1))


def test_is_result() -> None:
    """isResult"""
    assert result.is_result(Ok(1))
    assert result.is_result(Err("e"))
    assert not result.is_result(Some(1))


def test_get_success() -> None:
    """getSuccess"""
    assert option.get_success(Ok(1)) == Some(1)
    assert option.get_success(Err("a")) is None


def test_get_failure() -> None:
    """getFailure"""
    assert option.get_failure(Ok(1)) is None
    assert option.get_failure(Err("e")) == Some("e")


def test_get_or_null() -> None:
    """getOrNull"""
    assert Ok(1).get_or_none() == 1
    assert Err("a").get_or_none() is None


def test_get_or_throw_with() -> None:
    """getOrThrowWith"""
    assert Ok(1).get_or_raise_with(lambda e: ValueError(f"Unexpected Err: {e}")) == 1
    with pytest.raises(ValueError, match="Unexpected Err: e"):
        Err("e").get_or_raise_with(lambda e: ValueError(f"Unexpected Err: {e}"))


def test_merge() -> None:
    """merge"""
    assert Ok(1).merge() == 1
    assert Err("a").merge() == "a"


def test_tap() -> None:
    """tap"""
    seen: list[int] = []
    assert Ok(42).tap(seen.append) == Ok(42)
    assert seen == [42]
    failure: Result[int, str] = Err("err")
    assert failure.tap(seen.append) == Err("err")
    assert seen == [42]


def test_flip() -> None:
    """flip"""
    assert Ok("a").flip() == Err("a")
    assert Err("b").flip() == Ok("b")


def test_lift_predicate() -> None:
    """liftPredicate"""

    def is_positive(n: int) -> bool:
        return n > 0

    def is_number(n: str | int) -> TypeIs[int]:
        return isinstance(n, int)

    assert result.lift_predicate(1, is_positive, lambda n: f"{n} is not positive") == Ok(1)
    assert result.lift_predicate(-1, is_positive, lambda n: f"{n} is not positive") == Err(
        "-1 is not positive"
    )
    assert result.lift_predicate(1, is_number, lambda n: f"{n} is not a number") == Ok(1)
    assert result.lift_predicate("string", is_number, lambda n: f"{n} is not a number") == Err(
        "string is not a number"
    )


def test_filter_or_fail() -> None:
    """filterOrFail"""
    assert Ok(1).filter_or_fail(lambda n: n > 0, lambda _: "a") == Ok(1)
    assert Ok(1).filter_or_fail(lambda n: n > 1, lambda _: "a") == Err("a")
    failure: Result[int, int] = Err(1)
    assert failure.filter_or_fail(lambda n: n > 0, lambda _: "a") == Err(1)


def test_and_then_replaces_successes_with_result_or_plain_values() -> None:
    """andThen replaces successes with Result or plain values"""
    # and_then takes the next Result, as Effect.and_then takes the next effect;
    # Effect's function and plain-value forms are flat_map and map.
    assert Ok(1).and_then(Ok(2)) == Ok(2)
    assert Ok(1).flat_map(lambda _: Ok(2)) == Ok(2)
    assert Ok(1).map(lambda _: 2) == Ok(2)
    assert Err("e").and_then(Ok(2)) == Err("e")


def test_or_else_recovers_failures_and_preserves_successes() -> None:
    """orElse recovers failures and preserves successes"""
    ok: Result[int, str] = Ok(1)
    err: Result[int, str] = Err("a")
    assert ok.or_else(lambda _: Ok(2)) == Ok(1)
    assert ok.or_else(lambda _: Err("b")) == Ok(1)
    assert err.or_else(lambda _: Ok(2)) == Ok(2)
    assert err.or_else(lambda _: Err("b")) == Err("b")


def test_transpose_option() -> None:
    """transposeOption"""
    assert result.transpose_option(Some(Ok(1))) == Ok(Some(1))
    assert result.transpose_option(None) == Ok(None)
    assert result.transpose_option(Some(Err("e"))) == Err("e")


def test_transpose_map_option() -> None:
    """transposeMapOption"""
    none: Option[int] = None
    assert result.transpose_map_option(Some(1), Ok) == Ok(Some(1))
    assert result.transpose_map_option(none, Ok) == Ok(None)
    assert result.transpose_map_option(Some("e"), Err) == Err("e")
