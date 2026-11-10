"""The check of a provider's answers against their decisions (Effect's
``validateAnswer`` / ``settleAnswers`` in ``DecisionModel``): each answer
becomes an ``Ok`` answer or an ``Err(Unanswered)``, the first failed check
naming the reason."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, Literal, NotRequired, TypedDict, TypeGuard, cast

from pyfect.ai import decision as D
from pyfect.result import Err, Ok

_SUM_TOLERANCE = 1e-6


class ProviderClassifyAnswer(TypedDict):
    """A classify answer; ``probabilities`` left out (or ``None``) when the
    provider has no distribution."""

    _tag: Literal["Classify"]
    label: str
    probabilities: NotRequired[Mapping[str, float] | None]
    confidence: NotRequired[float | None]


class ProviderRateAnswer(TypedDict):
    """A rate answer: the label is the most probable level's (ties go to
    the first), so the provider gives none."""

    _tag: Literal["Rate"]
    rating: float
    probabilities: NotRequired[Mapping[str, float] | None]
    confidence: NotRequired[float | None]


class ProviderProbabilityAnswer(TypedDict):
    _tag: Literal["Probability"]
    probability: float


class ProviderBoundingBox(TypedDict):
    """A box as a provider gives it (Effect's ``Decision.BoundingBox``)."""

    left: float
    top: float
    right: float
    bottom: float


class ProviderLocateAnswer(TypedDict):
    _tag: Literal["Locate"]
    box: ProviderBoundingBox
    confidence: NotRequired[float | None]


class ProviderRefusalAnswer(TypedDict):
    """The provider declined to answer."""

    _tag: Literal["Refusal"]


type ProviderAnswer = (
    ProviderClassifyAnswer
    | ProviderRateAnswer
    | ProviderProbabilityAnswer
    | ProviderLocateAnswer
    | ProviderRefusalAnswer
)
"""A provider's answer to one decision, a plain dict tagged by ``_tag``
(Effect's ``ProviderAnswer``). Keys it does not name are dropped."""


type _Raw = Mapping[str, object]
"""An answer as validation reads it: the provider's dict, whose values are
checked before use (Effect's ``validateAnswer`` takes ``unknown``)."""


def _unanswered(reason: D.UnansweredReason, description: str) -> Err[D.Unanswered]:
    return Err(D.Unanswered(reason, description))


def _invalid(description: str) -> Err[D.Unanswered]:
    return _unanswered("Invalid", description)


def _is_finite(value: object) -> TypeGuard[float]:
    """A finite JavaScript number: an int or float, not a bool."""
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _is_unit(value: object) -> TypeGuard[float]:
    return _is_finite(value) and 0 <= value <= 1


def _distribution(
    key: str,
    labels: Sequence[str],
    raw: object,
    rounding_error: float,
) -> D.Outcome[dict[str, float]]:
    """The distribution over ``labels``, rescaled to sum to 1 when its drift
    is within the provider's rounding (``len(labels) * rounding_error``)."""
    if not isinstance(raw, Mapping):
        return _unanswered(
            "NoDistribution", f'Provider returned no probabilities for decision "{key}"'
        )
    probabilities: dict[str, float] = {}
    total = 0.0  # added in order, as JavaScript does: builtin sum() is compensated
    for label in labels:
        value = cast("_Raw", raw).get(label)
        if not _is_unit(value):
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


def _confidence(key: str, confidence: object) -> D.Outcome[float | None]:
    if confidence is None or _is_unit(confidence):
        return Ok(confidence)
    return _invalid(f'Provider returned confidence outside [0, 1] for decision "{key}"')


def _classify(
    key: str, decision: D.Classify[Any], answer: _Raw, rounding_error: float
) -> D.Outcome[D.AnyAnswer]:
    labels = list(decision.criteria)
    label = answer.get("label")
    if not isinstance(label, str) or label not in labels:
        return _invalid(f'Provider returned an unknown label for decision "{key}"')
    confidence = _confidence(key, answer.get("confidence"))
    if isinstance(confidence, Err):
        return confidence
    probabilities = _distribution(key, labels, answer.get("probabilities"), rounding_error)
    if isinstance(probabilities, Err):
        return probabilities
    return Ok(D.ClassifyAnswer(label, probabilities.value, confidence.value))


def _rate(
    key: str, decision: D.Rate[Any], answer: _Raw, rounding_error: float
) -> D.Outcome[D.AnyAnswer]:
    levels = [level.label for level in decision.criteria]
    rating = answer.get("rating")
    if not (_is_finite(rating) and 0 <= rating <= len(levels) - 1):
        return _invalid(
            f'Provider returned a rating outside [0, {len(levels) - 1}] for decision "{key}"'
        )
    confidence = _confidence(key, answer.get("confidence"))
    if isinstance(confidence, Err):
        return confidence
    probabilities = _distribution(key, levels, answer.get("probabilities"), rounding_error)
    if isinstance(probabilities, Err):
        return probabilities
    found = probabilities.value
    label = levels[0]
    for level in levels[1:]:
        if found[level] > found[label]:
            label = level
    return Ok(D.RateAnswer(rating, label, found, confidence.value))


def _probability(key: str, answer: _Raw) -> D.Outcome[D.ProbabilityAnswer]:
    probability = answer.get("probability")
    if not _is_unit(probability):
        return _invalid(f'Provider returned a probability outside [0, 1] for decision "{key}"')
    return Ok(D.ProbabilityAnswer(probability))


def _locate(key: str, answer: _Raw) -> D.Outcome[D.AnyAnswer]:
    box = answer.get("box")
    if not isinstance(box, Mapping):
        return _invalid(f'Provider returned a box with edges outside [0, 1] for decision "{key}"')
    sides = cast("_Raw", box)
    edges = [e for name in ("left", "top", "right", "bottom") if _is_unit(e := sides.get(name))]
    if len(edges) != 4:
        return _invalid(f'Provider returned a box with edges outside [0, 1] for decision "{key}"')
    left, top, right, bottom = edges
    if left > right or top > bottom:
        return _invalid(f'Provider returned a box with crossed edges for decision "{key}"')
    confidence = _confidence(key, answer.get("confidence"))
    if isinstance(confidence, Err):
        return confidence
    return Ok(D.LocateAnswer(D.BoundingBox(left, top, right, bottom), confidence.value))


def validate(  # noqa: PLR0911
    key: str, decision: D.AnyDecision, answer: ProviderAnswer | None, rounding_error: float
) -> D.Outcome[D.AnyAnswer]:
    """``answer`` checked against ``decision`` (named ``key``)."""
    if answer is None:
        return _unanswered("Missing", f'Provider returned no answer for decision "{key}"')
    raw = cast("_Raw", answer)
    tag = raw.get("_tag")
    if tag == "Refusal":
        return _unanswered("Refused", f'Provider refused to answer decision "{key}"')
    if tag != decision.tag:
        return _invalid(
            f'Provider returned a "{tag}" answer for decision "{key}", expected "{decision.tag}"'
        )
    match decision:
        case D.Classify():
            return _classify(key, decision, raw, rounding_error)
        case D.Rate():
            return _rate(key, decision, raw, rounding_error)
        case D.Probability():
            return _probability(key, raw)
        case D.Locate():
            return _locate(key, raw)


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
