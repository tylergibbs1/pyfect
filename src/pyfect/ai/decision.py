"""Decisions a ``DecisionModel`` answers about one input (Effect's
``Decision``): ``classify`` (one label of a set), ``rate`` (a place on an
ordered scale), ``probability`` (how likely a statement holds) and
``locate`` (where a target is in an ``Image`` field of the input), named
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

import base64
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import (
    Any,
    ClassVar,
    Generic,
    Literal,
    LiteralString,
    TypedDict,
    TypeIs,
    TypeVar,
    cast,
    overload,
)

from pyfect import schema as S
from pyfect._json_value import JsonValue
from pyfect._url import Url
from pyfect.ai._decision_image import Image as ImageValue
from pyfect.result import Result
from pyfect.schema import transformation as T

type Description = str | Mapping[str, JsonValue] | Sequence[JsonValue]
"""Instructions or a description: a string, a JSON object or a JSON array."""

L = TypeVar("L", bound=str)
L_co = TypeVar("L_co", bound=str, covariant=True)
A = TypeVar("A")
RE_co = TypeVar("RE_co", covariant=True)


@dataclass(frozen=True, eq=False)
class Classify(Generic[L]):
    """Assigns the input one label of ``criteria`` (labels to descriptions,
    ``None`` for a label without one)."""

    tag: ClassVar[str] = "Classify"
    instructions: Description
    criteria: Mapping[L, Description | None]


@dataclass(frozen=True)
class Level(Generic[L_co]):
    """A level of a ``Rate`` scale: the label answers use and the
    description the provider sees."""

    label: L_co
    description: Description


@dataclass(frozen=True, eq=False)
class Rate(Generic[L_co]):
    """Places the input on ``criteria``, levels from lowest to highest."""

    tag: ClassVar[str] = "Rate"
    instructions: Description
    criteria: tuple[Level[L_co], ...]


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


@dataclass(frozen=True, eq=False)
class Locate:
    """Finds one target in an image field of the input. ``image`` is the
    field's path in the encoded input (``"photo"``, ``"frames[2].frame"``);
    the answer is a bounding box around the target."""

    tag: ClassVar[str] = "Locate"
    image: str
    instructions: Description


IMAGE_KEY = "~effect/ai/Decision/Image"
"""The key that marks an encoded ``Image``."""


class _Base64Image(TypedDict):
    mediaType: str
    base64: str


class _UrlImage(TypedDict):
    mediaType: str
    url: str


ImageEncoded = TypedDict("ImageEncoded", {"~effect/ai/Decision/Image": "_Base64Image | _UrlImage"})
"""The JSON encoding of an ``Image``: base64 data or a URL with its media
type, under ``IMAGE_KEY``."""


def _is_image(value: object) -> TypeIs[ImageValue]:
    return isinstance(value, ImageValue)


def _decode_image(encoded: Mapping[str, Mapping[str, object]]) -> ImageValue:
    image = encoded[IMAGE_KEY]
    data = image["base64"] if "base64" in image else image["url"]
    return ImageValue(str(image["mediaType"]), data)  # pyright: ignore[reportArgumentType]


def _encode_image(image: ImageValue) -> dict[str, dict[str, object]]:
    data = image.data
    if isinstance(data, Url):
        return {IMAGE_KEY: {"mediaType": image.media_type, "url": data}}
    text = data if isinstance(data, str) else base64.b64encode(data).decode()
    return {IMAGE_KEY: {"mediaType": image.media_type, "base64": text}}


_IMAGE_REF = S.Union(
    S.Struct(_Base64Image),
    S.Struct(_UrlImage, url=S.URLFromString),
)

Image: S.Bottom[ImageValue, Mapping[str, object]] = cast(
    "Any",
    S.Struct(ImageEncoded, **{IMAGE_KEY: _IMAGE_REF}).pipe(
        S.decode_to(
            S.declare(_is_image, expected="DecisionModel.Image"),
            T.transform(decode=_decode_image, encode=_encode_image),  # pyright: ignore[reportArgumentType]
        )
    ),
)
"""The schema of an image input field (Effect's ``Decision.Image``). Its
type is ``decision_model.Image``: a media type with base64 data, bytes or a
URL. ``decide`` replaces each one in the encoded input with a reference
string and sends the images to the provider separately; an image used in
several fields is sent once. Decisions refer to it by the field's path."""


type AnyDecision = Classify[Any] | Rate[Any] | Probability | Locate
type NonLocateDecision = Classify[Any] | Rate[Any] | Probability
"""The decisions a provider without ``supports_locate`` receives."""


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


@dataclass(frozen=True)
class BoundingBox:
    """The smallest rectangle around a located target. Each edge is a
    fraction of the image's size from the top-left corner: ``left`` and
    ``right`` of its width, ``top`` and ``bottom`` of its height, all in
    ``[0, 1]``, with ``left <= right`` and ``top <= bottom``."""

    left: float
    top: float
    right: float
    bottom: float


@dataclass(frozen=True)
class LocateAnswer:
    """A ``Locate`` answer. A target absent from the image still gets a box,
    so pair the decision with a ``probability`` that it is present;
    ``confidence`` is an optional, provider-defined measure in ``[0, 1]``."""

    box: BoundingBox
    confidence: float | None = None


type AnyAnswer = ClassifyAnswer[Any] | RateAnswer[Any] | ProbabilityAnswer | LocateAnswer

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
class Definition(Generic[A, RE_co]):
    """An input schema and the named decisions answered together in one
    provider call. ``A`` stays invariant: ``decide(definition, input=...)``
    infers ``A`` from both, and a covariant ``A`` would widen it to accept any input."""

    input: S.Codec[A, Any, Any, RE_co]
    decisions: Mapping[str, AnyDecision]
    json_input: S.Bottom[A, JsonValue, Any, RE_co] = field(init=False, repr=False)
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
    def __getitem__(self, key: Locate) -> LocateAnswer: ...
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
    def __getitem__(self, key: Locate) -> Outcome[LocateAnswer]: ...
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


def locate(*, image: str, instructions: Description) -> Locate:
    """A decision finding one target in the image field at ``image``: keys
    of the encoded input joined with ``.``, array indices in brackets
    (``"frames[2].frame"``). The model must support locate decisions, and
    ``decide`` fails with ``InvalidUserInputError`` when the path holds no
    image. The answer is always one box, even when the target is absent:
    pair it with a ``probability`` decision that the target is present."""
    return Locate(image, instructions)


def make[T, R](
    *, input: S.Codec[T, Any, Any, R], decisions: Mapping[str, AnyDecision]
) -> Definition[T, R]:
    """A definition of ``decisions`` about values of ``input``. Raises
    ``ValueError`` when ``decisions`` is empty."""
    if not decisions:
        raise ValueError("Decision.make: decisions must not be empty")
    return Definition(input, decisions)


__all__ = [
    "IMAGE_KEY",
    "Answers",
    "AnyAnswer",
    "AnyDecision",
    "BoundingBox",
    "Classify",
    "ClassifyAnswer",
    "Definition",
    "Description",
    "Image",
    "ImageEncoded",
    "Level",
    "Locate",
    "LocateAnswer",
    "NonLocateDecision",
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
    "locate",
    "make",
    "probability",
    "rate",
]
