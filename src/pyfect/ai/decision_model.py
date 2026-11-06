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

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import pyfect as fx
from pyfect import schema as S
from pyfect._core import Effect
from pyfect._json_value import JsonValue
from pyfect._url import Url
from pyfect._wire_codec import key, wire_codec
from pyfect.ai import _decision_answers as V
from pyfect.ai import ai_error as E
from pyfect.ai import decision as D
from pyfect.ai._decision_answers import (
    ProviderAnswer,
    ProviderClassifyAnswer,
    ProviderProbabilityAnswer,
    ProviderRateAnswer,
    ProviderRefusalAnswer,
)
from pyfect.context import Tag
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


@dataclass(frozen=True)
class Image:
    """An image sent with the input: base64 text, bytes or a URL."""

    media_type: str
    data: str | bytes | Url


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


@dataclass(frozen=True)
class ProviderOptions:
    """One provider call: the JSON ``state``, every decision to answer and
    the images (``None`` when there are none)."""

    state: JsonValue
    decisions: Mapping[str, D.AnyDecision]
    images: tuple[Image, ...] | None = None


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


type ProviderDecide = Callable[[ProviderOptions], Effect[ProviderResponse, E.AiError]]


def _error(method: Method, reason: E.AnyReason) -> E.AiError:
    return E.make(module="DecisionModel", method=method, reason=reason)


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
        [Method, D.Definition[Any, Any], Any, Sequence[Image] | None],
        Effect[DecideSettledResponse, E.AiError, Any],
    ]

    def decide[A, R](
        self, definition: D.Definition[A, R], *, input: A, images: Sequence[Image] | None = None
    ) -> Effect[DecideResponse, E.AiError, R]:
        """Every decision's answer; see the module's ``decide``."""

        def answered(settled: DecideSettledResponse) -> Effect[DecideResponse, E.AiError]:
            return _require_answers(definition, settled.outcomes).map(
                lambda answers: DecideResponse(
                    answers, settled.usage, settled.id, settled.model_id, settled.metadata
                )
            )

        return (
            self._settle("decide", definition, input, images)
            .flat_map(answered)
            .with_span("DecisionModel.decide")
        )

    def decide_settled[A, R](
        self, definition: D.Definition[A, R], *, input: A, images: Sequence[Image] | None = None
    ) -> Effect[DecideSettledResponse, E.AiError, R]:
        """Each decision's outcome; see the module's ``decide_settled``."""
        return self._settle("decideSettled", definition, input, images).with_span(
            "DecisionModel.decideSettled"
        )


class DecisionModel(Tag[Service], key="effect/ai/DecisionModel"):
    """The current decision model."""


def make(
    *,
    decide: ProviderDecide,
    probability_precision: int | None = None,
    supports_images: bool = False,
) -> Effect[Service]:
    """A decision model over a provider's ``decide`` call. Answers must
    cover every decision with its own labels; distributions must sum to 1
    within ``1e-6``, confidences and probabilities lie in ``[0, 1]`` and
    ratings in ``[0, len(criteria) - 1]``. A provider that rounds each
    probability to ``probability_precision`` decimals may drift from 1 by
    half a unit of the last place per label: such drift is accepted and
    rescaled. Images fail with ``InvalidUserInputError`` unless
    ``supports_images``; so does an input its schema cannot encode."""
    rounding_error = 0.0 if probability_precision is None else 0.5 * 10**-probability_precision

    def call(
        method: Method, state: JsonValue, decisions: Mapping[str, D.AnyDecision], images: Any
    ) -> Effect[ProviderResponse, E.AiError]:
        found = tuple(images) if images else None
        if found is not None and not supports_images:
            description = "This decision model does not accept images"
            return fx.fail(_error(method, E.InvalidUserInputError(description=description)))
        return fx.suspend(lambda: decide(ProviderOptions(state, decisions, found)))

    def settle(
        method: Method, definition: D.Definition[Any, Any], input: Any, images: Any
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
            encoded.map_error(
                lambda error: _error(method, E.InvalidUserInputError(description=error.message))
            )
            .flat_map(lambda state: call(method, state, definition.decisions, images))
            .map(settled)
        )

    return fx.sync(lambda: Service(settle))


def decide[A, R](
    definition: D.Definition[A, R], *, input: A, images: Sequence[Image] | None = None
) -> Effect[DecideResponse, E.AiError, DecisionModel | R]:
    """Every decision's answer from the current ``DecisionModel``. The input
    is encoded with ``S.to_codec_json`` of the definition's schema, needing
    its encoding services. Fails with ``ContentPolicyError`` when the
    provider refused any decision, else with ``InvalidOutputError`` for the
    first unanswered decision in definition order."""
    return DecisionModel().flat_map(
        lambda model: model.decide(definition, input=input, images=images)
    )


def decide_settled[A, R](
    definition: D.Definition[A, R], *, input: A, images: Sequence[Image] | None = None
) -> Effect[DecideSettledResponse, E.AiError, DecisionModel | R]:
    """Each decision's ``Ok`` answer or ``Err(Unanswered)``; encoding and
    provider failures still fail the effect, and the usage covers the
    whole call."""
    return DecisionModel().flat_map(
        lambda model: model.decide_settled(definition, input=input, images=images)
    )


__all__ = [
    "DECISION_USAGE",
    "DecideResponse",
    "DecideSettledResponse",
    "DecisionModel",
    "DecisionUsage",
    "Image",
    "Metadata",
    "ProviderAnswer",
    "ProviderClassifyAnswer",
    "ProviderDecide",
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
