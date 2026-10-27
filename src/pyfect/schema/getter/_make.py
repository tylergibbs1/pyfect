"""The getter constructors of Effect's ``SchemaGetter``."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never, cast

from pyfect._core import Effect
from pyfect.exit import Exit, Failure, Success
from pyfect.exit import fail as fail_exit
from pyfect.option import Option, Some
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast import FilterIssue, normalize_filter_output, to_effect, unknown
from pyfect.schema.getter._getter import (
    PASSTHROUGH,
    Getter,
    Outcome,
    Transform,
    TransformEffect,
    TransformOptional,
    TransformOptionalEffect,
)
from pyfect.schema.issue import Forbidden, Issue, MissingKey, reported


def transform[T, E](f: Callable[[E], T], /) -> Getter[T, E]:
    """``f`` of a present value (Effect's ``transform``)."""
    return Transform(f)


def transform_optional[T, E](f: Callable[[Option[E]], Option[T]], /) -> Getter[T, E]:
    """``f`` of the input as an ``Option``: it may supply a missing value
    or omit a present one (Effect's ``transformOptional``)."""
    return TransformOptional(f)


def transform_effect[T, E, R = Never](
    f: Callable[[E, ParseOptions], Outcome[T, R]], /
) -> Getter[T, E, R]:
    """``f(value, options)`` of a present value: an effect failing with an
    ``Issue`` (or an ``Exit``), maybe needing services (Effect's
    ``transformEffect``)."""
    return TransformEffect(f)


def transform_optional_effect[T, E, R = Never](
    f: Callable[[Option[E], ParseOptions], Outcome[Option[T], R]], /
) -> Getter[T, E, R]:
    """``f(option, options)``, the effectful ``transform_optional``."""
    return TransformOptionalEffect(f)


def passthrough[T]() -> Getter[T, T]:
    """The input, unchanged (Effect's ``passthrough``)."""
    return PASSTHROUGH


def passthrough_supertype() -> Getter[Any, Any]:
    """The input, unchanged, from a supertype ``E`` to its subtype ``T``
    (Effect's ``passthroughSupertype``). Python cannot say that ``T`` is a
    subtype of ``E``, so it is typed ``Any``: name the types where it is used."""
    return PASSTHROUGH


def passthrough_subtype() -> Getter[Any, Any]:
    """The input, unchanged, from a subtype ``E`` to its supertype ``T``
    (Effect's ``passthroughSubtype``)."""
    return PASSTHROUGH


def succeed[T](value: T, /) -> Getter[T, object]:
    """Always ``value``, present or not (Effect's ``succeed``)."""
    return TransformOptional(lambda _: Some(value))


def fail[E](f: Callable[[Option[E], ParseOptions], Issue], /) -> Getter[Never, E]:
    """Always the issue ``f`` makes (Effect's ``fail``)."""
    return TransformOptionalEffect(lambda input, options: fail_exit(f(input, options)))


def forbidden[E](message: Callable[[Option[E]], str], /) -> Getter[Never, E]:
    """Always a ``Forbidden`` issue with ``message`` (Effect's ``forbidden``)."""

    def issue(input: Option[E], options: ParseOptions) -> Issue:
        annotations = {"message": message(input)}
        if input is None:
            return Forbidden(annotations)
        return Forbidden(annotations, reported(input.value, options))

    return fail(issue)


forbidden_encoding: Getter[Never, object] = forbidden(lambda _: "Encoding is not supported")
"""Encoding fails with ``"Encoding is not supported"`` (Effect's
``forbiddenEncoding``)."""


def required[T](**annotations: object) -> Getter[T, T]:
    """A missing value is a ``MissingKey`` with the key ``annotations``
    (Effect's ``required``)."""

    def run(input: Option[T], options: ParseOptions) -> Exit[Option[T], Issue]:
        return fail_exit(MissingKey(annotations or None)) if input is None else Success(input)

    return TransformOptionalEffect(run)


def omit() -> Getter[Never, object]:
    """No output: the key is left out (Effect's ``omit``)."""
    return TransformOptional(lambda _: None)


def with_default[T, R = Never](default: Outcome[T, R], /) -> Getter[T, T, R]:
    """A missing value is the outcome of ``default`` (Effect's
    ``withDefault``; Python has no ``undefined``, so only a missing value
    is replaced)."""

    def run(input: Option[T], options: ParseOptions) -> Outcome[Option[T], R]:
        if input is not None:
            return Success(input)
        if isinstance(default, Success):
            return Success(Some(default.value))
        if isinstance(default, Failure):
            return default
        return default.map(Some)

    return TransformOptionalEffect(run)


type CheckOutput = bool | FilterIssue | None


def check_effect[T, R = Never](
    f: Callable[[T, ParseOptions], Effect[CheckOutput, Never, R]], /
) -> Getter[T, T, R]:
    """The value, once the effect ``f`` makes accepts it: ``None`` / ``True``
    pass, ``False`` is an ``InvalidValue``, a string its message, an issue
    itself (Effect's ``checkEffect``). ``f`` may need services."""

    def run(value: T, options: ParseOptions) -> Effect[T, Issue, R]:
        def decide(out: CheckOutput) -> Outcome[T]:
            issue = normalize_filter_output(unknown, out, value, options)
            return Success(value) if issue is None else fail_exit(issue)

        return f(value, options).flat_map(lambda out: _effect(decide(out)))

    return TransformEffect(run)


def _effect[T](outcome: Outcome[T, Any]) -> Effect[T, Issue, Any]:
    return cast("Effect[T, Issue, Any]", to_effect(outcome))
