"""Decisions a ``DecisionModel`` answers about one input (Effect's
``Decision``): ``classify`` (one label of a set), ``rate`` (a place on an
ordered scale) and ``probability`` (how likely a statement holds), named
and paired with an input schema by ``make``::

    department = decision.classify(
        instructions="Which team should handle this",
        criteria={"billing": "payments", "technical": "bugs"},
    )
    urgent = decision.probability(instructions="The message is time-sensitive")
    triage = decision.make(input=Ticket, decisions={"department": department, "urgent": urgent})

The answers of a response are keyed by name, and typed when looked up by
the decision itself: ``response.answers[department].label`` is
``Literal["billing", "technical"]``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Generic, Literal, LiteralString, TypedDict, TypeVar, overload

from pyfect import schema as S
from pyfect._json_value import JsonValue
from pyfect.result import Result

type Description = str | Mapping[str, JsonValue] | Sequence[JsonValue]
"""Instructions or a description: a string, a JSON object or a JSON array."""

L = TypeVar("L", bound=str)
A = TypeVar("A")
RE = TypeVar("RE")


@dataclass(frozen=True, eq=False)
class Classify(Generic[L]):
    """Assigns the input one label of ``criteria`` (labels to descriptions,
    ``None`` for a label without one)."""

    tag: ClassVar[str] = "Classify"
    instructions: Description
    criteria: Mapping[L, Description | None]


@dataclass(frozen=True)
class Level(Generic[L]):
    """A level of a ``Rate`` scale: the label answers use and the
    description the provider sees."""

    label: L
    description: Description


@dataclass(frozen=True, eq=False)
class Rate(Generic[L]):
    """Places the input on ``criteria``, levels from lowest to highest."""

    tag: ClassVar[str] = "Rate"
    instructions: Description
    criteria: tuple[Level[L], ...]


class ProbabilityCriteria(TypedDict):
    """What each outcome of a ``Probability`` decision means."""

    false: Description
    true: Description


@dataclass(frozen=True, eq=False)
class Probability:
    """Estimates how likely a statement about the input is to hold; the
    answer is the probability of ``true``."""

    tag: ClassVar[str] = "Probability"
    instructions: Description
    criteria: ProbabilityCriteria | None = None


type AnyDecision = Classify[Any] | Rate[Any] | Probability


@dataclass(frozen=True)
class ClassifyAnswer(Generic[L]):
    """The provider's ``label`` (not necessarily the most probable one),
    the distribution over every label and an optional confidence in
    ``[0, 1]``."""

    label: L
    probabilities: Mapping[L, float]
    confidence: float | None = None


@dataclass(frozen=True)
class RateAnswer(Generic[L]):
    """``rating``: the probability-weighted position, in
    ``[0, len(criteria) - 1]``; ``label``: the most probable level (the
    first on ties)."""

    rating: float
    label: L
    probabilities: Mapping[L, float]
    confidence: float | None = None


@dataclass(frozen=True)
class ProbabilityAnswer:
    probability: float


type AnyAnswer = ClassifyAnswer[Any] | RateAnswer[Any] | ProbabilityAnswer

type UnansweredReason = Literal["Missing", "Refused", "NoDistribution", "Invalid"]


@dataclass(frozen=True)
class Unanswered:
    """Why a decision has no valid answer: ``Missing`` (no answer),
    ``Refused``, ``Invalid`` (a wrong kind, value, confidence or
    distribution) or ``NoDistribution`` (otherwise valid, but without
    probabilities). ``description`` is what ``decide`` fails with."""

    reason: UnansweredReason
    description: str


type Outcome[T] = Result[T, Unanswered]


@dataclass(frozen=True, eq=False)
class Definition(Generic[A, RE]):
    """An input schema and the named decisions answered together in one
    provider call."""

    input: S.Codec[A, Any, Any, RE]
    decisions: Mapping[str, AnyDecision]
    json_input: S.Bottom[A, JsonValue, Any, RE] = field(init=False, repr=False)
    """``input`` as a JSON codec (``S.to_codec_json``): the state sent."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "json_input", S.to_codec_json(self.input))

    def name_of(self, decision: AnyDecision) -> str:
        """The name ``decision`` has here; ``KeyError`` when it has none."""
        for name, candidate in self.decisions.items():
            if candidate is decision:
                return name
        raise KeyError(decision)


