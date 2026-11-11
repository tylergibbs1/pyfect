"""Filters: functions from an input to ``Ok(pass) | Err(fail)`` (Effect's
``Filter`` module).

Every pyfect combinator that takes a filter (``catch_filter``,
``filter_map``, ``Stream.filter_map``, ...) takes a plain function of this
shape; the helpers here build and combine them::

    from pyfect import filters

    positive = filters.from_predicate(lambda n: n > 0)
    halves = filters.compose(positive, lambda n: Ok(n // 2) if n % 2 == 0 else Err(n))

The module is ``filters`` because ``fx.filter`` is Effect's ``Effect.filter``.
"""

from __future__ import annotations

from collections.abc import Callable, Container
from datetime import datetime
from typing import Any, Never, TypeIs, overload

from pyfect._core import Effect
from pyfect._reasons import HasReason
from pyfect._some import Option, Some
from pyfect.result import Err, Ok, Result

type Filter[I, P = I, F = I] = Callable[[I], Result[P, F]]
type FilterEffect[I, P, F, E = Never, R = Never] = Callable[[I], Effect[Result[P, F], E, R]]


def make[I, P, F](f: Callable[[I], Result[P, F]]) -> Filter[I, P, F]:
    """``f`` itself, typed as a filter."""
    return f


def make_effect[I, P, F, E = Never, R = Never](
    f: Callable[[I], Effect[Result[P, F], E, R]],
) -> FilterEffect[I, P, F, E, R]:
    """``f`` itself, typed as an effectful filter."""
    return f


def map_fail[I, P, F, F2](self: Filter[I, P, F], f: Callable[[F], F2]) -> Filter[I, P, F2]:
    return lambda i: self(i).map_error(f)


def try_[I, O](f: Callable[[I], O]) -> Filter[I, O, I]:
    """Pass ``f(input)``; fail with the input if ``f`` raises an ``Exception``."""

    def run(i: I) -> Result[O, I]:
        try:
            return Ok(f(i))
        except Exception:
            return Err(i)

    return run


@overload
def from_predicate[A, B](predicate: Callable[[A], TypeIs[B]]) -> Filter[A, B, A]: ...
@overload
def from_predicate[A](predicate: Callable[[A], bool]) -> Filter[A, A, A]: ...
def from_predicate(predicate: Callable[[Any], bool]) -> Filter[Any, Any, Any]:
    return lambda i: Ok(i) if predicate(i) else Err(i)


def from_predicate_option[A, B](f: Callable[[A], Option[B]]) -> Filter[A, B, A]:
    """Pass the value of ``f(input)``; fail with the input when it is ``None``."""

    def run(i: A) -> Result[B, A]:
        o = f(i)
        return Err(i) if o is None else Ok(o.value)

    return run


def to_predicate[A](self: Filter[A, object, object]) -> Callable[[A], bool]:
    return lambda i: isinstance(self(i), Ok)


def to_option[A, P](self: Filter[A, P, object]) -> Callable[[A], Option[P]]:
    def run(i: A) -> Option[P]:
        r = self(i)
        return Some(r.value) if isinstance(r, Ok) else None

    return run


def to_result[A, P, F](self: Filter[A, P, F]) -> Callable[[A], Result[P, F]]:
    return self


def _is_str(u: object) -> TypeIs[str]:
    return isinstance(u, str)


def _is_number(u: object) -> TypeIs[int | float]:
    return isinstance(u, (int, float)) and not isinstance(u, bool)


def _is_bool(u: object) -> TypeIs[bool]:
    return isinstance(u, bool)


def _is_datetime(u: object) -> TypeIs[datetime]:
    return isinstance(u, datetime)


string: Filter[object, str, object] = from_predicate(_is_str)
number: Filter[object, int | float, object] = from_predicate(_is_number)
"""An ``int`` or ``float``, not a ``bool``."""
boolean: Filter[object, bool, object] = from_predicate(_is_bool)
date: Filter[object, datetime, object] = from_predicate(_is_datetime)


