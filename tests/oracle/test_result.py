"""Ports of Effect's ``Result.test.ts``.

Omitted: ``void``, ``succeedNone`` and ``succeedSome`` (``Ok(None)`` and
``Ok(Some(x))`` are the literals); ``toString`` / ``toJSON`` / ``inspect``
(the dataclass ``repr`` is Python's form); ``pipe composes Result
operations`` (Result has methods, not ``pipe``); ``isResult`` (use
``isinstance``); ``fromOption``, ``getSuccess`` / ``getFailure``,
``getOrNull`` / ``getOrUndefined``, ``getOrThrowWith``, ``merge``, ``tap``,
``flip``, ``liftPredicate``, ``filterOrFail``, ``makeEquivalence``,
``andThen``, ``orElse`` and the transposes (a ``match`` statement says each
in a line, so they are not ported); Do notation and ``gen`` (Python has no
typed do-notation; see docs/PARITY.md section 4).
"""

import pytest

from pyfect import result
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
    # Effect's struct form is omitted: a dict comprehension over ``match``
    # does it in Python.
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
