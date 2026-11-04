"""Ports of Effect's ``test/ai/DecisionModel.test.ts``. Each docstring is the
Effect test title (with its ``describe``); a title Effect writes in a loop is
one parametrized test.

Python mappings: ``answers.department`` is ``answers[department]`` (the
decision itself, typed) or ``answers["department"]``; a structured rate level
``{label, description}`` is an entry of a mapping criteria
(``{"low": "low", "high": {"impact": "outage"}}``); a provider rate answer has
no ``label`` field (the label is the most probable level's), so "rate derives
the argmax label without a provider label" and "rate ignores a conflicting
provider label" check that the label comes from the distribution; provider
answers are dataclasses, so "extra provider keys never leak into answers" can
only add extra decision names and extra probability labels. ``undefined`` is
``None``: an optional key is absent or holds ``None`` (``S.NullOr``), so "JSON
encoding distinguishes absent optional fields from explicit undefined" checks
an absent key and an explicit ``None``. The ``__proto__`` / ``constructor`` /
``toString`` titles check that such keys are ordinary keys, in order.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, NotRequired, TypedDict, TypeIs

import pytest

import pyfect as fx
from pyfect import layer as L
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai import decision as D
from pyfect.ai import decision_model as DM
from pyfect.ai import model as M
from pyfect.context import Tag
from pyfect.http import url
from pyfect.result import Err, Ok
from pyfect.schema import getter as G
from pyfect.schema import transformation as Tr


class Ticket(TypedDict):
    subject: str
    priority: float


TICKET = S.Struct(Ticket, priority=S.FiniteFromString)

department = D.classify(
    instructions="Which team should handle this",
    criteria={"billing": "payments", "technical": "bugs", "sales": "pricing"},
)
frustration = D.rate(instructions="How frustrated", criteria=["calm", "frustrated", "angry"])
urgent = D.probability(
    instructions="The message is time-sensitive",
    criteria={"false": "No time pressure", "true": "Needs action now"},
)
DECISIONS: dict[str, D.AnyDecision] = {
    "department": department,
    "frustration": frustration,
    "urgent": urgent,
}
TRIAGE = D.make(input=TICKET, decisions=DECISIONS)

ticket: Ticket = {"subject": "Card was charged twice", "priority": 3}

EXPECTED = {
    "department": D.ClassifyAnswer(
        "billing", {"billing": 0.8, "technical": 0.15, "sales": 0.05}, 0.8
    ),
    "frustration": D.RateAnswer(
        1.4, "frustrated", {"calm": 0.1, "frustrated": 0.5, "angry": 0.4}, 0.5
    ),
    "urgent": D.ProbabilityAnswer(0.9),
}

TRIAGE_ANSWERS: dict[str, DM.ProviderAnswer] = {
    "department": DM.ProviderClassifyAnswer(
        "billing", {"billing": 0.8, "technical": 0.15, "sales": 0.05}, 0.8
    ),
    "frustration": DM.ProviderRateAnswer(1.4, {"calm": 0.1, "frustrated": 0.5, "angry": 0.4}, 0.5),
    "urgent": DM.ProviderProbabilityAnswer(0.9),
}

type Decide = Callable[[DM.ProviderOptions], fx.Effect[DM.ProviderResponse, E.AiError]]


def make_layer(decide: Decide, **options: Any) -> fx.Layer[DM.DecisionModel]:
    return L.effect(DM.DecisionModel, DM.make(decide=decide, **options))


def succeed_with(
    answers: Mapping[str, DM.ProviderAnswer],
    input_tokens: float | None = None,
    output_tokens: float | None = None,
) -> fx.Layer[DM.DecisionModel]:
    return make_layer(
        lambda _: fx.succeed(DM.ProviderResponse(answers, input_tokens, output_tokens))
    )


def recording(
    calls: list[DM.ProviderOptions], answers: Mapping[str, DM.ProviderAnswer] = TRIAGE_ANSWERS
) -> fx.Layer[DM.DecisionModel]:
    def decide(options: DM.ProviderOptions) -> fx.Effect[DM.ProviderResponse, E.AiError]:
        calls.append(options)
        return fx.succeed(DM.ProviderResponse(answers))

    return make_layer(decide)


def failure_of(effect: fx.Effect[Any, E.AiError, Any]) -> fx.Effect[E.AiError, Any, Any]:
    return effect.flip()


def unanswered(outcome: D.Outcome[Any]) -> D.Unanswered:
    assert isinstance(outcome, Err)
    return outcome.error


class Redactor(Tag[Callable[[str], str]], key="Redactor"):
    pass


REDACTED_STRING = S.String.pipe(
    S.decode_to(
        S.String,
        Tr.Transformation(
            G.passthrough(),
            G.transform_effect(lambda value, _: Redactor().map(lambda redact: redact(value))),
        ),
    )
)


# Decision ---------------------------------------------------------------------------------


def test_make_keeps_input_and_decisions():
    """Decision / make keeps the input schema and decisions"""
    assert TRIAGE.input is TICKET
    assert list(TRIAGE.decisions) == ["department", "frustration", "urgent"]
    assert isinstance(TRIAGE.decisions["department"], D.Classify)
    assert isinstance(TRIAGE.decisions["frustration"], D.Rate)
    assert isinstance(TRIAGE.decisions["urgent"], D.Probability)


def test_constructors_keep_instructions_and_criteria():
    """Decision / constructors keep instructions and criteria"""
    assert department.instructions == "Which team should handle this"
    assert department.criteria == {"billing": "payments", "technical": "bugs", "sales": "pricing"}
    assert frustration.criteria == (
        D.Level("calm", "calm"),
        D.Level("frustrated", "frustrated"),
        D.Level("angry", "angry"),
    )
    assert urgent.criteria == {"false": "No time pressure", "true": "Needs action now"}


def test_probability_omitted_criteria():
    """Decision / probability accepts omitted criteria"""
    decision = D.probability(instructions="Needs action now")
    assert decision.tag == "Probability"
    assert decision.instructions == "Needs action now"
    assert decision.criteria is None


def test_probability_preserves_criteria():
    """Decision / probability preserves explicit criteria, including empty descriptions"""
    criteria: D.ProbabilityCriteria = {"false": "", "true": "Needs action now"}
    decision = D.probability(instructions="Is urgent", criteria=criteria)
    assert decision.instructions == "Is urgent"
    assert decision.criteria is criteria


def test_make_fails_on_empty_decisions():
    """Decision / make fails on empty decisions"""
    with pytest.raises(ValueError, match="must not be empty"):
        D.make(input=S.String, decisions={})


def test_rate_fails_with_one_criterion():
    """Decision / rate fails with fewer than two criteria"""
    with pytest.raises(ValueError, match="at least two levels"):
        D.rate(instructions="How much", criteria=["only"])


def test_make_rejects_a_decision_under_two_names():
    """A decision object under two names would make ``answers[decision]``
    ambiguous (Python only: Effect looks answers up by name)."""
    with pytest.raises(ValueError, match="one name"):
        D.make(input=S.String, decisions={"a": urgent, "b": urgent})


# DecisionModel ----------------------------------------------------------------------------


@testing.effect
def test_probability_without_criteria():
    """DecisionModel / probability without criteria reaches the provider and returns an answer"""
    needs = D.probability(instructions="Needs action now")
    definition = D.make(input=S.String, decisions={"urgent": needs})
    calls: list[DM.ProviderOptions] = []
    response = yield from DM.decide(definition, input="Help now").pipe(
        fx.provide(recording(calls, {"urgent": TRIAGE_ANSWERS["urgent"]}))
    )
    assert len(calls) == 1
    assert calls[0].state == "Help now"
    assert calls[0].decisions is definition.decisions
    assert needs.criteria is None
    assert dict(response.answers) == {"urgent": D.ProbabilityAnswer(0.9)}


KEYS = ["__proto__", "constructor", "toString"]


@pytest.mark.parametrize("key", KEYS)
@testing.effect
def test_rate_probability_key(key: str):
    """DecisionModel / preserves the own enumerable rate probability __proto__ / constructor /
    toString"""
    intensity = D.rate(instructions="How intense", criteria=["low", key, "high"])
    definition = D.make(input=S.String, decisions={"intensity": intensity})
    response = yield from DM.decide(definition, input="Help").pipe(
        fx.provide(
            succeed_with(
                {"intensity": DM.ProviderRateAnswer(1.1, {"low": 0.1, key: 0.7, "high": 0.2})}
            )
        )
    )
    answer = response.answers[intensity]
    assert list(answer.probabilities) == ["low", key, "high"]
    assert answer.probabilities == {"low": 0.1, key: 0.7, "high": 0.2}
    assert answer.label == key
    assert answer.rating == 1.1


@pytest.mark.parametrize("key", KEYS)
@testing.effect
def test_answer_key(key: str):
    """DecisionModel / preserves the own enumerable answer key __proto__ / constructor /
    toString"""
    decision = D.probability(
        instructions="Needs action now", criteria={"false": "No", "true": "Yes"}
    )
    definition = D.make(input=S.String, decisions={key: decision})
    response = yield from DM.decide(definition, input="Help").pipe(
        fx.provide(succeed_with({key: DM.ProviderProbabilityAnswer(0.75)}))
    )
    assert list(response.answers) == [key]
    assert response.answers[key] == D.ProbabilityAnswer(0.75)


@pytest.mark.parametrize("key", KEYS)
@testing.effect
def test_classification_probability_key(key: str):
    """DecisionModel / preserves the own enumerable classification probability __proto__ /
    constructor / toString"""
    category = D.classify(
        instructions="Choose a category",
        criteria={key: "Special category", "ordinary": "Ordinary category"},
    )
    definition = D.make(input=S.String, decisions={"category": category})
    response = yield from DM.decide(definition, input="Help").pipe(
        fx.provide(
            succeed_with(
                {"category": DM.ProviderClassifyAnswer(key, {key: 0.75, "ordinary": 0.25})}
            )
        )
    )
    probabilities = response.answers[category].probabilities
    assert list(probabilities) == [key, "ordinary"]
    assert probabilities[key] == 0.75
    assert probabilities["ordinary"] == 0.25
    assert response.answers[category].label == key


@testing.effect
def test_usage_round_trip():
    """DecisionModel / round trips usage with undefined tokens through JSON"""
    usage = DM.DecisionUsage(None, None)
    encoded = yield from S.encode_effect(DM.DECISION_USAGE)(usage)
    data = json.loads(json.dumps(encoded))
    decoded = yield from S.decode_unknown_effect(DM.DECISION_USAGE)(data)
    assert data == {}
    assert decoded == DM.DecisionUsage()


@testing.effect
def test_decide_returns_answers_and_usage():
    """DecisionModel / decide returns answers keyed by decision with usage"""
    response = yield from DM.decide(TRIAGE, input=ticket).pipe(
        fx.provide(succeed_with(TRIAGE_ANSWERS, input_tokens=12))
    )
    answers = response.answers
    assert sorted(answers) == ["department", "frustration", "urgent"]
    assert answers[department].label == "billing"
    assert answers[department].probabilities == {"billing": 0.8, "technical": 0.15, "sales": 0.05}
    assert answers[department].confidence == 0.8
    assert answers[frustration].rating == 1.4
    assert answers[frustration].label == "frustrated"
    assert answers[frustration].probabilities == {"calm": 0.1, "frustrated": 0.5, "angry": 0.4}
    assert answers[frustration].confidence == 0.5
    assert answers[urgent] == D.ProbabilityAnswer(0.9)
    assert response.usage.input_tokens == 12
    assert response.usage.output_tokens is None
    assert response.metadata == {}


@testing.effect
def test_decide_returns_ids_and_metadata():
    """DecisionModel / decide returns the provider's response id, model id and metadata"""
    layer = make_layer(
        lambda _: fx.succeed(
            DM.ProviderResponse(
                TRIAGE_ANSWERS,
                12,
                3,
                id="decision-1",
                model_id="provider/model-2026",
                metadata={"provider": {"cost": 0.002}},
            )
        )
    )
    response = yield from DM.decide(TRIAGE, input=ticket).pipe(fx.provide(layer))
    assert response.id == "decision-1"
    assert response.model_id == "provider/model-2026"
    assert response.metadata == {"provider": {"cost": 0.002}}


