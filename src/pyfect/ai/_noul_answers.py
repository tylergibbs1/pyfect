"""The provider answers of a ``choice`` / ``score`` / ``noul`` response,
the answer format Cloudflare's Clef and TypeSafe's System One share."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, TypedDict

from pyfect.ai import decision as D
from pyfect.ai import decision_model as DM


class ChoiceAnswer(TypedDict):
    type: Literal["choice"]
    choice: str
    probabilities: Mapping[str, float]
    confidence: float


class ScoreAnswer(TypedDict):
    type: Literal["score"]
    score: float
    probabilities: Mapping[str, float]
    confidence: float


class NoulAnswer(TypedDict):
    type: Literal["noul"]
    noul: float


type Answer = ChoiceAnswer | ScoreAnswer | NoulAnswer


def provider_answers(
    decisions: Mapping[str, D.AnyDecision], answers: Mapping[str, Answer]
) -> dict[str, DM.ProviderAnswer]:
    """Each decision's answer; a score's probabilities are by level index,
    so they are keyed by the levels' labels (an index with no level is
    dropped)."""
    found: dict[str, DM.ProviderAnswer] = {}
    for key, decision in decisions.items():
        answer = answers.get(key)
        if answer is None:
            continue
        match answer["type"]:
            case "choice":
                found[key] = DM.ProviderClassifyAnswer(
                    answer["choice"], answer["probabilities"], answer["confidence"]
                )
            case "score":
                levels = decision.criteria if isinstance(decision, D.Rate) else ()
                by_index = answer["probabilities"]
                probabilities = {
                    level.label: by_index[str(index)]
                    for index, level in enumerate(levels)
                    if str(index) in by_index
                }
                found[key] = DM.ProviderRateAnswer(
                    answer["score"], probabilities, answer["confidence"]
                )
            case "noul":
                found[key] = DM.ProviderProbabilityAnswer(answer["noul"])
    return found
