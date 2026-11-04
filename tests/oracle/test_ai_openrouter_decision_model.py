"""Ports of Effect's ``packages/ai/openrouter/test/OpenRouterDecisionModel.test.ts``.
Each docstring is the Effect test title (with its ``describe``); Effect's
loops over probabilities, label names, API URLs and statuses are
parametrized tests. A structured rate level ``{label, description}`` is an
entry of a mapping criteria; an explicitly undefined optional input field
is a ``None`` field (Python has no ``undefined``). The label names
``__proto__``, ``constructor`` and ``toString`` are ordinary keys in
Python; their tests still pin that each round trips in order."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
import math
from collections.abc import Callable, Sequence
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai import decision as D
from pyfect.ai import decision_model as DM
from pyfect.ai import model as M
from pyfect.ai.openrouter import client
from pyfect.ai.openrouter import config as openrouter_config
from pyfect.ai.openrouter import decision_model as odm
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redact
from pyfect.result import Err, Ok

from ._ai_http import MockHttp, body_json, json_response

MODEL = "test/decision-model"


class Ticket(TypedDict):
    message: str
    orderId: str


department = D.classify(
    instructions="Which team should handle this",
    criteria={
        "billing": "Payment or subscription issues",
        "technical": "Bugs or integration problems",
        "sales": "Pricing or account questions",
    },
)
frustration = D.rate(
    instructions="How frustrated the customer appears",
    criteria=["Calm, just stating facts", "Frustrated but civil", "Very angry, strong language"],
)
urgent = D.probability(
    instructions="The message conveys urgency or time-sensitivity",
    criteria={"false": "No time pressure", "true": "Needs action now"},
)
DECISIONS: dict[str, Any] = {"department": department, "frustration": frustration, "urgent": urgent}
TICKET_TRIAGE = D.make(input=S.Struct(Ticket), decisions=DECISIONS)
TICKET: Ticket = {
    "message": "Hi, I've been trying to connect my Stripe account for 3 days and it keeps "
    "failing. Please help ASAP.",
    "orderId": "A-104",
}

DEPARTMENT_ANSWER: dict[str, Any] = {
    "type": "choice",
    "choice": "billing",
    "probabilities": {"billing": 0.84, "technical": 0.159, "sales": 0.001},
    "confidence": 0.596,
}
FRUSTRATION_ANSWER: dict[str, Any] = {
    "type": "score",
    "score": 1.6,
    "legend": {
        "0": "Calm, just stating facts",
        "1": "Frustrated but civil",
        "2": "Very angry, strong language",
    },
    "probabilities": {"0": 0.05, "1": 0.3, "2": 0.65},
    "confidence": 0.78,
}
URGENT_ANSWER = {"type": "noul", "noul": 0.999}
DECISIONS_RESPONSE: dict[str, Any] = {
    "model": MODEL,
    "answers": {
        "department": DEPARTMENT_ANSWER,
        "frustration": FRUSTRATION_ANSWER,
        "urgent": URGENT_ANSWER,
    },
    "usage": {"input_tokens": 312, "output_tokens": 48},
}

structured = D.rate(
    instructions=["How severe?"], criteria={"Minor": "Minor", "Critical": {"impact": "outage"}}
)
STRUCTURED = D.make(input=S.String, decisions={"severity": structured})


def _without(answer: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: value for key, value in answer.items() if key not in keys}


def _with_answers(**answers: Any) -> dict[str, Any]:
    return {**DECISIONS_RESPONSE, "answers": {**DECISIONS_RESPONSE["answers"], **answers}}


type Handler = Callable[[HttpClientRequest], Any]


def answering(body: object, requests: list[HttpClientRequest] | None = None) -> Handler:
    def respond(request: HttpClientRequest) -> Any:
        if requests is not None:
            requests.append(request)
        return fx.succeed(json_response(request, body))

    return respond


def _unexpected(_: HttpClientRequest) -> Any:
    return fx.die(RuntimeError("Unexpected HTTP request"))


def with_client[A](
    effect: fx.Effect[A, Any, Any], handler: Handler, api_url: str | None = None
) -> fx.Effect[A, Any, Any]:
    """Effect's ``makeClientLayer``."""
    layer = client.layer(
        api_url=api_url,
        api_key=redact("or-test-key"),
        site_referrer="https://example.com",
        site_title="Decision contract tests",
    )
    return effect.pipe(fx.provide(layer)).pipe(fx.provide(MockHttp(handler).layer))


