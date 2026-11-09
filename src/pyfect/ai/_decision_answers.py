"""The check of a provider's answers against their decisions (Effect's
``validateAnswer`` / ``settleAnswers`` in ``DecisionModel``): each answer
becomes an ``Ok`` answer or an ``Err(Unanswered)``, the first failed check
naming the reason."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from pyfect.ai import decision as D
from pyfect.result import Err, Ok

_SUM_TOLERANCE = 1e-6


@dataclass(frozen=True)
class ProviderClassifyAnswer:
    """A classify answer; ``probabilities`` ``None`` when the provider has
    no distribution."""

    tag: ClassVar[str] = "Classify"
    label: str
    probabilities: Mapping[str, float] | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class ProviderRateAnswer:
    """A rate answer: the label is the most probable level's, so the
    provider gives none."""

    tag: ClassVar[str] = "Rate"
    rating: float
    probabilities: Mapping[str, float] | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class ProviderProbabilityAnswer:
    tag: ClassVar[str] = "Probability"
    probability: float


@dataclass(frozen=True)
class ProviderLocateAnswer:
    """A locate answer; ``box`` ``None`` when the provider gave none."""

    tag: ClassVar[str] = "Locate"
    box: D.BoundingBox | None
    confidence: float | None = None


@dataclass(frozen=True)
class ProviderRefusalAnswer:
    """The provider declined to answer."""

    tag: ClassVar[str] = "Refusal"


type ProviderAnswer = (
    ProviderClassifyAnswer
    | ProviderRateAnswer
    | ProviderProbabilityAnswer
    | ProviderLocateAnswer
    | ProviderRefusalAnswer
)


def _unanswered(reason: D.UnansweredReason, description: str) -> Err[D.Unanswered]:
    return Err(D.Unanswered(reason, description))


def _invalid(description: str) -> Err[D.Unanswered]:
    return _unanswered("Invalid", description)


def _is_unit(value: float) -> bool:
    return math.isfinite(value) and 0 <= value <= 1


def _distribution(
    key: str,
    labels: Sequence[str],
    raw: Mapping[str, float] | None,
    rounding_error: float,
) -> D.Outcome[dict[str, float]]:
    """The distribution over ``labels``, rescaled to sum to 1 when its drift
    is within the provider's rounding (``len(labels) * rounding_error``)."""
    if raw is None:
        return _unanswered(
            "NoDistribution", f'Provider returned no probabilities for decision "{key}"'
        )
    probabilities: dict[str, float] = {}
    total = 0.0  # added in order, as JavaScript does: builtin sum() is compensated
    for label in labels:
        value = raw.get(label)
        if value is None or not _is_unit(value):
            return _invalid(
                f'Provider returned no probability for label "{label}" of decision "{key}"'
            )
        probabilities[label] = value
        total += value
    drift = abs(total - 1)
    if total == 0 or drift > len(labels) * rounding_error + _SUM_TOLERANCE:
        return _invalid(
            f'Provider returned probabilities that do not sum to 1 for decision "{key}"'
        )
    if drift > _SUM_TOLERANCE:
        probabilities = {label: value / total for label, value in probabilities.items()}
    return Ok(probabilities)


def _confidence(key: str, confidence: float | None) -> D.Outcome[float | None]:
    if confidence is None or _is_unit(confidence):
        return Ok(confidence)
    return _invalid(f'Provider returned confidence outside [0, 1] for decision "{key}"')


def _classify(
    key: str, decision: D.Classify[Any], answer: ProviderClassifyAnswer, rounding_error: float
) -> D.Outcome[D.AnyAnswer]:
    labels = list(decision.criteria)
    if answer.label not in labels:
        return _invalid(f'Provider returned an unknown label for decision "{key}"')
    confidence = _confidence(key, answer.confidence)
    if isinstance(confidence, Err):
        return confidence
    probabilities = _distribution(key, labels, answer.probabilities, rounding_error)
    if isinstance(probabilities, Err):
        return probabilities
    return Ok(D.ClassifyAnswer(answer.label, probabilities.value, confidence.value))


