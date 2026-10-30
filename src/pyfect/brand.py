"""Branded types with checked constructors (Effect's ``Brand``).

A brand is a ``typing.NewType``: nominal under pyright, the plain value at
run time. ``Brand[Base, NewType]`` makes constructors for it: ``make`` and
``check`` ones that validate, ``nominal`` one that does not, and ``all``
one with the checks of several::

    Int = NewType("Int", float)
    PositiveInt = NewType("PositiveInt", float)

    to_int = Brand[float, Int].make(lambda n: n.is_integer() or f"Expected {n} to be an integer")
    positive = Brand[float, Int].check(S.is_greater_than(0))
    to_positive_int = Brand[float, PositiveInt].all(to_int, positive)

    to_positive_int(1.0)          # PositiveInt(1.0)
    to_positive_int(-1.5)         # raises BrandError
    to_positive_int.result(-1.5)  # Err(BrandError(...))

A predicate passes with ``True`` or ``None``; ``False`` fails with
``"Expected <filter>"`` and a string fails with that message. ``check``
takes schema checks (``S.is_int()``, ``S.make_filter(...)``). Every check
runs and the messages are joined by newlines, except that an aborted check
(``.abort()``) that fails stops the rest. ``S.from_brand(brand)`` runs a
brand's checks in a schema.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Self, TypeGuard, cast

from pyfect.errors import TaggedError
from pyfect.option import Option, Some
from pyfect.result import Err, Ok, Result
from pyfect.schema.ast import Check, FilterOutput, collect_issues, make_filter, unknown
from pyfect.schema.issue import Composite, Issue, format_issue


@dataclass(eq=False)
class BrandError(TaggedError, ValueError):
    """A value failed a brand's checks. ``issue`` says why; ``message``
    (also ``str(error)``) is the issue in Effect's default format, one line
    per failed check."""

    issue: Issue

    @property
    def message(self) -> str:
        return format_issue(self.issue)


@dataclass(frozen=True, slots=True)
class Brand[A, B]:
    """A checked constructor that brands an ``A`` as ``B`` (Effect's
    ``Brand.Constructor``). Name both types when making one:
    ``Brand[float, Int].make(...)``. Calling it raises ``BrandError`` on
    failure; ``option``, ``result`` and ``is_`` report it instead.
    ``checks`` are schema checks, so ``S.from_brand`` can run them."""

    checks: tuple[Check[A], ...] = ()

    @classmethod
    def nominal(cls) -> Self:
        """A constructor that checks nothing."""
        return cls()

    @classmethod
    def make(cls, predicate: Callable[[A], FilterOutput]) -> Self:
        """A constructor with one check, ``predicate``: ``True`` / ``None``
        pass, ``False`` fails with ``"Expected <filter>"`` and a string
        fails with that message."""
        return cls((make_filter(predicate),))

    @classmethod
    def check(cls, first: Check[A], /, *rest: Check[A]) -> Self:
        """A constructor running the schema checks in order (every one,
        unless one marked ``abort()`` fails)."""
        return cls((first, *rest))

    @classmethod
    def all(cls, first: Brand[A, object], /, *rest: Brand[A, object]) -> Self:
        """A constructor running the checks of every brand given, in order."""
        return cls(tuple(c for b in (first, *rest) for c in b.checks))

    def __call__(self, value: A) -> B:
        match self.result(value):
            case Ok(branded):
                return branded
            case Err(error):
                raise error

    def result(self, value: A) -> Result[B, BrandError]:
        checks = cast("tuple[Check[Any], ...]", self.checks)
        issues = collect_issues(checks, value, unknown, {"errors": "all"})
        if issues is not None:
            return Err(BrandError(Composite(unknown, issues)))
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


__all__ = ["Brand", "BrandError"]
