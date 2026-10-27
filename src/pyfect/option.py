"""``Some[A] | None``: an optional value that stays unambiguous when ``A``
itself admits ``None``.

pyfect uses plain ``X | None`` wherever ``X`` can't be ``None``. ``Option``
is for the places where it can: ``Some(None)`` is a present ``None``, and
``None`` is absence. Take one apart with pattern matching::

    match found:
        case Some(value):
            ...
        case None:
            ...
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Generic, Never, TypeVar

from pyfect.errors import NoSuchElementException

A_co = TypeVar("A_co", covariant=True)


@dataclass(frozen=True, slots=True)
class Some(Generic[A_co]):
    value: A_co


type Option[A] = Some[A] | None


def from_optional[A](value: A | None) -> Option[A]:
    """``None`` stays absent; anything else is present."""
    return None if value is None else Some(value)


def from_iterable[A](items: Iterable[A]) -> Option[A]:
    """The first item, if there is one."""
    return next((Some(x) for x in items), None)


def map[A, B](option: Option[A], f: Callable[[A], B]) -> Option[B]:
    return None if option is None else Some(f(option.value))


def flat_map[A, B = Never](option: Option[A], f: Callable[[A], Option[B]]) -> Option[B]:
    return None if option is None else f(option.value)


def get_or_else[A, B](option: Option[A], f: Callable[[], B]) -> A | B:
    return f() if option is None else option.value


def get_or_none[A](option: Option[A]) -> A | None:
    """Back to ``A | None``, losing the distinction ``Option`` keeps."""
    return None if option is None else option.value


def get_or_raise[A](option: Option[A]) -> A:
    """The value, or raise ``NoSuchElementException``."""
    if option is None:
        raise NoSuchElementException("get_or_raise called on None")
    return option.value
