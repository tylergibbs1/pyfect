"""Why an effect failed.

A ``Cause`` is a flat list of reasons, as in Effect 4:

- ``Fail``: an expected, typed error. This is what the ``E`` channel tracks.
- ``Die``: a defect. An exception nobody planned for.
- ``Interrupt``: the fiber was interrupted, optionally by another fiber.

Most causes hold one reason. More appear when finalizers fail while
unwinding, or when concurrent work fails in several places at once.

Each reason carries annotations: services keyed by tag, such as the
``tracer.StackTrace`` frame a failure inside a span records. They take part
in equality, as in Effect, but not in the hash.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Generic, Never, Self, TypeVar, cast

from pyfect.result import Err, Ok, Result

if TYPE_CHECKING:
    from pyfect._stack_frame import StackFrame
    from pyfect.context import Context, Tag

E_co = TypeVar("E_co", covariant=True)

type Annotations = Mapping[type[Tag[Any]], object]

_NO_ANNOTATIONS: Annotations = MappingProxyType({})


class _Annotated:
    """``annotate`` for the reason classes."""

    __slots__ = ()
    annotations: Annotations

    def annotate(self, annotations: Context, *, overwrite: bool = False) -> Self:
        """A copy carrying ``annotations`` too. Keys it already has keep
        their value unless ``overwrite``; with nothing new, ``self``."""
        merged = _merge_annotations(self.annotations, annotations.unsafe_map, overwrite)
        return self if merged is None else replace(self, annotations=merged)  # pyright: ignore[reportArgumentType, reportUnknownVariableType]


def _merge_annotations(
    current: Annotations, added: Annotations, overwrite: bool
) -> Annotations | None:
    """``current`` with ``added``, or ``None`` when that changes nothing."""
    new = {
        k: v for k, v in added.items() if k not in current or (overwrite and current[k] is not v)
    }
    return MappingProxyType({**current, **new}) if new else None


@dataclass(frozen=True, slots=True)
class Fail(_Annotated, Generic[E_co]):
    error: E_co
    annotations: Annotations = field(default=_NO_ANNOTATIONS, hash=False, repr=False, kw_only=True)


@dataclass(frozen=True, slots=True)
class Die(_Annotated):
    defect: BaseException
    annotations: Annotations = field(default=_NO_ANNOTATIONS, hash=False, repr=False, kw_only=True)


@dataclass(frozen=True, slots=True)
class Interrupt(_Annotated):
    fiber_id: int | None = None
    annotations: Annotations = field(default=_NO_ANNOTATIONS, hash=False, repr=False, kw_only=True)


type Reason[E] = Fail[E] | Die | Interrupt


@dataclass(frozen=True, slots=True, weakref_slot=True)
class Cause(Generic[E_co]):
    reasons: tuple[Reason[E_co], ...]

    def __add__[E2](self, other: Cause[E2]) -> Cause[E_co | E2]:
        """Both causes' reasons in order, without repeating equal ones."""
        if not self.reasons:
            return other
        if not other.reasons:
            return self
        combined = _dedupe((*self.reasons, *other.reasons))
        return self if combined == self.reasons else Cause(combined)

    def add_interrupts(self, interrupts: Cause[Never]) -> Cause[E_co]:
        """Add each interruption not recorded yet: one per interrupting
        fiber and the frame it interrupted from."""
        seen = {_interruptor(r) for r in self.reasons if isinstance(r, Interrupt)}
        new: list[Reason[E_co]] = []
        for r in interrupts.reasons:
            if isinstance(r, Interrupt) and (key := _interruptor(r)) not in seen:
                seen.add(key)
                new.append(r)
        return Cause((*self.reasons, *new)) if new else self

    def annotate(self, annotations: Context, *, overwrite: bool = False) -> Cause[E_co]:
        """Every reason carrying ``annotations`` too (see ``Fail.annotate``)."""
        if not annotations.unsafe_map:
            return self
        reasons = tuple(r.annotate(annotations, overwrite=overwrite) for r in self.reasons)
        changed = any(a is not b for a, b in zip(reasons, self.reasons, strict=True))
        return Cause(reasons) if changed else self

    @property
    def annotations(self) -> Context:
        """Every reason's annotations; a later reason wins a shared key."""
        merged: dict[type[Tag[Any]], object] = {}
        for r in self.reasons:
            merged.update(r.annotations)
        return _context(merged)

    def map[E2](self, f: Callable[[E_co], E2]) -> Cause[E2]:
        """Apply ``f`` to every typed error, keeping its annotations;
        defects and interruptions stay."""
        return Cause(
            tuple(
                Fail(f(r.error), annotations=r.annotations) if isinstance(r, Fail) else r
                for r in self.reasons
            )
        )

    @property
    def failures(self) -> tuple[E_co, ...]:
        return tuple(r.error for r in self.reasons if isinstance(r, Fail))

    @property
    def defects(self) -> tuple[BaseException, ...]:
        return tuple(r.defect for r in self.reasons if isinstance(r, Die))

    @property
    def interruptors(self) -> frozenset[int]:
        """The ids of the fibers that interrupted; external interrupts have none."""
        return frozenset(
            r.fiber_id for r in self.reasons if isinstance(r, Interrupt) and r.fiber_id is not None
        )

    @property
    def has_fails(self) -> bool:
        return any(isinstance(r, Fail) for r in self.reasons)

    @property
    def has_dies(self) -> bool:
        return any(isinstance(r, Die) for r in self.reasons)

    @property
    def has_interrupts(self) -> bool:
        return any(isinstance(r, Interrupt) for r in self.reasons)

    @property
    def has_interrupts_only(self) -> bool:
        return bool(self.reasons) and all(isinstance(r, Interrupt) for r in self.reasons)

    def elect_defects(self) -> Cause[E_co]:
        """If there is a defect, every typed error becomes a defect too."""
        if not self.has_dies:
            return self
        return Cause(
            tuple(
                Die(_as_exception(r.error), annotations=r.annotations) if isinstance(r, Fail) else r
                for r in self.reasons
            )
        )

    def find_fail(self) -> Fail[E_co] | Cause[Never]:
        """The first ``Fail``, even beside a defect; otherwise this cause,
        which then holds no typed error. For observing errors (``tap_error``),
        never for recovering from them: use ``find_recoverable_error``."""
        for r in self.reasons:
            if isinstance(r, Fail):
                return r
        return self.without_failures()

    def find_error(self) -> Result[E_co, Cause[Never]]:
        """``Ok`` of the first typed error, else ``Err`` of this cause, which
        then holds no typed error."""
        found = self.find_fail()
        return Ok(found.error) if isinstance(found, Fail) else Err(found)

    def find_die(self) -> Die | None:
        return next((r for r in self.reasons if isinstance(r, Die)), None)

    def find_defect(self) -> BaseException | None:
        die = self.find_die()
        return None if die is None else die.defect

    def find_interrupt(self) -> Interrupt | None:
        return next((r for r in self.reasons if isinstance(r, Interrupt)), None)

    def filter_interruptors(self) -> frozenset[int] | None:
        """``interruptors`` if the cause holds an interruption (the set is
        empty when every one was external), else ``None``."""
        return self.interruptors if self.has_interrupts else None

    def find_recoverable_error(self) -> Fail[E_co] | Cause[Never]:
        """What a typed recovery handler may act on.

        The first ``Fail``, unless the cause holds a defect: defects take
        precedence, so the result is then the cause to re-fail with, every
        typed error elected to a defect. A cause with no typed error is
        returned as is. Interruptions do not block recovery.
        """
        if not self.has_dies:
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
        return _interrupted(self) if self.reasons else EmptyCauseError("Empty cause")

    def pretty_errors(self) -> tuple[BaseException, ...]:
        """One exception per typed error and defect, in order. Typed errors
        that are not exceptions are wrapped in ``UnhandledError``. A cause of
        interruptions alone gives one ``Interrupted`` naming the interruptors;
        an empty cause gives none."""
        errors = tuple(
            _as_exception(r.error) if isinstance(r, Fail) else r.defect
            for r in self.reasons
            if not isinstance(r, Interrupt)
        )
        return errors if errors or not self.reasons else (_interrupted(self),)

    def pretty(self) -> str:
        """``pretty_errors`` rendered with their tracebacks and cause chains,
        each followed by the span frames its reason records (Effect's
        ``    at span (location)`` lines)."""
        from pyfect._stack_frame import StackTrace, render

        errors = self.pretty_errors()
        reasons = [r for r in self.reasons if not isinstance(r, Interrupt)] or self.reasons[:1]
        return "\n\n".join(
            "\n".join(
                [
                    "".join(traceback.format_exception(e)).rstrip(),
                    *render(_frame(r.annotations, StackTrace)),
                ]
            )
            for e, r in zip(errors, reasons, strict=True)
        )


