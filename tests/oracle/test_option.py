"""Ports of Effect's ``Option.test.ts``, for pyfect's ``Some[A] | None``.

pyfect keeps only the Option helpers that pull their weight (docs/PARITY.md
section 5.1); the rest are a ``match`` statement or a conditional
expression. Omitted: ``makeReducer`` / ``makeReducerFailFast``,
``makeOrder``, ``makeEquivalence`` (``key=`` functions and ``==``); ``gen``
and Do notation (no typed do-notation in Python); ``toString`` /
``toJSON`` / ``inspect`` (the dataclass ``repr``); ``isOption``, ``isNone``,
``isSome`` (``isinstance`` and ``is None`` narrow natively);
``getSuccess`` / ``getFailure``, ``toRefinement``, ``firstSomeOf``,
``orElse`` / ``orElseResult`` / ``orElseSome``, ``getOrThrowWith``,
``unit``, ``product`` / ``productMany``, ``andThen``, ``partitionMap``,
``filterMap``, ``getOrUndefined``, ``fromUndefinedOr`` / ``fromNullOr``
(Python has one ``None``), ``flatMapNullishOr``, ``liftPredicate``,
``containsWith`` / ``contains``, ``exists``, ``liftNullishOr``,
``liftThrowable``, ``tap``, ``filter``, ``zipWith``, ``reduceCompact``,
``all``, ``.pipe()``, ``lift2``, ``as`` / ``asVoid``, ``flatten``,
``zipLeft`` / ``zipRight``, ``composeK`` and ``toArray`` (one-liners or not
ported).
"""

import pytest

from pyfect import NoSuchElementException, option
from pyfect.option import Option, Some


def absent() -> Option[int]:
    return None


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


def test_get_or_throw() -> None:
    """getOrThrow"""
    assert option.get_or_raise(Some(1)) == 1
    with pytest.raises(NoSuchElementException, match="get_or_raise called on None"):
        option.get_or_raise(None)


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


def test_match() -> None:
    """match"""

    def match(o: Option[str]) -> str:
        match o:
            case Some(s):
                return f"some{len(s)}"
            case None:
                return "none"

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


def test_from_nullish_or() -> None:
    """fromNullishOr"""
    assert option.from_optional(2) == Some(2)
    assert option.from_optional(None) is None
