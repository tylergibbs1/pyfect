"""Why an effect failed.

A ``Cause`` is a flat list of reasons, as in Effect 4:

- ``Fail``: an expected, typed error. This is what the ``E`` channel tracks.
- ``Die``: a defect. An exception nobody planned for.
- ``Interrupt``: the fiber was interrupted, optionally by another fiber.

Most causes hold one reason. More appear when finalizers fail while
unwinding, or when concurrent work fails in several places at once.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Generic, Never, TypeVar

E_co = TypeVar("E_co", covariant=True)


@dataclass(frozen=True, slots=True)
class Fail(Generic[E_co]):
    error: E_co


@dataclass(frozen=True, slots=True)
class Die:
    defect: BaseException


@dataclass(frozen=True, slots=True)
class Interrupt:
    fiber_id: int | None = None


type Reason[E] = Fail[E] | Die | Interrupt


@dataclass(frozen=True, slots=True)
class Cause(Generic[E_co]):
    reasons: tuple[Reason[E_co], ...]

    def __add__[E2](self, other: Cause[E2]) -> Cause[E_co | E2]:
        """Both causes' reasons in order, without repeating equal ones."""
        if not self.reasons:
            return other
        if not other.reasons:
            return self
        return Cause(_dedupe((*self.reasons, *other.reasons)))

    def add_interrupts(self, interrupts: Cause[Never]) -> Cause[E_co]:
        """Add each interruption whose fiber is not recorded yet."""
        seen = {r.fiber_id for r in self.reasons if isinstance(r, Interrupt)}
        new: list[Reason[E_co]] = []
        for r in interrupts.reasons:
            if isinstance(r, Interrupt) and r.fiber_id not in seen:
                seen.add(r.fiber_id)
                new.append(r)
        return Cause((*self.reasons, *new)) if new else self

    @property
    def failures(self) -> tuple[E_co, ...]:
        return tuple(r.error for r in self.reasons if isinstance(r, Fail))

    @property
    def defects(self) -> tuple[BaseException, ...]:
        return tuple(r.defect for r in self.reasons if isinstance(r, Die))

    @property
    def is_interrupted(self) -> bool:
        return any(isinstance(r, Interrupt) for r in self.reasons)

    @property
    def is_interrupted_only(self) -> bool:
        return bool(self.reasons) and all(isinstance(r, Interrupt) for r in self.reasons)

    @property
    def has_defects(self) -> bool:
        return any(isinstance(r, Die) for r in self.reasons)

    def elect_defects(self) -> Cause[E_co]:
        """If there is a defect, every typed error becomes a defect too."""
        if not self.has_defects:
            return self
        return Cause(
            tuple(Die(_as_exception(r.error)) if isinstance(r, Fail) else r for r in self.reasons)
        )

    def find_error(self) -> Fail[E_co] | Cause[Never]:
        """The first ``Fail``, even beside a defect; otherwise this cause,
        which then holds no typed error. For observing errors (``tap_error``),
        never for recovering from them: use ``find_recoverable_error``."""
        for r in self.reasons:
            if isinstance(r, Fail):
                return r
        return self.without_failures()

    def find_recoverable_error(self) -> Fail[E_co] | Cause[Never]:
        """What a typed recovery handler may act on.

        The first ``Fail``, unless the cause holds a defect: defects take
        precedence, so the result is then the cause to re-fail with, every
        typed error elected to a defect. A cause with no typed error is
        returned as is. Interruptions do not block recovery.
        """
        if not self.has_defects:
            for r in self.reasons:
                if isinstance(r, Fail):
                    return r
        return self.elect_defects().without_failures()

    def without_failures(self) -> Cause[Never]:
        """Keep defects and interruptions; drop typed errors."""
        return Cause(tuple(r for r in self.reasons if not isinstance(r, Fail)))

    def squash(self) -> BaseException:
        """The single exception that best represents this cause.

        Priority: the first typed error, then the first defect, then
        interruption. Typed errors that are not exceptions are wrapped in
        ``UnhandledError`` so they can still be raised.
        """
        if self.failures:
            return _as_exception(self.failures[0])
        if self.defects:
            return self.defects[0]
        return Interrupted() if self.reasons else EmptyCauseError("Empty cause")

    def pretty(self) -> str:
        """Each typed error and defect, exceptions with their traceback and
        cause chain. Interruptions are listed only when nothing else failed,
        as in Effect."""
        blocks: list[str] = []
        interrupters: list[str] = []
        for r in self.reasons:
            match r:
                case Fail(error=BaseException() as e) | Die(defect=e):
                    blocks.append("".join(traceback.format_exception(e)).rstrip())
                case Fail(error=e):
                    blocks.append(f"Fail: {e!r}")
                case Interrupt(fiber_id=fid):
                    interrupters.append("externally" if fid is None else f"by fiber #{fid}")
        if not blocks and interrupters:
            blocks.append(
                "All fibers interrupted without error\n"
                + "\n".join(f"  interrupted {by}" for by in interrupters)
            )
        return "\n\n".join(blocks)


class UnhandledError(Exception):
    """Raised at a run boundary for a typed error that is not an exception."""

    def __init__(self, error: object) -> None:
        super().__init__(repr(error))
        self.error = error


class Interrupted(Exception):
    """Raised at a run boundary when the fiber was interrupted."""


class EmptyCauseError(Exception):
    """What an empty cause squashes to: it records no reason at all."""


def _as_exception(error: object) -> BaseException:
    return error if isinstance(error, BaseException) else UnhandledError(error)


def _dedupe[E](reasons: tuple[Reason[E], ...]) -> tuple[Reason[E], ...]:
    """Drop repeated reasons, keeping order. Like Effect's dedupeReasons,
    reasons are bucketed by hash so only collisions are compared. Errors
    that can't be hashed are compared against everything kept so far."""
    kept: list[Reason[E]] = []
    buckets: dict[int, list[Reason[E]]] = {}
    unhashable: list[Reason[E]] = []
    for r in reasons:
        try:
            h = hash(r)
        except TypeError:
            if r in kept:
                continue
            unhashable.append(r)
        else:
            bucket = buckets.setdefault(h, [])
            if r in bucket or r in unhashable:
                continue
            bucket.append(r)
        kept.append(r)
    return tuple(kept)


def merge[E](*causes: Cause[E]) -> Cause[E]:
    """Combine causes of failures that happened together: a body and its
    finalizers, or concurrent siblings. A defect in any of them makes
    every typed error a defect, so the result cannot be recovered."""
    combined: Cause[E] = Cause(())
    for c in causes:
        combined = combined + c
    return combined.elect_defects()


def fail[E](error: E) -> Cause[E]:
    return Cause((Fail(error),))


def die(defect: BaseException) -> Cause[Never]:
    return Cause((Die(defect),))


def interrupt(fiber_id: int | None = None) -> Cause[Never]:
    return Cause((Interrupt(fiber_id),))
