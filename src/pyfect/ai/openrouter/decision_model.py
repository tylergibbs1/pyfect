"""OpenRouter's alpha Decisions API as a ``DecisionModel`` (Effect's
``OpenRouterDecisionModel``)::

    program.pipe(fx.provide(decision_model.model("openai/gpt-4o-mini").layer))

The state is sent as is and must be a string, a JSON object or an array.
Each decision is a named question (``choice``, ``score`` with the levels'
descriptions, ``noul``); a score's probabilities come back by level index
and are keyed by the levels' labels. Answers without a distribution are
``NoDistribution`` for ``decide_settled`` (an ``InvalidOutputError`` for
``decide``). Probabilities are rounded to two decimals, so their drift is
accepted. The reported ``cost`` and serving ``provider`` are returned
under ``metadata["openrouter"]``; ``Config`` adds routing and tracing
options to each request.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Never

import pyfect as fx
from pyfect import layer as L
from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai import ai_error as E
from pyfect.ai import decision as D
from pyfect.ai import decision_model as DM
from pyfect.ai import model as M
from pyfect.ai.openrouter import schema as W
from pyfect.ai.openrouter.client import OpenRouterClient
from pyfect.ai.openrouter.client import Service as ClientService
from pyfect.context import Tag

ConfigService = W.DecisionsOptions


class Config(Tag[ConfigService], key="@effect/ai-openrouter/OpenRouterDecisionModel/Config"):
    """Per-request routing and tracing options, over the model's."""


def _question(decision: D.AnyDecision) -> W.DecisionsQuestion:
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


def _answers(
    decisions: Mapping[str, D.AnyDecision], answers: Mapping[str, W.Answer]
) -> dict[str, DM.ProviderAnswer]:
    found: dict[str, DM.ProviderAnswer] = {}
    for key, answer in answers.items():
        match answer["type"]:
            case "noul":
                found[key] = DM.ProviderProbabilityAnswer(answer["noul"])
            case "choice":
                found[key] = DM.ProviderClassifyAnswer(
                    answer["choice"], answer.get("probabilities"), answer.get("confidence")
                )
            case "score":
                by_index = answer.get("probabilities")
                decision = decisions.get(key)
                levels = decision.criteria if isinstance(decision, D.Rate) else ()
                probabilities = (
                    None
                    if by_index is None
                    else {
                        level.label: by_index[str(index)]
                        for index, level in enumerate(levels)
                        if str(index) in by_index
                    }
                )
                found[key] = DM.ProviderRateAnswer(
                    answer["score"], probabilities, answer.get("confidence")
                )
    return found


def _metadata(response: W.DecisionsResponse) -> dict[str, Any]:
    openrouter: dict[str, Any] = {}
    cost = response["usage"].get("cost")
    if cost is not None:
        openrouter["cost"] = cost
    provider = response.get("provider")
    if provider is not None:
        openrouter["provider"] = provider
    return {"openrouter": openrouter}


def _invalid_state() -> E.AiError:
    return E.make(
        module="OpenRouterDecisionModel",
        method="decide",
        reason=E.InvalidUserInputError(
            description="OpenRouter decision state must be a string, object, or array"
        ),
    )


def make(
    *, model: str, config: ConfigService | None = None
) -> Effect[DM.Service, Never, OpenRouterClient]:
    """A ``DecisionModel`` asking ``model`` through the ``OpenRouterClient``;
    a provided ``Config`` overrides ``config`` per request."""

    def build(client: ClientService) -> Effect[DM.Service]:
        def decide(options: DM.ProviderOptions) -> Effect[DM.ProviderResponse, E.AiError]:
            state = options.state
            if state is None or isinstance(state, bool | int | float):
                return fx.fail(_invalid_state())
            questions = {key: _question(d) for key, d in options.decisions.items()}

            def send(current: Mapping[str, Any]) -> Effect[DM.ProviderResponse, E.AiError]:
                request: W.DecisionsRequest = {  # pyright: ignore[reportAssignmentType]
                    **current,
                    "model": model,
                    "state": state,
                    "questions": questions,
                }
                return client.create_decisions(request).map(
                    lambda sent: DM.ProviderResponse(
                        _answers(options.decisions, sent[0]["answers"]),
                        sent[0]["usage"]["input_tokens"],
                        sent[0]["usage"]["output_tokens"],
                        sent[0].get("id"),
                        sent[0]["model"],
                        _metadata(sent[0]),
                    )
                )

            return P.current_config(Config, config).flat_map(send)

        return DM.make(decide=decide, probability_precision=2)

    return OpenRouterClient().flat_map(build)


def layer(
    *, model: str, config: ConfigService | None = None
) -> L.Layer[DM.DecisionModel, Never, OpenRouterClient]:
    """``DecisionModel`` over the ``OpenRouterClient``."""
    return L.effect(DM.DecisionModel, make(model=model, config=config))


def model(
    model: str, config: ConfigService | None = None
) -> M.Model[DM.DecisionModel, OpenRouterClient]:
    """The decision model as a ``Model`` (provider ``"openrouter"``)."""
    return M.make("openrouter", model, layer(model=model, config=config))


__all__ = ["Config", "ConfigService", "layer", "make", "model"]
