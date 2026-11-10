"""What a ``CircuitBreaker`` decides with: trip policies, call outcomes,
circuit states and the transitions between them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Final, Literal

from pyfect.duration import Duration, Seconds, to_seconds

# --- trip policies --------------------------------------------------------------------


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True, slots=True)
class Consecutive:
    """Open after ``failure_count`` failures in a row (an integer >= 1)."""

    failure_count: int

    def __post_init__(self) -> None:
        if not _is_count(self.failure_count) or self.failure_count < 1:
            raise ValueError(
                "CircuitBreaker.consecutive: failures must be an integer >= 1, "
                f"got {self.failure_count}"
            )


@dataclass(frozen=True, slots=True)
class Rate:
    """Open once at least ``minimum_calls`` of the last ``size`` recorded
    calls are in and at least ``threshold`` of them failed."""

    threshold: float
    minimum_calls: int
    size: int

    def __post_init__(self) -> None:
        if not 0 <= self.threshold <= 1:
            raise ValueError(
                f"CircuitBreaker.rate: threshold must be in [0, 1], got {self.threshold}"
            )
        if not _is_count(self.size) or self.size < 1:
            raise ValueError(f"CircuitBreaker.rate: size must be an integer >= 1, got {self.size}")
        if not _is_count(self.minimum_calls) or not 1 <= self.minimum_calls <= self.size:
            raise ValueError(
                "CircuitBreaker.rate: minimumCalls must be an integer in [1, size], "
                f"got {self.minimum_calls}"
            )


type TripPolicy = Consecutive | Rate
"""When a closed circuit opens."""


def consecutive(failures: int) -> TripPolicy:
    """Open after ``failures`` failures in a row."""
    return Consecutive(failures)


def rate(
    *, threshold: float = 0.5, size: int = 100, minimum_calls: int | None = None
) -> TripPolicy:
    """Open once ``threshold`` (default half) of the last ``size`` (default
    100) recorded calls failed, counting only once ``minimum_calls``
    (default ``size``) are in."""
    return Rate(threshold, size if minimum_calls is None else minimum_calls, size)


# --- outcomes -------------------------------------------------------------------------

type OutcomeKind = Literal["Success", "Failure", "Ignored"]


@dataclass(frozen=True, slots=True)
class SuccessOutcome:
    """The call counts as a success."""

    kind: ClassVar[Literal["Success"]] = "Success"


@dataclass(frozen=True, slots=True)
class IgnoredOutcome:
    """The call does not count."""

    kind: ClassVar[Literal["Ignored"]] = "Ignored"


@dataclass(frozen=True, slots=True)
class FailureOutcome:
    """The call counts as a failure; ``retry_after`` (a server's hint) is
    the least the opening it causes lasts, up to ``max_open_duration``."""

    retry_after: Seconds | None = None
    kind: ClassVar[Literal["Failure"]] = "Failure"


type Outcome = SuccessOutcome | IgnoredOutcome | FailureOutcome
"""How a call counts (what ``classify`` gives)."""

success: Final[Outcome] = SuccessOutcome()
ignored: Final[Outcome] = IgnoredOutcome()


def failure(*, retry_after: Duration | None = None) -> Outcome:
    """A failure, opening for at least ``retry_after`` if it opens."""
    return FailureOutcome(None if retry_after is None else to_seconds(retry_after))


@dataclass(frozen=True, slots=True)
class ClassifyContext:
    """What ``classify`` learns beside the exit: ``probe`` is ``True`` for
    the half-open probe, so an outcome ignored while closed (a rate-limited
    response, say) can count as a failure that reopens the circuit."""

    probe: bool


# --- states ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Closed:
    """Calls run and are counted."""

    key: str


@dataclass(frozen=True, slots=True)
class Open:
    """Calls are rejected for ``retry_after`` more; the circuit has opened
    ``consecutive_openings`` times without staying closed."""

    key: str
    retry_after: Seconds
    consecutive_openings: int


@dataclass(frozen=True, slots=True)
class HalfOpen:
    """One probe call may run (``probing`` while it does); its outcome
    closes or reopens the circuit."""

    key: str
    probing: bool
    consecutive_openings: int


type State = Closed | Open | HalfOpen


# --- transitions ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OpenTransition:
    """The circuit opened (from ``from_``) for ``retry_after``."""

    key: str
    from_: Literal["Closed", "HalfOpen"]
    retry_after: Seconds
    consecutive_openings: int
    to: ClassVar[Literal["Open"]] = "Open"


@dataclass(frozen=True, slots=True)
class HalfOpenTransition:
    """The open time ended and a probe was admitted."""

    key: str
    from_: ClassVar[Literal["Open"]] = "Open"
    to: ClassVar[Literal["HalfOpen"]] = "HalfOpen"


@dataclass(frozen=True, slots=True)
class CloseTransition:
    """A probe succeeded."""

    key: str
    from_: ClassVar[Literal["HalfOpen"]] = "HalfOpen"
    to: ClassVar[Literal["Closed"]] = "Closed"


type Transition = OpenTransition | HalfOpenTransition | CloseTransition
"""A change of a key's state, published on ``transitions``."""


@dataclass(frozen=True, slots=True)
class Admission:
    """A call the store let through: ``generation`` fences its record
    against later ones, ``probe`` says it is the half-open probe, and
    ``transition`` is the one admitting it caused."""

    generation: int
    probe: bool
    consecutive_openings: int
    transition: Transition | None = field(default=None)
