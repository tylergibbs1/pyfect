"""TypeSafe's System One as a ``DecisionModel`` (Effect's
``TypeSafeDecisionModel``)::

    program.pipe(fx.provide(decision_model.model("jev-latest").layer)).pipe(
        fx.provide(client.layer_config())
    )

Each decision is sent as a named question (``choice``, ``score`` with the
levels' descriptions, ``noul``); a score's probabilities come back by level
index and are keyed by the levels' labels. System One takes no images.
Probabilities are rounded to two decimals, so their drift is accepted.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Never

from pyfect import layer as L
from pyfect._core import Effect
from pyfect.ai import _noul_answers as N
from pyfect.ai import ai_error as E
from pyfect.ai import decision as D
from pyfect.ai import decision_model as DM
from pyfect.ai import model as M
from pyfect.ai.typesafe import schema as W
from pyfect.ai.typesafe.client import Service as ClientService
from pyfect.ai.typesafe.client import TypeSafeClient

type Model = Literal["jev-latest", "jev-preview", "jev-1.13.0"]
"""Model names (any other string is accepted too)."""


def _question(decision: D.AnyDecision) -> W.Question:
    match decision:
        case D.Classify():
            criteria = dict(decision.criteria)
            return {"type": "choice", "instructions": decision.instructions, "criteria": criteria}
        case D.Rate():
            levels = [level.description for level in decision.criteria]
            return {"type": "score", "instructions": decision.instructions, "criteria": levels}
        case D.Probability():
            question: W.NoulQuestion = {"type": "noul", "instructions": decision.instructions}
            if decision.criteria is not None:
                question["criteria"] = {**decision.criteria}
            return question


def questions(decisions: Mapping[str, D.AnyDecision]) -> dict[str, W.Question]:
    """The request's questions, by decision name."""
    return {key: _question(decision) for key, decision in decisions.items()}


def make(*, model: Model | str) -> Effect[DM.Service, Never, TypeSafeClient]:
    """A ``DecisionModel`` asking ``model`` through the ``TypeSafeClient``."""

    def build(client: ClientService) -> Effect[DM.Service]:
        def decide(options: DM.ProviderOptions) -> Effect[DM.ProviderResponse, E.AiError]:
            request: W.SystemOneRequest = {
                "model": model,
                "state": options.state,
                "questions": questions(options.decisions),
            }

            def answered(response: W.SystemOneResponse) -> DM.ProviderResponse:
                usage = response.get("usage", {})
                return DM.ProviderResponse(
                    N.provider_answers(options.decisions, response["answers"]),
                    usage.get("input_tokens"),
                    usage.get("output_tokens"),
                )

            return client.system_one(request).map(answered)

        return DM.make(decide=decide, probability_precision=2)

    return TypeSafeClient().flat_map(build)


def layer(*, model: Model | str) -> L.Layer[DM.DecisionModel, Never, TypeSafeClient]:
    """``DecisionModel`` over the ``TypeSafeClient``."""
    return L.effect(DM.DecisionModel, make(model=model))


def model(model: Model | str) -> M.Model[DM.DecisionModel, TypeSafeClient]:
    """The decision model as a ``Model`` (provider ``"typesafe"``)."""
    return M.make("typesafe", model, layer(model=model))


__all__ = ["Model", "layer", "make", "model", "questions"]