@testing.effect
def test_distributions_without_confidence():
    """DecisionModel / classify and rate retain distributions when the provider omits
    confidence"""
    answers = {
        "department": DM.ProviderClassifyAnswer(
            "billing", {"billing": 0.8, "technical": 0.15, "sales": 0.05}
        ),
        "frustration": DM.ProviderRateAnswer(1.4, {"calm": 0.1, "frustrated": 0.5, "angry": 0.4}),
        "urgent": TRIAGE_ANSWERS["urgent"],
    }
    response = yield from DM.decide(TRIAGE, input=ticket).pipe(fx.provide(succeed_with(answers)))
    assert response.answers[department] == D.ClassifyAnswer(
        "billing", {"billing": 0.8, "technical": 0.15, "sales": 0.05}
    )
    assert response.answers[frustration] == D.RateAnswer(
        1.4, "frustrated", {"calm": 0.1, "frustrated": 0.5, "angry": 0.4}
    )


@testing.effect
def test_service_decide():
    """DecisionModel / the service exposes the same decide operation"""
    model = yield from DM.DecisionModel().pipe(fx.provide(succeed_with(TRIAGE_ANSWERS)))
    response = yield from model.decide(TRIAGE, input=ticket)
    assert response.answers[department].label == "billing"
    assert response.answers[urgent].probability == 0.9