class _ByName[V](Mapping[str, V]):
    __slots__ = ("_definition", "_values")

    def __init__(self, definition: Definition[Any, Any], values: Mapping[str, V]) -> None:
        self._definition = definition
        self._values = values

    def _get(self, key: str | AnyDecision) -> V:
        return self._values[key if isinstance(key, str) else self._definition.name_of(key)]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({dict(self._values)!r})"


class Answers(_ByName[AnyAnswer]):
    """Answers by decision name; ``answers[decision]`` is typed by the
    decision's kind and labels."""

    __slots__ = ()

    @overload
    def __getitem__(self, key: Classify[L]) -> ClassifyAnswer[L]: ...
    @overload
    def __getitem__(self, key: Rate[L]) -> RateAnswer[L]: ...
    @overload
    def __getitem__(self, key: Probability) -> ProbabilityAnswer: ...
    @overload
    def __getitem__(self, key: str) -> AnyAnswer: ...
    def __getitem__(self, key: str | AnyDecision) -> AnyAnswer:
        return self._get(key)


class Outcomes(_ByName[Outcome[AnyAnswer]]):
    """Each decision's answer (``Ok``) or ``Unanswered`` reason (``Err``),
    by name; ``outcomes[decision]`` is typed as ``Answers`` is."""

    __slots__ = ()

    @overload
    def __getitem__(self, key: Classify[L]) -> Outcome[ClassifyAnswer[L]]: ...
    @overload
    def __getitem__(self, key: Rate[L]) -> Outcome[RateAnswer[L]]: ...
    @overload
    def __getitem__(self, key: Probability) -> Outcome[ProbabilityAnswer]: ...
    @overload
    def __getitem__(self, key: str) -> Outcome[AnyAnswer]: ...
    def __getitem__(self, key: str | AnyDecision) -> Outcome[AnyAnswer]:
        return self._get(key)


@overload
def classify[LL: LiteralString](
    *, instructions: Description, criteria: Mapping[LL, Description | None]
) -> Classify[LL]: ...
@overload
def classify(
    *, instructions: Description, criteria: Mapping[str, Description | None]
) -> Classify[str]: ...
def classify(
    *, instructions: Description, criteria: Mapping[Any, Description | None]
) -> Classify[Any]:
    """A classification over the labels of ``criteria``; raises
    ``ValueError`` for fewer than two labels."""
    if len(criteria) < 2:
        raise ValueError("Decision.classify: criteria must contain at least two labels")
    return Classify(instructions, criteria)


@overload
def rate[LL: LiteralString](
    *, instructions: Description, criteria: list[LL] | tuple[LL, ...] | Mapping[LL, Description]
) -> Rate[LL]: ...
@overload
def rate(
    *, instructions: Description, criteria: Sequence[str] | Mapping[str, Description]
) -> Rate[str]: ...
def rate(
    *, instructions: Description, criteria: Sequence[Any] | Mapping[Any, Description]
) -> Rate[Any]:
    """A rating over ``criteria``, lowest first: labels that are their own
    descriptions, or a mapping of labels to descriptions. Raises
    ``ValueError`` for fewer than two levels or a repeated label."""
    if isinstance(criteria, Mapping):
        levels = tuple(Level(label, description) for label, description in criteria.items())
    else:
        levels = tuple(Level(label, label) for label in criteria)
    if len(levels) < 2:
        raise ValueError("Decision.rate: criteria must contain at least two levels")
    if len({level.label for level in levels}) != len(levels):
        raise ValueError("Decision.rate: criteria must contain distinct levels")
    return Rate(instructions, levels)


def probability(
    *, instructions: Description, criteria: ProbabilityCriteria | None = None
) -> Probability:
    """A probability decision; ``criteria`` describes both outcomes."""
    return Probability(instructions, criteria)


def make[T, R](
    *, input: S.Codec[T, Any, Any, R], decisions: Mapping[str, AnyDecision]
) -> Definition[T, R]:
    """A definition of ``decisions`` about values of ``input``. Raises
    ``ValueError`` when ``decisions`` is empty."""
    if not decisions:
        raise ValueError("Decision.make: decisions must not be empty")
    return Definition(input, decisions)


__all__ = [
    "Answers",
    "AnyAnswer",
    "AnyDecision",
    "Classify",
    "ClassifyAnswer",
    "Definition",
    "Description",
    "Level",
    "Outcome",
    "Outcomes",
    "Probability",
    "ProbabilityAnswer",
    "ProbabilityCriteria",
    "Rate",
    "RateAnswer",
    "Unanswered",
    "UnansweredReason",
    "classify",
    "make",
    "probability",
    "rate",
]
