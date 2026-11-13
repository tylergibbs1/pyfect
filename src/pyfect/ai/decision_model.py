"""The provider-neutral service answering decisions (Effect's
``DecisionModel``).

``decide(definition, input=...)`` encodes the input as JSON, sends every
decision of the definition in one provider call and checks the answers;
``decide_settled`` makes the same call but keeps each decision's outcome,
so valid answers survive beside missing, refused or invalid ones::

    response = yield from decision_model.decide(triage, input=ticket)
    response.answers[department].label

Providers build the service with ``make(decide=...)``; the provider
packages (``pyfect.ai.openai``, ``pyfect.ai.cloudflare``,
``pyfect.ai.typesafe``) each give a ``layer`` and a ``model``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, TypeVar, overload

import pyfect as fx
from pyfect import schema as S
from pyfect._core import Effect
from pyfect._ids import stringify, v4_bytes
from pyfect._json_value import JsonValue
from pyfect._url import Url
from pyfect._wire_codec import key, wire_codec
from pyfect.ai import _decision_answers as V
from pyfect.ai import ai_error as E
from pyfect.ai import decision as D
from pyfect.ai._decision_answers import (
    ProviderAnswer,
    ProviderBoundingBox,
    ProviderClassifyAnswer,
    ProviderLocateAnswer,
    ProviderProbabilityAnswer,
    ProviderRateAnswer,
    ProviderRefusalAnswer,
)
from pyfect.ai._decision_image import Image
from pyfect.context import Tag
from pyfect.http import url as url_
from pyfect.random import Random, RandomService
from pyfect.result import Ok

type Method = Literal["decide", "decideSettled"]


@dataclass(frozen=True)
class DecisionUsage:
    """Token usage the provider reported; ``None`` when it did not."""

    input_tokens: float | None = None
    output_tokens: float | None = None


DECISION_USAGE = wire_codec(
    DecisionUsage,
    [
        key("inputTokens", "input_tokens", S.Finite, optional=True),
        key("outputTokens", "output_tokens", S.Finite, optional=True),
    ],
    identifier="effect/ai/DecisionModel/DecisionUsage",
)


type Path = tuple[str | int, ...]


@dataclass(frozen=True)
class ProviderImage:
    """An image found in the encoded input (Effect's ``ProviderImage``):
    ``reference`` replaces it in the state, ``path`` is where it was first
    found, and ``image.data`` is base64 text or a URL."""

    reference: str
    path: Path
    image: Image


type Metadata = Mapping[str, JsonValue]
"""Provider metadata by provider name (a reported cost, ...)."""


@dataclass(frozen=True)
class DecideResponse:
    answers: D.Answers
    usage: DecisionUsage
    id: str | None = None
    """The provider's response id."""
    model_id: str | None = None
    """The model that answered (an alias may resolve to another)."""
    metadata: Metadata = field(default_factory=dict[str, JsonValue])


@dataclass(frozen=True)
class DecideSettledResponse:
    outcomes: D.Outcomes
    usage: DecisionUsage
    id: str | None = None
    model_id: str | None = None
    metadata: Metadata = field(default_factory=dict[str, JsonValue])


# Covariant: a provider that takes every kind of decision also takes the
# options of one without locate decisions.
DD_co = TypeVar("DD_co", bound=D.AnyDecision, covariant=True, default=D.AnyDecision)


@dataclass(frozen=True)
class ProviderOptions(Generic[DD_co]):
    """One provider call: the JSON ``state`` (each image replaced by its
    reference), every decision to answer and the images found in the input
    (``None`` when there are none). ``DD_co`` is the kinds of decision the
    provider receives: locate ones only with ``supports_locate``."""

    state: JsonValue
    decisions: Mapping[str, DD_co]
    images: tuple[ProviderImage, ...] | None = None


@dataclass(frozen=True)
class ProviderResponse:
    """The provider's answers by decision name (a decision it did not
    answer is left out), checked before the caller sees them."""

    answers: Mapping[str, ProviderAnswer]
    input_tokens: float | None = None
    output_tokens: float | None = None
    id: str | None = None
    model_id: str | None = None
    metadata: Metadata | None = None


type ProviderDecide[DD: D.AnyDecision = D.AnyDecision] = Callable[
    [ProviderOptions[DD]], Effect[ProviderResponse, E.AiError]
]


def _error(method: Method, reason: E.AnyReason) -> E.AiError:
    return E.make(module="DecisionModel", method=method, reason=reason)


def _invalid_input(method: Method, description: str) -> E.AiError:
    return _error(method, E.InvalidUserInputError(description=description))


def _provider_image(value: JsonValue) -> Image | None:
    if not isinstance(value, Mapping) or len(value) != 1:
        return None
    image = value.get(D.IMAGE_KEY)
    if not isinstance(image, Mapping) or len(image) != 2:
        return None
    media_type = image.get("mediaType")
    if not isinstance(media_type, str):
        return None
    data = image.get("base64")
    if isinstance(data, str):
        return Image(media_type, data)
    text = image.get("url")
    if isinstance(text, str):
        parsed = url_.from_string(text)
        if isinstance(parsed, Ok):
            return Image(media_type, parsed.value)
    return None


def _format_path(path: Path) -> str:
    return "".join(
        f"[{segment}]" if isinstance(segment, int) else segment if index == 0 else f".{segment}"
        for index, segment in enumerate(path)
    )


def _random_uuid(random: RandomService) -> str:
    data = bytes(math.floor(random.next_double_unsafe() * 256) for _ in range(16))
    return stringify(v4_bytes(data))


@dataclass(frozen=True)
class _Extracted:
    state: JsonValue
    images: tuple[ProviderImage, ...]
    paths: frozenset[str]


def _extract_images(state: JsonValue, random: RandomService) -> _Extracted:
    """``state`` with each encoded ``decision.Image`` replaced by a
    reference; equal images share one. ``paths`` holds every path where an
    image was found."""
    extraction = _ImageExtraction(random)
    walked = extraction.walk(state, ())
    return _Extracted(walked, tuple(extraction.images), frozenset(extraction.paths))


class _ImageExtraction:
    __slots__ = ("images", "paths", "random", "references")

    def __init__(self, random: RandomService) -> None:
        self.random = random
        self.images: list[ProviderImage] = []
        self.references: dict[tuple[str, str], str] = {}
        self.paths: set[str] = set()

    def walk(self, value: JsonValue, path: Path) -> JsonValue:
        image = _provider_image(value)
        if image is not None:
            self.paths.add(_format_path(path))
            data = image.data
            found = f"url:{url_.href(data)}" if isinstance(data, Url) else f"base64:{data!s}"
            reference = self.references.get((image.media_type, found))
            if reference is None:
                reference = self.references[image.media_type, found] = _random_uuid(self.random)
                self.images.append(ProviderImage(reference, path, image))
            return reference
        if isinstance(value, (list, tuple)):
            return [self.walk(item, (*path, index)) for index, item in enumerate(value)]
        if isinstance(value, Mapping):
            return {k: self.walk(item, (*path, k)) for k, item in value.items()}
        return value


def _require_answers(
    definition: D.Definition[Any, Any], outcomes: D.Outcomes
) -> Effect[D.Answers, E.AiError]:
    """The answers, or the failure ``decide`` reports: a refusal of any
    decision first, else the first unanswered decision."""
    answers: dict[str, D.AnyAnswer] = {}
    refused: list[str] = []
    first: D.Unanswered | None = None
    for name in outcomes:
        outcome = outcomes[name]
        if isinstance(outcome, Ok):
            answers[name] = outcome.value
        elif outcome.error.reason == "Refused":
            refused.append(f'"{name}"')
        elif first is None:
            first = outcome.error
    if refused:
        description = f"Provider refused to answer decisions {', '.join(refused)}"
        return fx.fail(_error("decide", E.ContentPolicyError(description=description)))
    if first is not None:
        return fx.fail(_error("decide", E.InvalidOutputError(description=first.description)))
    return fx.succeed(D.Answers(definition, answers))


@dataclass(frozen=True)
class Service:
    """Answers definitions; build one with ``make``."""

    _settle: Callable[
        [Method, D.Definition[Any, Any], Any],
        Effect[DecideSettledResponse, E.AiError, Any],
    ]

    def decide[A, R](
        self, definition: D.Definition[A, R], *, input: A
    ) -> Effect[DecideResponse, E.AiError, R]:
        """Every decision's answer; see the module's ``decide``."""

        def answered(settled: DecideSettledResponse) -> Effect[DecideResponse, E.AiError]:
            return _require_answers(definition, settled.outcomes).map(
                lambda answers: DecideResponse(
                    answers, settled.usage, settled.id, settled.model_id, settled.metadata
                )
            )

        return (
            self._settle("decide", definition, input)
            .flat_map(answered)
            .with_span("DecisionModel.decide")
        )

    def decide_settled[A, R](
        self, definition: D.Definition[A, R], *, input: A
    ) -> Effect[DecideSettledResponse, E.AiError, R]:
        """Each decision's outcome; see the module's ``decide_settled``."""
        return self._settle("decideSettled", definition, input).with_span(
            "DecisionModel.decideSettled"
        )


class DecisionModel(Tag[Service], key="effect/ai/DecisionModel"):
    """The current decision model."""


@overload
def make(
    *,
    decide: ProviderDecide[D.NonLocateDecision],
    probability_precision: int | None = None,
    supports_images: bool = False,
    supports_locate: Literal[False] = False,
) -> Effect[Service]: ...
@overload
def make(
    *,
    decide: ProviderDecide[D.AnyDecision],
    probability_precision: int | None = None,
    supports_images: bool = False,
    supports_locate: Literal[True],
) -> Effect[Service]: ...
def make(
    *,
    decide: ProviderDecide[Any],
    probability_precision: int | None = None,
    supports_images: bool = False,
    supports_locate: bool = False,
) -> Effect[Service]:
    """A decision model over a provider's ``decide`` call. Answers must
    cover every decision with its own labels; distributions must sum to 1
    within ``1e-6``, confidences and probabilities lie in ``[0, 1]``,
    ratings in ``[0, len(criteria) - 1]`` and boxes have edges in ``[0, 1]``
    that do not cross. A provider that rounds each probability to
    ``probability_precision`` decimals may drift from 1 by half a unit of
    the last place per label: such drift is accepted and rescaled.

    Once encoded, each ``decision.Image`` in the input is replaced with a
    reference string and the provider gets the images in ``images``; an
    input with images fails with ``InvalidUserInputError`` unless
    ``supports_images``, as does one its schema cannot encode. Locate
    decisions reach ``decide`` only with ``supports_locate``; otherwise a
    definition with one fails with ``InvalidUserInputError``, as does a
    locate decision whose path holds no image."""
    rounding_error = 0.0 if probability_precision is None else 0.5 * 10**-probability_precision

    def call(
        method: Method, extracted: _Extracted, decisions: Mapping[str, D.AnyDecision]
    ) -> Effect[ProviderResponse, E.AiError]:
        images = extracted.images
        if images and not supports_images:
            return fx.fail(_invalid_input(method, "This decision model does not accept images"))
        for name, decision in decisions.items():
            if not isinstance(decision, D.Locate):
                continue
            if not supports_locate:
                description = "This decision model does not support locate decisions"
                return fx.fail(_invalid_input(method, description))
            if decision.image not in extracted.paths:
                description = (
                    f'Locate decision "{name}" targets "{decision.image}", which holds no image'
                )
                return fx.fail(_invalid_input(method, description))
        options = ProviderOptions(extracted.state, decisions, images or None)
        return fx.suspend(lambda: decide(options))

    def settle(
        method: Method, definition: D.Definition[Any, Any], input: Any
    ) -> Effect[DecideSettledResponse, E.AiError, Any]:
        def settled(response: ProviderResponse) -> DecideSettledResponse:
            outcomes = V.settle(definition.decisions, response.answers, rounding_error)
            return DecideSettledResponse(
                D.Outcomes(definition, outcomes),
                DecisionUsage(response.input_tokens, response.output_tokens),
                response.id,
                response.model_id,
                {} if response.metadata is None else response.metadata,
            )

        encoded: Effect[JsonValue, Any, Any] = S.encode_effect(definition.json_input)(input)
        return (
            encoded.map_error(lambda error: _invalid_input(method, error.message))
            .flat_map(lambda state: Random().map(lambda random: _extract_images(state, random)))
            .flat_map(lambda extracted: call(method, extracted, definition.decisions))
            .map(settled)
        )

    return fx.sync(lambda: Service(settle))


def decide[A, R](
    definition: D.Definition[A, R], *, input: A
) -> Effect[DecideResponse, E.AiError, DecisionModel | R]:
    """Every decision's answer from the current ``DecisionModel``. The input
    is encoded with ``S.to_codec_json`` of the definition's schema, needing
    its encoding services. Fails with ``ContentPolicyError`` when the
    provider refused any decision, else with ``InvalidOutputError`` for the
    first unanswered decision in definition order."""
    return DecisionModel().flat_map(lambda model: model.decide(definition, input=input))


def decide_settled[A, R](
    definition: D.Definition[A, R], *, input: A
) -> Effect[DecideSettledResponse, E.AiError, DecisionModel | R]:
    """Each decision's ``Ok`` answer or ``Err(Unanswered)``; encoding and
    provider failures still fail the effect, and the usage covers the
    whole call."""
    return DecisionModel().flat_map(lambda model: model.decide_settled(definition, input=input))


__all__ = [
    "DECISION_USAGE",
    "DecideResponse",
    "DecideSettledResponse",
    "DecisionModel",
    "DecisionUsage",
    "Image",
    "Metadata",
    "Path",
    "ProviderAnswer",
    "ProviderBoundingBox",
    "ProviderClassifyAnswer",
    "ProviderDecide",
    "ProviderImage",
    "ProviderLocateAnswer",
    "ProviderOptions",
    "ProviderProbabilityAnswer",
    "ProviderRateAnswer",
    "ProviderRefusalAnswer",
    "ProviderResponse",
    "Service",
    "decide",
    "decide_settled",
    "make",
]
