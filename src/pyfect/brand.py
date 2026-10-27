"""Branded types with checked constructors (Effect's ``Brand``).

A brand is a ``typing.NewType``: nominal under pyright, the plain value at
run time. ``Brand[Base, NewType]`` makes constructors for it: ``make`` and
``check`` ones that validate, ``nominal`` one that does not, and ``all``
one with the checks of several::

    Int = NewType("Int", float)
    PositiveInt = NewType("PositiveInt", float)

    to_int = Brand[float, Int].make(lambda n: n.is_integer() or f"Expected {n} to be an integer")
    positive = Brand[float, Int].check(Filter(lambda n: n > 0, expected="a value greater than 0"))
    to_positive_int = Brand[float, PositiveInt].all(to_int, positive)

    to_positive_int(1.0)          # PositiveInt(1.0)
    to_positive_int(-1.5)         # raises BrandError
    to_positive_int.result(-1.5)  # Err(BrandError(...))

A predicate passes with ``True`` or ``None``; ``False`` fails with
``"Expected <expected>"`` and a string fails with that message. Every
filter runs and the messages are joined by newlines, except that an
aborted filter (``Filter.abort()``) that fails stops the rest.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Self, TypeGuard, cast

from pyfect.errors import TaggedError
from pyfect.option import Option, Some
from pyfect.result import Err, Ok, Result

type FilterOutput = bool | str | None
"""What a predicate gives: ``True`` / ``None`` to accept, ``False`` or a
message to reject."""


@dataclass(frozen=True, slots=True)
class Filter[A]:
    """One check of a brand. ``expected`` names what passes (``False`` reads
    ``"Expected <expected>"``); ``message`` replaces every failure's text."""

    predicate: Callable[[A], FilterOutput]
    expected: str | None = None
    message: str | None = None
    aborted: bool = False

    def abort(self) -> Filter[A]:
        """This filter, stopping the checks after it when it fails."""
        return replace(self, aborted=True)


def _failure[A](f: Filter[A], value: A) -> str | None:
    out = f.predicate(value)
    if out is True or out is None:
        return None
    if f.message is not None:
        return f.message
    if isinstance(out, str):
        return out
    return f"Expected {'<filter>' if f.expected is None else f.expected}"


@dataclass(eq=False)
class BrandError(TaggedError, ValueError):
    """A value failed a brand's checks; ``message`` has one line per
    failed filter."""

    message: str


@dataclass(frozen=True, slots=True)
class Brand[A, B]:
    """A checked constructor that brands an ``A`` as ``B`` (Effect's
    ``Brand.Constructor``). Name both types when making one:
    ``Brand[float, Int].make(...)``. Calling it raises ``BrandError`` on
    failure; ``option``, ``result`` and ``is_`` report it instead."""

    filters: tuple[Filter[A], ...] = ()

    @classmethod
    def nominal(cls) -> Self:
        """A constructor that checks nothing."""
        return cls()

    @classmethod
    def make(cls, predicate: Callable[[A], FilterOutput]) -> Self:
        """A constructor with one check, ``predicate``."""
        return cls((Filter(predicate),))

    @classmethod
    def check(cls, first: Filter[A], /, *rest: Filter[A]) -> Self:
        """A constructor running the filters in order."""
        return cls((first, *rest))

    @classmethod
    def all(cls, first: Brand[A, object], /, *rest: Brand[A, object]) -> Self:
        """A constructor running the checks of every brand given, in order."""
        return cls(tuple(f for b in (first, *rest) for f in b.filters))

    def __call__(self, value: A) -> B:
        match self.result(value):
            case Ok(branded):
                return branded
            case Err(error):
                raise error

    def result(self, value: A) -> Result[B, BrandError]:
        failures: list[str] = []
        for f in self.filters:
            failure = _failure(f, value)
            if failure is not None:
                failures.append(failure)
                if f.aborted:
                    break
        if failures:
            return Err(BrandError("\n".join(failures)))
        # A brand is a ``NewType``: the branded value is the value itself.
        return Ok(cast("B", value))

    def option(self, value: A) -> Option[B]:
        """``Some(branded)``, or ``None`` when ``value`` fails."""
        match self.result(value):
            case Ok(branded):
                return Some(branded)
            case Err():
                return None

    def is_(self, value: A) -> TypeGuard[B]:
        """``value`` passes the checks (and so is already a ``B`` at run time)."""
        return isinstance(self.result(value), Ok)
