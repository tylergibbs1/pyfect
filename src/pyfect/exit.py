"""The outcome of running an effect: ``Success[A] | Failure[E]``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Never, TypeVar

from pyfect.cause import Cause
from pyfect.cause import die as _die_cause
from pyfect.cause import fail as _fail_cause
from pyfect.cause import interrupt as _interrupt_cause

A_co = TypeVar("A_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)


@dataclass(frozen=True, slots=True)
class Success(Generic[A_co]):
    value: A_co


@dataclass(frozen=True, slots=True)
class Failure(Generic[E_co]):
    cause: Cause[E_co]


type Exit[A, E] = Success[A] | Failure[E]


def succeed[A](value: A) -> Success[A]:
    return Success(value)


def fail[E](error: E) -> Failure[E]:
    return Failure(_fail_cause(error))


def die(defect: BaseException) -> Failure[Never]:
    return Failure(_die_cause(defect))


def interrupt(fiber_id: int | None = None) -> Failure[Never]:
    return Failure(_interrupt_cause(fiber_id))
