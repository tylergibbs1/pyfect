"""The outcome of running an effect: ``Success[A] | Failure[E]``.

Test which one you have with ``match`` (``case Success(v)`` /
``case Failure(cause)``), ``isinstance``, or the ``is_success`` /
``is_failure`` guards. The methods exist on both classes, so they work on
an ``Exit`` without narrowing first.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Generic, Never, TypeIs, TypeVar

from pyfect.cause import Cause
from pyfect.cause import die as _die_cause
from pyfect.cause import fail as _fail_cause
from pyfect.cause import interrupt as _interrupt_cause

A_co = TypeVar("A_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)


@dataclass(frozen=True, slots=True)
class Success(Generic[A_co]):
    value: A_co

    def map[B](self, f: Callable[[A_co], B]) -> Success[B]:
        return Success(f(self.value))

    def map_error(self, f: Callable[[Never], object]) -> Success[A_co]:
        return self

    def map_both[B](
        self, *, on_failure: Callable[[Never], object], on_success: Callable[[A_co], B]
    ) -> Success[B]:
        return Success(on_success(self.value))

    def as_void(self) -> Success[None]:
        return Success(None)

    def match[C](
        self, *, on_failure: Callable[[Never], object], on_success: Callable[[A_co], C]
    ) -> C:
        return on_success(self.value)


@dataclass(frozen=True, slots=True)
class Failure(Generic[E_co]):
    cause: Cause[E_co]

    def map(self, f: Callable[[Never], object]) -> Failure[E_co]:
        return self

    def map_error[E2](self, f: Callable[[E_co], E2]) -> Failure[E2]:
        """Map the typed errors; defects and interruptions stay."""
        return Failure(self.cause.map(f))

    def map_both[E2](
        self, *, on_failure: Callable[[E_co], E2], on_success: Callable[[Never], object]
    ) -> Failure[E2]:
        return Failure(self.cause.map(on_failure))

    def as_void(self) -> Failure[E_co]:
        return self

    def match[B](
        self, *, on_failure: Callable[[Cause[E_co]], B], on_success: Callable[[Never], object]
    ) -> B:
        return on_failure(self.cause)


type Exit[A, E] = Success[A] | Failure[E]


def succeed[A](value: A) -> Success[A]:
    return Success(value)


def fail[E](error: E) -> Failure[E]:
    return Failure(_fail_cause(error))


def die(defect: BaseException) -> Failure[Never]:
    return Failure(_die_cause(defect))


def interrupt(fiber_id: int | None = None) -> Failure[Never]:
    return Failure(_interrupt_cause(fiber_id))


def is_success[A, E](ex: Exit[A, E]) -> TypeIs[Success[A]]:
    return isinstance(ex, Success)


def is_failure[A, E](ex: Exit[A, E]) -> TypeIs[Failure[E]]:
    return isinstance(ex, Failure)


def as_void_all[E = Never](exits: Iterable[Exit[object, E]]) -> Exit[None, E]:
    """``Success(None)`` if every exit succeeded, otherwise one failure
    holding every failed exit's reasons, in order."""
    reasons = tuple(r for ex in exits if isinstance(ex, Failure) for r in ex.cause.reasons)
    return Failure(Cause(reasons)) if reasons else Success(None)


__all__ = [
    "Exit",
    "Failure",
    "Success",
    "as_void_all",
    "die",
    "fail",
    "interrupt",
    "is_failure",
    "is_success",
    "succeed",
]
