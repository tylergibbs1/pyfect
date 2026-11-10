"""TypeSafe's System One as a ``DecisionModel`` (Effect's
``TypeSafeDecisionModel``)::

    program.pipe(fx.provide(decision_model.model("jev-latest").layer)).pipe(
        fx.provide(client.layer_config())
    )

Each decision is sent as a named question (``choice``, ``score`` with the
levels' descriptions, ``noul``, ``box``); a score's probabilities come back
by level index and are keyed by the levels' labels. Probabilities are
rounded to two decimals, so their drift is accepted.

Each ``decision.Image`` field is sent as a base64 asset keyed by the
reference that replaces it in ``state``, so instructions name an image by its
field path (`` `photo` ``); requests with images opt in to TypeSafe's preview
image support. Locate decisions become box questions whose instructions end
with the image path, and need Jev 1.14 (``"jev-preview"`` or
``"jev-1.14.0"``). Images must be PNG or JPEG, 256 to 1568 pixels on each
side: the API rejects other sizes rather than resizing, and ignores EXIF
orientation. Remote URLs fail with ``InvalidUserInputError``, as TypeSafe
does not fetch them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Literal, Never, cast

import pyfect as fx
from pyfect import layer as L
from pyfect._core import Effect
from pyfect._js import decode_uri_component, js_string
from pyfect._url import Url
from pyfect.ai import _noul_answers as N
from pyfect.ai import ai_error as E
from pyfect.ai import decision as D
from pyfect.ai import decision_model as DM
from pyfect.ai import model as M
from pyfect.ai.typesafe import schema as W
from pyfect.ai.typesafe.client import Service as ClientService
from pyfect.ai.typesafe.client import TypeSafeClient

type Model = Literal["jev-latest", "jev-preview", "jev-1.13.0", "jev-1.14.0"]
"""Model names (any other string is accepted too)."""

_DATA_URL = re.compile(r"^data:([^,;]*)[^,]*;base64,(.*)$", re.IGNORECASE | re.DOTALL)


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
        case D.Locate():
            instructions = f"{_text(decision.instructions)} in `{decision.image}`"
            return {"type": "box", "instructions": instructions}


def _text(instructions: D.Description) -> str:
    """JavaScript's template-literal ``${instructions}``."""
    return js_string(instructions)


def questions(decisions: Mapping[str, D.AnyDecision]) -> dict[str, W.Question]:
    """The request's questions, by decision name."""
    return {key: _question(decision) for key, decision in decisions.items()}


def _invalid_input(description: str) -> E.AiError:
    return E.make(
        module="TypeSafeDecisionModel",
        method="decide",
        reason=E.InvalidUserInputError(description=description),
    )


def _asset(image: DM.Image) -> W.ImageAsset | E.AiError:
    data, media_type = image.data, image.media_type
    if isinstance(data, Url):
        match = _DATA_URL.match(str(data).split("#", 1)[0])
        if match is None:
            return _invalid_input(
                "TypeSafe accepts bytes, base64 strings, or base64 data URLs; "
                "it does not fetch URLs"
            )
        media_type = match[1] or media_type
        try:
            data = decode_uri_component(match[2])
        except ValueError:
            return _invalid_input("TypeSafe image data URLs must contain valid percent-encoding")
    text = f"{data!s}"
    match media_type.lower():
        case "image/png":
            return {"type": "image", "format": "png", "data_base64": text}
        case "image/jpeg" | "image/jpg":
            return {"type": "image", "format": "jpg", "data_base64": text}
        case _:
            return _invalid_input(f"TypeSafe accepts PNG or JPEG images, not {media_type}")


def _box_answers(
    decisions: Mapping[str, D.AnyDecision], answers: Mapping[str, W.Answer]
) -> dict[str, DM.ProviderAnswer]:
    found: dict[str, DM.ProviderAnswer] = {}
    for key in decisions:
        answer = answers.get(key)
        if answer is not None and answer["type"] == "box":
            box = answer["box"]
            found[key] = {
                "_tag": "Locate",
                "box": {
                    "left": box["left"],
                    "top": box["top"],
                    "right": box["right"],
                    "bottom": box["bottom"],
                },
                "confidence": answer["confidence"],
            }
    return found


def make(*, model: Model | str) -> Effect[DM.Service, Never, TypeSafeClient]:
    """A ``DecisionModel`` asking ``model`` through the ``TypeSafeClient``."""

    def build(client: ClientService) -> Effect[DM.Service]:
        def decide(options: DM.ProviderOptions) -> Effect[DM.ProviderResponse, E.AiError]:
            request: W.SystemOneRequest = {
                "model": model,
                "state": options.state,
                "questions": questions(options.decisions),
            }
            if options.images is not None:
                assets: dict[str, W.ImageAsset] = {}
                for found in options.images:
                    asset = _asset(found.image)
                    if isinstance(asset, E.AiError):
                        return fx.fail(asset)
                    assets[found.reference] = asset
                request["assets"] = assets

            def answered(response: W.SystemOneResponse) -> DM.ProviderResponse:
                usage = response.get("usage", {})
                text_answers = {
                    key: answer
                    for key, answer in response["answers"].items()
                    if answer["type"] != "box"
                }
                return DM.ProviderResponse(
                    {
                        **N.provider_answers(
                            options.decisions, cast("Mapping[str, N.Answer]", text_answers)
                        ),
                        **_box_answers(options.decisions, response["answers"]),
                    },
                    usage.get("input_tokens"),
                    usage.get("output_tokens"),
                )

            return client.system_one(request).map(answered)

        return DM.make(
            decide=decide, probability_precision=2, supports_images=True, supports_locate=True
        )

    return TypeSafeClient().flat_map(build)


def layer(*, model: Model | str) -> L.Layer[DM.DecisionModel, Never, TypeSafeClient]:
    """``DecisionModel`` over the ``TypeSafeClient``."""
    return L.effect(DM.DecisionModel, make(model=model))


def model(model: Model | str) -> M.Model[DM.DecisionModel, TypeSafeClient]:
    """The decision model as a ``Model`` (provider ``"typesafe"``)."""
    return M.make("typesafe", model, layer(model=model))


__all__ = ["Model", "layer", "make", "model", "questions"]
