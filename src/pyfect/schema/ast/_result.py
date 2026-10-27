"""What parsing gives: an ``Exit`` when it ran synchronously, an ``Effect``
when a transformation needs one (Effect's parsers return an ``Exit``, which
is an ``Effect`` there, whenever they can).

``MISSING`` stands for an absent value: a struct key or a tuple element
that is not there. A node without an encoding gives it back unchanged; a
getter sees it as ``None`` (Effect's ``Option.none()``) and may replace it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final, Never, TypeIs, cast, final

from pyfect._core import Effect
from pyfect.effect import from_exit
from pyfect.exit import Exit, Failure, Success
from pyfect.exit import die as die_exit
from pyfect.run import run_sync_exit
from pyfect.schema.issue import Issue


@final
class Missing:
    """The type of ``MISSING``."""

    __slots__ = ()
    _instance: Missing | None = None

    def __new__(cls) -> Missing:
        if cls._instance is None:
            cls._instance = object.__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<missing>"

    def __reduce__(self) -> str:
        return "MISSING"


MISSING: Final = Missing()
"""An absent value (see the module)."""
MISSING_EXIT: Final[Success[object]] = Success(MISSING)

type ParseResult = Exit[object, Issue] | Effect[object, Issue, Any]
"""A parse's outcome: an ``Exit`` when it ran synchronously, else the
``Effect`` that finishes it."""


def call[*Ts](f: Callable[[*Ts], ParseResult], /, *args: *Ts) -> ParseResult:
    """``f(*args)``, a user callback (a getter's function, a middleware):
    a raise is a defect, as in Effect."""
    try:
        return f(*args)
    except Exception as defect:
        return die_exit(defect)


def is_exit(result: ParseResult) -> TypeIs[Exit[object, Issue]]:
    return isinstance(result, (Success, Failure))


def to_effect(result: ParseResult) -> Effect[object, Issue, Any]:
    if isinstance(result, (Success, Failure)):
        return from_exit(result)
    return result


def then(result: ParseResult, f: Callable[[Exit[object, Issue]], ParseResult]) -> ParseResult:
    """``f`` of the outcome, whichever it is: called now for an ``Exit``,
    when the effect ends otherwise."""
    if isinstance(result, (Success, Failure)):
        return f(result)
    return result.exit().flat_map(lambda exit: to_effect(f(exit)))


def flat_map(result: ParseResult, f: Callable[[object], ParseResult]) -> ParseResult:
    """``f`` of the parsed value; a failure stays as it is."""
    if isinstance(result, Success):
        return f(result.value)
    if isinstance(result, Failure):
        return result
    return result.flat_map(lambda value: to_effect(f(value)))


def map_value(result: ParseResult, f: Callable[[object], object]) -> ParseResult:
    """The parsed value changed by ``f``."""
    if isinstance(result, Success):
        return Success(f(result.value))
    if isinstance(result, Failure):
        return result
    return result.map(f)


def map_issue(result: ParseResult, f: Callable[[Issue], Issue]) -> ParseResult:
    """Each issue of a failure changed by ``f``; defects stay."""
    if isinstance(result, Success):
        return result
    if isinstance(result, Failure):
        return Failure(result.cause.map(f))
    return result.map_error(f)


def run_now(result: ParseResult) -> Exit[object, Issue]:
    """The outcome, running an effect to its end on this thread (for the
    synchronous adapters and checks; its services must be provided)."""
    if isinstance(result, (Success, Failure)):
        return result
    return run_sync_exit(cast("Effect[object, Issue, Never]", result))