def provided[A](
    effect: fx.Effect[A, Any, Any],
    handler: Handler,
    *,
    layer: Any = None,
    api_url: str | None = None,
) -> fx.Effect[A, Any, Any]:
    """``effect`` under ``layer`` (the model's by default) and the client."""
    model_layer = odm.layer(model=MODEL) if layer is None else layer
    return with_client(effect.pipe(fx.provide(model_layer)), handler, api_url)


def _decide(handler: Handler, definition: Any = TICKET_TRIAGE, input: Any = TICKET) -> Any:
    return provided(DM.decide(definition, input=input), handler)


def _decide_error(handler: Handler, definition: Any = TICKET_TRIAGE, input: Any = TICKET) -> Any:
    return provided(DM.decide(definition, input=input).flip(), handler)


def _total(probabilities: Any) -> float:
    return math.fsum(probabilities.values())


@testing.effect
def test_rounded_choice_probabilities():
    """OpenRouterDecisionModel / accepts rounded choice probabilities that total 0.99"""
    neutral3 = D.classify(
        instructions="Choose a sentiment",
        criteria={"negative": "Negative", "neutral": "Neutral", "positive": "Positive"},
    )
    definition = D.make(input=S.String, decisions={"neutral3": neutral3})
    body = {
        "model": MODEL,
        "answers": {
            "neutral3": {
                "type": "choice",
                "choice": "neutral",
                "probabilities": {"negative": 0.02, "neutral": 0.93, "positive": 0.04},
                "confidence": 0.93,
            }
        },
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    result = yield from _decide(answering(body), definition, "It is fine")
    assert result.answers[neutral3].label == "neutral"
    assert _total(result.answers[neutral3].probabilities) == pytest.approx(1, abs=1e-6)


@pytest.mark.parametrize(
    ("probabilities", "succeeds"),
    [
        ({"a": 0.5, "b": 0.5, "extra": 0.01}, True),
        ({"a": 0.49, "b": 0.49}, False),
        ({"a": 1.01, "b": -0.02}, False),
        ({"a": 0, "b": 0}, False),
        ({key: 0.13 if key == "h" else 0.12 for key in "abcdefgh"}, True),
    ],
    ids=[
        "extra provider key",
        "drift outside two-decimal rounding",
        "out-of-range probability",
        "all-zero distribution",
        "eight rounded labels",
    ],
)
@testing.effect
def test_choice_distribution(probabilities: dict[str, float], succeeds: bool):
    """OpenRouterDecisionModel / ${name}"""
    choice = D.classify(
        instructions="Pick a label",
        criteria={key: key for key in probabilities if key != "extra"},
    )
    definition = D.make(input=S.String, decisions={"choice": choice})
    body = {
        "model": MODEL,
        "answers": {
            "choice": {
                "type": "choice",
                "choice": "a",
                "probabilities": probabilities,
                "confidence": 0.5,
            }
        },
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    result = yield from _decide(answering(body), definition, "test").result()
    if succeeds:
        assert isinstance(result, Ok)
        found = result.value.answers[choice].probabilities
        assert _total(found) == pytest.approx(1, abs=1e-6)
        if "extra" in probabilities:
            assert dict(found) == {"a": 0.5, "b": 0.5}
    else:
        assert isinstance(result, Err)
        assert isinstance(result.error.reason, E.InvalidOutputError)


@testing.effect
def test_rounded_score_probabilities():
    """OpenRouterDecisionModel / normalizes rounded score probabilities"""
    score = D.rate(instructions="Rate", criteria=["low", "mid", "high"])
    definition = D.make(input=S.String, decisions={"score": score})
    body = {
        "model": MODEL,
        "answers": {
            "score": {
                "type": "score",
                "score": 1,
                "probabilities": {"0": 0.1, "1": 0.7, "2": 0.19},
                "confidence": 0.7,
            }
        },
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    result = yield from _decide(answering(body), definition, "test")
    assert _total(result.answers[score].probabilities) == pytest.approx(1, abs=1e-6)


@testing.effect
def test_absent_probability_criteria():
    """OpenRouterDecisionModel / omits absent probability criteria from the encoded question"""
    needs_action = D.probability(instructions="Needs action now")
    definition = D.make(input=S.String, decisions={"urgent": needs_action})
    requests: list[HttpClientRequest] = []
    body = {
        "model": MODEL,
        "answers": {"urgent": {"type": "noul", "noul": 0.75}},
        "usage": {"input_tokens": 20, "output_tokens": 4},
    }
    result = yield from _decide(answering(body, requests), definition, "Help ASAP")
    assert body_json(requests[0])["questions"]["urgent"] == {
        "type": "noul",
        "instructions": "Needs action now",
    }
    assert result.answers[needs_action] == D.ProbabilityAnswer(0.75)


SPECIAL_KEYS = ["__proto__", "constructor", "toString"]


@pytest.mark.parametrize("key", SPECIAL_KEYS)
@testing.effect
def test_classification_label_round_trip(key: str):
    """OpenRouterDecisionModel / round trips a classification label named ${key}"""
    category = D.classify(
        instructions="Choose a category",
        criteria={key: "Special category", "ordinary": "Ordinary category"},
    )
    definition = D.make(input=S.String, decisions={"category": category})
    requests: list[HttpClientRequest] = []
    body = {
        "model": MODEL,
        "answers": {
            "category": {
                "type": "choice",
                "choice": key,
                "probabilities": {key: 0.75, "ordinary": 0.25},
                "confidence": 0.5,
            }
        },
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    result = yield from _decide(answering(body, requests), definition, "Help")
    criteria = body_json(requests[0])["questions"]["category"]["criteria"]
    assert list(criteria) == [key, "ordinary"]
    assert criteria[key] == "Special category"
    answer = result.answers[category]
    assert list(answer.probabilities) == [key, "ordinary"]
    assert dict(answer.probabilities) == {key: 0.75, "ordinary": 0.25}
    assert answer.label == key


@pytest.mark.parametrize("key", SPECIAL_KEYS)
@testing.effect
def test_score_level_named(key: str):
    """OpenRouterDecisionModel / maps a score distribution to a rate level named ${key}"""
    intensity = D.rate(instructions="How intense", criteria=["low", key, "high"])
    definition = D.make(input=S.String, decisions={"intensity": intensity})
    requests: list[HttpClientRequest] = []
    body = {
        "model": MODEL,
        "answers": {
            "intensity": {
                "type": "score",
                "score": 1.1,
                "legend": {"0": "low", "1": key, "2": "high"},
                "probabilities": {"0": 0.1, "1": 0.7, "2": 0.2},
                "confidence": 0.5,
            }
        },
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    result = yield from _decide(answering(body, requests), definition, "Help")
    assert body_json(requests[0])["questions"]["intensity"]["criteria"] == ["low", key, "high"]
    answer = result.answers[intensity]
    assert list(answer.probabilities) == ["low", key, "high"]
    assert dict(answer.probabilities) == {"low": 0.1, key: 0.7, "high": 0.2}
    assert answer.label == key
    assert answer.rating == 1.1


@pytest.mark.parametrize("key", SPECIAL_KEYS)
@testing.effect
def test_question_named(key: str):
    """OpenRouterDecisionModel / sends an own enumerable question named ${key}"""
    decision = D.probability(
        instructions="Needs action now", criteria={"false": "No", "true": "Yes"}
    )
    definition = D.make(input=S.String, decisions={key: decision})
    requests: list[HttpClientRequest] = []
    body = {
        "model": MODEL,
        "answers": {key: {"type": "noul", "noul": 0.75}},
        "usage": {"input_tokens": 20, "output_tokens": 4},
    }
    result = yield from _decide(answering(body, requests), definition, "Help")
    questions = body_json(requests[0])["questions"]
    assert list(questions) == [key]
    assert questions[key] == {
        "type": "noul",
        "instructions": "Needs action now",
        "criteria": {"false": "No", "true": "Yes"},
    }
    assert result.answers[decision] == D.ProbabilityAnswer(0.75)


@pytest.mark.parametrize(
    "api_url",
    [
        "https://proxy.test/openrouter/v1",
        "https://proxy.test/openrouter/v1/",
        "https://proxy.test/openrouter",
        "https://proxy.test/openrouter/",
    ],
)
@testing.effect
def test_alpha_endpoint(api_url: str):
    """OpenRouterDecisionModel / resolves the alpha endpoint for ${apiUrl}"""
    requests: list[HttpClientRequest] = []
    yield from provided(
        DM.decide(TICKET_TRIAGE, input=TICKET),
        answering(DECISIONS_RESPONSE, requests),
        api_url=api_url,
    )
    assert len(requests) == 1
    assert requests[0].url == "https://proxy.test/openrouter/alpha/decisions"


@testing.effect
def test_scoped_client_transform():
    """OpenRouterDecisionModel / applies a scoped client transform only to the enclosed decisions
    request"""
    requests: list[HttpClientRequest] = []
    scoped = DM.decide(TICKET_TRIAGE, input=TICKET).pipe(
        openrouter_config.with_client_transform(
            lambda http: http.map_request(
                lambda request: request.set_header("x-decision-scope", "scoped")
            )
        )
    )
    yield from provided(
        scoped.flat_map(lambda _: DM.decide(TICKET_TRIAGE, input=TICKET)),
        answering(DECISIONS_RESPONSE, requests),
    )
    assert len(requests) == 2
    assert requests[0].headers["x-decision-scope"] == "scoped"
    assert "x-decision-scope" not in requests[1].headers


@testing.effect
def test_numeric_state():
    """OpenRouterDecisionModel / rejects numeric state before making an HTTP request"""
    definition = D.make(input=S.Finite, decisions=DECISIONS)
    error = yield from _decide_error(_unexpected, definition, 42)
    assert isinstance(error, E.AiError)
    assert isinstance(error.reason, E.InvalidUserInputError)


@testing.effect
def test_malformed_response():
    """OpenRouterDecisionModel / maps a malformed successful response to a non-retryable client
    InvalidResponseError"""
    body = {**DECISIONS_RESPONSE, "usage": {"input_tokens": "not a number", "output_tokens": 48}}
    error = yield from _decide_error(answering(body))
    assert isinstance(error, E.AiError)
    assert error.module == "OpenRouterClient"
    assert error.method == "createDecisions"
    assert isinstance(error.reason, E.InvalidResponseError)


@testing.effect
def test_make_service():
    """OpenRouterDecisionModel / make constructs a DecisionModel service"""
    service = yield from with_client(odm.make(model=MODEL), _unexpected)
    assert callable(service.decide)


@testing.effect
def test_config_and_overrides():
    """OpenRouterDecisionModel / forwards request config and scoped overrides"""
    requests: list[HttpClientRequest] = []
    layer = odm.layer(
        model=MODEL,
        config={
            "provider": {"order": ["test-provider"]},
            "session_id": "session-1",
            "user": "default-user",
            "trace": {"trace_id": "default"},
        },
    )
    yield from provided(
        DM.decide(TICKET_TRIAGE, input=TICKET).pipe(
            fx.provide_service(odm.Config, {"user": "scoped-user", "trace": {"trace_id": "scoped"}})
        ),
        answering(DECISIONS_RESPONSE, requests),
        layer=layer,
    )
    body = body_json(requests[0])
    assert body["provider"] == {"order": ["test-provider"]}
    assert body["session_id"] == "session-1"
    assert body["user"] == "scoped-user"
    assert body["trace"] == {"trace_id": "scoped"}


@testing.effect
def test_absent_optional_fields():
    """OpenRouterDecisionModel / accepts absent confidence, cost, id and provider without inventing
    values"""
    body = _with_answers(
        department=_without(DEPARTMENT_ANSWER, "confidence"),
        frustration=_without(FRUSTRATION_ANSWER, "confidence", "legend"),
    )
    result = yield from _decide(answering(body))
    answers = result.answers
    assert answers[department].confidence is None
    assert answers[frustration].confidence is None
    assert answers[frustration].label == "Very angry, strong language"
    assert answers[urgent].probability == 0.999
    assert (result.usage.input_tokens, result.usage.output_tokens) == (312, 48)
    assert result.id is None
    assert result.metadata["openrouter"] == {}


@testing.effect
def test_response_id_model_cost_provider():
    """OpenRouterDecisionModel / returns the response id, resolved model, cost and serving provider
    OpenRouterDecisionModel / returns the response id, resolved model, cost and serving provider"""
    body = {
        **DECISIONS_RESPONSE,
        "model": "test/decision-model-1.2",
        "id": "decision-1",
        "provider": "test-provider",
        "usage": {**DECISIONS_RESPONSE["usage"], "cost": 0.001},
    }
    result = yield from provided(
        DM.decide(TICKET_TRIAGE, input=TICKET),
        answering(body),
        layer=odm.layer(model="test/decision-model-latest"),
    )
    assert (result.usage.input_tokens, result.usage.output_tokens) == (312, 48)
    assert result.id == "decision-1"
    assert result.model_id == "test/decision-model-1.2"
    assert result.metadata["openrouter"] == {"cost": 0.001, "provider": "test-provider"}
    assert not hasattr(result.answers[department], "cost")


@testing.effect
def test_choice_without_probabilities():
    """OpenRouterDecisionModel / fails with InvalidOutputError when a choice answer omits
    probabilities"""
    body = _with_answers(department=_without(DEPARTMENT_ANSWER, "probabilities"))
    error = yield from _decide_error(answering(body))
    assert isinstance(error, E.AiError)
    assert isinstance(error.reason, E.InvalidOutputError)


@testing.effect
def test_model_provider_metadata():
    """OpenRouterDecisionModel / model provides DecisionModel with openrouter provider metadata"""
    program = M.ProviderName().zip(M.ModelName()).zip(DM.DecisionModel())
    (provider, model_name), model = yield from provided(
        program, _unexpected, layer=odm.model(MODEL).layer
    )
    assert provider == "openrouter"
    assert model_name == MODEL
    assert callable(model.decide)


@testing.effect
def test_state_and_questions_in_one_request():
    """OpenRouterDecisionModel / sends the encoded input as state and every decision as a question
    in one request"""
    requests: list[HttpClientRequest] = []
    yield from _decide(answering(DECISIONS_RESPONSE, requests))
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url == "https://openrouter.ai/api/alpha/decisions"
    assert request.headers["authorization"] == "Bearer or-test-key"
    assert request.headers["http-referer"] == "https://example.com"
    assert request.headers["x-title"] == "Decision contract tests"
    assert body_json(request) == {
        "state": {"message": TICKET["message"], "orderId": "A-104"},
        "model": MODEL,
        "questions": {
            "department": {
                "type": "choice",
                "instructions": "Which team should handle this",
                "criteria": {
                    "billing": "Payment or subscription issues",
                    "technical": "Bugs or integration problems",
                    "sales": "Pricing or account questions",
                },
            },
            "frustration": {
                "type": "score",
                "instructions": "How frustrated the customer appears",
                "criteria": [
                    "Calm, just stating facts",
                    "Frustrated but civil",
                    "Very angry, strong language",
                ],
            },
            "urgent": {
                "type": "noul",
                "instructions": "The message conveys urgency or time-sensitivity",
                "criteria": {"false": "No time pressure", "true": "Needs action now"},
            },
        },
    }


@testing.effect
def test_answers_mapped():
    """OpenRouterDecisionModel / maps choice, score, and noul answers onto classify, rate, and
    probability answers"""
    result = yield from _decide(answering(DECISIONS_RESPONSE))
    answers = result.answers
    assert answers[department].label == "billing"
    assert dict(answers[department].probabilities) == {
        "billing": 0.84,
        "technical": 0.159,
        "sales": 0.001,
    }
    assert answers[department].confidence == 0.596
    assert answers[frustration].rating == 1.6
    assert answers[frustration].label == "Very angry, strong language"
    assert dict(answers[frustration].probabilities) == {
        "Calm, just stating facts": 0.05,
        "Frustrated but civil": 0.3,
        "Very angry, strong language": 0.65,
    }
    assert answers[frustration].confidence == 0.78
    assert answers[urgent] == D.ProbabilityAnswer(0.999)
    assert result.usage.input_tokens == 312
    assert result.usage.output_tokens == 48


class OptionalTicket(TypedDict):
    message: str
    orderId: str | None


@testing.effect
def test_undefined_optional_field_as_null():
    """OpenRouterDecisionModel / encodes an explicitly undefined optional input field as JSON null
    OpenRouterDecisionModel / encodes an explicitly undefined optional input field as JSON null"""
    requests: list[HttpClientRequest] = []
    definition = D.make(
        input=S.Struct(OptionalTicket, orderId=S.NullOr(S.String)), decisions=DECISIONS
    )
    result = yield from _decide(
        answering(DECISIONS_RESPONSE, requests),
        definition,
        {"message": TICKET["message"], "orderId": None},
    )
    assert len(requests) == 1
    assert body_json(requests[0])["state"] == {"message": TICKET["message"], "orderId": None}
    assert result.answers[urgent].probability == 0.999


@testing.effect
def test_pinned_model_id():
    """OpenRouterDecisionModel / sends a pinned model id through unchanged"""
    requests: list[HttpClientRequest] = []
    pinned = "test/decision-model-pinned"
    model_name = yield from provided(
        DM.decide(TICKET_TRIAGE, input=TICKET).flat_map(lambda _: M.ModelName()),
        answering({**DECISIONS_RESPONSE, "model": pinned}, requests),
        layer=odm.model(pinned).layer,
    )
    assert model_name == pinned
    assert body_json(requests[0])["model"] == pinned


URGENCY = D.probability(
    instructions="The message conveys urgency",
    criteria={"false": "No time pressure", "true": "Needs action now"},
)
URGENCY_RESPONSE = {
    "model": MODEL,
    "answers": {"urgent": {"type": "noul", "noul": 0.93}},
    "usage": {"input_tokens": 20, "output_tokens": 4},
}


@testing.effect
def test_string_state():
    """OpenRouterDecisionModel / passes a string input through as a string state"""
    requests: list[HttpClientRequest] = []
    sentiment = D.make(input=S.String, decisions={"urgent": URGENCY})
    yield from _decide(
        answering(URGENCY_RESPONSE, requests), sentiment, "My card was charged twice."
    )
    assert body_json(requests[0])["state"] == "My card was charged twice."


@testing.effect
def test_array_state():
    """OpenRouterDecisionModel / passes an array input through as an array state"""
    requests: list[HttpClientRequest] = []
    conversation = D.make(input=S.Array(S.String), decisions={"urgent": URGENCY})
    messages: Sequence[str] = ["Hi", "My customer number is TS1337.", "My card was charged twice."]
    yield from _decide(answering(URGENCY_RESPONSE, requests), conversation, messages)
    assert body_json(requests[0])["state"] == list(messages)


@testing.effect
def test_mismatched_answer_type():
    """OpenRouterDecisionModel / fails with InvalidOutputError when an answer type does not match
    the decision"""
    body = _with_answers(
        urgent={
            "type": "choice",
            "choice": "true",
            "probabilities": {"true": 0.9, "false": 0.1},
            "confidence": 0.8,
        }
    )
    error = yield from _decide_error(answering(body))
    assert isinstance(error, E.AiError)
    assert isinstance(error.reason, E.InvalidOutputError)


@testing.effect
def test_missing_answer():
    """OpenRouterDecisionModel / fails with InvalidOutputError when an answer is missing"""
    body = {
        **DECISIONS_RESPONSE,
        "answers": _without(DECISIONS_RESPONSE["answers"], "urgent"),
    }
    error = yield from _decide_error(answering(body))
    assert isinstance(error, E.AiError)
    assert isinstance(error.reason, E.InvalidOutputError)


@testing.effect
def test_score_without_probabilities():
    """OpenRouterDecisionModel / fails with InvalidOutputError when a score answer omits
    probabilities"""
    body = _with_answers(frustration=_without(FRUSTRATION_ANSWER, "probabilities"))
    error = yield from _decide_error(answering(body))
    assert isinstance(error, E.AiError)
    assert isinstance(error.reason, E.InvalidOutputError)


@testing.effect
def test_settled_no_distribution():
    """OpenRouterDecisionModel / decideSettled reports choice and score answers without
    probabilities as NoDistribution"""
    body = _with_answers(
        department=_without(DEPARTMENT_ANSWER, "probabilities"),
        frustration=_without(FRUSTRATION_ANSWER, "probabilities"),
    )
    settled = yield from provided(DM.decide_settled(TICKET_TRIAGE, input=TICKET), answering(body))
    outcomes = settled.outcomes
    department_outcome = outcomes[department]
    assert isinstance(department_outcome, Err)
    assert department_outcome.error.reason == "NoDistribution"
    frustration_outcome = outcomes[frustration]
    assert isinstance(frustration_outcome, Err)
    assert frustration_outcome.error.reason == "NoDistribution"
    assert isinstance(outcomes[urgent], Ok)


@testing.effect
def test_score_skips_level():
    """OpenRouterDecisionModel / fails with InvalidOutputError when a score distribution skips a
    level index"""
    body = _with_answers(
        frustration={**FRUSTRATION_ANSWER, "probabilities": {"0": 0.35, "2": 0.65}}
    )
    error = yield from _decide_error(answering(body))
    assert isinstance(error, E.AiError)
    assert isinstance(error.reason, E.InvalidOutputError)


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (400, E.InvalidRequestError),
        (401, E.AuthenticationError),
        (402, E.UnknownError),
        (403, E.AuthenticationError),
        (404, E.InvalidRequestError),
        (413, E.UnknownError),
        (429, E.RateLimitError),
        (500, E.InternalProviderError),
        (502, E.InternalProviderError),
        (503, E.InternalProviderError),
        (524, E.InternalProviderError),
        (529, E.InternalProviderError),
    ],
)
@testing.effect
def test_http_status_mapping(status: int, reason: type[Any]):
    """OpenRouterDecisionModel / maps HTTP ${status} using the existing OpenRouter error mapping"""

    def respond(request: HttpClientRequest) -> Any:
        body = {"error": {"message": "Decision request failed", "code": status}}
        return fx.succeed(json_response(request, body, status=status, headers={"retry-after": "3"}))

    error = yield from _decide_error(respond)
    assert isinstance(error, E.AiError)
    assert isinstance(error.reason, reason)


@testing.effect
def test_structured_descriptions():
    """OpenRouterDecisionModel / sends structured descriptions and maps score indices to labels"""
    requests: list[HttpClientRequest] = []
    body = {
        "model": MODEL,
        "usage": {"input_tokens": 120, "output_tokens": 0},
        "answers": {
            "severity": {
                "type": "score",
                "score": 0.9,
                "probabilities": {"0": 0.1, "1": 0.9},
                "confidence": 0.9,
                "legend": {"0": "Minor", "1": {"impact": "outage"}},
            }
        },
    }
    result = yield from _decide(answering(body, requests), STRUCTURED, "Checkout is down")
    assert body_json(requests[0])["questions"] == {
        "severity": {
            "type": "score",
            "instructions": ["How severe?"],
            "criteria": ["Minor", {"impact": "outage"}],
        }
    }
    assert result.answers[structured].label == "Critical"
    assert dict(result.answers[structured].probabilities) == {"Minor": 0.1, "Critical": 0.9}