@testing.effect
def test_provider_receives_state_and_decisions():
    """DecisionModel / the provider receives the encoded input as state and every decision in
    one call"""
    calls: list[DM.ProviderOptions] = []
    yield from DM.decide(TRIAGE, input=ticket).pipe(fx.provide(recording(calls)))
    assert len(calls) == 1
    assert calls[0].state == {"subject": "Card was charged twice", "priority": "3"}
    assert calls[0].decisions is TRIAGE.decisions


@testing.effect
def test_forwards_images():
    """DecisionModel / forwards images to an image-capable provider"""
    images = [
        DM.Image("image/png", bytes([137, 80, 78, 71])),
        DM.Image("image/jpeg", "/9j/4AAQ"),
        DM.Image("image/webp", url.parse("https://example.com/image.webp")),
    ]

    def decide(options: DM.ProviderOptions) -> fx.Effect[DM.ProviderResponse, E.AiError]:
        assert options.images == tuple(images)
        return fx.succeed(DM.ProviderResponse(TRIAGE_ANSWERS))

    response = yield from DM.decide(TRIAGE, input=ticket, images=images).pipe(
        fx.provide(make_layer(decide, supports_images=True))
    )
    assert response.answers[urgent].probability == 0.9


@pytest.mark.parametrize("supports_images", [None, False])
@testing.effect
def test_rejects_images(supports_images: bool | None):
    """DecisionModel / rejects images with InvalidUserInputError when supportsImages is
    undefined / false"""
    options = {} if supports_images is None else {"supports_images": supports_images}
    layer = make_layer(
        lambda _: fx.die(RuntimeError("A text-only provider must not be called with images")),
        **options,
    )
    error = yield from failure_of(
        DM.decide(TRIAGE, input=ticket, images=[DM.Image("image/png", "iVBORw0KGgo=")])
    ).pipe(fx.provide(layer))
    assert isinstance(error, E.AiError)
    assert isinstance(error.reason, E.InvalidUserInputError)


