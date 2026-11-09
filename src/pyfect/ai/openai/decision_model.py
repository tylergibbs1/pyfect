"""OpenAI's Decisions API as a ``DecisionModel`` (Effect's
``OpenAiDecisionModel``)::

    program.pipe(fx.provide(decision_model.model("gpt-6-luna").layer))

A string state is sent as ``input`` unchanged, any other state as JSON;
with images, ``input`` is one user message with the state as text followed
by the images (bytes and base64 text as ``data:`` URLs; a remote URL fails
with ``InvalidUserInputError``, OpenAI takes inline images only).
Probability criteria are appended to the question's instructions, each
rating level is sent with its label and description, and structured
instructions and descriptions (and ``None``) are sent as JSON text.
Probabilities are rounded to two decimals, so their drift is accepted.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Literal, Never

import pyfect as fx
from pyfect import layer as L
from pyfect._core import Effect
from pyfect._url import Url
from pyfect.ai import _provider as P
from pyfect.ai import ai_error as E
from pyfect.ai import decision as D
from pyfect.ai import decision_model as DM
from pyfect.ai import model as M
from pyfect.ai.openai import _schema as W
from pyfect.ai.openai.client import OpenAiClient
from pyfect.ai.openai.client import Service as ClientService

type Model = Literal["gpt-6-luna"]
"""Model names (any other string is accepted too)."""


def _text(description: D.Description | None) -> str:
    return description if isinstance(description, str) else P.dumps(description)


def _question(name: str, decision: D.AnyDecision) -> W.DecisionQuestion:
    instructions = _text(decision.instructions)
    match decision:
        case D.Classify():
            choices: list[W.DecisionChoice] = [
                {"value": value, "description": _text(description)}
                for value, description in decision.criteria.items()
            ]
            return {
                "type": "choice",
                "name": name,
                "instructions": instructions,
                "choices": choices,
            }
        case D.Rate():
            levels: list[W.DecisionLevel] = [
                {"label": level.label, "description": _text(level.description)}
                for level in decision.criteria
            ]
            return {"type": "score", "name": name, "instructions": instructions, "levels": levels}
        case D.Probability():
            criteria = decision.criteria
            if criteria is not None:
                instructions = (
                    f"{instructions}\n\nfalse: {_text(criteria['false'])}"
                    f"\ntrue: {_text(criteria['true'])}"
                )
            return {"type": "predicate", "name": name, "instructions": instructions}


def _image_url(image: DM.Image) -> str:
    data = image.data
    if isinstance(data, Url):
        return str(data)
    encoded = data if isinstance(data, str) else base64.b64encode(data).decode()
    return f"data:{image.media_type};base64,{encoded}"


def _answers(
    response: W.CreateDecisionsResponse, decisions: Mapping[str, D.AnyDecision]
) -> dict[str, DM.ProviderAnswer]:
    """The answers by name; a refusal outranks a later answer of its name."""
    answers: dict[str, DM.ProviderAnswer] = {}
    for answer in response["answers"]:
        name = answer["name"]
        if isinstance(answers.get(name), DM.ProviderRefusalAnswer):
            continue
        match answer["type"]:
            case "refusal":
                answers[name] = DM.ProviderRefusalAnswer()
            case "choice":
                answers[name] = DM.ProviderClassifyAnswer(
                    answer["choice"],
                    {p["value"]: p["probability"] for p in answer["probabilities"]},
                    answer["confidence"],
                )
            case "score":
                decision = decisions.get(name)
                levels = decision.criteria if isinstance(decision, D.Rate) else ()
                probabilities = {
                    levels[p["value"]].label: p["probability"]
                    for p in answer["probabilities"]
                    if 0 <= p["value"] < len(levels)
                }
                answers[name] = DM.ProviderRateAnswer(
                    answer["score"], probabilities, answer["confidence"]
                )
            case "predicate":
                answers[name] = DM.ProviderProbabilityAnswer(answer["probability"])
    return answers


def _remote_url_error() -> E.AiError:
    return E.make(
        module="OpenAiDecisionModel",
        method="decide",
        reason=E.InvalidUserInputError(
            description="OpenAI decisions accept base64 or data URL images, not remote URLs"
        ),
    )


def make(*, model: Model | str) -> Effect[DM.Service, Never, OpenAiClient]:
    """A ``DecisionModel`` asking ``model`` through the ``OpenAiClient``."""

    def build(client: ClientService) -> Effect[DM.Service]:
        def decide(options: DM.ProviderOptions) -> Effect[DM.ProviderResponse, E.AiError]:
            images = options.images
            if images is not None and any(
                isinstance(image.data, Url) and image.data.protocol != "data:" for image in images
            ):
                return fx.fail(_remote_url_error())
            text = options.state if isinstance(options.state, str) else P.dumps(options.state)
            request: W.CreateDecisionsRequest = {
                "model": model,
                "input": text
                if images is None
                else [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": text},
                            *(
                                W.DecisionInputImage(type="input_image", image_url=_image_url(i))
                                for i in images
                            ),
                        ],
                    }
                ],
                "questions": [_question(name, d) for name, d in options.decisions.items()],
            }
            return client.create_decisions(request).map(
                lambda response: DM.ProviderResponse(
                    _answers(response, options.decisions),
                    response.get("usage", {}).get("input_tokens"),
                    response.get("usage", {}).get("output_tokens"),
                )
            )

        return DM.make(decide=decide, probability_precision=2, supports_images=True)

    return OpenAiClient().flat_map(build)


def layer(*, model: Model | str) -> L.Layer[DM.DecisionModel, Never, OpenAiClient]:
    """``DecisionModel`` over the ``OpenAiClient``."""
    return L.effect(DM.DecisionModel, make(model=model))


def model(model: Model | str) -> M.Model[DM.DecisionModel, OpenAiClient]:
    """The decision model as a ``Model`` (provider ``"openai"``)."""
    return M.make("openai", model, layer(model=model))


__all__ = ["Model", "layer", "make", "model"]