def _rate(
    key: str, decision: D.Rate[Any], answer: ProviderRateAnswer, rounding_error: float
) -> D.Outcome[D.AnyAnswer]:
    levels = [level.label for level in decision.criteria]
    rating = answer.rating
    if not (math.isfinite(rating) and 0 <= rating <= len(levels) - 1):
        return _invalid(
            f'Provider returned a rating outside [0, {len(levels) - 1}] for decision "{key}"'
        )
    confidence = _confidence(key, answer.confidence)
    if isinstance(confidence, Err):
        return confidence
    probabilities = _distribution(key, levels, answer.probabilities, rounding_error)
    if isinstance(probabilities, Err):
        return probabilities
    found = probabilities.value
    label = levels[0]
    for level in levels[1:]:
        if found[level] > found[label]:
            label = level
    return Ok(D.RateAnswer(rating, label, found, confidence.value))


def _probability(key: str, answer: ProviderProbabilityAnswer) -> D.Outcome[D.ProbabilityAnswer]:
    if not _is_unit(answer.probability):
        return _invalid(f'Provider returned a probability outside [0, 1] for decision "{key}"')
    return Ok(D.ProbabilityAnswer(answer.probability))


def _locate(key: str, answer: ProviderLocateAnswer) -> D.Outcome[D.AnyAnswer]:
    box = answer.box
    if box is None or not all(_is_unit(e) for e in (box.left, box.top, box.right, box.bottom)):
        return _invalid(f'Provider returned a box with edges outside [0, 1] for decision "{key}"')
    if box.left > box.right or box.top > box.bottom:
        return _invalid(f'Provider returned a box with crossed edges for decision "{key}"')
    confidence = _confidence(key, answer.confidence)
    if isinstance(confidence, Err):
        return confidence
    bounds = D.BoundingBox(box.left, box.top, box.right, box.bottom)
    return Ok(D.LocateAnswer(bounds, confidence.value))


def validate(
    key: str, decision: D.AnyDecision, answer: ProviderAnswer | None, rounding_error: float
) -> D.Outcome[D.AnyAnswer]:
    """``answer`` checked against ``decision`` (named ``key``)."""
    match answer:
        case None:
            return _unanswered("Missing", f'Provider returned no answer for decision "{key}"')
        case ProviderRefusalAnswer():
            return _unanswered("Refused", f'Provider refused to answer decision "{key}"')
        case _:
            return _answered(key, decision, answer, rounding_error)


def _answered(
    key: str,
    decision: D.AnyDecision,
    answer: ProviderClassifyAnswer
    | ProviderRateAnswer
    | ProviderProbabilityAnswer
    | ProviderLocateAnswer,
    rounding_error: float,
) -> D.Outcome[D.AnyAnswer]:
    match decision, answer:
        case D.Classify(), ProviderClassifyAnswer():
            return _classify(key, decision, answer, rounding_error)
        case D.Rate(), ProviderRateAnswer():
            return _rate(key, decision, answer, rounding_error)
        case D.Probability(), ProviderProbabilityAnswer():
            return _probability(key, answer)
        case D.Locate(), ProviderLocateAnswer():
            return _locate(key, answer)
        case _:
            return _invalid(
                f'Provider returned a "{answer.tag}" answer for decision "{key}", '
                f'expected "{decision.tag}"'
            )


def settle(
    decisions: Mapping[str, D.AnyDecision],
    answers: Mapping[str, ProviderAnswer],
    rounding_error: float,
) -> dict[str, D.Outcome[D.AnyAnswer]]:
    """Every decision's outcome, in definition order; answers to other
    names are dropped."""
    return {
        key: validate(key, decision, answers.get(key), rounding_error)
        for key, decision in decisions.items()
    }