@pytest.mark.parametrize("images", [None, []])
@testing.effect
def test_allows_no_images(images: list[DM.Image] | None):
    """DecisionModel / allows omitted / empty images for a text-only provider"""

    def decide(options: DM.ProviderOptions) -> fx.Effect[DM.ProviderResponse, E.AiError]:
        assert options.images is None
        return fx.succeed(DM.ProviderResponse(TRIAGE_ANSWERS))

    response = yield from DM.decide(TRIAGE, input=ticket, images=images).pipe(
        fx.provide(make_layer(decide))
    )
    assert response.answers[urgent].probability == 0.9


@testing.effect
def test_string_state():
    """DecisionModel / a string input is passed to the provider as a string state"""
    tone = D.classify(
        instructions="Tone of the message", criteria={"positive": "happy", "negative": "unhappy"}
    )
    sentiment = D.make(input=S.String, decisions={"tone": tone})
    calls: list[DM.ProviderOptions] = []
    answers = {
        "tone": DM.ProviderClassifyAnswer("positive", {"positive": 0.95, "negative": 0.05}, 0.95)
    }
    response = yield from DM.decide(sentiment, input="I love this").pipe(
        fx.provide(recording(calls, answers))
    )
    assert [call.state for call in calls] == ["I love this"]
    assert response.answers[tone].label == "positive"


class Nested(TypedDict):
    amount: int
    createdAt: datetime
    priority: float
    values: tuple[int, ...]


@testing.effect
def test_nested_json_codecs():
    """DecisionModel / derives JSON codecs for nested input before calling the provider"""
    definition = D.make(
        input=S.Struct(
            Nested,
            amount=S.BigInt,
            createdAt=S.DateTimeUtc,
            priority=S.FiniteFromString,
            values=S.Array(S.BigInt),
        ),
        decisions=DECISIONS,
    )
    calls: list[DM.ProviderOptions] = []
    nested: Nested = {
        "amount": 42,
        "createdAt": datetime(2026, 1, 1, tzinfo=UTC),
        "priority": 3,
        "values": (1, 2),
    }
    yield from DM.decide(definition, input=nested).pipe(fx.provide(recording(calls)))
    assert json.loads(json.dumps(calls[0].state)) == {
        "amount": "42",
        "createdAt": "2026-01-01T00:00:00.000Z",
        "priority": "3",
        "values": ["1", "2"],
    }


class Note(TypedDict):
    note: NotRequired[str | None]


@testing.effect
def test_absent_and_explicit_optional():
    """DecisionModel / JSON encoding distinguishes absent optional fields from explicit
    undefined"""
    definition = D.make(input=S.Struct(Note, note=S.NullOr(S.String)), decisions=DECISIONS)
    calls: list[DM.ProviderOptions] = []
    layer = recording(calls)
    yield from DM.decide(definition, input={}).pipe(fx.provide(layer))
    yield from DM.decide(definition, input={"note": None}).pipe(fx.provide(layer))
    assert [call.state for call in calls] == [{}, {"note": None}]


