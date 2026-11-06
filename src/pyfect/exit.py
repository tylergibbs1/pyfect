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

from pyfect._some import Some
from pyfect.cause import Cause
from pyfect.cause import die as _die_cause
from pyfect.cause import fail as _fail_cause
from pyfect.cause import interrupt as _interrupt_cause
from pyfect.result import Err, Ok, Result

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

    @property
    def has_fails(self) -> bool:
        return False

    @property
    def has_dies(self) -> bool:
        return False

    @property
    def has_interrupts(self) -> bool:
        return False

    def filter_success(self) -> Ok[Success[A_co]]:
        return Ok(self)

    def filter_value(self) -> Ok[A_co]:
        return Ok(self.value)

    def filter_failure(self) -> Err[Success[A_co]]:
        return Err(self)

    def filter_cause(self) -> Err[Success[A_co]]:
        return Err(self)

    def find_error(self) -> Err[Success[A_co]]:
        return Err(self)

    def find_defect(self) -> Err[Success[A_co]]:
        return Err(self)

    def get_success(self) -> Some[A_co]:
        return Some(self.value)

    def get_cause(self) -> None:
        return None


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

    @property
    def has_fails(self) -> bool:
        return self.cause.has_fails

    @property
    def has_dies(self) -> bool:
        return self.cause.has_dies

    @property
    def has_interrupts(self) -> bool:
        return self.cause.has_interrupts

    def filter_success(self) -> Err[Failure[E_co]]:
        return Err(self)

    def filter_value(self) -> Err[Failure[E_co]]:
        return Err(self)

    def filter_failure(self) -> Ok[Failure[E_co]]:
        return Ok(self)

    def filter_cause(self) -> Ok[Cause[E_co]]:
        return Ok(self.cause)

    def find_error(self) -> Result[E_co, Failure[E_co]]:
        """``Ok`` of the first typed error, else ``Err`` of this exit."""
        found = self.cause.find_error()
        return found if isinstance(found, Ok) else Err(self)

    def find_defect(self) -> Result[object, Failure[E_co]]:
        found = self.cause.find_defect()
        return found if isinstance(found, Ok) else Err(self)

    def get_success(self) -> None:
        return None

    def get_cause(self) -> Some[Cause[E_co]]:
        return Some(self.cause)


type Exit[A, E] = Success[A] | Failure[E]


def succeed[A](value: A) -> Success[A]:
    return Success(value)


void: Success[None] = Success(None)
"""``Success(None)``."""


def fail_cause[E](cause: Cause[E]) -> Failure[E]:
    return Failure(cause)


def fail[E](error: E) -> Failure[E]:
    return Failure(_fail_cause(error))


def die(defect: object) -> Failure[Never]:
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
    "fail_cause",
    "interrupt",
    "is_failure",
    "is_success",
    "succeed",
    "void",
]