def equals[A](value: A) -> Filter[object, A, object]:
    """Pass ``value`` itself for an input equal to it."""
    return lambda u: Ok(value) if u == value else Err(u)


def has[I: Container[Any]](key: object) -> Filter[I, I, I]:
    """Pass a container holding ``key``."""
    return lambda i: Ok(i) if key in i else Err(i)


def instance_of[T](cls: type[T]) -> Filter[object, T, object]:
    return lambda u: Ok(u) if isinstance(u, cls) else Err(u)


def reason[E: HasReason[Any], R](error: type[E], reason: type[R]) -> Filter[object, R, object]:
    """Pass the ``reason`` of an ``error`` instance whose reason is a
    ``reason`` instance (Effect's ``Filter.reason(tag, reasonTag)``)."""

    def run(u: object) -> Result[R, object]:
        if isinstance(u, error):
            found: object = u.reason
            if isinstance(found, reason):
                return Ok(found)
        return Err(u)

    return run


def or_[I, P1, P2, F2](
    self: Filter[I, P1, object], that: Filter[I, P2, F2]
) -> Filter[I, P1 | P2, F2]:
    """``self``'s pass, else whatever ``that`` gives for the input."""

    def run(i: I) -> Result[P1 | P2, F2]:
        r = self(i)
        return r if isinstance(r, Ok) else that(i)

    return run


def zip_with[I, PL, FL, PR, FR, A](
    left: Filter[I, PL, FL], right: Filter[I, PR, FR], f: Callable[[PL, PR], A]
) -> Filter[I, A, FL | FR]:
    """Both filters on the same input; the first failure, or ``f`` of both passes."""

    def run(i: I) -> Result[A, FL | FR]:
        lr = left(i)
        if isinstance(lr, Err):
            return lr
        rr = right(i)
        if isinstance(rr, Err):
            return rr
        return Ok(f(lr.value, rr.value))

    return run


def zip[I, PL, FL, PR, FR](
    left: Filter[I, PL, FL], right: Filter[I, PR, FR]
) -> Filter[I, tuple[PL, PR], FL | FR]:
    return zip_with(left, right, lambda a, b: (a, b))


def and_left[I, PL, FL, FR](
    left: Filter[I, PL, FL], right: Filter[I, object, FR]
) -> Filter[I, PL, FL | FR]:
    return zip_with(left, right, lambda a, _: a)


def and_right[I, FL, PR, FR](
    left: Filter[I, object, FL], right: Filter[I, PR, FR]
) -> Filter[I, PR, FL | FR]:
    return zip_with(left, right, lambda _, b: b)


def compose[I, PL, FL, PR, FR](
    left: Filter[I, PL, FL], right: Filter[PL, PR, FR]
) -> Filter[I, PR, FL | FR]:
    """``right`` on what ``left`` passes."""

    def run(i: I) -> Result[PR, FL | FR]:
        lr = left(i)
        return lr if isinstance(lr, Err) else right(lr.value)

    return run


def compose_passthrough[I, PL, PR](
    left: Filter[I, PL, object], right: Filter[PL, PR, object]
) -> Filter[I, PR, I]:
    """``compose``, failing with the original input whichever filter fails."""

    def run(i: I) -> Result[PR, I]:
        lr = left(i)
        if isinstance(lr, Err):
            return Err(i)
        rr = right(lr.value)
        return Err(i) if isinstance(rr, Err) else rr

    return run


__all__ = [
    "Filter",
    "FilterEffect",
    "and_left",
    "and_right",
    "boolean",
    "compose",
    "compose_passthrough",
    "date",
    "equals",
    "from_predicate",
    "from_predicate_option",
    "has",
    "instance_of",
    "make",
    "make_effect",
    "map_fail",
    "number",
    "or_",
    "reason",
    "string",
    "to_option",
    "to_predicate",
    "to_result",
    "try_",
    "zip",
    "zip_with",
]