def _is_datetime(value: object) -> TypeIs[datetime]:
    return isinstance(value, datetime)


@testing.effect
def test_json_codec_failure():
    """DecisionModel / JSON codec encoding failures become InvalidUserInputError before the
    provider runs"""
    calls: list[DM.ProviderOptions] = []
    definition = D.make(input=S.declare(_is_datetime), decisions=DECISIONS)
    error = yield from failure_of(
        DM.decide(definition, input=datetime(2026, 1, 1, tzinfo=UTC))
    ).pipe(fx.provide(recording(calls)))
    assert calls == []
    assert isinstance(error, E.AiError)
    assert isinstance(error.reason, E.InvalidUserInputError)


class Body(TypedDict):
    body: str


@testing.effect
def test_encoding_services():
    """DecisionModel / input encoding services are resolved from the environment"""
    needs = D.probability(instructions="Needs action now", criteria={"false": "No", "true": "Yes"})
    redacted = D.make(input=S.Struct(Body, body=REDACTED_STRING), decisions={"urgent": needs})
    calls: list[DM.ProviderOptions] = []
    yield from (
        DM.decide(redacted, input={"body": "call me at 555-0100"})
        .pipe(fx.provide(recording(calls, {"urgent": DM.ProviderProbabilityAnswer(0.5)})))
        .pipe(
            fx.provide_service(Redactor, lambda value: re.sub(r"\d{3}-\d{4}", "[redacted]", value))
        )
    )
    assert [call.state for call in calls] == [{"body": "call me at [redacted]"}]


@testing.effect
def test_input_encoding_failure():
    """DecisionModel / input encoding failures surface as AiError"""
    calls: list[DM.ProviderOptions] = []
    needs = D.probability(instructions="Needs action now", criteria={"false": "No", "true": "Yes"})
    strict = D.make(input=S.String.check(S.is_min_length(3)), decisions={"urgent": needs})
    error = yield from failure_of(DM.decide(strict, input="hi")).pipe(fx.provide(recording(calls)))
    assert calls == []
    assert isinstance(error, E.AiError)
    assert isinstance(error.reason, E.InvalidUserInputError)


@testing.effect
def test_provider_error_propagates():
    """DecisionModel / provider AiError propagates through decide and decideSettled"""
    error = E.make(
        module="DecisionModelTest", method="decide", reason=E.UnknownError(description="boom")
    )
    layer = make_layer(lambda _: fx.fail(error))
    assert (yield from failure_of(DM.decide(TRIAGE, input=ticket)).pipe(fx.provide(layer))) is error
    settled = DM.decide_settled(TRIAGE, input=ticket)
    assert (yield from failure_of(settled).pipe(fx.provide(layer))) is error


def _decide_error(answers: Mapping[str, DM.ProviderAnswer]) -> fx.Effect[E.AiError, Any, Any]:
    return failure_of(DM.decide(TRIAGE, input=ticket)).pipe(fx.provide(succeed_with(answers)))


@testing.effect
def test_missing_answer():
    """DecisionModel / decide fails with InvalidOutputError when an answer is missing"""
    answers = {k: TRIAGE_ANSWERS[k] for k in ("department", "frustration")}
    error = yield from _decide_error(answers)
    assert isinstance(error.reason, E.InvalidOutputError)


@testing.effect
def test_unknown_label():
    """DecisionModel / decide fails with InvalidOutputError when a classify label is not a
    criteria key"""
    answer = DM.ProviderClassifyAnswer("legal", {"billing": 0.8, "technical": 0.15, "sales": 0.05})
    error = yield from _decide_error({**TRIAGE_ANSWERS, "department": answer})
    assert isinstance(error.reason, E.InvalidOutputError)


@testing.effect
def test_incomplete_classify_distribution():
    """DecisionModel / decide fails with InvalidOutputError when a classify distribution is
    incomplete"""
    answer = DM.ProviderClassifyAnswer("billing", {"billing": 1}, 0.8)
    error = yield from _decide_error({**TRIAGE_ANSWERS, "department": answer})
    assert isinstance(error.reason, E.InvalidOutputError)


@testing.effect
def test_incomplete_rate_distribution():
    """DecisionModel / decide fails with InvalidOutputError when a rate distribution is
    incomplete"""
    answer = DM.ProviderRateAnswer(1.4, {"calm": 0.5, "angry": 0.5}, 0.5)
    error = yield from _decide_error({**TRIAGE_ANSWERS, "frustration": answer})
    assert isinstance(error.reason, E.InvalidOutputError)


