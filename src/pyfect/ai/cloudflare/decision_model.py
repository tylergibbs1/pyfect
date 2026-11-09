"""Cloudflare's Clef as a ``DecisionModel`` (Effect's
``CloudflareDecisionModel``)::

    program.pipe(fx.provide(decision_model.model("clef-flash").layer)).pipe(
        fx.provide(client.layer_config())
    )

Each decision is sent as a named question (``choice``, ``score`` with the
levels' descriptions, ``noul``); a score's probabilities come back by level
index and are keyed by the levels' labels. Images are sent as base64 data
with their media type, or as ``data:`` URLs; a remote URL fails with
``InvalidUserInputError`` (Clef does not fetch it). Probabilities are
rounded to four decimals, so their drift is accepted.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Literal, Never

import pyfect as fx
from pyfect import layer as L
from pyfect._core import Effect
from pyfect._url import Url
from pyfect.ai import _noul_answers as N
from pyfect.ai import ai_error as E
from pyfect.ai import decision as D
from pyfect.ai import decision_model as DM
from pyfect.ai import model as M
from pyfect.ai.cloudflare import schema as W
from pyfect.ai.cloudflare.client import CloudflareClient
from pyfect.ai.cloudflare.client import Service as ClientService

type Model = Literal["clef", "clef-flash"]
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


def _image(image: DM.Image) -> W.Image:
    data = image.data
    if isinstance(data, Url):
        return str(data)
    encoded = data if isinstance(data, str) else base64.b64encode(data).decode()
    return {"content_type": image.media_type, "base64": encoded}


def _remote_url_error() -> E.AiError:
    return E.make(
        module="CloudflareDecisionModel",
        method="decide",
        reason=E.InvalidUserInputError(
            description="Cloudflare Clef accepts base64 or data URL images, not remote URLs"
        ),
    )


def make(*, model: Model | str) -> Effect[DM.Service, Never, CloudflareClient]:
    """A ``DecisionModel`` asking ``model`` through the ``CloudflareClient``."""

    def build(client: ClientService) -> Effect[DM.Service]:
        def decide(options: DM.ProviderOptions) -> Effect[DM.ProviderResponse, E.AiError]:
            images = options.images
            if images is not None and any(
                isinstance(image.data, Url) and image.data.protocol != "data:" for image in images
            ):
                return fx.fail(_remote_url_error())
            request: W.DecisionsRequest = {
                "model": model,
                "state": options.state,
                "questions": questions(options.decisions),
            }
            if images is not None:
                request["images"] = [_image(image) for image in images]
            return client.create_decisions(request).map(
                lambda response: DM.ProviderResponse(
                    N.provider_answers(options.decisions, response["answers"]),
                    response["usage"]["input_tokens"],
                    response["usage"]["output_tokens"],
                )
            )

        return DM.make(decide=decide, probability_precision=4, supports_images=True)

    return CloudflareClient().flat_map(build)


def layer(*, model: Model | str) -> L.Layer[DM.DecisionModel, Never, CloudflareClient]:
    """``DecisionModel`` over the ``CloudflareClient``."""
    return L.effect(DM.DecisionModel, make(model=model))


def model(model: Model | str) -> M.Model[DM.DecisionModel, CloudflareClient]:
    """The decision model as a ``Model`` (provider ``"cloudflare"``)."""
    return M.make("cloudflare", model, layer(model=model))


__all__ = ["Model", "layer", "make", "model", "questions"]