class UnhandledError(Exception):
    """Raised at a run boundary for a typed error that is not an exception."""

    def __init__(self, error: object) -> None:
        super().__init__(repr(error))
        self.error = error


class Interrupted(Exception):
    """Raised at a run boundary when the fiber was interrupted."""


class EmptyCauseError(Exception):
    """What an empty cause squashes to: it records no reason at all."""


def _interrupted(cause: Cause[object]) -> Interrupted:
    from pyfect._stack_frame import InterruptorStackTrace, render

    error = Interrupted("All fibers interrupted without error")
    for r in cause.reasons:
        if isinstance(r, Interrupt):
            by = "externally" if r.fiber_id is None else f"by fiber #{r.fiber_id}"
            frames = render(_frame(r.annotations, InterruptorStackTrace))
            error.add_note("\n".join([f"interrupted {by}", *frames]))
    return error


def _frame(annotations: Annotations, tag: type[Tag[StackFrame]]) -> StackFrame | None:
    return cast("StackFrame | None", annotations.get(tag))


def _interruptor(reason: Interrupt) -> tuple[int | None, object]:
    """What tells interruptions apart: the fiber, and the frame it
    interrupted from."""
    from pyfect._stack_frame import InterruptorStackTrace

    return reason.fiber_id, reason.annotations.get(InterruptorStackTrace)


def _context(services: Mapping[type[Tag[Any]], object]) -> Context:
    from pyfect.context import Context

    return Context(services)


def reason_annotations(reason: Reason[object]) -> Context:
    """A reason's annotations as a ``Context``."""
    return _context(reason.annotations)


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


empty: Cause[Never] = Cause(())


def from_reasons[E = Never](reasons: Iterable[Reason[E]]) -> Cause[E]:
    """A cause holding exactly ``reasons``, in order, repeats included."""
    return Cause(tuple(reasons))


def fail[E](error: E) -> Cause[E]:
    return Cause((Fail(error),))


def die(defect: BaseException) -> Cause[Never]:
    return Cause((Die(defect),))


def interrupt(fiber_id: int | None = None) -> Cause[Never]:
    return Cause((Interrupt(fiber_id),))