@testing.effect
def test_probability_outside_unit():
    """DecisionModel / decide fails with InvalidOutputError when a probability is outside
    [0, 1]"""
    answer = DM.ProviderProbabilityAnswer(1.5)
    error = yield from _decide_error({**TRIAGE_ANSWERS, "urgent": answer})
    assert isinstance(error.reason, E.InvalidOutputError)


@testing.effect
def test_settled_keeps_valid_answers():
    """DecisionModel / decideSettled keeps valid answers beside refused and missing decisions"""
    answers = {
        "department": DM.ProviderRefusalAnswer(),
        "frustration": TRIAGE_ANSWERS["frustration"],
    }
    response = yield from DM.decide_settled(TRIAGE, input=ticket).pipe(
        fx.provide(succeed_with(answers, input_tokens=12))
    )
    outcomes = response.outcomes
    assert sorted(outcomes) == ["department", "frustration", "urgent"]
    assert outcomes[frustration] == Ok(EXPECTED["frustration"])
    assert unanswered(outcomes[department]).reason == "Refused"
    assert unanswered(outcomes[urgent]) == D.Unanswered(
        "Missing", 'Provider returned no answer for decision "urgent"'
    )
    assert response.usage.input_tokens == 12


@pytest.mark.parametrize(
    ("key", "answer", "reason", "description"),
    [
        pytest.param(
            "department",
            DM.ProviderClassifyAnswer("legal"),
            "Invalid",
            'Provider returned an unknown label for decision "department"',
            id="an unknown label is Invalid even without probabilities",
        ),
        pytest.param(
            "department",
            DM.ProviderClassifyAnswer("billing"),
            "NoDistribution",
            'Provider returned no probabilities for decision "department"',
            id="a classify answer without probabilities is NoDistribution",
        ),
        pytest.param(
            "frustration",
            DM.ProviderRateAnswer(1),
            "NoDistribution",
            'Provider returned no probabilities for decision "frustration"',
            id="a rate answer without probabilities is NoDistribution",
        ),
        pytest.param(
            "department",
            DM.ProviderClassifyAnswer("billing", {"billing": 1}),
            "Invalid",
            'Provider returned no probability for label "technical" of decision "department"',
            id="an incomplete distribution is Invalid",
        ),
    ],
)
@testing.effect
def test_settled_reason_and_strict_description(
    key: str, answer: DM.ProviderAnswer, reason: str, description: str
):
    """DecisionModel / an unknown label is Invalid even without probabilities / a classify
    answer without probabilities is NoDistribution / a rate answer without probabilities is
    NoDistribution / an incomplete distribution is Invalid, with the description strict decide
    fails with"""
    layer = succeed_with({**TRIAGE_ANSWERS, key: answer})
    settled = yield from DM.decide_settled(TRIAGE, input=ticket).pipe(fx.provide(layer))
    error = yield from failure_of(DM.decide(TRIAGE, input=ticket)).pipe(fx.provide(layer))
    assert unanswered(settled.outcomes[key]) == D.Unanswered(reason, description)  # pyright: ignore[reportArgumentType]
    assert isinstance(error.reason, E.InvalidOutputError)
    assert error.reason.description == description


@testing.effect
def test_refusal_before_invalid():
    """DecisionModel / decide fails with ContentPolicyError for a refusal before reporting
    earlier invalid answers"""
    error = yield from _decide_error(
        {
            **TRIAGE_ANSWERS,
            "department": DM.ProviderClassifyAnswer(
                "legal", {"billing": 0.8, "technical": 0.15, "sales": 0.05}
            ),
            "frustration": DM.ProviderRefusalAnswer(),
        }
    )
    assert isinstance(error.reason, E.ContentPolicyError)
    assert error.reason.description == 'Provider refused to answer decisions "frustration"'


@testing.effect
def test_model_make_wraps_layer():
    """DecisionModel / Model.make wraps a DecisionModel layer with provider metadata"""
    wrapped = M.make("fake", "fake-decisions", succeed_with(TRIAGE_ANSWERS))
    provider = yield from M.ProviderName().pipe(fx.provide(wrapped.layer))
    model_name = yield from M.ModelName().pipe(fx.provide(wrapped.layer))
    response = yield from DM.decide(TRIAGE, input=ticket).pipe(fx.provide(wrapped.layer))
    assert provider == "fake"
    assert model_name == "fake-decisions"
    assert response.answers[department].label == "billing"


# Decision validation contracts ------------------------------------------------------------


@pytest.mark.parametrize("criteria", [{}, {"only": "Only label"}])
def test_classify_rejects_labels(criteria: dict[str, str]):
    """Decision validation contracts / classify rejects 0 / 1 labels"""
    with pytest.raises(ValueError, match="at least two labels"):
        D.classify(instructions="Choose", criteria=criteria)


