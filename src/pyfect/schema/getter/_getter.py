"""``Getter[T, E, R]``: one direction of a transformation (Effect's
``SchemaGetter.Getter``). It takes a value of ``E``, or none (a missing
key), and gives a value of ``T`` or none, maybe needing services ``R``.

The five kinds are Effect's: ``Passthrough``, ``Transform`` (a function of
a present value), ``TransformOptional`` (of an ``Option``),
``TransformEffect`` and ``TransformOptionalEffect`` (their effectful
forms). ``compose`` keeps the most specific kind, so a chain of plain
transforms runs without an effect. A function that raises is a defect.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar, Final, Generic, Literal, Never, Self, TypeVar, cast

from pyfect._core import Effect
from pyfect.exit import Exit, Failure, Success
from pyfect.option import Option, Some
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast import (
    MISSING,
    MISSING_EXIT,
    ParseResult,
    call,
    flat_map,
    map_value,
    to_effect,
)
from pyfect.schema.issue import Issue

T_co = TypeVar("T_co", covariant=True)
E_contra = TypeVar("E_contra", contravariant=True)
R_co = TypeVar("R_co", covariant=True, default=Never)

type Tag = Literal[
    "Passthrough", "Transform", "TransformOptional", "TransformEffect", "TransformOptionalEffect"
]
type Outcome[T, R = Never] = Effect[T, Issue, R] | Exit[T, Issue]
"""What an effectful getter's function gives: an ``Effect``, or an
``Exit`` when it knows the outcome at once."""


@dataclass(frozen=True, slots=True, eq=False)
class Getter(ABC, Generic[T_co, E_contra, R_co]):
    """A getter (see the module); ``tag`` is its kind."""

    tag: ClassVar[Tag]

    @abstractmethod
    def apply(self, value: object, options: ParseOptions) -> ParseResult:
        """The output for ``value`` (``MISSING`` when there is none)."""

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        return f(self)

    def compose[T2, R2 = Never](
        self, other: Getter[T2, T_co, R2], /
    ) -> Getter[T2, E_contra, R_co | R2]:
        """This getter, then ``other`` on its output (Effect's ``compose``)."""
        return cast("Getter[T2, E_contra, R_co | R2]", _compose(self, other))

    def map[T2](self, f: Callable[[T_co], T2], /) -> Getter[T2, E_contra, R_co]:
        """The output changed by ``f``."""
        return self.compose(Transform(f))


def _present(f: Callable[[Any], object], value: object) -> ParseResult:
    return call(lambda: Success(f(value)))


def _option(value: object) -> Option[object]:
    return None if value is MISSING else Some(value)


def _value(option: Option[object]) -> object:
    return MISSING if option is None else option.value


@dataclass(frozen=True, slots=True, eq=False)
class Passthrough(Getter[Any, Any, Never]):
    """The input, unchanged."""

    tag = "Passthrough"

    def apply(self, value: object, options: ParseOptions) -> ParseResult:
        return Success(value)


PASSTHROUGH: Final = Passthrough()


@dataclass(frozen=True, slots=True, eq=False)
class Transform(Getter[T_co, E_contra, Never]):
    """``f`` of a present value; none stays none."""

    f: Callable[[E_contra], T_co]
    tag = "Transform"

    def apply(self, value: object, options: ParseOptions) -> ParseResult:
        if value is MISSING:
            return MISSING_EXIT
        return _present(self.f, value)


@dataclass(frozen=True, slots=True, eq=False)
class TransformOptional(Getter[T_co, E_contra, Never]):
    """``f`` of the input as an ``Option`` (``None`` when missing)."""

    f: Callable[[Option[E_contra]], Option[T_co]]
    tag = "TransformOptional"

    def apply(self, value: object, options: ParseOptions) -> ParseResult:
        return map_value(_present(self.f, _option(value)), _option_value)


def _option_value(option: object) -> object:
    return _value(cast("Option[object]", option))


@dataclass(frozen=True, slots=True, eq=False)
class TransformEffect(Getter[T_co, E_contra, R_co]):
    """``f(value, options)`` of a present value; none stays none."""

    f: Callable[[E_contra, ParseOptions], Outcome[T_co, R_co]]
    tag = "TransformEffect"

    def apply(self, value: object, options: ParseOptions) -> ParseResult:
        if value is MISSING:
            return MISSING_EXIT
        return _run(self.f, value, options)


@dataclass(frozen=True, slots=True, eq=False)
class TransformOptionalEffect(Getter[T_co, E_contra, R_co]):
    """``f(option, options)`` of the input as an ``Option``."""

    f: Callable[[Option[E_contra], ParseOptions], Outcome[Option[T_co], R_co]]
    tag = "TransformOptionalEffect"

    def apply(self, value: object, options: ParseOptions) -> ParseResult:
        return map_value(_run(self.f, _option(value), options), _option_value)


def _run(
    f: Callable[[Any, ParseOptions], Outcome[Any, Any]], value: object, options: ParseOptions
) -> ParseResult:
    return call(f, value, options)


def apply_result(
    getter: Getter[Any, Any, Any], result: ParseResult, options: ParseOptions
) -> ParseResult:
    """``getter`` on the value of a parse; a failure stays as it is."""
    if type(result) is Success:
        return getter.apply(result.value, options)
    return flat_map(result, lambda value: getter.apply(value, options))


def run[T, E, R](
    getter: Getter[T, E, R], input: Option[E], options: ParseOptions
) -> Effect[Option[T], Issue, R]:
    """The getter's output for ``input`` (Effect's ``SchemaGetter.run``)."""
    result = getter.apply(_value(cast("Option[object]", input)), options)
    return cast("Effect[Option[T], Issue, R]", to_effect(map_value(result, _option)))


# ------------------------------------------------------------------ compose


type _Any = Getter[Any, Any, Any]


def _compose(first: _Any, second: _Any) -> _Any:
    if isinstance(first, Passthrough):
        return second
    if isinstance(second, Passthrough):
        return first
    build = _SPECIALIZED.get((first.tag, second.tag))
    if build is None:
        return TransformOptionalEffect(lambda o, options: _then_optional(first, second, o, options))
    return build(cast("Any", first).f, cast("Any", second).f)


type _Build = Callable[[Any, Any], _Any]

_SPECIALIZED: dict[tuple[Tag, Tag], _Build] = {
    ("Transform", "Transform"): lambda f, g: Transform(lambda e: g(f(e))),
    ("Transform", "TransformOptional"): lambda f, g: TransformOptional(
        lambda o: g(_map_option(o, f))
    ),
    ("Transform", "TransformEffect"): lambda f, g: TransformEffect(
        lambda e, options: g(f(e), options)
    ),
    ("TransformOptional", "Transform"): lambda f, g: TransformOptional(
        lambda o: _map_option(f(o), g)
    ),
    ("TransformOptional", "TransformOptional"): lambda f, g: TransformOptional(lambda o: g(f(o))),
    ("TransformEffect", "Transform"): lambda f, g: TransformEffect(
        lambda e, options: _map_outcome(f(e, options), g)
    ),
    ("TransformEffect", "TransformEffect"): lambda f, g: TransformEffect(
        lambda e, options: _then_outcome(f(e, options), lambda t: g(t, options))
    ),
}
"""The compositions keeping a specific kind (Effect's ``compose``); the
others run as a ``TransformOptionalEffect``."""


def _map_option(option: Option[Any], f: Callable[[Any], object]) -> Option[object]:
    return None if option is None else Some(f(option.value))


def _map_outcome(outcome: Outcome[Any, Any], f: Callable[[Any], object]) -> Outcome[object, Any]:
    if isinstance(outcome, Success):
        return Success(f(outcome.value))
    if isinstance(outcome, Failure):
        return outcome
    return outcome.map(f)


def _then_outcome(
    outcome: Outcome[Any, Any], f: Callable[[Any], Outcome[object, Any]]
) -> Outcome[object, Any]:
    if isinstance(outcome, Success):
        return f(outcome.value)
    if isinstance(outcome, Failure):
        return outcome
    return outcome.flat_map(lambda value: to_effect(f(value)))


def _then_optional(
    first: Getter[Any, Any, Any],
    second: Getter[Any, Any, Any],
    input: Option[Any],
    options: ParseOptions,
) -> Outcome[Option[object], Any]:
    result = flat_map(
        first.apply(_value(input), options), lambda value: second.apply(value, options)
    )
    return cast("Outcome[Option[object], Any]", map_value(result, _option))