def test_rate_rejects_duplicates():
    """Decision validation contracts / rate rejects duplicate levels"""
    with pytest.raises(ValueError, match="distinct levels"):
        D.rate(instructions="Rate", criteria=["low", "high", "low"])


@testing.effect
def test_rate_structured_levels():
    """Decision validation contracts / rate validates and labels answers by the labels of
    structured levels"""
    severity = D.rate(
        instructions={"question": "How severe?"},
        criteria={"low": "low", "high": {"impact": "outage"}},
    )
    definition = D.make(input=S.String, decisions={"severity": severity})
    response = yield from DM.decide(definition, input="Export fails").pipe(
        fx.provide(
            succeed_with({"severity": DM.ProviderRateAnswer(0.9, {"low": 0.1, "high": 0.9})})
        )
    )
    assert response.answers[severity].label == "high"
    assert response.answers[severity].probabilities == {"low": 0.1, "high": 0.9}


@testing.effect
def test_rate_argmax_label():
    """Decision validation contracts / rate derives the argmax label without a provider label"""
    response = yield from DM.decide(TRIAGE, input=ticket).pipe(
        fx.provide(succeed_with(TRIAGE_ANSWERS))
    )
    assert response.answers[frustration].label == "frustrated"


@pytest.mark.parametrize(
    ("probabilities", "expected"),
    [
        pytest.param(
            {"calm": 0.1, "frustrated": 0.5, "angry": 0.4},
            "frustrated",
            id="ignores a conflicting provider label",
        ),
        pytest.param({"angry": 0.5, "frustrated": 0.5, "calm": 0}, "frustrated", id="breaks ties"),
    ],
)
@testing.effect
def test_rate_label_from_distribution(probabilities: dict[str, float], expected: str):
    """Decision validation contracts / rate ignores a conflicting provider label / rate breaks
    ties in criteria order"""
    answer = DM.ProviderRateAnswer(1.4, probabilities, 0.5)
    response = yield from DM.decide(TRIAGE, input=ticket).pipe(
        fx.provide(succeed_with({**TRIAGE_ANSWERS, "frustration": answer}))
    )
    assert response.answers[frustration].label == expected


@testing.effect
def test_classify_keeps_provider_label():
    """Decision validation contracts / classify retains the provider label even when it is not
    the argmax"""
    answer = DM.ProviderClassifyAnswer("sales", {"billing": 0.8, "technical": 0.15, "sales": 0.05})
    response = yield from DM.decide(TRIAGE, input=ticket).pipe(
        fx.provide(succeed_with({**TRIAGE_ANSWERS, "department": answer}))
    )
    assert response.answers[department].label == "sales"


EPSILON = sys.float_info.epsilon


def _with(key: str, **changes: Any) -> dict[str, DM.ProviderAnswer]:
    from dataclasses import replace

    return {**TRIAGE_ANSWERS, key: replace(TRIAGE_ANSWERS[key], **changes)}


@pytest.mark.parametrize("key", ["department", "frustration"])
@pytest.mark.parametrize(
    "confidence", [-EPSILON, 1 + EPSILON, float("nan"), float("inf"), float("-inf")]
)
@testing.effect
def test_rejects_confidence(key: str, confidence: float):
    """Decision validation contracts / department / frustration rejects confidence
    -2.220446049250313e-16 / 1.0000000000000002 / NaN / Infinity / -Infinity"""
    error = yield from _decide_error(_with(key, confidence=confidence))
    assert isinstance(error.reason, E.InvalidOutputError)


@pytest.mark.parametrize("key", ["department", "frustration"])
@pytest.mark.parametrize("confidence", [0, 1])
@testing.effect
def test_accepts_confidence_boundary(key: str, confidence: float):
    """Decision validation contracts / department / frustration accepts confidence boundary
    0 / 1"""
    response = yield from DM.decide(TRIAGE, input=ticket).pipe(
        fx.provide(succeed_with(_with(key, confidence=confidence)))
    )
    answer = response.answers[key]
    assert isinstance(answer, D.ClassifyAnswer | D.RateAnswer)
    assert answer.confidence == confidence


TOTALS = [
    (1, True),
    (1 - 0.5e-6, True),
    (1 + 0.5e-6, True),
    (1 + 1e-6, True),
    # Adjacent representable totals straddle the lower tolerance boundary.
    (0.9999990000000001, True),
    (0.9999989999999999, False),
    (1 + 1e-6 + EPSILON, False),
    (0.99, False),
    (1.01, False),
    (0, False),
]


@pytest.mark.parametrize("key", ["department", "frustration"])
@pytest.mark.parametrize(("total", "accepted"), TOTALS)
@testing.effect
def test_distribution_total(key: str, total: float, accepted: bool):
    """Decision validation contracts / department / frustration accepts / rejects distribution
    total 1 / 0.9999995 / 1.0000005 / 1.000001 / 0.9999990000000001 / 0.9999989999999999 /
    1.0000010000000002 / 0.99 / 1.01 / 0"""
    labels = (
        ["billing", "technical", "sales"]
        if key == "department"
        else ["calm", "frustrated", "angry"]
    )
    probabilities = {labels[0]: total / 2, labels[1]: total / 2, labels[2]: 0}
    result = (
        yield from DM.decide(TRIAGE, input=ticket)
        .pipe(fx.provide(succeed_with(_with(key, probabilities=probabilities))))
        .result()
    )
    if accepted:
        assert isinstance(result, Ok)
        answer = result.value.answers[key]
        assert isinstance(answer, D.ClassifyAnswer | D.RateAnswer)
        assert answer.probabilities == probabilities
    else:
        assert isinstance(result, Err)
        assert isinstance(result.error.reason, E.InvalidOutputError)


@pytest.mark.parametrize(
    "rating", [-EPSILON, 2 + 2 * EPSILON, float("nan"), float("inf"), float("-inf")]
)
@testing.effect
def test_rejects_rating(rating: float):
    """Decision validation contracts / rate rejects rating -2.220446049250313e-16 /
    2.0000000000000004 / NaN / Infinity / -Infinity"""
    error = yield from _decide_error(_with("frustration", rating=rating))
    assert isinstance(error.reason, E.InvalidOutputError)


@pytest.mark.parametrize("rating", [0, 1.4, 2])
@testing.effect
def test_accepts_rating(rating: float):
    """Decision validation contracts / rate accepts rating 0 / 1.4 / 2"""
    response = yield from DM.decide(TRIAGE, input=ticket).pipe(
        fx.provide(succeed_with(_with("frustration", rating=rating)))
    )
    assert response.answers[frustration].rating == rating


@testing.effect
def test_extra_keys_never_leak():
    """Decision validation contracts / extra provider keys never leak into answers"""
    raw: dict[str, DM.ProviderAnswer] = {
        **TRIAGE_ANSWERS,
        "extraDecision": DM.ProviderProbabilityAnswer(0.5),
        "department": DM.ProviderClassifyAnswer(
            "billing", {"billing": 0.8, "technical": 0.15, "sales": 0.05, "extra": 1}, 0.8
        ),
        "frustration": DM.ProviderRateAnswer(
            1.4, {"calm": 0.1, "frustrated": 0.5, "angry": 0.4, "extra": 1}, 0.5
        ),
    }
    response = yield from DM.decide(TRIAGE, input=ticket).pipe(fx.provide(succeed_with(raw)))
    assert dict(response.answers) == EXPECTED


def test_answers_by_unknown_decision():
    """A decision that is not part of the definition has no answer (Python only)."""
    answers = D.Answers(TRIAGE, {"urgent": D.ProbabilityAnswer(0.9)})
    with pytest.raises(KeyError):
        answers[D.probability(instructions="Other")]


@testing.effect
def test_rescaled_distribution_matches_effect():
    """A rounded distribution is summed left to right, as JavaScript adds, before it is
    rescaled (Python only: values from Effect under Node)."""
    probabilities = {"billing": 0.01, "technical": 0.29, "sales": 0.69}
    layer = make_layer(
        lambda _: fx.succeed(DM.ProviderResponse(_with("department", probabilities=probabilities))),
        probability_precision=2,
    )
    response = yield from DM.decide(TRIAGE, input=ticket).pipe(fx.provide(layer))
    assert dict(response.answers[department].probabilities) == {
        "billing": 0.010101010101010102,
        "technical": 0.29292929292929293,
        "sales": 0.6969696969696969,
    }


@testing.effect
def test_zero_distribution_rejected_at_any_precision():
    """An all-zero distribution is invalid even when the rounding allowance covers its drift
    (Python only: Effect's ``total === 0`` check)."""
    zeros = {"billing": 0.0, "technical": 0.0, "sales": 0.0}
    layer = make_layer(
        lambda _: fx.succeed(DM.ProviderResponse(_with("department", probabilities=zeros))),
        probability_precision=0,
    )
    error = yield from failure_of(DM.decide(TRIAGE, input=ticket)).pipe(fx.provide(layer))
    assert isinstance(error.reason, E.InvalidOutputError)
    assert "do not sum to 1" in (error.reason.description or "")
